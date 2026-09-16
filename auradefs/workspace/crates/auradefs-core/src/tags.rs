//! Finding every file that carries a tag.
//!
//! A tag lives on the file, as `user.xdg.tags`, and that is the truth: it
//! travels with the file to another disk and another desktop. But "show me
//! everything tagged Work" cannot be answered from the files, because that
//! would mean reading an extended attribute from every file on the system.
//!
//! So there is an index, and it is a cache rather than a second source of
//! truth. Every write goes to the attribute first and the index second, a
//! read prunes what has gone away, and where the two disagree the attribute
//! wins. The file is the same one the Python backend used, so both can be
//! running during the changeover without either losing a tag.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::error::{Error, Result};
use crate::mime::xdg_data_home;

/// The index file, shared with the prototype backend.
pub fn index_path() -> Result<PathBuf> {
    Ok(xdg_data_home()
        .ok_or_else(|| Error::NotFound("no data directory".into()))?
        .join("aurade/filetags.json"))
}

/// Tag name to the paths carrying it. Ordered, so the file does not churn
/// between writes and a difference in it is a real difference.
pub type Index = BTreeMap<String, Vec<String>>;

fn read_index() -> Index {
    let Ok(path) = index_path() else { return Index::new() };
    let Ok(text) = std::fs::read_to_string(path) else { return Index::new() };
    //: A corrupt index is a cache miss, not a failure. It rebuilds as files
    //: are tagged again, and refusing to start over it would make one bad
    //: write permanent.
    serde_json::from_str(&text).unwrap_or_default()
}

fn write_index(index: &Index) -> Result<()> {
    let path = index_path()?;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| Error::io(dir.display().to_string(), e))?;
    }
    let text = serde_json::to_string(index)
        .map_err(|e| Error::Tool { tool: "json".into(), message: e.to_string() })?;
    let tmp = path.with_extension(format!("tmp{}", std::process::id()));
    std::fs::write(&tmp, text).map_err(|e| Error::io(tmp.display().to_string(), e))?;
    std::fs::rename(&tmp, &path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        Error::io(path.display().to_string(), e)
    })
}

/// Set the tags on a file and record it.
///
/// The attribute is written first. If the filesystem will not take one, which
/// is every FAT formatted stick, that is reported rather than hidden: a tag
/// that only exists in this machine's index is not a tag that travels, and the
/// UI should say so.
/// The names a set actually gets, in the order they were given.
///
/// Trimmed, empties dropped, duplicates dropped, and anything with a comma in
/// it dropped: the attribute on the file is a comma separated list, so a name
/// containing one cannot be written there and would exist only in this
/// machine's index. Silently, because this runs behind a text box where a
/// stray comma is a typo rather than a request.
pub fn clean(tags: &[String]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for tag in tags {
        let tag = tag.trim();
        if tag.is_empty() || tag.contains(',') {
            continue;
        }
        if !out.iter().any(|t| t == tag) {
            out.push(tag.to_string());
        }
    }
    out
}

pub fn set(path: &Path, tags: &[String]) -> Result<Stored> {
    let tags = &clean(tags)[..];
    let stored = match crate::xattr::set_tags(path, tags) {
        Ok(()) => true,
        //: The index can still hold it, so the sidebar works on this machine.
        //: What is lost is portability, and the caller is told.
        Err(Error::Unsupported(_)) => false,
        Err(e) => return Err(e),
    };
    let key = path.display().to_string();
    let mut index = read_index();
    //: Out of every tag first, then into the ones it now has. A tag removed in
    //: the dialog has to leave the index or the sidebar keeps offering it.
    index.retain(|_, paths| {
        paths.retain(|p| p != &key);
        !paths.is_empty()
    });
    for tag in tags {
        let entry = index.entry(tag.clone()).or_default();
        if !entry.contains(&key) {
            entry.push(key.clone());
        }
    }
    write_index(&index)?;
    Ok(Stored { tags: crate::xattr::tags(path).unwrap_or_else(|_| tags.to_vec()), on_the_file: stored })
}

/// What a write ended up doing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Stored {
    pub tags: Vec<String>,
    /// False when the filesystem has no extended attributes, so the tag exists
    /// only in this machine's index.
    pub on_the_file: bool,
}

