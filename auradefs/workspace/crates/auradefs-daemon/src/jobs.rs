//! Long operations, and being able to watch and stop them.
//!
//! A copy of forty gigabytes cannot be a request that blocks until it is done.
//! Starting one returns an id straight away, the work happens on its own
//! thread, and the page asks how it is going. That is also what makes Cancel a
//! real button rather than one that only stops the next thing.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use auradefs_core::ops::fs::{Flow, Progress};

/// Where one operation has got to.
#[derive(Debug, Clone, Default)]
pub struct Snapshot {
    pub kind: String,
    pub state: &'static str,
    pub total_items: u64,
    pub done_items: u64,
    pub total_bytes: u64,
    pub done_bytes: u64,
    pub current: String,
    pub error: Option<String>,
    pub error_code: Option<String>,
    pub result: Option<serde_json::Value>,
}

/// The shared state of one job. The worker writes it; a request reads it.
pub struct Job {
    pub id: u64,
    cancel: AtomicBool,
    snapshot: Mutex<Snapshot>,
    finished: Mutex<Option<Instant>>,
}

impl Job {
    /// Report progress, and find out whether to keep going. This is the
    /// function handed to the core as its reporter.
    pub fn report(&self, progress: &Progress) -> Flow {
        {
            let mut snap = self.snapshot.lock().unwrap_or_else(|e| e.into_inner());
            snap.total_items = progress.total_items;
            snap.done_items = progress.done_items;
            snap.total_bytes = progress.total_bytes;
            snap.done_bytes = progress.done_bytes;
            snap.current = progress.current.display().to_string();
        }
        if self.cancel.load(Ordering::Relaxed) {
            Flow::Cancel
        } else {
            Flow::Continue
        }
    }

    pub fn cancelled(&self) -> bool {
        self.cancel.load(Ordering::Relaxed)
    }

    pub fn snapshot(&self) -> Snapshot {
        self.snapshot.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    fn finish(&self, state: &'static str, error: Option<(String, String)>, result: Option<serde_json::Value>) {
        {
            let mut snap = self.snapshot.lock().unwrap_or_else(|e| e.into_inner());
            snap.state = state;
            if let Some((message, code)) = error {
                snap.error = Some(message);
                snap.error_code = Some(code);
            }
            snap.result = result;
        }
        *self.finished.lock().unwrap_or_else(|e| e.into_inner()) = Some(Instant::now());
    }
}

/// Every job this service has started.
pub struct Jobs {
    next: AtomicU64,
    map: Mutex<HashMap<u64, Arc<Job>>>,
}

/// How long a finished job's result stays readable. Long enough for a page to
/// come back from a reload and see what happened, short enough that a session
/// running for a week does not accumulate them.
const KEEP_FINISHED: Duration = Duration::from_secs(600);

impl Jobs {
    pub fn new() -> Jobs {
        Jobs { next: AtomicU64::new(1), map: Mutex::new(HashMap::new()) }
    }

    /// Start work on its own thread and hand back the id at once.
    pub fn start<F>(&self, kind: &str, work: F) -> u64
    where
        F: FnOnce(&Job) -> auradefs_core::Result<serde_json::Value> + Send + 'static,
    {
        self.reap();
        let id = self.next.fetch_add(1, Ordering::Relaxed);
        let job = Arc::new(Job {
            id,
            cancel: AtomicBool::new(false),
            snapshot: Mutex::new(Snapshot {
                kind: kind.to_string(),
                state: "running",
                ..Default::default()
            }),
            finished: Mutex::new(None),
        });
        self.map
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(id, Arc::clone(&job));

        std::thread::Builder::new()
            .name(format!("job-{id}"))
            .spawn(move || match work(&job) {
                Ok(result) => {
                    let state = if job.cancelled() { "cancelled" } else { "done" };
                    job.finish(state, None, Some(result));
                }
                Err(e) => job.finish("error", Some((e.to_string(), e.code().to_string())), None),
            })
            //: A thread that will not start is a failure of the whole service,
            //: not of this one request, so it is reported as the job's error
            //: rather than being silently lost.
            .map_err(|e| {
                if let Some(job) = self.get(id) {
                    job.finish("error", Some((e.to_string(), "io".into())), None);
                }
            })
            .ok();
        id
    }

    pub fn get(&self, id: u64) -> Option<Arc<Job>> {
        self.map.lock().unwrap_or_else(|e| e.into_inner()).get(&id).cloned()
    }