/// Every tag and the files carrying it, with anything that has gone away
/// dropped. The pruned index is written back, so the file does not grow
/// forever with paths that no longer exist.
pub fn all() -> Result<Index> {
    let index = read_index();
    let mut live = Index::new();
    let mut changed = false;
    for (tag, paths) in &index {
        let kept: Vec<String> = paths
            .iter()
            .filter(|p| Path::new(p).symlink_metadata().is_ok())
            .cloned()
            .collect();
        if kept.len() != paths.len() {
            changed = true;
        }
        if !kept.is_empty() {
            live.insert(tag.clone(), kept);
        }
    }
    if changed {
        let _ = write_index(&live);
    }
    Ok(live)
}

/// The files carrying one tag.
pub fn with_tag(tag: &str) -> Result<Vec<PathBuf>> {
    let tag = tag.trim();
    if tag.is_empty() {
        return Err(Error::BadRequest("a tag is required".into()));
    }
    Ok(all()?
        .get(tag)
        .map(|paths| paths.iter().map(PathBuf::from).collect())
        .unwrap_or_default())
}

/// Make the index agree with the files again.
///
/// The index goes stale in one way pruning cannot fix: a file moved by another
/// program keeps its attribute and loses its entry, and a file whose tags were
/// changed by another program keeps a wrong entry. This re-reads the attribute
/// for every indexed path and rebuilds from what the files actually say.
/// Returns how many entries changed.
pub fn reconcile() -> Result<usize> {
    let index = read_index();
    let mut paths: Vec<String> = index.values().flatten().cloned().collect();
    paths.sort();
    paths.dedup();

    let mut rebuilt = Index::new();
    let mut changed = 0;
    for key in paths {
        let path = Path::new(&key);
        if path.symlink_metadata().is_err() {
            changed += 1;
            continue;
        }
        let on_file = crate::xattr::tags(path).unwrap_or_default();
        let indexed: Vec<&String> = index
            .iter()
            .filter(|(_, paths)| paths.contains(&key))
            .map(|(tag, _)| tag)
            .collect();
        if indexed.len() != on_file.len() || !on_file.iter().all(|t| indexed.contains(&t)) {
            changed += 1;
        }
        for tag in on_file {
            rebuilt.entry(tag).or_default().push(key.clone());
        }
    }
    if changed > 0 {
        write_index(&rebuilt)?;
    }
    Ok(changed)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// These share one process wide environment variable, so they run under a
    /// lock rather than in parallel.
    fn with_data_home<T>(tag: &str, body: impl FnOnce(&Path) -> T) -> T {
        static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
        let _guard = LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let base = std::env::temp_dir().join(format!("auradefs-tags-{tag}"));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(base.join("files")).unwrap();
        let before = std::env::var("XDG_DATA_HOME").ok();
        unsafe { std::env::set_var("XDG_DATA_HOME", base.join("data")) };
        let out = body(&base);
        unsafe {
            match before {
                Some(v) => std::env::set_var("XDG_DATA_HOME", v),
                None => std::env::remove_var("XDG_DATA_HOME"),
            }
        }
        out
    }

    fn file(base: &Path, name: &str) -> PathBuf {
        let path = base.join("files").join(name);
        std::fs::write(&path, b"x").unwrap();
        path
    }

    #[test]
    fn a_tag_is_findable_from_the_index_and_readable_from_the_file() {
        with_data_home("basic", |base| {
            let one = file(base, "one.txt");
            let two = file(base, "two.txt");
            set(&one, &["Work".into(), "Urgent".into()]).unwrap();
            set(&two, &["Work".into()]).unwrap();

            let index = all().unwrap();
            assert_eq!(index["Work"].len(), 2);
            assert_eq!(index["Urgent"], [one.display().to_string()]);
            assert_eq!(with_tag("Work").unwrap().len(), 2);
            assert!(with_tag("Nothing").unwrap().is_empty());
            assert!(with_tag("  ").is_err());
        });
    }

    #[test]
    fn removing_a_tag_takes_it_out_of_the_index() {
        with_data_home("remove", |base| {
            let one = file(base, "one.txt");
            set(&one, &["Work".into(), "Urgent".into()]).unwrap();
            set(&one, &["Work".into()]).unwrap();
            let index = all().unwrap();
            assert!(!index.contains_key("Urgent"), "a removed tag stayed: {index:?}");
            assert_eq!(index["Work"].len(), 1);

            //: And clearing them all leaves no empty tag behind.
            set(&one, &[]).unwrap();
            assert!(all().unwrap().is_empty());
        });
    }

    #[test]
    fn tagging_the_same_file_twice_is_not_two_entries() {
        with_data_home("twice", |base| {
            let one = file(base, "one.txt");
            set(&one, &["Work".into()]).unwrap();
            set(&one, &["Work".into()]).unwrap();
            assert_eq!(all().unwrap()["Work"].len(), 1);
        });
    }

    #[test]
    fn a_name_that_cannot_be_written_to_the_file_is_dropped_before_the_index_sees_it() {
        let given: Vec<String> = ["  Blue ", "Red", "Blue", "no,pe", "", "   "]
            .iter()
            .map(|s| s.to_string())
            .collect();
        assert_eq!(clean(&given), ["Blue", "Red"]);
        //: The order given, not sorted: the dialog lists them back in the
        //: order they were typed.
        assert_eq!(clean(&["Zeta".to_string(), "Alpha".to_string()]), ["Zeta", "Alpha"]);
        assert!(clean(&[",".to_string()]).is_empty());
    }

    #[test]
    fn a_file_that_has_gone_away_drops_out_and_the_index_is_rewritten() {
        with_data_home("pruned", |base| {
            let one = file(base, "one.txt");
            let two = file(base, "two.txt");
            set(&one, &["Work".into()]).unwrap();
            set(&two, &["Work".into()]).unwrap();
            std::fs::remove_file(&two).unwrap();

            assert_eq!(all().unwrap()["Work"], [one.display().to_string()]);
            //: Written back, so the next read does not have to prune it again.
            let raw = std::fs::read_to_string(index_path().unwrap()).unwrap();
            assert!(!raw.contains("two.txt"), "the pruned path stayed in the file: {raw}");
        });
    }

    #[test]
    fn a_corrupt_index_is_a_cache_miss_rather_than_a_failure() {
        with_data_home("corrupt", |base| {
            let path = index_path().unwrap();
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(&path, b"not json at all").unwrap();
            assert!(all().unwrap().is_empty());
            //: And it recovers: the next write rebuilds it.
            let one = file(base, "one.txt");
            set(&one, &["Work".into()]).unwrap();
            assert_eq!(all().unwrap()["Work"].len(), 1);
        });
    }

    #[test]
    fn the_index_file_is_the_one_the_python_backend_wrote() {
        with_data_home("shape", |base| {
            let one = file(base, "one.txt");
            set(&one, &["Work".into()]).unwrap();
            let raw = std::fs::read_to_string(index_path().unwrap()).unwrap();
            let parsed: serde_json::Value = serde_json::from_str(&raw).unwrap();
            //: A plain object of tag to list of absolute paths, which is what
            //: the other backend reads and writes.
            assert_eq!(parsed["Work"][0], one.display().to_string());
            assert!(index_path().unwrap().ends_with("aurade/filetags.json"));
        });
    }

    #[test]
    fn reconciling_rebuilds_from_what_the_files_say() {
        with_data_home("reconcile", |base| {
            let one = file(base, "one.txt");
            if crate::xattr::set(&one, "user.auradefs.probe", b"1").is_err() {
                eprintln!("skipped: no extended attributes here");
                return;
            }
            set(&one, &["Work".into()]).unwrap();

            //: Another program changes the tag on the file without telling the
            //: index. The index now says Work and the file says Personal.
            crate::xattr::set_tags(&one, &["Personal".into()]).unwrap();
            assert_eq!(all().unwrap()["Work"].len(), 1, "the stale entry should still be there");

            let changed = reconcile().unwrap();
            assert_eq!(changed, 1);
            let index = all().unwrap();
            assert!(!index.contains_key("Work"), "the stale tag survived: {index:?}");
            assert_eq!(index["Personal"], [one.display().to_string()]);
        });
    }

    #[test]
    fn reconciling_a_clean_index_changes_nothing() {
        with_data_home("reconcile-clean", |base| {
            let one = file(base, "one.txt");
            if crate::xattr::set(&one, "user.auradefs.probe", b"1").is_err() {
                eprintln!("skipped: no extended attributes here");
                return;
            }
            set(&one, &["Work".into()]).unwrap();
            assert_eq!(reconcile().unwrap(), 0);
            assert_eq!(all().unwrap()["Work"].len(), 1);
        });
    }
}