    /// Ask a job to stop. It stops at its next progress report, which is at
    /// most one file or one megabyte away.
    pub fn cancel(&self, id: u64) -> bool {
        match self.get(id) {
            Some(job) => {
                job.cancel.store(true, Ordering::Relaxed);
                true
            }
            None => false,
        }
    }

    pub fn list(&self) -> Vec<(u64, Snapshot)> {
        let map = self.map.lock().unwrap_or_else(|e| e.into_inner());
        let mut out: Vec<(u64, Snapshot)> = map.iter().map(|(id, job)| (*id, job.snapshot())).collect();
        out.sort_by_key(|(id, _)| *id);
        out
    }

    /// Drop finished jobs that nobody is going to ask about again.
    fn reap(&self) {
        let mut map = self.map.lock().unwrap_or_else(|e| e.into_inner());
        map.retain(|_, job| {
            match *job.finished.lock().unwrap_or_else(|e| e.into_inner()) {
                Some(at) => at.elapsed() < KEEP_FINISHED,
                None => true,
            }
        });
    }
}

impl Default for Jobs {
    fn default() -> Self {
        Jobs::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn wait_for(jobs: &Jobs, id: u64, state: &str) -> Snapshot {
        for _ in 0..2000 {
            let snap = jobs.get(id).unwrap().snapshot();
            if snap.state == state {
                return snap;
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        panic!("job {id} never reached {state}");
    }

    #[test]
    fn a_job_runs_and_its_result_is_readable_afterwards() {
        let jobs = Jobs::new();
        let id = jobs.start("test", |_job| Ok(serde_json::json!({"copied": 3})));
        let snap = wait_for(&jobs, id, "done");
        assert_eq!(snap.kind, "test");
        assert_eq!(snap.result.unwrap()["copied"], 3);
        assert!(snap.error.is_none());
    }

    #[test]
    fn a_failure_keeps_both_the_message_and_the_code() {
        let jobs = Jobs::new();
        let id = jobs.start("test", |_job| {
            Err(auradefs_core::Error::Denied("/root/secret".into()))
        });
        let snap = wait_for(&jobs, id, "error");
        assert_eq!(snap.error_code.as_deref(), Some("denied"));
        assert!(snap.error.unwrap().contains("/root/secret"));
    }

    #[test]
    fn progress_is_visible_while_the_work_is_still_going() {
        let jobs = Jobs::new();
        let (tx, rx) = std::sync::mpsc::channel::<()>();
        let id = jobs.start("test", move |job| {
            job.report(&Progress {
                total_items: 10,
                done_items: 4,
                total_bytes: 100,
                done_bytes: 40,
                current: std::path::PathBuf::from("/tmp/now"),
            });
            //: Hold the job open until the test has looked at it.
            let _ = rx.recv();
            Ok(serde_json::Value::Null)
        });
        for _ in 0..2000 {
            let snap = jobs.get(id).unwrap().snapshot();
            if snap.done_items == 4 {
                assert_eq!(snap.state, "running");
                assert_eq!(snap.total_bytes, 100);
                assert_eq!(snap.current, "/tmp/now");
                let _ = tx.send(());
                wait_for(&jobs, id, "done");
                return;
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        panic!("progress never appeared");
    }

    #[test]
    fn cancelling_reaches_the_worker_at_its_next_report() {
        let jobs = Jobs::new();
        let id = jobs.start("test", |job| {
            for _ in 0..100_000 {
                if job.report(&Progress::default()) == Flow::Cancel {
                    return Ok(serde_json::json!({"stopped": true}));
                }
                std::thread::sleep(Duration::from_millis(1));
            }
            Ok(serde_json::json!({"stopped": false}))
        });
        assert!(jobs.cancel(id));
        let snap = wait_for(&jobs, id, "cancelled");
        assert_eq!(snap.result.unwrap()["stopped"], true);
        //: Cancelling something that is not there is a no, not a panic.
        assert!(!jobs.cancel(9999));
    }

    #[test]
    fn ids_are_never_reused_within_a_run() {
        let jobs = Jobs::new();
        let mut seen = Vec::new();
        for _ in 0..20 {
            let id = jobs.start("test", |_| Ok(serde_json::Value::Null));
            assert!(!seen.contains(&id), "id {id} came back");
            seen.push(id);
        }
        for id in &seen {
            wait_for(&jobs, *id, "done");
        }
        assert_eq!(jobs.list().len(), 20);
    }
}
