//! The routes, and the shapes they answer in.
//!
//! Everything a route does is a call into `auradefs-core`. Nothing here decides
//! policy: the checks that matter live in the library, so the D-Bus interface
//! that comes later gets the same answers as this one rather than a second,
//! slightly different set of rules.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

use auradefs_core::{
    Error, Result,
    apps::{self, Registry},
    cover, git, media, mime,
    mime::MimeDb,
    ops::{archive, fs as fsops, image as imageops, list, search, trash, volume},
    tags,
    places, props, system, thumbs, volumes, xattr,
};
use serde_json::{Value, json};

use crate::http::{Request, Response};
use crate::jobs::Jobs;

/// Everything the routes share. Loaded once at startup, because reading the
/// mime database and scanning every desktop file per request would cost more
/// than the request.
pub struct Service {
    pub mime: MimeDb,
    pub apps: RwLock<Registry>,
    pub jobs: Jobs,
    pub started: std::time::Instant,
}

impl Service {
    pub fn new() -> Service {
        Service {
            mime: MimeDb::load(),
            apps: RwLock::new(Registry::load()),
            jobs: Jobs::new(),
            started: std::time::Instant::now(),
        }
    }
}

// ---------------------------------------------------------------- helpers ---

/// A required path parameter, made absolute. Relative paths are refused rather
/// than resolved against whatever this process's working directory happens to
/// be, which is not something the caller can see.
fn path_param(req: &Request, name: &str) -> Result<PathBuf> {
    let value = req
        .param(name)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| Error::BadRequest(format!("{name} is required")))?;
    absolute(value)
}

fn absolute(value: &str) -> Result<PathBuf> {
    let path = PathBuf::from(expand_home(value));
    if !path.is_absolute() {
        return Err(Error::BadRequest(format!("{value} must be an absolute path")));
    }
    Ok(path)
}

/// `~` and `~/x`, which is what a location bar accepts.
fn expand_home(value: &str) -> String {
    let Ok(home) = std::env::var("HOME") else { return value.to_string() };
    if value == "~" {
        return home;
    }
    match value.strip_prefix("~/") {
        Some(rest) => format!("{home}/{rest}"),
        None => value.to_string(),
    }
}

fn body_str(body: &Value, name: &str) -> Result<String> {
    body.get(name)
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty())
        .map(str::to_string)
        .ok_or_else(|| Error::BadRequest(format!("{name} is required")))
}

fn body_path(body: &Value, name: &str) -> Result<PathBuf> {
    absolute(&body_str(body, name)?)
}

fn body_paths(body: &Value, name: &str) -> Result<Vec<PathBuf>> {
    let array = body
        .get(name)
        .and_then(Value::as_array)
        .ok_or_else(|| Error::BadRequest(format!("{name} must be a list of paths")))?;
    if array.is_empty() {
        return Err(Error::BadRequest(format!("{name} is empty")));
    }
    array
        .iter()
        .map(|v| {
            v.as_str()
                .ok_or_else(|| Error::BadRequest(format!("{name} must be a list of paths")))
                .and_then(absolute)
        })
        .collect()
}

/// A whole number in the body, as a number or the string form of one; absent
/// is None and anything else is a 400, since a dictionary size that is not a
/// number is not a request this can quietly make sense of.
fn body_u32(body: &Value, name: &str) -> Result<Option<u32>> {
    match body.get(name) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => v
            .as_u64()
            .or_else(|| v.as_str().and_then(|s| s.trim().parse().ok()))
            .and_then(|n| u32::try_from(n).ok())
            .map(Some)
            .ok_or_else(|| Error::BadRequest(format!("{name} is not a whole number"))),
    }
}

fn body_bool(body: &Value, name: &str, default: bool) -> bool {
    body.get(name).and_then(Value::as_bool).unwrap_or(default)
}

fn flag(req: &Request, name: &str) -> bool {
    matches!(req.param(name), Some("1") | Some("true"))
}

/// What to do about a name that is taken. It arrives in the query string,
/// which is where the page has always put it, and in the body for callers that
/// find that odd. Unset means keep both: on the wire the safe answer is the one
/// that loses nothing, and refusing outright would make a drag and drop onto a
/// folder fail rather than ask.
fn conflict_from(req: &Request, body: &Value) -> Result<fsops::Conflict> {
    let raw = req
        .param("conflict")
        .map(str::to_string)
        .or_else(|| body.get("conflict").and_then(Value::as_str).map(str::to_string))
        .unwrap_or_default();
    let raw = raw.trim().to_ascii_lowercase().replace(['_', ' '], "-");
    Ok(match raw.as_str() {
        "" | "keep-both" | "keepboth" | "keep-both-new-name" | "generate-new-name" | "rename" => {
            fsops::Conflict::KeepBoth
        }
        "skip" => fsops::Conflict::Skip,
        "replace" | "replace-existing" => fsops::Conflict::Replace,
        "fail-if-exists" | "fail" | "none" => fsops::Conflict::Fail,
        other => return Err(Error::BadRequest(format!("unknown conflict mode: {other}"))),
    })
}

/// The first of these keys that is present, as an absolute path. Two backends
/// named the same things differently and the page uses both spellings.
fn body_path_any(body: &Value, keys: &[&str]) -> Result<PathBuf> {
    for key in keys {
        if let Some(value) = body.get(*key).and_then(Value::as_str).filter(|v| !v.is_empty()) {
            return absolute(value);
        }
    }
    Err(Error::BadRequest(format!("{} is required", keys.join(" or "))))
}

/// Split a full destination path into the folder that will hold it and the
/// name. `{path, name}` says both directly; `{path}` alone means the whole
/// thing, which is how the prototype backend was asked.
fn parent_and_name(body: &Value) -> Result<(PathBuf, String)> {
    let path = body_path(body, "path")?;
    match body.get("name").and_then(Value::as_str).filter(|n| !n.is_empty()) {
        Some(name) => Ok((path, name.to_string())),
        None => {
            let name = path
                .file_name()
                .ok_or_else(|| Error::BadRequest("no name in the path".into()))?
                .to_string_lossy()
                .to_string();
            let parent = path
                .parent()
                .ok_or_else(|| Error::BadRequest("no folder in the path".into()))?
                .to_path_buf();
            Ok((parent, name))
        }
    }
}

/// Did the caller ask for this to run in the background? The presence of the
/// parameter is the request, with or without a value, which is how the page
/// spells it.
/// A git transfer, told to a job the way a copy tells it.
///
/// Objects are what git counts and bytes are what it moves, so both cross:
/// the bar reads the objects and the line under it reads the bytes. The byte
/// total stays zero because git does not know it until the transfer is over,
/// and a total invented here would be a bar that lies.
fn transferred<'a>(job: &'a crate::jobs::Job, what: &'a str) -> impl FnMut(git::Transfer) -> bool + 'a {
    move |t| {
        let progress = fsops::Progress {
            total_items: t.total as u64,
            done_items: t.objects as u64,
            total_bytes: 0,
            done_bytes: t.bytes,
            current: PathBuf::from(what),
        };
        job.report(&progress) == fsops::Flow::Continue
    }
}

/// What a fetch brought back, as the page reads it.
fn fetched_json(f: &git::Fetched) -> Value {
    json!({
        "remote": f.remote,
        "objects": f.objects,
        "bytes": f.bytes,
        "branch": f.branch,
        "ahead": f.ahead,
        "behind": f.behind,
    })
}

/// The remote a request names, or none, meaning the repository's own.
fn remote_param(body: &Value) -> Option<String> {
    body.get("remote").and_then(Value::as_str).filter(|v| !v.is_empty()).map(str::to_string)
}

fn wants_job(req: &Request) -> bool {
    req.query.contains_key("job")
}

fn file_key(path: &Path) -> String {
    format!("file://{}", path.display())
}

/// The status a refusal deserves. The page branches on the code, but a status
/// that matches the meaning keeps the network tab readable and lets a proxy or
/// a fetch wrapper do the right thing.
pub fn status_for(error: &Error) -> u16 {
    match error {
        Error::NotFound(_) => 404,
        Error::Denied(_) | Error::ReadOnly(_) => 403,
        Error::Exists(_) | Error::Conflict(_) => 409,
        Error::Escapes(_) | Error::BadRequest(_) => 400,
        Error::Unsupported(_) => 501,
        //: The one status that means "ask and come back", which is exactly
        //: what the password dialog does with it.
        Error::NeedsPassword(_) => 401,
        Error::Io { .. } | Error::Tool { .. } => 500,
    }
}

fn error_body(error: &Error) -> Value {
    json!({
        "error": error.to_string(),
        "code": error.code(),
        "errno": error.errno(),
    })
}

// --------------------------------------------------------------- listings ---

fn row_json(row: &list::Row, dir: &Path) -> Value {
    let full = dir.join(&row.name);
    let mut value = json!({
        //: The first six keys are the shape the page already reads. Everything
        //: after them is additive, so an older page ignores it and a newer one
        //: does not need a second request per row.
        "key": file_key(&full),
        "name": row.name,
        "isDirectory": row.kind == list::Kind::Folder,
        "isLink": matches!(row.kind, list::Kind::Link { .. }),
        "linkTarget": row.link_target.as_ref().map(|t| t.display().to_string()),
        //: A link whose far end is gone. Files cannot put one in an archive
        //: and asks before leaving it out, so the page has to know which
        //: rows those are before it starts.
        "broken": matches!(row.kind, list::Kind::Link { broken: true, .. }),
        "parent": file_key(dir),

        "kind": row.kind.name(),
        "size": row.size,
        "modificationTime": row.modified * 1000,
        "created": row.created.map(|c| c * 1000),
        "mode": row.mode,
        "hidden": row.hidden,
        "mimeType": row.mime,
        "tags": row.tags,
        "customIcon": row.custom_icon,
    });
    if let list::Kind::Link { broken, to_folder } = row.kind {
        value["linkBroken"] = json!(broken);
        value["linkToFolder"] = json!(to_folder);
    }
    if let Some(entry) = row.git {
        value["git"] = json!({
            "status": entry.status.name(),
            "letter": entry.status.letter(),
            "staged": entry.staged,
        });
    }
    value
}

/// The metadata snapshot, keyed the way the page expects.
fn meta_json(rows: &[list::Row], dir: &Path) -> Value {
    let mut out = serde_json::Map::new();
    for row in rows {
        let full = dir.join(&row.name);
        let is_dir = row.kind == list::Kind::Folder;
        let mut meta = json!({
            "modificationTime": row.modified * 1000,
            "isLink": matches!(row.kind, list::Kind::Link { .. }),
            "linkTarget": row.link_target.as_ref().map(|t| t.display().to_string()),
            "hidden": row.hidden,
            "onDisk": 0,
            "readonly": !writable(&full),
        });
        if !is_dir {
            meta["size"] = json!(row.size);
            meta["mimeType"] = json!(row.mime);
        }
        out.insert(file_key(&full), meta);
    }
    Value::Object(out)
}

/// One entry in the shape the page reads, built from a path rather than from a
/// listing row. The tag view is a list of paths from an index, not a folder, so
/// it cannot go through the same walk and still has to answer identically.
fn entry_for_path(path: &Path, mime: &MimeDb) -> Option<(Value, Value)> {
    let meta = std::fs::symlink_metadata(path).ok()?;
    use std::os::unix::fs::MetadataExt;
    let is_link = meta.file_type().is_symlink();
    //: Whether it is a directory is asked of the target, because a link to a
    //: folder opens as one.
    let is_dir = std::fs::metadata(path).map(|m| m.is_dir()).unwrap_or(false);
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| path.display().to_string());
    let link_target = if is_link {
        std::fs::read_link(path).ok().map(|t| t.display().to_string())
    } else {
        None
    };
    let entry = json!({
        "key": file_key(path),
        "name": name,
        "isDirectory": is_dir,
        "isLink": is_link,
        "linkTarget": link_target,
        "parent": file_key(path.parent().unwrap_or(Path::new("/"))),
    });
    let mut row_meta = json!({
        "modificationTime": meta.mtime() * 1000,
        "isLink": is_link,
        "linkTarget": entry["linkTarget"],
        "hidden": name.starts_with('.'),
        "onDisk": meta.blocks() * 512,
        "readonly": !writable(path),
    });
    if !is_dir {
        row_meta["size"] = json!(meta.len());
        if let Some(found) = mime.by_name(&name) {
            row_meta["mimeType"] = json!(found);
        }
    }
    Some((entry, row_meta))
}

/// Can this user change the thing at `path`? Both the file and the directory
/// holding it have to allow it, because a rename is a write to the directory.
fn writable(path: &Path) -> bool {
    use rustix::fs::Access;
    let ok = |p: &Path| rustix::fs::access(p, Access::WRITE_OK).is_ok();
    ok(path) && path.parent().map(ok).unwrap_or(false)
}

fn stat_json(path: &Path, mime: &MimeDb) -> Result<Value> {
    let meta = std::fs::symlink_metadata(path)
        .map_err(|e| Error::io(path.display().to_string(), e))?;
    use std::os::unix::fs::MetadataExt;
    let is_dir = meta.is_dir();
    let mut out = json!({
        "path": path.display().to_string(),
        "key": file_key(path),
        "name": path.file_name().map(|n| n.to_string_lossy().to_string()),
        "isDirectory": is_dir,
        "isLink": meta.file_type().is_symlink(),
        //: A folder's own entry size is not its size, and showing it as one is
        //: worse than showing nothing.
        "size": if is_dir { Value::Null } else { json!(meta.len()) },
        "onDisk": meta.blocks() * 512,
        "created": meta.ctime() * 1000,
        "accessed": meta.atime() * 1000,
        "modified": meta.mtime() * 1000,
        //: Written the way a properties dialog shows it. The number is next to
        //: it under its own key for anything that wants to compute with it.
        "mode": format!("0o{:o}", meta.mode() & 0o7777),
        "modeBits": meta.mode() & 0o7777,
        "uid": meta.uid(),
        "gid": meta.gid(),
        "nlink": meta.nlink(),
        "linkTarget": std::fs::read_link(path).ok().map(|t| t.display().to_string()),
        "readonly": !writable(path),
        "mimeType": if is_dir { mime::DIRECTORY.to_string() } else { mime.of_path(path)? },
    });
    for (key, value) in shortcut_fields(path) {
        out[key] = value;
    }
    Ok(out)
}

/// A password from the body, treating an absent one and an empty one alike.
///
/// An empty string is what a password box sends when it was never typed in, so
/// it means no password rather than a password of no characters. The write
/// path refuses an empty one it was given deliberately; this is the read of
/// what the caller sent.
fn body_password(body: &Value) -> Option<String> {
    body.get("password")
        .and_then(Value::as_str)
        .map(str::to_string)
        .filter(|p| !p.is_empty())
}

/// The answer for a file that gets no picture.
///
/// Not an error: most files have no thumbnail, and the caller should not have
/// to tell that apart from a failure before it can show a type icon.
fn no_thumb(path: &Path, reason: &str) -> Value {
    json!({
        "path": path.display().to_string(),
        "supported": false,
        "reason": reason,
    })
}

/// Where a shortcut points, for the Shortcut tab.
///
/// Two things count as a shortcut here: a symlink, and a `.desktop` file.
/// Anything else returns nothing at all, which is how the page knows not to
/// offer the tab.
fn shortcut_fields(path: &Path) -> Vec<(&'static str, Value)> {
    let Ok(meta) = std::fs::symlink_metadata(path) else { return Vec::new() };
    if meta.file_type().is_symlink() {
        let Ok(target) = std::fs::read_link(path) else { return Vec::new() };
        let resolved = if target.is_absolute() {
            target.clone()
        } else {
            //: Relative to the link's own folder, which is where the kernel
            //: resolves it from.
            normalise(&path.parent().unwrap_or(Path::new("/")).join(&target))
        };
        return vec![
            ("linkKind", json!("symlink")),
            ("linkTarget", json!(target.display().to_string())),
            ("linkResolved", json!(resolved.display().to_string())),
            ("linkArgs", json!("")),
            ("linkWorkingDir", json!(resolved
                .parent()
                .map(|p| p.display().to_string())
                .unwrap_or_default())),
            ("linkBroken", json!(!resolved.exists())),
        ];
    }
    if path.extension().map(|e| e != "desktop").unwrap_or(true) {
        return Vec::new();
    }
    let Ok(text) = std::fs::read_to_string(path) else { return Vec::new() };
    let Some(entry) = apps::DesktopEntry::parse(path, "shortcut", &text) else {
        return Vec::new();
    };
    let Some(exec) = entry.exec.as_deref().filter(|e| !e.trim().is_empty()) else {
        return Vec::new();
    };
    //: The program and its arguments as written, because the tab shows the
    //: launcher's own line rather than what it would expand to.
    let (program, args) = match exec.split_once(' ') {
        Some((p, rest)) => (p.to_string(), rest.to_string()),
        None => (exec.to_string(), String::new()),
    };
    let found = apps::which(&program);
    vec![
        ("linkKind", json!("desktop")),
        ("linkTarget", json!(program)),
        ("linkResolved", json!(found
            .as_ref()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| program.clone()))),
        ("linkArgs", json!(args)),
        ("linkWorkingDir", json!(entry
            .path_dir
            .as_ref()
            .map(|p| p.display().to_string())
            .unwrap_or_default())),
        ("linkBroken", json!(found.is_none() && !Path::new(&program).exists())),
    ]
}

/// Remove `.` and `..` from a path without touching the disk. Used only to
/// report where a relative symlink leads, never to open anything.
fn normalise(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for part in path.components() {
        match part {
            std::path::Component::ParentDir => {
                out.pop();
            }
            std::path::Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

// ----------------------------------------------------------------- routes ---

/// Dispatch. Returns the response, including the one for an unknown route.
pub fn route(service: &Arc<Service>, req: &Request) -> Response {
    if req.method == "OPTIONS" {
        return Response::empty(204);
    }
    let body: Value = if req.body.is_empty() {
        Value::Null
    } else {
        match serde_json::from_slice(&req.body) {
            Ok(v) => v,
            Err(_) => {
                return Response::json(
                    400,
                    &json!({"error": "the body is not JSON", "code": "bad-request", "errno": 22}),
                );
            }
        }
    };

    match handle(service, req, &body) {
        Ok(Answer::Json(value)) => Response::json(200, &value),
        Ok(Answer::Bytes(content_type, bytes)) => Response::bytes(200, &content_type, bytes),
        Ok(Answer::NotFound) => Response::json(
            404,
            &json!({"error": "unknown endpoint", "code": "not-found", "errno": 2}),
        ),
        Err(e) => Response::json(status_for(&e), &error_body(&e)),
    }
}

pub enum Answer {
    Json(Value),
    Bytes(String, Vec<u8>),
    NotFound,
}

fn handle(service: &Arc<Service>, req: &Request, body: &Value) -> Result<Answer> {
    let method = req.method.as_str();
    let path = req.path.as_str();
    let value = match (method, path) {
        // ------------------------------------------------------- the service
        ("GET", "/api/health") => json!({
            "ok": true,
            "backend": "auradefs",
            "version": env!("CARGO_PKG_VERSION"),
            "uptimeSeconds": service.started.elapsed().as_secs(),
        }),
        ("GET", "/api/system") => json!({
            //: The four the About page reads, read and never assumed.
            "os": pretty_os_name(),
            "kernel": first_line("/proc/sys/kernel/osrelease"),
            "arch": std::env::consts::ARCH,
            "host": hostname(),

            "home": std::env::var("HOME").ok(),
            "user": rustix::process::getuid().as_raw(),
            "hostname": hostname(),
            "archiveFormats": archive_formats(),
            "hashes": ["crc32", "md5", "sha1", "sha256", "sha384", "sha512"],
            "capabilities": [
                "list", "search", "trash", "archive", "git", "tags", "streams",
                "thumbnails", "volumes", "acl", "hashes", "apps", "places",
                "fonts", "certificates", "signatures", "wallpaper", "jobs",
                "details", "rotate", "attributes", "split", "git-remote",
                //: Making a branch is local, but the prototype backend cannot,
                //: so the page asks rather than assuming it from "git".
                "git-branch",
                //: The cover inside a sound file, read for its thumbnail and
                //: changed or removed from its Properties. The prototype
                //: backend has no tag writer, so the page asks.
                "album-cover",
            ],
            //: Named separately from the capability because it can be true on
            //: one machine and false on the next with the same build.
            "mediaProbe": media::can_probe(),
            //: Read once per health check rather than assumed: Run with
            //: PowerShell is a real command on this system when `pwsh` is
            //: installed and a row that cannot work when it is not, and the
            //: page needs to know which before it draws the menu.
            "powershell": apps::have_powershell(),
        }),
        ("GET", "/api/archive-formats") => archive_formats(),
        //: What a 7z write will need, for the dialog's two lines, from the
        //: same options the write itself uses, so the number the user reads
        //: is the number the refusal would quote.
        ("GET", "/api/archive-estimate") => {
            let level = match req.param("level") {
                Some(named) => archive::Level::from_name(named)
                    .ok_or_else(|| Error::BadRequest(format!("unknown level: {named}")))?,
                None => archive::Level::default(),
            };
            let number = |name: &str| -> Result<Option<u32>> {
                match req.param(name).filter(|v| !v.is_empty()) {
                    None => Ok(None),
                    Some(v) => v
                        .parse::<u32>()
                        .map(Some)
                        .map_err(|_| Error::BadRequest(format!("{name} is not a number: {v}"))),
                }
            };
            let options = archive::Options {
                level,
                dictionary: number("dictionary")?,
                word_size: number("word_size")?,
                threads: number("threads")?.unwrap_or(1),
                ..Default::default()
            };
            let estimate = options.lzma2_estimate();
            json!({
                "level": level.name(),
                "dictionary": estimate.dictionary,
                "word_size": estimate.word_size,
                "threads": estimate.threads,
                "chunk": estimate.chunk,
                "bytes": estimate.bytes,
                "available": archive::available_memory(),
                "cpus": std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1),
            })
        }

        // ------------------------------------------------------------ listing
        ("GET", "/api/list") => {
            let dir = req
                .param("path")
                .filter(|p| !p.is_empty())
                .map(absolute)
                .transpose()?
                .unwrap_or(places::home()?);
            let options = list::Options {
                show_hidden: flag(req, "hidden"),
                include_tags: !flag(req, "plain"),
                include_git: !flag(req, "plain"),
                limit: req
                    .param("limit")
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(250_000),
                sort: match req.param("sort") {
                    Some("size") => list::Sort::Size,
                    Some("modified") => list::Sort::Modified,
                    Some("created") => list::Sort::Created,
                    Some("kind") => list::Sort::Kind,
                    _ => list::Sort::Name,
                },
                descending: flag(req, "desc"),
                folders_first: !flag(req, "mixed"),
                ..Default::default()
            };
            let page = list::list(&dir, &options, &service.mime)?;
            let entries: Vec<Value> = page.rows.iter().map(|r| row_json(r, &dir)).collect();
            //: The directory's modification time in nanoseconds, which is the
            //: cheapest honest answer: it changes exactly when the listing
            //: does. A number, because that is what the page compares.
            let revision = std::fs::metadata(&dir)
                .map(|m| {
                    use std::os::unix::fs::MetadataExt;
                    m.mtime() as i64 * 1_000_000_000 + m.mtime_nsec() as i64
                })
                .unwrap_or(0);
            json!({
                "path": dir.display().to_string(),
                "revision": revision,
                "entries": entries,
                "meta": meta_json(&page.rows, &dir),
                "total": page.total,
                "hiddenCount": page.hidden_count,
                "truncated": page.truncated,
                "git": page.git.as_ref().map(|g| json!({
                    "root": g.root.display().to_string(),
                    "branch": g.branch,
                    "head": g.head,
                    "detached": g.detached,
                    "ahead": g.ahead,
                    "behind": g.behind,
                })),
            })
        }
        ("GET", "/api/stat") => stat_json(&path_param(req, "path")?, &service.mime)?,
        ("GET", "/api/search") => {
            //: `root` is what the page has always sent; `path` is the spelling
            //: every other route here uses. Both work.
            let root = match req.param("root").filter(|p| !p.is_empty()) {
                Some(value) => absolute(value)?,
                None => path_param(req, "path")?,
            };
            let mut query = search::Query::parse(
                req.param("q").ok_or_else(|| Error::BadRequest("q is required".into()))?,
            );
            //: A separate parameter as well as the `content:` prefix inside
            //: the query, because the search box has a checkbox for it.
            if let Some(text) = req.param("content").filter(|t| !t.is_empty()) {
                query.content = Some(text.to_string());
            }
            let limits = search::Limits {
                max_results: req.param("limit").and_then(|v| v.parse().ok()).unwrap_or(2_000),
                max_depth: req.param("depth").and_then(|v| v.parse().ok()).unwrap_or(32),
                include_hidden: flag(req, "hidden"),
                ..Default::default()
            };
            let mut results = Vec::new();
            let report = search::search(&root, &query, &limits, &mut |hit| {
                results.push(json!({
                    "key": file_key(&hit.path),
                    "name": hit.name,
                    "isDirectory": hit.is_dir,
                    "path": hit.path.display().to_string(),
                    "size": hit.size,
                    "modificationTime": hit.modified * 1000,
                    "line": hit.line.as_ref().map(|(n, text)| json!({"number": n, "text": text})),
                }));
                true
            })?;
            json!({
                "root": root.display().to_string(),
                "results": results,
                "examined": report.examined,
                "stopped": format!("{:?}", report.stopped).to_lowercase(),
            })
        }

        // ------------------------------------------------------- the contents
        ("GET", "/api/preview") => {
            let file = path_param(req, "path")?;
            let limit: u64 = req.param("limit").and_then(|v| v.parse().ok()).unwrap_or(512 * 1024);
            let meta = std::fs::metadata(&file)
                .map_err(|e| Error::io(file.display().to_string(), e))?;
            if meta.is_dir() {
                return Err(Error::BadRequest("is a directory".into()));
            }
            let mime_type = service.mime.of_path(&file)?;
            let wanted = meta.len().min(limit) as usize;
            let mut bytes = vec![0u8; wanted];
            {
                use std::io::Read;
                let mut handle = std::fs::File::open(&file)
                    .map_err(|e| Error::io(file.display().to_string(), e))?;
                let read = handle
                    .read(&mut bytes)
                    .map_err(|e| Error::io(file.display().to_string(), e))?;
                bytes.truncate(read);
            }
            let binary = bytes.contains(&0) || String::from_utf8(bytes.clone()).is_err();
            json!({
                "path": file.display().to_string(),
                "binary": binary,
                "text": if binary { String::new() } else { String::from_utf8_lossy(&bytes).into_owned() },
                "size": meta.len(),
                "truncated": meta.len() > wanted as u64,
                "mimeType": mime_type,
            })
        }
        ("GET", "/api/hash") => {
            let file = path_param(req, "path")?;
            let names = req.param("algo").unwrap_or("sha256");
            let mut wanted = Vec::new();
            for name in names.split(',').filter(|n| !n.is_empty()) {
                wanted.push(
                    props::Algorithm::parse(name)
                        .ok_or_else(|| Error::BadRequest(format!("unknown algo: {name}")))?,
                );
            }
            let computed = props::hashes(&file, &wanted)?;
            let mut out = serde_json::Map::new();
            for (algorithm, digest) in &computed {
                out.insert(algorithm.name().to_string(), json!(digest));
            }
            //: One algorithm asked for gets the singular answer as well, which
            //: is what the hashes tab reads.
            let single = computed.first().filter(|_| computed.len() == 1);
            json!({
                "path": file.display().to_string(),
                "algo": single.map(|(a, _)| a.name()),
                "hex": single.map(|(_, h)| h.clone()),
                "hashes": out,
            })
        }

        // ---------------------------------------------------------- thumbnails
        ("GET", "/api/thumb") | ("GET", "/api/thumbnail") => {
            let file = path_param(req, "path")?;
            let size = thumbs::Size::for_display(
                req.param("size").and_then(|v| v.parse().ok()).unwrap_or(128),
            );
            //: The extension decides before anything is opened. The same words
            //: the page already shows, so the reason a row has no picture does
            //: not change with the backend behind it.
            let Some(kind) = thumbs::Kind::of_path(&file) else {
                return Ok(Answer::Json(no_thumb(&file, "not an image")));
            };
            let meta = std::fs::metadata(&file)
                .map_err(|e| Error::io(file.display().to_string(), e))?;
            if meta.is_dir() {
                return Err(Error::BadRequest("a folder has no thumbnail".into()));
            }
            if meta.len() > thumbs::MAX_SOURCE_BYTES {
                return Ok(Answer::Json(no_thumb(&file, "too large")));
            }
            let made = match thumbs::thumbnail(&file, size) {
                Ok(Some(made)) => made,
                //: A sound file without a cover is the ordinary case, not a
                //: file that failed to decode, and the page's words for the
                //: two differ.
                Ok(None) if kind == thumbs::Kind::Audio => {
                    return Ok(Answer::Json(no_thumb(&file, "no cover")));
                }
                Ok(None) => return Ok(Answer::Json(no_thumb(&file, "could not decode"))),
                //: A missing pdftoppm or ffmpeg is neither a fault in the
                //: request nor a fault in the file. The row gets no picture and
                //: the caller carries on.
                Err(Error::Tool { .. }) => {
                    return Ok(Answer::Json(no_thumb(&file, "no converter")));
                }
                Err(e) => return Err(e),
            };
            let bytes =
                std::fs::read(&made).map_err(|e| Error::io(made.display().to_string(), e))?;
            if flag(req, "raw") {
                return Ok(Answer::Bytes("image/png".into(), bytes));
            }
            let (tw, th) = image_size(&made).unwrap_or((0, 0));
            //: The source's own size, and nothing when there is not one to
            //: read. A PDF page and a video frame have no dimensions stored in
            //: the file, and reporting the thumbnail's as theirs would be a
            //: number that means something else.
            let natural = match kind {
                thumbs::Kind::Image => image_size(&file),
                _ => None,
            };
            json!({
                "path": file.display().to_string(),
                "supported": true,
                //: The thumbnail's own type, not the source's: this is what
                //: goes in the src.
                "mime": "image/png",
                "kind": kind.name(),
                "width": natural.map(|(w, _)| w),
                "height": natural.map(|(_, h)| h),
                "thumb_width": tw,
                "thumb_height": th,
                //: The file's size, not the thumbnail's, because every other
                //: byte count this service reports is the thing itself.
                "bytes": meta.len(),
                "uri": crate::b64::data_uri("image/png", &bytes),
                "thumbnail": made.display().to_string(),
                "size": size.pixels(),
            })
        }
        ("POST", "/api/thumb-cache/clear") => {
            let root = thumbs::cache_home()?.join("thumbnails");
            match body_paths(body, "paths") {
                //: Named files: only their thumbnails go.
                Ok(paths) => {
                    for path in &paths {
                        thumbs::forget(path)?;
                    }
                    json!({"removed": paths.len(), "bytes": 0, "path": root.display().to_string()})
                }
                //: Nothing named means the whole cache, which is what the
                //: settings button does.
                Err(_) => {
                    let (removed, bytes) = clear_thumbnail_cache(&root);
                    json!({"removed": removed, "bytes": bytes, "path": root.display().to_string()})
                }
            }
        }

        ("POST", "/api/rotate") => {
            //: A selection, because that is how the toolbar button is pressed.
            //: One path is a selection of one.
            let files = match body_paths(body, "paths") {
                Ok(paths) => paths,
                Err(_) => vec![body_path_any(body, &["path", "file"])?],
            };
            let turn = body
                .get("turn")
                .and_then(Value::as_str)
                .map(|name| {
                    imageops::Turn::from_name(name)
                        .ok_or_else(|| Error::BadRequest(format!("unknown turn: {name}")))
                })
                .transpose()?
                .unwrap_or(imageops::Turn::Right);
            //: Every file is checked before any is written, so a selection
            //: with one folder in it does not leave half of it turned.
            for file in &files {
                let meta = std::fs::metadata(file)
                    .map_err(|e| Error::io(file.display().to_string(), e))?;
                if meta.is_dir() {
                    return Err(Error::BadRequest(format!(
                        "{} is a folder",
                        file.display()
                    )));
                }
            }
            let mut turned = Vec::with_capacity(files.len());
            for file in &files {
                let done = imageops::turn(file, turn)?;
                turned.push(json!({
                    "path": done.path.display().to_string(),
                    //: So the caller can say "turned without re-encoding",
                    //: which is the difference a photographer cares about.
                    "lossless": done.lossless,
                    "orientation": done.orientation,
                    "width": done.width,
                    "height": done.height,
                }));
            }
            json!({"turn": turn.name(), "turned": turned})
        }
        //: The cover inside a sound file, as the Properties window shows it:
        //: the bytes themselves with `raw`, else a data URI beside what the
        //: tag says about it. A file that can carry one and does not is an
        //: answer, not an error; a file that cannot carry one says so.
        ("GET", "/api/album-cover") => {
            let file = path_param(req, "path")?;
            let supported = cover::can_carry(&file);
            let found = if supported { cover::read(&file)? } else { None };
            if flag(req, "raw") {
                return match found {
                    Some(found) => Ok(Answer::Bytes(found.mime, found.bytes)),
                    None => Err(Error::NotFound(format!("{} has no cover", file.display()))),
                };
            }
            json!({
                "path": file.display().to_string(),
                "supported": supported,
                "cover": found.is_some(),
                "mime": found.as_ref().map(|c| c.mime.clone()),
                "bytes": found.as_ref().map(|c| c.bytes.len()),
                "front": found.as_ref().map(|c| c.front),
                "uri": found.as_ref().map(|c| crate::b64::data_uri(&c.mime, &c.bytes)),
            })
        }
        //: Change or remove the cover, on every file of a selection the way
        //: the reference's Properties window applies it to each of a
        //: multi-selection. `image` names the picture; no image, or
        //: `remove`, strips what is there. Every file is checked before any
        //: is written, so a selection with one WMA in it does not leave the
        //: first half of it changed.
        ("POST", "/api/album-cover") => {
            let files = match body_paths(body, "paths") {
                Ok(paths) => paths,
                Err(_) => vec![body_path_any(body, &["path", "file"])?],
            };
            let image = match body.get("image") {
                None | Some(Value::Null) => None,
                Some(v) => Some(absolute(v.as_str().ok_or_else(|| {
                    Error::BadRequest("image must be a path".into())
                })?)?),
            };
            let removing = body_bool(body, "remove", false) || image.is_none();
            for file in &files {
                let meta = std::fs::metadata(file)
                    .map_err(|e| Error::io(file.display().to_string(), e))?;
                if meta.is_dir() {
                    return Err(Error::BadRequest(format!("{} is a folder", file.display())));
                }
                if !cover::can_carry(file) {
                    return Err(Error::Unsupported(format!(
                        "{} cannot carry a cover",
                        file.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()
                    )));
                }
            }
            let mut changed = Vec::with_capacity(files.len());
            for file in &files {
                let had = match (&image, removing) {
                    (Some(picture), false) => {
                        cover::change(file, picture)?;
                        true
                    }
                    _ => cover::remove(file)?,
                };
                //: The cached thumbnail was the old cover, or the memory of
                //: there being none. Either is wrong now.
                thumbs::forget(file)?;
                changed.push(json!({
                    "path": file.display().to_string(),
                    "removed": removing && had,
                    "changed": !removing,
                }));
            }
            json!({
                "ok": true,
                "action": if removing { "remove" } else { "change" },
                "image": image.as_ref().map(|p| p.display().to_string()),
                "files": changed,
            })
        }
        ("GET", "/api/details") => {
            let file = path_param(req, "path")?;
            //: One route rather than folding this into stat, because stat is
            //: called for every row on screen and this runs a decoder and, for
            //: media, another process. The Details tab asks for one file.
            let photo = media::photo(&file)?;
            let media = media::media(&file)?;
            let pixels = thumbs::dimensions(&file);
            json!({
                "path": file.display().to_string(),
                //: The real size of the image, read from the decoder rather
                //: than from EXIF: EXIF says what the camera wrote and an edit
                //: does not always update it.
                "width": pixels.map(|(w, _)| w),
                "height": pixels.map(|(_, h)| h),
                "photo": photo,
                "media": media,
                //: So the tab can leave the media rows out entirely rather
                //: than show a column of blanks on a machine with no ffprobe.
                "canProbe": media::can_probe(),
            })
        }

        // ------------------------------------------------------- the metadata
        ("GET", "/api/xattr") => {
            let file = path_param(req, "path")?;
            let (source, referrer) = xattr::origin(&file)?;
            //: Names to values, not a list of names: the properties tab shows
            //: both columns, and a second request per attribute to fill the
            //: second one would be a request per attribute.
            let mut attributes = serde_json::Map::new();
            for name in xattr::list(&file)? {
                let value = xattr::get(&file, &name)?.unwrap_or_default();
                attributes.insert(name, json!(String::from_utf8_lossy(&value)));
            }
            json!({
                "path": file.display().to_string(),
                "xattrs": Value::Object(attributes),
                "streams": xattr::streams(&file)?
                    .into_iter()
                    .map(|s| json!({"name": s.name, "size": s.size}))
                    .collect::<Vec<_>>(),
                "comment": xattr::comment(&file)?,
                "origin": json!({"url": source, "referrer": referrer}),
            })
        }
        ("GET", "/api/stream") => {
            let file = path_param(req, "path")?;
            let name = req
                .param("name")
                .ok_or_else(|| Error::BadRequest("name is required".into()))?;
            let found = xattr::read_stream(&file, name)?;
            json!({
                "path": file.display().to_string(),
                "name": name,
                "found": found.is_some(),
                "text": found.as_ref().map(|v| String::from_utf8_lossy(v).into_owned()),
            })
        }
        ("POST", "/api/stream") => {
            let file = body_path(body, "path")?;
            let name = body_str(body, "name")?;
            match body.get("text").and_then(Value::as_str) {
                Some(text) => xattr::write_stream(&file, &name, text.as_bytes())?,
                None => xattr::remove_stream(&file, &name)?,
            }
            json!({"ok": true})
        }
        ("GET", "/api/tags") => {
            let file = path_param(req, "path")?;
            json!({"path": file.display().to_string(), "tags": xattr::tags(&file)?})
        }
        ("POST", "/api/tags") => {
            let file = body_path(body, "path")?;
            let wanted: Vec<String> = body
                .get("tags")
                .and_then(Value::as_array)
                .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
                .unwrap_or_default();
            //: Through the index, not straight to the attribute: a tag that
            //: only exists on the file cannot be found again without reading
            //: every file on the system.
            let stored = tags::set(&file, &wanted)?;
            json!({
                "path": file.display().to_string(),
                "tags": stored.tags,
                "stored": stored.on_the_file,
            })
        }
        ("GET", "/api/tags/all") => json!({"tags": tags::all()?}),
        ("GET", "/api/tags/list") => {
            let tag = req
                .param("tag")
                .map(str::trim)
                .filter(|t| !t.is_empty())
                .ok_or_else(|| Error::BadRequest("tag is required".into()))?;
            let mut entries = Vec::new();
            let mut meta = serde_json::Map::new();
            for path in tags::with_tag(tag)? {
                //: A path in the index that has since gone is skipped rather
                //: than listed as a row that cannot be opened.
                let Some((entry, row)) = entry_for_path(&path, &service.mime) else { continue };
                meta.insert(file_key(&path), row);
                entries.push(entry);
            }
            entries.sort_by(|a, b| {
                let folder = b["isDirectory"].as_bool().cmp(&a["isDirectory"].as_bool());
                folder.then_with(|| {
                    list::natural_cmp(
                        a["name"].as_str().unwrap_or(""),
                        b["name"].as_str().unwrap_or(""),
                    )
                })
            });
            json!({
                "path": format!("tag:{tag}"),
                "revision": 0,
                "tag": tag,
                "entries": entries,
                "meta": Value::Object(meta),
            })
        }
        ("POST", "/api/tags/reconcile") => json!({"changed": tags::reconcile()?}),
        ("GET", "/api/icon") => {
            let file = path_param(req, "path")?;
            json!({"path": file.display().to_string(), "icon": xattr::icon(&file)?})
        }
        ("POST", "/api/icon") => {
            let file = body_path(body, "path")?;
            let wanted = body.get("icon").and_then(Value::as_str).map(str::trim).unwrap_or("");
            let stored = match xattr::set_icon(&file, Some(wanted)) {
                Ok(()) => true,
                //: A folder on a filesystem with no extended attributes cannot
                //: carry an icon. That is worth saying rather than failing.
                Err(Error::Unsupported(_)) => false,
                Err(e) => return Err(e),
            };
            json!({
                "path": file.display().to_string(),
                "icon": xattr::icon(&file)?.unwrap_or_default(),
                "stored": stored,
            })
        }
        ("GET", "/api/icon/dir") => {
            let dir = path_param(req, "path")?;
            let options = list::Options { include_tags: true, include_git: false, ..Default::default() };
            let page = list::list(&dir, &options, &service.mime)?;
            let mut out = serde_json::Map::new();
            for row in page.rows.iter().filter(|r| r.custom_icon.is_some()) {
                //: Keyed by the whole path, because that is what a row carries
                //: as its identity. Keying by name would need the page to know
                //: which folder the answer was about.
                out.insert(dir.join(&row.name).display().to_string(), json!(row.custom_icon));
            }
            json!({"path": dir.display().to_string(), "icons": out})
        }

        // ------------------------------------------------------- properties
        ("GET", "/api/props") => {
            let file = path_param(req, "path")?;
            let own = props::ownership(&file)?;
            json!({
                "path": file.display().to_string(),
                "uid": own.uid,
                "gid": own.gid,
                "user": own.user,
                "group": own.group,
                "mode": own.mode,
                "symbolic": own.symbolic(),
                "acl": props::acl(&file).ok().map(|entries| entries
                    .into_iter()
                    .map(|e| json!({
                        "kind": e.kind, "who": e.who, "perms": e.perms(), "default": e.default,
                    }))
                    .collect::<Vec<_>>()),
                "link": props::link_target(&file)?.map(|l| json!({
                    "target": l.target.display().to_string(),
                    "resolved": l.resolved.display().to_string(),
                    "exists": l.exists,
                })),
                //: Here as well as behind their own route, because the General
                //: tab draws these two boxes from what it already fetched.
                "attributes": props::attributes(&file)?,
            })
        }
        ("POST", "/api/chmod") => {
            let file = body_path(body, "path")?;
            let mode = body
                .get("mode")
                .and_then(Value::as_u64)
                .ok_or_else(|| Error::BadRequest("mode is required".into()))?;
            props::set_mode(&file, mode as u32)?;
            json!({"path": file.display().to_string(), "mode": props::ownership(&file)?.mode})
        }
        ("GET", "/api/attributes") => {
            let file = path_param(req, "path")?;
            let attrs = props::attributes(&file)?;
            json!({"path": file.display().to_string(), "attributes": attrs})
        }
        ("POST", "/api/attributes") => {
            let file = body_path(body, "path")?;
            //: Each is optional and each is applied on its own, so a dialog
            //: that changed one box does not have to send the other back and
            //: risk writing a value it read a minute ago.
            let mut changed = Vec::new();
            if let Some(read_only) = body.get("readOnly").and_then(Value::as_bool) {
                props::set_read_only(&file, read_only)?;
                changed.push("readOnly");
            }
            if let Some(hidden) = body.get("hidden").and_then(Value::as_bool) {
                props::set_hidden(&file, hidden)?;
                changed.push("hidden");
            }
            if changed.is_empty() {
                return Err(Error::BadRequest("nothing to change".into()));
            }
            json!({
                "path": file.display().to_string(),
                "changed": changed,
                "attributes": props::attributes(&file)?,
            })
        }
        ("POST", "/api/acl") => {
            let file = body_path(body, "path")?;
            let entries: Vec<props::AclEntry> = body
                .get("entries")
                .and_then(Value::as_array)
                .map(|a| {
                    a.iter()
                        .filter_map(|e| {
                            let perms = e.get("perms").and_then(Value::as_str).unwrap_or("");
                            Some(props::AclEntry {
                                kind: e.get("kind")?.as_str()?.to_string(),
                                who: e.get("who").and_then(Value::as_str).unwrap_or("").to_string(),
                                read: perms.contains('r'),
                                write: perms.contains('w'),
                                execute: perms.contains('x'),
                                default: e.get("default").and_then(Value::as_bool).unwrap_or(false),
                            })
                        })
                        .collect()
                })
                .unwrap_or_default();
            props::set_acl(&file, &entries)?;
            json!({"ok": true})
        }
        ("GET", "/api/size") => {
            let dir = path_param(req, "path")?;
            let cap = req.param("max").and_then(|v| v.parse().ok()).unwrap_or(2_000_000);
            let size = props::size_of(&dir, cap)?;
            json!({
                "path": dir.display().to_string(),
                "files": size.files,
                "folders": size.folders,
                "bytes": size.bytes,
                "onDisk": size.on_disk,
                "partial": size.partial,
            })
        }

        // ------------------------------------------------------------ volumes
        ("GET", "/api/volumes") => json!({"volumes": sidebar_volumes()?}),
        //: The block devices, which are a different question from the places
        //: the sidebar shows and were answering under the same name before.
        ("GET", "/api/drives") => json!({
            "drives": volumes::volumes()?
                .into_iter()
                .map(|v| json!({
                    "path": v.path.display().to_string(),
                    "name": v.name,
                    "label": v.label,
                    "uuid": v.uuid,
                    "fstype": v.fstype,
                    "model": v.model,
                    "size": v.size,
                    "mountPoint": v.mount_point.as_ref().map(|m| m.display().to_string()),
                    "removable": v.removable,
                    "readOnly": v.read_only,
                    "optical": v.optical,
                    "encrypted": v.encrypted,
                    "locked": v.locked,
                    "system": v.system,
                    "usage": v.usage.map(|u| json!({
                        "total": u.total, "free": u.free, "available": u.available,
                        "used": u.used(), "fractionUsed": u.fraction_used(),
                    })),
                }))
                .collect::<Vec<_>>(),
        }),
        ("GET", "/api/mounts") => json!({
            "mounts": volumes::mounts()?
                .into_iter()
                .map(|m| json!({
                    "source": m.source,
                    "mountPoint": m.mount_point.display().to_string(),
                    "fstype": m.fstype,
                    "options": m.options,
                    "readOnly": m.read_only,
                }))
                .collect::<Vec<_>>(),
        }),
        ("POST", "/api/mount") => {
            let device = body_path(body, "device")?;
            json!({"mountPoint": volumes::mount(&device)?.display().to_string()})
        }
        ("POST", "/api/unmount") => {
            volumes::unmount(&body_path(body, "device")?)?;
            json!({"ok": true})
        }
        ("POST", "/api/eject") => {
            volumes::eject(&body_path(body, "device")?)?;
            json!({"ok": true})
        }

        // ---------------------------------------------------------------- git
        ("GET", "/api/git") => {
            let dir = path_param(req, "path")?;
            match git::info(&dir, flag(req, "ignored"))? {
                Some(info) => {
                    //: The rows the page is drawing are the direct children of
                    //: the folder it is showing, so a change deep in a tree is
                    //: reported against whichever child contains it. That is
                    //: the row the person is looking at.
                    let mut status: BTreeMap<String, git::Status> = BTreeMap::new();
                    for (rel, entry) in &info.entries {
                        let full = info.root.join(rel);
                        let Ok(under) = full.strip_prefix(&dir) else { continue };
                        let Some(first) = under.components().next() else { continue };
                        let key = dir.join(first.as_os_str()).display().to_string();
                        status
                            .entry(key)
                            .and_modify(|worst| {
                                if entry.status > *worst {
                                    *worst = entry.status;
                                }
                            })
                            .or_insert(entry.status);
                    }
                    let branches: Vec<String> = git::branches(&dir)
                        .unwrap_or_default()
                        .into_iter()
                        .filter(|b| !b.is_remote)
                        .map(|b| b.name)
                        .take(50)
                        .collect();
                    json!({
                        "repo": true,
                        "path": dir.display().to_string(),
                        "repository": true,
                        "root": info.root.display().to_string(),
                        "branch": info.branch,
                        "head": info.head,
                        "detached": info.detached,
                        "ahead": info.ahead,
                        "behind": info.behind,
                        "branches": branches,
                        //: One letter per row, which is what the details column
                        //: turns into a word.
                        "status": status
                            .into_iter()
                            .map(|(path, s)| (path, json!(s.letter())))
                            .collect::<serde_json::Map<_, _>>(),
                        "entries": info.entries.iter().map(|(path, entry)| {
                            (path.clone(), json!({
                                "status": entry.status.name(),
                                "letter": entry.status.letter(),
                                "staged": entry.staged,
                            }))
                        }).collect::<serde_json::Map<_, _>>(),
                    })
                }
                None => json!({
                    "repo": false,
                    "path": dir.display().to_string(),
                    "repository": false,
                    "branches": Vec::<String>::new(),
                    "status": serde_json::Map::new(),
                }),
            }
        }
        ("GET", "/api/git/branches") => json!({
            "branches": git::branches(&path_param(req, "path")?)?
                .into_iter()
                .map(|b| json!({
                    "name": b.name, "head": b.is_head, "remote": b.is_remote, "upstream": b.upstream,
                }))
                .collect::<Vec<_>>(),
        }),
        ("GET", "/api/git/commit") => {
            let file = path_param(req, "path")?;
            let dir = file.parent().unwrap_or(&file).to_path_buf();
            json!({
                "commit": git::last_commit(&dir, &file)?.map(|c| json!({
                    "sha": c.sha, "shortSha": c.short_sha, "summary": c.summary,
                    "author": c.author, "email": c.email, "time": c.time * 1000,
                })),
            })
        }
        //: The last commit for every child of a folder at once, for the four
        //: git columns of the details layout: one walk rather than one
        //: request a row. Nothing at all outside a repository, so the page
        //: can tell "no history" from "not tracked".
        ("GET", "/api/git/commits") => {
            let dir = path_param(req, "path")?;
            json!({
                "path": dir.display().to_string(),
                "commits": git::last_commits(&dir)?.map(|found| {
                    found.into_iter().map(|(name, c)| (name, json!({
                        "sha": c.sha, "shortSha": c.short_sha, "summary": c.summary,
                        "author": c.author, "email": c.email, "time": c.time * 1000,
                    }))).collect::<serde_json::Map<String, Value>>()
                }),
            })
        }
        ("POST", "/api/git/checkout") => {
            let dir = body_path(body, "path")?;
            git::checkout(&dir, &body_str(body, "branch")?)?;
            json!({"ok": true})
        }
        ("POST", "/api/git/branch") => {
            let dir = body_path(body, "path")?;
            git::create_branch(
                &dir,
                &body_str(body, "name")?,
                body.get("from").and_then(Value::as_str),
                body_bool(body, "switch", true),
            )?;
            json!({"ok": true})
        }

        ("POST", "/api/git/init") => {
            let dir = body_path(body, "path")?;
            json!({"path": git::init(&dir, body_bool(body, "bare", false))?.display().to_string()})
        }
        ("POST", "/api/git/clone") => {
            let url = body_str(body, "url")?;
            //: Checked here as well as inside, so a bad address is a 400 from
            //: the request rather than a job that starts and then fails.
            git::safe_remote(&url)?;
            let into = body_path(body, "into")?;
            if wants_job(req) {
                json!({"job": service.jobs.start("clone", move |job| {
                    let where_to = git::clone(&url, &into, &mut transferred(job, &url))?;
                    Ok(json!({"path": where_to.display().to_string()}))
                }).to_string()})
            } else {
                let where_to = git::clone(&url, &into, &mut git::unwatched)?;
                json!({"path": where_to.display().to_string()})
            }
        }
        ("POST", "/api/git/fetch") => {
            let dir = body_path(body, "path")?;
            let remote = remote_param(body);
            if wants_job(req) {
                json!({"job": service.jobs.start("fetch", move |job| {
                    let name = remote.clone().unwrap_or_else(|| "origin".into());
                    let got = git::fetch(&dir, remote.as_deref(), &mut transferred(job, &name))?;
                    Ok(fetched_json(&got))
                }).to_string()})
            } else {
                fetched_json(&git::fetch(&dir, remote.as_deref(), &mut git::unwatched)?)
            }
        }
        ("POST", "/api/git/pull") | ("POST", "/api/git/sync") => {
            let dir = body_path(body, "path")?;
            let remote = remote_param(body);
            //: Sync is a pull and then a push, and it is one route away from
            //: pull because the two differ by that one step and nothing else.
            let both = path.ends_with("sync");
            let kind = if both { "sync" } else { "pull" };
            let finish = move |done: git::Pulled| json!({
                "fetched": fetched_json(&done.fetched),
                "moved": done.moved,
                "branch": done.fetched.branch,
                "ahead": done.fetched.ahead,
                "behind": done.fetched.behind,
            });
            if wants_job(req) {
                json!({"job": service.jobs.start(kind, move |job| {
                    let name = remote.clone().unwrap_or_else(|| "origin".into());
                    let mut watch = transferred(job, &name);
                    let done = if both {
                        git::sync(&dir, remote.as_deref(), &mut watch)?
                    } else {
                        git::pull(&dir, remote.as_deref(), &mut watch)?
                    };
                    Ok(finish(done))
                }).to_string()})
            } else {
                let done = if both {
                    git::sync(&dir, remote.as_deref(), &mut git::unwatched)?
                } else {
                    git::pull(&dir, remote.as_deref(), &mut git::unwatched)?
                };
                finish(done)
            }
        }
        ("POST", "/api/git/push") => {
            let dir = body_path(body, "path")?;
            let remote = remote_param(body);
            if wants_job(req) {
                json!({"job": service.jobs.start("push", move |job| {
                    let name = remote.clone().unwrap_or_else(|| "origin".into());
                    let branch = git::push(&dir, remote.as_deref(), &mut transferred(job, &name))?;
                    Ok(json!({"branch": branch}))
                }).to_string()})
            } else {
                json!({"branch": git::push(&dir, remote.as_deref(), &mut git::unwatched)?})
            }
        }

        // -------------------------------------------------------- the actions
        ("POST", "/api/mkdir") => {
            let (dir, name) = parent_and_name(body)?;
            json!({"path": fsops::create(&dir, &name, fsops::NewItem::Folder)?.display().to_string()})
        }
        ("POST", "/api/mkfile") => {
            let (dir, name) = parent_and_name(body)?;
            let kind = match body.get("template").and_then(Value::as_str) {
                Some(template) => fsops::NewItem::FromTemplate(absolute(template)?),
                None => fsops::NewItem::File,
            };
            json!({"path": fsops::create(&dir, &name, kind)?.display().to_string()})
        }
        ("POST", "/api/mksymlink") => {
            let target = body_path_any(body, &["target"])?;
            //: `link` is the whole path of the link to make; `path` plus an
            //: optional `name` says the same thing in two pieces.
            let (dir, name) = match body.get("link").and_then(Value::as_str) {
                Some(link) => {
                    let link = absolute(link)?;
                    let name = link
                        .file_name()
                        .ok_or_else(|| Error::BadRequest("no name in the link".into()))?
                        .to_string_lossy()
                        .to_string();
                    (link.parent().unwrap_or(Path::new("/")).to_path_buf(), Some(name))
                }
                None => (
                    body_path(body, "path")?,
                    body.get("name").and_then(Value::as_str).map(str::to_string),
                ),
            };
            let made = fsops::make_shortcut(&target, &dir, name.as_deref())?;
            json!({
                "link": made.display().to_string(),
                "target": target.display().to_string(),
                "path": made.display().to_string(),
            })
        }
        ("POST", "/api/rename") => {
            let file = body_path(body, "path")?;
            let renamed = fsops::rename(&file, &body_str(body, "name")?, conflict_from(req, body)?)?;
            json!({"path": renamed.display().to_string()})
        }
        ("POST", "/api/folder-with-selection") => {
            let dir = body_path(body, "path")?;
            let sources = body_paths(body, "paths")?;
            let name = body_str(body, "name")?;
            let made = fsops::folder_with_selection(&sources, &dir, &name, &mut fsops::silent)?;
            json!({"path": made.display().to_string()})
        }
        ("POST", "/api/flatten") => {
            let dir = body_path(body, "path")?;
            let out = fsops::flatten(&dir, conflict_from(req, body)?, &mut fsops::silent)?;
            json!({"moved": out.items, "renamed": out.renamed.len()})
        }

        // --------------------------------------------- the ones that take time
        ("POST", "/api/copy") => transfer(service, req, body, false)?,
        ("POST", "/api/move") => transfer(service, req, body, true)?,
        ("POST", "/api/delete") => {
            //: A policy of Never is a refusal the caller configured, so it is
            //: answered as one rather than as a failure.
            let policy = req
                .param("policy")
                .map(str::to_string)
                .or_else(|| body.get("policy").and_then(Value::as_str).map(str::to_string))
                .unwrap_or_else(|| "Always".into());
            match policy.to_ascii_lowercase().as_str() {
                "always" => {}
                "never" => return Err(Error::Denied("delete refused by policy Never".into())),
                other => return Err(Error::BadRequest(format!("unknown policy: {other}"))),
            }
            let paths = body_paths(body, "paths")?;
            if wants_job(req) {
                json!({"job": service.jobs.start("delete", move |job| {
                    let out = fsops::delete(&paths, &mut |p| job.report(p))?;
                    Ok(json!({"deleted": out.items, "cancelled": out.cancelled}))
                }).to_string()})
            } else {
                let out = fsops::delete(&paths, &mut fsops::silent)?;
                json!({
                    "deleted": out.written.iter().map(|p| p.display().to_string()).collect::<Vec<_>>(),
                    "items": out.items,
                })
            }
        }
        ("POST", "/api/duplicate") => {
            let paths = body_paths(body, "paths")?;
            json!({"job": service.jobs.start("duplicate", move |job| {
                let out = fsops::duplicate(&paths, &mut |p| job.report(p))?;
                Ok(json!({
                    "created": out.written.iter().map(|p| p.display().to_string()).collect::<Vec<_>>(),
                    "cancelled": out.cancelled,
                }))
            }).to_string()})
        }

        // -------------------------------------------------------------- trash
        ("POST", "/api/trash") => {
            let paths = body_paths(body, "paths")?;
            let mut moved = Vec::new();
            for path in &paths {
                let bin = trash::Trash::for_path(path);
                let name = bin.trash(path)?;
                moved.push(json!({
                    "name": name,
                    "from": path.display().to_string(),
                    "trashRoot": bin.root().display().to_string(),
                }));
            }
            json!({
                //: The names, which is what a caller needs to restore one, and
                //: the detail alongside for a view that wants to show where it
                //: went.
                "trashed": moved.iter().map(|m| m["name"].clone()).collect::<Vec<_>>(),
                "items": moved,
            })
        }
        ("GET", "/api/trash") | ("GET", "/api/trash/list") => {
            let mut entries = Vec::new();
            for bin in all_trashes() {
                //: A trash directory that will not list is skipped rather than
                //: failing the whole view: one unreadable volume must not hide
                //: everything the user deleted everywhere else.
                let Ok(items) = bin.list() else { continue };
                for item in items {
                    entries.push(json!({
                        "name": item.name,
                        "originalPath": item.original.display().to_string(),
                        "date": item.deleted,
                        "deletedAt": item.deleted,
                        "isDirectory": item.is_dir,
                        "size": item.size,
                        //: Which trash it is in, so Restore can be told where
                        //: to look rather than having to search again.
                        "trashRoot": bin.root().display().to_string(),
                    }));
                }
            }
            json!({"entries": entries})
        }
        ("POST", "/api/restore") => {
            let mut names: Vec<String> = body
                .get("names")
                .and_then(Value::as_array)
                .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
                .unwrap_or_default();
            //: One name is the older spelling and still the common case.
            if let Some(one) = body.get("name").and_then(Value::as_str).filter(|n| !n.is_empty()) {
                names.push(one.to_string());
            }
            if names.is_empty() {
                return Err(Error::BadRequest("a trash name is required".into()));
            }
            //: The caller can say which trash, from what the listing told it.
            //: Without that, every trash is tried, because the name alone does
            //: not say which volume the item came from.
            let bins = match body.get("trashRoot").and_then(Value::as_str) {
                Some(root) => vec![trash::Trash::at(absolute(root)?)],
                None => all_trashes(),
            };
            let mut restored = Vec::new();
            for name in names {
                let mut last = None;
                for bin in &bins {
                    match bin.restore(&name) {
                        Ok(back) => {
                            restored.push(back.display().to_string());
                            last = None;
                            break;
                        }
                        Err(e) => last = Some(e),
                    }
                }
                if let Some(e) = last {
                    return Err(e);
                }
            }
            json!({"path": restored.first().cloned(), "restored": restored})
        }
        ("POST", "/api/restore-all") => {
            let mut restored = Vec::new();
            let mut failed = Vec::new();
            for bin in all_trashes() {
                let Ok(items) = bin.list() else { continue };
                for item in items {
                    //: One that will not come back does not stop the rest: the
                    //: usual reason is that something is in its place again,
                    //: and the others are still worth restoring. The ones that
                    //: did not are named, because a silent partial restore is
                    //: how someone concludes a file is gone.
                    match bin.restore(&item.name) {
                        Ok(back) => restored.push(back.display().to_string()),
                        Err(e) => failed.push(json!({"name": item.name, "error": e.to_string()})),
                    }
                }
            }
            json!({"restored": restored, "failed": failed})
        }
        ("POST", "/api/empty-trash") => {
            let mut removed = 0;
            for bin in all_trashes() {
                removed += bin.empty().unwrap_or(0);
            }
            json!({"emptied": removed, "removed": removed})
        }

        // ----------------------------------------------------------- archives
        ("POST", "/api/extract") => {
            let file = body_path_any(body, &["archive", "path"])?;
            let into = body_path_any(body, &["dest", "into"])?;
            let destination = match body.get("destination").and_then(Value::as_str) {
                Some("here") => archive::Destination::Here,
                Some("folder") => archive::Destination::ChildFolder,
                _ => archive::Destination::Smart,
            };
            let password = body_password(body);
            //: The Extract dialog's Encoding row, for a zip whose names were
            //: written without the UTF-8 flag. Absent or "default" reads
            //: them as UTF-8 where they are and CP437 where they are not.
            let names = archive::Names::from_label(
                body.get("encoding").and_then(Value::as_str).unwrap_or(""),
            )?;
            if wants_job(req) {
                let password = password.clone();
                json!({"job": service.jobs.start("extract", move |job| {
                    let (target, done) = archive::extract_with(
                        &file, &into, destination, password.as_deref(), names,
                        &mut |p| job.report(p))?;
                    Ok(json!({
                        "extracted": target.display().to_string(),
                        "items": done.items,
                        "bytes": done.bytes,
                        //: A stopped extraction leaves what it wrote, so the
                        //: caller is told rather than left to guess from a
                        //: folder that is half full.
                        "cancelled": done.cancelled,
                    }))
                }).to_string()})
            } else {
                let (target, done) = archive::extract_with(
                    &file, &into, destination, password.as_deref(), names, &mut fsops::silent)?;
                json!({
                    "extracted": target.display().to_string(),
                    "archive": file.display().to_string(),
                    "path": target.display().to_string(),
                    "items": done.items,
                    "bytes": done.bytes,
                })
            }
        }
        ("POST", "/api/compress") => {
            let sources = body_paths(body, "paths")?;
            let out = body_path_any(body, &["dest", "out"])?;
            //: A named format wins; otherwise the destination's own suffix
            //: says what to write, which is what a Save dialog produces.
            let format = match body.get("format").and_then(Value::as_str) {
                Some(named) => archive_format_named(named)?,
                None => archive::Format::from_name(&out.display().to_string()).ok_or_else(|| {
                    Error::BadRequest(format!("{} is not a format this can write", out.display()))
                })?,
            };
            let base = body
                .get("base")
                .and_then(Value::as_str)
                .map(absolute)
                .transpose()?
                .or_else(|| sources[0].parent().map(Path::to_path_buf))
                .ok_or_else(|| Error::BadRequest("no base directory".into()))?;
            //: An unknown level name is refused rather than quietly treated as
            //: normal: the request asked for something specific, and writing a
            //: differently sized archive without saying so is worse than a 400.
            let level = match body.get("level").and_then(Value::as_str) {
                Some(named) => archive::Level::from_name(named)
                    .ok_or_else(|| Error::BadRequest(format!("unknown level: {named}")))?,
                None => archive::Level::default(),
            };
            //: Same rule as the level: a size that is not one of the offered
            //: ones is a 400, not a quiet whole archive under a name that
            //: promised parts.
            let split = match body.get("split").and_then(Value::as_str) {
                Some(named) => volume::Split::from_name(named)
                    .ok_or_else(|| Error::BadRequest(format!("unknown split size: {named}")))?,
                None => volume::Split::NONE,
            };
            let options = archive::Options {
                level,
                password: body_password(body),
                split,
                dictionary: body_u32(body, "dictionary")?,
                word_size: body_u32(body, "word_size")?,
                threads: body_u32(body, "threads")?.unwrap_or(1),
            };
            if wants_job(req) {
                let options = options.clone();
                json!({"job": service.jobs.start("compress", move |job| {
                    let done = archive::compress(
                        &base, &sources, &out, format, &options, &mut |p| job.report(p))?;
                    Ok(json!({
                        "archive": out.display().to_string(),
                        "items": done.items,
                        "bytes": done.bytes,
                        "parts": part_names(&done),
                        //: A stopped compress has taken its archive with it,
                        //: so there is no path to hand back for that case.
                        "cancelled": done.cancelled,
                    }))
                }).to_string()})
            } else {
                let done = archive::compress(
                    &base, &sources, &out, format, &options, &mut fsops::silent)?;
                //: A split archive is not at the path that was asked for: that
                //: file is gone and the parts stand in its place, so `path`
                //: names the first of them and the whole set is listed beside
                //: it. A caller that opens `path` opens the archive either way.
                let first = done.parts.first().cloned().unwrap_or_else(|| out.clone());
                json!({
                    "archive": first.display().to_string(),
                    "path": first.display().to_string(),
                    "level": level.name(),
                    "encrypted": options.password.is_some(),
                    "split": split.bytes(),
                    "parts": part_names(&done),
                    "items": done.items,
                    "bytes": done.bytes,
                })
            }
        }
        ("GET", "/api/archive-list") => {
            let file = path_param(req, "path")?;
            //: In the query string because this is a GET, which means it can
            //: end up in a log. The page sends it only after being asked for
            //: one, and the alternative, a POST, would not be a listing.
            let password = req.param("password").filter(|v| !v.is_empty());
            let names = archive::Names::from_label(req.param("encoding").unwrap_or(""))?;
            //: Whether the names are in question at all, and the guess, so
            //: the dialog shows its Encoding row only for an archive that
            //: needs one, the way the reference does.
            let asked = archive::zip_names(&file)?;
            json!({
                "entries": archive::list_with(&file, password.as_deref(), names)?
                    .into_iter()
                    .map(|e| json!({"name": e.name, "size": e.size, "isDirectory": e.is_dir}))
                    .collect::<Vec<_>>(),
                "names": {
                    "undetermined": asked.undetermined,
                    "detected": asked.detected.map(|e| {
                        let (name, label) = archive::encoding_label(e);
                        json!({"name": name, "label": label})
                    }),
                },
            })
        }

        // --------------------------------------------------------------- jobs
        ("GET", "/api/job") => {
            let raw = req
                .param("id")
                .filter(|v| !v.is_empty())
                .ok_or_else(|| Error::BadRequest("id is required".into()))?;
            let id: u64 = raw.parse().map_err(|_| Error::NotFound(format!("job {raw}")))?;
            let job = service.jobs.get(id).ok_or_else(|| Error::NotFound(format!("job {id}")))?;
            let snap = job.snapshot();
            let finished = snap.state != "running";
            json!({
                //: A string, because the backend this replaces used a uuid and
                //: the page passes whatever it was given straight back.
                "id": job.id.to_string(),
                "done": finished,
                "processed": snap.done_items,
                "total": snap.total_items,
                "copied": snap
                    .result
                    .as_ref()
                    .and_then(|r| r.get("written").or_else(|| r.get("copied")))
                    .cloned()
                    .unwrap_or_else(|| json!([])),
                "cancelled": snap.state == "cancelled",
                "kind": snap.kind,
                "state": snap.state,
                "totalItems": snap.total_items,
                "doneItems": snap.done_items,
                "totalBytes": snap.total_bytes,
                "doneBytes": snap.done_bytes,
                "current": snap.current,
                "error": snap.error.as_ref().map(|message| json!({
                    "error": message,
                    "code": snap.error_code,
                })),
                "errorCode": snap.error_code,
                "result": snap.result,
            })
        }
        ("GET", "/api/jobs") => json!({
            "jobs": service.jobs.list().into_iter().map(|(id, snap)| json!({
                "id": id.to_string(), "kind": snap.kind, "state": snap.state,
                "doneItems": snap.done_items, "totalItems": snap.total_items,
            })).collect::<Vec<_>>(),
        }),
        ("POST", "/api/job/cancel") => {
            //: A number or the string form of one, because the id went out as
            //: a string.
            let id = body
                .get("id")
                .and_then(|v| v.as_u64().or_else(|| v.as_str().and_then(|s| s.parse().ok())))
                .ok_or_else(|| Error::BadRequest("id is required".into()))?;
            json!({"cancelled": service.jobs.cancel(id)})
        }

        // ------------------------------------------------------- applications
        ("GET", "/api/apps") => {
            let registry = service.apps.read().unwrap_or_else(|e| e.into_inner());
            let mime_type = match req.param("path") {
                Some(_) => service.mime.of_path(&path_param(req, "path")?)?,
                None => req
                    .param("mime")
                    .ok_or_else(|| Error::BadRequest("path or mime is required".into()))?
                    .to_string(),
            };
            let ancestry = service.mime.ancestry(&mime_type);
            let entry_json = |e: &apps::DesktopEntry| json!({
                "id": e.id,
                "name": e.name,
                "comment": e.comment,
                "icon": e.icon,
                "terminal": e.terminal,
                "actions": e.actions.iter().map(|a| json!({"id": a.id, "name": a.name})).collect::<Vec<_>>(),
            });
            json!({
                "mimeType": mime_type,
                "default": registry.default_for(&mime_type).map(entry_json),
                "handlers": registry
                    .handlers_for(&mime_type, &ancestry[1..])
                    .into_iter()
                    .map(entry_json)
                    .collect::<Vec<_>>(),
            })
        }
        ("GET", "/api/apps/all") => {
            let registry = service.apps.read().unwrap_or_else(|e| e.into_inner());
            json!({
                "apps": registry
                    .all()
                    .filter(|e| e.is_runnable() && !e.no_display)
                    .map(|e| json!({"id": e.id, "name": e.name, "icon": e.icon}))
                    .collect::<Vec<_>>(),
            })
        }
        ("POST", "/api/open") => {
            let paths = body_paths(body, "paths")?;
            let registry = service.apps.read().unwrap_or_else(|e| e.into_inner());
            let mut opened = 0;
            for path in &paths {
                let mime_type = service.mime.of_path(path)?;
                let entry = registry.default_for(&mime_type).ok_or_else(|| {
                    Error::NotFound(format!("nothing on this system opens {mime_type}"))
                })?;
                apps::open_with(&registry, &entry.id, std::slice::from_ref(path))?;
                let _ = places::add_recent(path, &mime_type, "auradefs");
                opened += 1;
            }
            json!({"opened": opened})
        }
        ("POST", "/api/open-with") => {
            let paths = body_paths(body, "paths")?;
            let id = body_str(body, "app")?;
            let registry = service.apps.read().unwrap_or_else(|e| e.into_inner());
            apps::open_with(&registry, &id, &paths)?;
            json!({"ok": true})
        }
        ("POST", "/api/set-default") => {
            let mime_type = body_str(body, "mime")?;
            let id = body_str(body, "app")?;
            let mut registry = service.apps.write().unwrap_or_else(|e| e.into_inner());
            json!({"written": registry.set_default(&mime_type, &id)?.display().to_string()})
        }
        ("POST", "/api/pin-to-launcher") => {
            let dir = body_path(body, "path")?;
            json!({"entry": apps::pin(&dir)?.display().to_string(), "pinned": true})
        }
        ("POST", "/api/unpin-from-launcher") => {
            let dir = body_path(body, "path")?;
            json!({"entry": apps::unpin(&dir)?.display().to_string(), "pinned": false})
        }
        ("GET", "/api/pinned-to-launcher") => {
            let dir = path_param(req, "path")?;
            json!({"pinned": apps::pinned(&dir), "path": dir.display().to_string()})
        }
        ("POST", "/api/powershell") => {
            apps::run_with_powershell(&body_path(body, "path")?)?;
            json!({"ok": true})
        }
        ("POST", "/api/apps/reload") => {
            *service.apps.write().unwrap_or_else(|e| e.into_inner()) = Registry::load();
            json!({"ok": true})
        }
        ("POST", "/api/terminal") => {
            apps::open_terminal(&body_path(body, "path")?)?;
            json!({"ok": true})
        }
        ("POST", "/api/run-admin") => {
            let file = body_path(body, "path")?;
            apps::run_as_admin(&file, &[])?;
            json!({"ok": true})
        }
        ("POST", "/api/run-terminal") => {
            let file = body_path(body, "path")?;
            apps::run_in_terminal(&file, &[])?;
            json!({"ok": true})
        }
        ("POST", "/api/run") => {
            system::run_with_options(&body_path(body, "path")?)?;
            json!({"ok": true})
        }
        ("GET", "/api/launch-options") => {
            let file = path_param(req, "path")?;
            let options = system::launch_options(&file)?;
            json!({"args": options.args, "env": options.env, "terminal": options.in_terminal})
        }
        ("POST", "/api/launch-options") => {
            let file = body_path(body, "path")?;
            let options = system::LaunchOptions {
                args: body
                    .get("args")
                    .and_then(Value::as_array)
                    .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
                    .unwrap_or_default(),
                env: body
                    .get("env")
                    .and_then(Value::as_array)
                    .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
                    .unwrap_or_default(),
                in_terminal: body_bool(body, "terminal", false),
            };
            system::set_launch_options(&file, &options)?;
            json!({"ok": true})
        }

        // ------------------------------------------------------------- places
        ("GET", "/api/places") => json!({
            "userDirs": places::user_dirs()?
                .into_iter()
                .map(|p| json!({
                    "label": p.label,
                    "path": p.path.display().to_string(),
                    "exists": p.exists,
                    "kind": p.kind.map(|k| k.label()),
                }))
                .collect::<Vec<_>>(),
            "bookmarks": places::bookmarks()?
                .into_iter()
                .map(|p| json!({
                    "label": p.label, "path": p.path.display().to_string(), "exists": p.exists,
                }))
                .collect::<Vec<_>>(),
        }),
        ("POST", "/api/bookmark") => {
            let dir = body_path(body, "path")?;
            places::add_bookmark(&dir, body.get("label").and_then(Value::as_str))?;
            json!({"ok": true})
        }
        ("DELETE", "/api/bookmark") => {
            places::remove_bookmark(&body_path(body, "path")?)?;
            json!({"ok": true})
        }
        ("POST", "/api/bookmark/reorder") => {
            places::reorder_bookmarks(&body_paths(body, "paths")?)?;
            json!({"ok": true})
        }
        ("GET", "/api/recent") => {
            let limit = req.param("limit").and_then(|v| v.parse().ok()).unwrap_or(50);
            //: Two different questions under one name, told apart by whether a
            //: place was named. With a root it means "what changed in here
            //: lately", which is a walk. Without one it means the desktop's own
            //: list of files that were opened, which is a file.
            if let Some(root) = req.param("root").filter(|r| !r.is_empty()) {
                let root = absolute(root)?;
                let found = list::recently_modified(&root, limit, flag(req, "hidden"), 200_000)?;
                return Ok(Answer::Json(json!({
                    "root": root.display().to_string(),
                    "recent": found
                        .into_iter()
                        .map(|r| json!({
                            "path": r.path.display().to_string(),
                            "key": file_key(&r.path),
                            "name": r.name,
                            "modified": r.modified * 1000,
                            "size": r.size,
                        }))
                        .collect::<Vec<_>>(),
                })));
            }
            json!({
                "recent": places::recent(limit)?
                    .into_iter()
                    .map(|r| json!({
                        "path": r.path.display().to_string(),
                        "key": file_key(&r.path),
                        "name": r.path.file_name().map(|n| n.to_string_lossy().to_string()),
                        "mimeType": r.mime,
                        "visited": r.visited,
                    }))
                    .collect::<Vec<_>>(),
            })
        }
        ("POST", "/api/recent") => {
            let file = body_path(body, "path")?;
            let mime_type = service.mime.of_path(&file)?;
            places::add_recent(&file, &mime_type, "auradefs")?;
            json!({"ok": true})
        }
        ("POST", "/api/recent/clear") => {
            places::clear_recent()?;
            json!({"ok": true})
        }

        // ------------------------------------------------------ the long tail
        ("GET", "/api/wallpaper") => {
            const SAMPLE_WIDTH: u32 = 64;
            match system::wallpaper()? {
                None => json!({"found": false, "reason": "no wallpaper set"}),
                Some(path) => match system::wallpaper_sample(SAMPLE_WIDTH) {
                    //: A wallpaper that will not decode is not an error worth
                    //: failing the request over: the page draws a flat colour
                    //: and carries on.
                    Err(e) => json!({"found": false, "reason": e.code()}),
                    Ok((bytes, width, height)) => json!({
                        "found": true,
                        "path": path.display().to_string(),
                        "width": width,
                        "height": height,
                        "sample_width": SAMPLE_WIDTH,
                        "bytes": bytes.len(),
                        "uri": crate::b64::data_uri("image/jpeg", &bytes),
                    }),
                },
            }
        }
        ("POST", "/api/wallpaper") => {
            system::set_wallpaper(&body_path(body, "path")?)?;
            json!({"ok": true})
        }
        ("POST", "/api/font") => {
            let file = body_path(body, "path")?;
            json!({"installed": system::install_font(&file)?.display().to_string()})
        }
        ("GET", "/api/font") => {
            let file = path_param(req, "path")?;
            let info = system::font_info(&file)?;
            json!({
                "family": info.family,
                "style": info.style,
                "fullName": info.full_name,
                "installed": system::font_installed(&file)?,
            })
        }
        ("GET", "/api/certificates") => json!({
            "certificates": system::certificates()?
                .into_iter()
                .map(|c| json!({"nickname": c.nickname, "trust": c.trust}))
                .collect::<Vec<_>>(),
        }),
        ("POST", "/api/certificate") => {
            let file = body_path(body, "path")?;
            let nickname = body_str(body, "nickname")?;
            //: Trusting a certificate is never the default. The caller has to
            //: say so, which means the user has to have been asked.
            let trust = match body.get("trust").and_then(Value::as_str) {
                Some("ca") => system::Trust::Ca,
                _ => system::Trust::None,
            };
            system::install_certificate(&file, &nickname, trust)?;
            json!({"ok": true})
        }
        ("GET", "/api/signature") => {
            let file = path_param(req, "path")?;
            let beside = system::signature_beside(&file);
            //: Asked on every properties dialog, so a file nobody signed must
            //: not cost a gpg that reads the whole of it.
            let signable = system::signable(&file, beside.as_deref());
            let checked = if signable {
                system::verify_signature(&file, beside.as_deref())?
            } else {
                system::Signature::unsigned()
            };
            json!({
                "path": file.display().to_string(),
                //: Whether this file is the sort of thing anyone signs. The
                //: properties window shows its Signatures tab for a file
                //: that is, and says no signature was found; for anything
                //: else the tab is not offered, which is Files' own rule.
                //: Without this the page could not tell "nobody signed it"
                //: from "not a question".
                "signable": signable,
                "signature": beside.map(|s| s.display().to_string()),
                "status": format!("{:?}", checked.status),
                "trusted": checked.status == system::SignatureStatus::GoodAndTrusted,
                "keyId": checked.key_id,
                "signer": checked.signer,
                "detail": checked.detail,
            })
        }
        ("POST", "/api/share") => {
            system::share(&body_paths(body, "paths")?)?;
            json!({"ok": true})
        }

        _ => return Ok(Answer::NotFound),
    };
    Ok(Answer::Json(value))
}

/// Every trash directory this user has: the home one, plus a `.Trash-$uid` at
/// the root of each mounted filesystem that has one.
///
/// The single home trash is not enough. Deleting a file from another volume
/// puts it in that volume's own trash, because moving it to the system disk
/// would turn a rename into a copy of the whole file. A Trash view that only
/// read the home directory would show none of those, and Restore would report
/// that a file it had just deleted did not exist.
fn all_trashes() -> Vec<trash::Trash> {
    let mut out = vec![trash::Trash::home()];
    let uid = rustix::process::getuid().as_raw();
    let Ok(mounts) = volumes::mounts() else { return out };
    for mount in mounts {
        //: Only real filesystems. A `.Trash-$uid` cannot exist under /proc or
        //: /sys, and probing them is pointless work on every listing.
        if matches!(
            mount.fstype.as_str(),
            "proc" | "sysfs" | "devtmpfs" | "devpts" | "cgroup" | "cgroup2" | "securityfs"
                | "debugfs" | "tracefs" | "bpf" | "pstore" | "mqueue" | "hugetlbfs" | "configfs"
                | "fusectl" | "binfmt_misc" | "autofs" | "efivarfs" | "ramfs" | "nsfs"
        ) {
            continue;
        }
        let candidate = mount.mount_point.join(format!(".Trash-{uid}"));
        if candidate.is_dir() && !out.iter().any(|t| t.root() == candidate) {
            out.push(trash::Trash::at(candidate));
        }
    }
    out
}

fn first_line(path: &str) -> String {
    std::fs::read_to_string(path)
        .map(|t| t.lines().next().unwrap_or("").trim().to_string())
        .unwrap_or_default()
}

fn hostname() -> String {
    let name = first_line("/proc/sys/kernel/hostname");
    if name.is_empty() { first_line("/etc/hostname") } else { name }
}

/// What this machine calls itself, from `/etc/os-release`.
fn pretty_os_name() -> String {
    let Ok(text) = std::fs::read_to_string("/etc/os-release") else {
        return first_line("/proc/sys/kernel/ostype");
    };
    for line in text.lines() {
        if let Some(value) = line.strip_prefix("PRETTY_NAME=") {
            return value.trim().trim_matches('"').to_string();
        }
    }
    first_line("/proc/sys/kernel/ostype")
}

fn image_size(path: &Path) -> Option<(u32, u32)> {
    thumbs::dimensions(path)
}

/// The places the sidebar shows: home, the special folders that exist, the
/// trash, and every real mount. Not the block devices, which are a different
/// question answered at `/api/drives`.
fn sidebar_volumes() -> Result<Vec<Value>> {
    let home = places::home()?;
    let usage_of = |path: &Path| {
        volumes::usage(path).ok().map(|u| {
            (u.total, u.used(), u.available, json!({"total": u.total, "free": u.available}))
        })
    };
    let record = |id: String,
                  root: &Path,
                  label: String,
                  kind: &str,
                  purpose: Option<&str>,
                  with_capacity: bool| {
        let numbers = usage_of(root);
        json!({
            "id": id,
            "root": file_key(root),
            "label": label,
            "kind": kind,
            "removable": false,
            "readOnly": false,
            //: Only home carries the bar. Repeating the same filesystem's
            //: numbers on every folder inside it would draw five identical
            //: bars for one disk.
            "capacity": if with_capacity {
                numbers.as_ref().map(|(_, _, _, c)| c.clone()).unwrap_or(Value::Null)
            } else {
                Value::Null
            },
            "purpose": purpose,
            "totalBytes": numbers.as_ref().map(|(t, _, _, _)| *t).unwrap_or(0),
            "usedBytes": numbers.as_ref().map(|(_, u, _, _)| *u).unwrap_or(0),
            "freeBytes": numbers.as_ref().map(|(_, _, f, _)| *f).unwrap_or(0),
        })
    };

    let mut out = vec![record(
        "local_root:home".into(),
        &home,
        "Home".into(),
        "system",
        Some("home"),
        true,
    )];
    for place in places::user_dirs()? {
        let Some(kind) = place.kind else { continue };
        if kind == places::UserDir::Home || !place.exists {
            continue;
        }
        let label = kind.label().to_string();
        out.push(record(
            format!("local_root:{label}"),
            &place.path,
            label.clone(),
            "system",
            Some(&label.to_lowercase()),
            false,
        ));
    }
    let bin = trash::Trash::home();
    if bin.root().is_dir() {
        out.push(record("trash".into(), bin.root(), "Trash".into(), "trash", None, false));
    }
    //: And the real mounts, which is what makes a plugged in stick a row.
    for mount in volumes::mounts()? {
        if !Path::new(&mount.source).is_absolute() || volumes::is_system_mount(&mount.mount_point) {
            continue;
        }
        let numbers = usage_of(&mount.mount_point);
        let label = mount
            .mount_point
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| mount.mount_point.display().to_string());
        out.push(json!({
            "id": format!("mount:{}", mount.source),
            "root": file_key(&mount.mount_point),
            "label": label,
            "kind": "mount",
            "removable": mount.mount_point.starts_with("/run/media")
                || mount.mount_point.starts_with("/media"),
            "readOnly": mount.read_only,
            "capacity": numbers.as_ref().map(|(_, _, _, c)| c.clone()).unwrap_or(Value::Null),
            "purpose": Value::Null,
            "totalBytes": numbers.as_ref().map(|(t, _, _, _)| *t).unwrap_or(0),
            "usedBytes": numbers.as_ref().map(|(_, u, _, _)| *u).unwrap_or(0),
            "freeBytes": numbers.as_ref().map(|(_, _, f, _)| *f).unwrap_or(0),
        }));
    }
    Ok(out)
}

fn archive_formats() -> Value {
    json!({
        "unpack": ["zip", "7z", "tar", "tar.gz", "tar.xz", "tar.zst", "tgz", "txz", "tzst"],
        "archive": ["zip", "7z", "tar", "tar.gz", "tar.xz", "tar.zst"],
        "levels": archive::Level::ALL.map(|l| l.name()),
        //: So the dialog can grey the password box out for the formats that
        //: have nowhere to put one, rather than taking it and losing it.
        "encrypt": ["zip", "7z"],
        //: And the same for the split box, which only 7z can honour.
        "split": ["7z"],
        //: The LZMA2 knobs: the dictionary and the word size are 7z's, and
        //: so is the thread count here, since the zip and tar writers run on
        //: one thread. The dialog greys each box for the other formats.
        "dictionary": ["7z"],
        "word_size": ["7z"],
        "threads": ["7z"],
        "dictionaries": archive::DICTIONARIES,
        "word_sizes": archive::WORD_SIZES,
        //: The Extract dialog's Encoding list, after Default, by the label
        //: the page sends back and the name it shows.
        "encodings": archive::ENCODINGS
            .iter()
            .map(|(name, label)| json!({"name": name, "label": label}))
            .collect::<Vec<_>>(),
        "splits": volume::Split::ALL
            .iter()
            .map(|(name, label, bytes)| json!({
                "name": name, "label": label, "bytes": bytes,
            }))
            .collect::<Vec<_>>(),
    })
}

/// The parts of a split archive as strings, empty when there was no split.
fn part_names(done: &archive::Done) -> Vec<String> {
    done.parts.iter().map(|p| p.display().to_string()).collect()
}

/// The name a caller used for a format, when they named one.
fn archive_format_named(name: &str) -> Result<archive::Format> {
    Ok(match name.trim().to_ascii_lowercase().as_str() {
        "zip" => archive::Format::Zip,
        "7z" | "sevenzip" => archive::Format::SevenZip,
        "tar" => archive::Format::Tar,
        "gztar" | "tar.gz" | "tgz" => archive::Format::TarGz,
        "xztar" | "tar.xz" | "txz" => archive::Format::TarXz,
        "zsttar" | "tar.zst" | "tzst" => archive::Format::TarZst,
        other => return Err(Error::BadRequest(format!("unknown format: {other}"))),
    })
}

/// Remove every thumbnail in the shared cache, reporting how many and how much.
fn clear_thumbnail_cache(root: &Path) -> (u64, u64) {
    let mut removed = 0;
    let mut bytes = 0;
    for size in ["normal", "large", "x-large", "xx-large", "fail"] {
        let dir = root.join(size);
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            let path = entry.path();
            //: The fail directory holds one folder per program, so it needs one
            //: more level. Anything else in here is not ours to delete.
            if path.is_dir() {
                let Ok(inner) = std::fs::read_dir(&path) else { continue };
                for one in inner.flatten() {
                    let len = one.metadata().map(|m| m.len()).unwrap_or(0);
                    if std::fs::remove_file(one.path()).is_ok() {
                        removed += 1;
                        bytes += len;
                    }
                }
                continue;
            }
            let len = entry.metadata().map(|m| m.len()).unwrap_or(0);
            if std::fs::remove_file(&path).is_ok() {
                removed += 1;
                bytes += len;
            }
        }
    }
    (removed, bytes)
}

/// Copy and move, which differ by one flag.
///
/// Both run in this request unless the caller asked for a job. That is the
/// older behaviour and the right default: most copies are small, and a page
/// that has to poll for a two file copy is a page that feels slow.
/// The names typed in the conflict dialog, one for any source: a body
/// object from source path to the name it should land under. A name for a
/// path that is not among the sources is a 400, since it means the page and
/// the request disagree about what is being moved.
fn typed_names(body: &Value, sources: &[PathBuf]) -> Result<Vec<Option<String>>> {
    let Some(map) = body.get("names") else { return Ok(Vec::new()) };
    let map = map
        .as_object()
        .ok_or_else(|| Error::BadRequest("names must map each path to a name".into()))?;
    let mut names = vec![None; sources.len()];
    for (raw, name) in map {
        let path = absolute(raw)?;
        let name = name
            .as_str()
            .ok_or_else(|| Error::BadRequest(format!("the name for {raw} is not a string")))?;
        let i = sources
            .iter()
            .position(|s| *s == path)
            .ok_or_else(|| Error::BadRequest(format!("{raw} is not among the paths")))?;
        names[i] = Some(name.to_string());
    }
    Ok(names)
}

fn transfer(service: &Arc<Service>, req: &Request, body: &Value, moving: bool) -> Result<Value> {
    let sources = body_paths(body, "paths")?;
    let into = body_path_any(body, &["dest", "into"])?;
    if !into.is_dir() {
        return Err(Error::NotFound(format!("{} is not a folder", into.display())));
    }
    let conflict = conflict_from(req, body)?;
    let names = typed_names(body, &sources)?;
    let kind = if moving { "move" } else { "copy" };

    if wants_job(req) {
        let id = service.jobs.start(kind, move |job| {
            let report = &mut |p: &fsops::Progress| job.report(p);
            let out = if moving {
                fsops::move_as(&sources, &names, &into, conflict, report)?
            } else {
                fsops::copy_as(&sources, &names, &into, conflict, report)?
            };
            Ok(json!({
                "written": out.written.iter().map(|p| p.display().to_string()).collect::<Vec<_>>(),
                "skipped": out.skipped.iter().map(|p| p.display().to_string()).collect::<Vec<_>>(),
                "items": out.items,
                "bytes": out.bytes,
                "cancelled": out.cancelled,
            }))
        });
        return Ok(json!({"job": id.to_string()}));
    }

    let out = if moving {
        fsops::move_as(&sources, &names, &into, conflict, &mut fsops::silent)?
    } else {
        fsops::copy_as(&sources, &names, &into, conflict, &mut fsops::silent)?
    };
    let written: Vec<String> = out.written.iter().map(|p| p.display().to_string()).collect();
    let mut value = json!({
        "skipped": out.skipped.iter().map(|p| p.display().to_string()).collect::<Vec<_>>(),
        "renamed": out.renamed.iter()
            .map(|(from, to)| json!([from.display().to_string(), to.display().to_string()]))
            .collect::<Vec<_>>(),
        "items": out.items,
        "bytes": out.bytes,
    });
    //: Named for what was asked, because that is the key the page reads.
    value[if moving { "moved" } else { "copied" }] = json!(written);
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_relative_path_is_refused_rather_than_resolved() {
        assert!(absolute("relative/path").is_err());
        assert!(absolute("").is_err());
        assert_eq!(absolute("/etc").unwrap(), Path::new("/etc"));
    }

    #[test]
    fn a_leading_tilde_is_the_home_directory_and_nothing_else_is() {
        unsafe { std::env::set_var("HOME", "/home/test") };
        assert_eq!(expand_home("~"), "/home/test");
        assert_eq!(expand_home("~/Documents"), "/home/test/Documents");
        //: Another user's home is not this one's, and a name that merely starts
        //: with a tilde is a name.
        assert_eq!(expand_home("~other/x"), "~other/x");
        assert_eq!(expand_home("/tmp/~x"), "/tmp/~x");
    }

    #[test]
    fn every_refusal_maps_to_the_status_that_means_it() {
        assert_eq!(status_for(&Error::NotFound("x".into())), 404);
        assert_eq!(status_for(&Error::Denied("x".into())), 403);
        assert_eq!(status_for(&Error::ReadOnly("x".into())), 403);
        assert_eq!(status_for(&Error::Exists("x".into())), 409);
        assert_eq!(status_for(&Error::Conflict("x".into())), 409);
        assert_eq!(status_for(&Error::Escapes("x".into())), 400);
        assert_eq!(status_for(&Error::BadRequest("x".into())), 400);
        assert_eq!(status_for(&Error::Unsupported("x".into())), 501);
        assert_eq!(status_for(&Error::Tool { tool: "x".into(), message: "y".into() }), 500);
    }

    #[test]
    fn an_error_body_carries_the_code_the_page_branches_on() {
        let body = error_body(&Error::Exists("/a/b".into()));
        assert_eq!(body["code"], "exists");
        assert_eq!(body["errno"], 17);
        assert!(body["error"].as_str().unwrap().contains("/a/b"));
    }

    fn request(query: &str) -> Request {
        let (path, params) = crate::http::split_target(query);
        Request {
            method: "POST".into(),
            path,
            query: params,
            headers: Default::default(),
            body: Vec::new(),
            keep_alive: true,
        }
    }

    /// Drive one route the way the socket does, minus the socket.
    fn call(service: &Arc<Service>, method: &str, target: &str, body: Value) -> Result<Value> {
        let mut req = request(target);
        req.method = method.into();
        match handle(service, &req, &body)? {
            Answer::Json(value) => Ok(value),
            Answer::Bytes(mime, bytes) => Ok(json!({"mime": mime, "len": bytes.len()})),
            Answer::NotFound => Err(Error::NotFound(target.into())),
        }
    }

    /// Half a second of silence in an MP3, through ffmpeg, or None where
    /// there is no ffmpeg to make one.
    fn silent_mp3(dir: &Path) -> Option<PathBuf> {
        let ffmpeg = apps::which("ffmpeg")?;
        let out = dir.join("silence.mp3");
        let status = std::process::Command::new(ffmpeg)
            .args(["-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "0.5"])
            .arg(&out)
            .status()
            .ok()?;
        status.success().then_some(out)
    }

    #[test]
    fn an_album_cover_is_changed_pictured_and_removed_through_the_api() {
        let dir = std::env::temp_dir().join("auradefs-api-cover");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("cache")).unwrap();
        let Some(track) = silent_mp3(&dir) else { return };
        let art = dir.join("art.png");
        image::RgbImage::from_pixel(8, 8, image::Rgb([220, 20, 20])).save(&art).unwrap();
        let service = Arc::new(Service::new());
        let path = track.display().to_string();
        let q = format!("/api/album-cover?path={path}");
        let thumb = format!("/api/thumb?path={path}");

        //: The cache is pointed at the scratch directory for the thumbnail
        //: half, so this test leaves nothing in the real one.
        static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
        let _guard = LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let before = std::env::var("XDG_CACHE_HOME").ok();
        unsafe { std::env::set_var("XDG_CACHE_HOME", dir.join("cache")) };
        let run = || -> Result<()> {
            let none = call(&service, "GET", &q, Value::Null)?;
            assert_eq!(none["supported"], true, "an MP3 can carry a cover");
            assert_eq!(none["cover"], false, "and this one has none yet");
            assert!(none["uri"].is_null());
            let no_thumb = call(&service, "GET", &thumb, Value::Null)?;
            assert_eq!(no_thumb["supported"], false);
            assert_eq!(no_thumb["reason"], "no cover", "the row's words for a track without art");
            let raw = call(&service, "GET", &format!("{q}&raw=1"), Value::Null);
            assert_eq!(raw.unwrap_err().code(), "not-found");

            let changed = call(&service, "POST", "/api/album-cover",
                json!({"path": path, "image": art.display().to_string()}))?;
            assert_eq!(changed["action"], "change");
            assert_eq!(changed["files"][0]["changed"], true);
            let has = call(&service, "GET", &q, Value::Null)?;
            assert_eq!(has["cover"], true);
            assert_eq!(has["mime"], "image/png");
            assert_eq!(has["front"], true);
            assert_eq!(has["bytes"].as_u64().unwrap(), std::fs::metadata(&art).unwrap().len());
            assert!(has["uri"].as_str().unwrap().starts_with("data:image/png;base64,"));
            let raw = call(&service, "GET", &format!("{q}&raw=1"), Value::Null)?;
            assert_eq!(raw["mime"], "image/png");
            assert_eq!(raw["len"].as_u64().unwrap(), std::fs::metadata(&art).unwrap().len());
            //: The thumbnail is the cover now, and it says so.
            let pictured = call(&service, "GET", &thumb, Value::Null)?;
            assert_eq!(pictured["supported"], true, "{pictured}");
            assert_eq!(pictured["kind"], "audio");
            assert_eq!(pictured["thumb_width"], 8);

            let removed = call(&service, "POST", "/api/album-cover",
                json!({"paths": [path], "remove": true}))?;
            assert_eq!(removed["action"], "remove");
            assert_eq!(removed["files"][0]["removed"], true, "there was one to remove");
            let gone = call(&service, "GET", &q, Value::Null)?;
            assert_eq!(gone["cover"], false);
            let no_thumb = call(&service, "GET", &thumb, Value::Null)?;
            assert_eq!(no_thumb["supported"], false, "the old cover's thumbnail was forgotten");
            //: Removing again is not an error and changes nothing.
            let again = call(&service, "POST", "/api/album-cover", json!({"path": path}))?;
            assert_eq!(again["files"][0]["removed"], false);
            Ok(())
        };
        let out = run();
        unsafe {
            match before {
                Some(v) => std::env::set_var("XDG_CACHE_HOME", v),
                None => std::env::remove_var("XDG_CACHE_HOME"),
            }
        }
        out.unwrap();
    }

    #[test]
    fn a_selection_with_one_file_that_cannot_carry_a_cover_changes_none_of_it() {
        let dir = std::env::temp_dir().join("auradefs-api-cover-mixed");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let Some(track) = silent_mp3(&dir) else { return };
        let clip = dir.join("clip.mkv");
        std::fs::write(&clip, b"not matroska either").unwrap();
        let art = dir.join("art.png");
        image::RgbImage::from_pixel(4, 4, image::Rgb([0, 0, 220])).save(&art).unwrap();
        let untouched = std::fs::read(&track).unwrap();
        let service = Arc::new(Service::new());
        let err = call(&service, "POST", "/api/album-cover", json!({
            "paths": [track.display().to_string(), clip.display().to_string()],
            "image": art.display().to_string(),
        }))
        .unwrap_err();
        assert_eq!(err.code(), "unsupported", "{err}");
        assert!(err.to_string().contains("clip.mkv"), "the refusal names the file: {err}");
        assert_eq!(std::fs::read(&track).unwrap(), untouched, "the MP3 before it was not written");
        //: A folder is refused the same way, before anything is written.
        let err = call(&service, "POST", "/api/album-cover", json!({
            "paths": [track.display().to_string(), dir.display().to_string()],
            "image": art.display().to_string(),
        }))
        .unwrap_err();
        assert_eq!(err.code(), "bad-request", "{err}");
        assert_eq!(std::fs::read(&track).unwrap(), untouched);
        //: And the capability the page asks for is declared.
        let system = call(&service, "GET", "/api/system", Value::Null).unwrap();
        let caps = system["capabilities"].as_array().unwrap();
        assert!(caps.iter().any(|c| c == "album-cover"), "{caps:?}");
    }

    #[test]
    fn a_whole_number_in_the_body_is_read_as_one_and_anything_else_is_refused() {
        assert_eq!(body_u32(&json!({}), "dictionary").unwrap(), None);
        assert_eq!(body_u32(&json!({"dictionary": null}), "dictionary").unwrap(), None);
        assert_eq!(body_u32(&json!({"dictionary": 65536}), "dictionary").unwrap(), Some(65536));
        assert_eq!(body_u32(&json!({"dictionary": "65536"}), "dictionary").unwrap(), Some(65536));
        assert_eq!(body_u32(&json!({"threads": " 4 "}), "threads").unwrap(), Some(4));
        for bad in [json!({"threads": "four"}), json!({"threads": -1}), json!({"threads": 1.5}),
                    json!({"threads": 5_000_000_000u64}), json!({"threads": true})] {
            let err = body_u32(&bad, "threads").unwrap_err();
            assert_eq!(err.code(), "bad-request", "{bad}");
        }
    }

    #[test]
    fn a_typed_name_lines_up_with_its_source_and_a_stray_one_is_refused() {
        let sources = vec![PathBuf::from("/a/one.txt"), PathBuf::from("/a/two.txt")];
        //: No names at all is an empty list, which the core reads as every
        //: source keeping its own name.
        assert_eq!(typed_names(&json!({}), &sources).unwrap(), Vec::<Option<String>>::new());
        assert_eq!(
            typed_names(&json!({"names": {"/a/two.txt": "deux.txt"}}), &sources).unwrap(),
            vec![None, Some("deux.txt".to_string())]
        );
        for bad in [
            json!({"names": {"/a/three.txt": "trois.txt"}}),
            json!({"names": {"/a/one.txt": 7}}),
            json!({"names": ["one"]}),
        ] {
            assert_eq!(typed_names(&bad, &sources).unwrap_err().code(), "bad-request", "{bad}");
        }
    }

    #[test]
    fn the_conflict_answer_defaults_to_keeping_both() {
        let none = request("/x");
        //: Unset is keep both. On the wire that is the answer that loses
        //: nothing: a drag onto a folder that already holds a file of that name
        //: should ask, and the nearest thing to asking is keeping both.
        assert_eq!(conflict_from(&none, &json!({})).unwrap(), fsops::Conflict::KeepBoth);
        assert_eq!(
            conflict_from(&request("/x?conflict=replace"), &json!({})).unwrap(),
            fsops::Conflict::Replace
        );
        assert_eq!(
            conflict_from(&request("/x?conflict=Keep_Both"), &json!({})).unwrap(),
            fsops::Conflict::KeepBoth
        );
        assert_eq!(
            conflict_from(&request("/x?conflict=fail-if-exists"), &json!({})).unwrap(),
            fsops::Conflict::Fail
        );
        //: The body is read when the query is silent, and the query wins when
        //: both are there.
        assert_eq!(
            conflict_from(&none, &json!({"conflict": "skip"})).unwrap(),
            fsops::Conflict::Skip
        );
        assert_eq!(
            conflict_from(&request("/x?conflict=skip"), &json!({"conflict": "replace"})).unwrap(),
            fsops::Conflict::Skip
        );
        //: A spelling nobody defined is a bad request, not a silent default.
        assert!(conflict_from(&request("/x?conflict=nonsense"), &json!({})).is_err());
    }

    #[test]
    fn a_job_is_only_started_when_one_was_asked_for() {
        assert!(!wants_job(&request("/api/copy")));
        //: The bare parameter is the request, which is how the page writes it.
        assert!(wants_job(&request("/api/copy?job")));
        assert!(wants_job(&request("/api/copy?job=1")));
    }

    #[test]
    fn a_destination_is_taken_from_either_spelling() {
        assert_eq!(
            body_path_any(&json!({"dest": "/a"}), &["dest", "into"]).unwrap(),
            PathBuf::from("/a")
        );
        assert_eq!(
            body_path_any(&json!({"into": "/b"}), &["dest", "into"]).unwrap(),
            PathBuf::from("/b")
        );
        //: The first named key wins, so there is one answer when both are sent.
        assert_eq!(
            body_path_any(&json!({"dest": "/a", "into": "/b"}), &["dest", "into"]).unwrap(),
            PathBuf::from("/a")
        );
        assert!(body_path_any(&json!({}), &["dest", "into"]).is_err());
        assert!(body_path_any(&json!({"dest": ""}), &["dest"]).is_err());
    }

    #[test]
    fn a_new_item_can_be_named_in_one_piece_or_two() {
        assert_eq!(
            parent_and_name(&json!({"path": "/home/cam", "name": "Notes"})).unwrap(),
            (PathBuf::from("/home/cam"), "Notes".to_string())
        );
        //: The whole path in one, which is how the older backend was asked.
        assert_eq!(
            parent_and_name(&json!({"path": "/home/cam/Notes"})).unwrap(),
            (PathBuf::from("/home/cam"), "Notes".to_string())
        );
        assert!(parent_and_name(&json!({"path": "/"})).is_err());
        assert!(parent_and_name(&json!({})).is_err());
    }

    #[test]
    fn a_format_name_maps_to_what_it_writes() {
        assert_eq!(archive_format_named("zip").unwrap(), archive::Format::Zip);
        assert_eq!(archive_format_named("GZTAR").unwrap(), archive::Format::TarGz);
        assert_eq!(archive_format_named("tar.xz").unwrap(), archive::Format::TarXz);
        assert!(archive_format_named("rar").is_err());
    }

    #[test]
    fn a_list_of_paths_is_checked_before_anything_runs() {
        assert!(body_paths(&json!({}), "paths").is_err());
        assert!(body_paths(&json!({"paths": []}), "paths").is_err());
        assert!(body_paths(&json!({"paths": ["relative"]}), "paths").is_err());
        assert!(body_paths(&json!({"paths": [1, 2]}), "paths").is_err());
        assert_eq!(
            body_paths(&json!({"paths": ["/a", "/b"]}), "paths").unwrap(),
            [PathBuf::from("/a"), PathBuf::from("/b")]
        );
    }

    #[test]
    fn a_relative_link_is_reported_against_its_own_folder() {
        assert_eq!(normalise(Path::new("/a/b/../c")), PathBuf::from("/a/c"));
        assert_eq!(normalise(Path::new("/a/./b")), PathBuf::from("/a/b"));
        assert_eq!(normalise(Path::new("/a/b/../../c")), PathBuf::from("/c"));
    }

    #[test]
    fn a_desktop_launcher_is_a_shortcut_and_a_plain_file_is_not() {
        let dir = std::env::temp_dir().join("auradefs-api-shortcut");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();

        let plain = dir.join("notes.txt");
        std::fs::write(&plain, b"x").unwrap();
        assert!(shortcut_fields(&plain).is_empty(), "a plain file got the tab");

        let launcher = dir.join("term.desktop");
        std::fs::write(
            &launcher,
            "[Desktop Entry]\nType=Application\nName=Terminal\nExec=/bin/sh -e bash\nPath=/tmp\n",
        )
        .unwrap();
        let fields: std::collections::HashMap<_, _> = shortcut_fields(&launcher).into_iter().collect();
        assert_eq!(fields["linkKind"], "desktop");
        assert_eq!(fields["linkTarget"], "/bin/sh");
        assert_eq!(fields["linkArgs"], "-e bash");
        assert_eq!(fields["linkWorkingDir"], "/tmp");
        assert_eq!(fields["linkBroken"], false);

        //: A launcher whose program is not installed is broken, and the tab
        //: says so rather than offering a row that does nothing.
        std::fs::write(
            &launcher,
            "[Desktop Entry]\nType=Application\nName=Ghost\nExec=/nowhere/ghost\n",
        )
        .unwrap();
        let fields: std::collections::HashMap<_, _> = shortcut_fields(&launcher).into_iter().collect();
        assert_eq!(fields["linkBroken"], true);

        //: A .desktop with no Exec line is not a shortcut to anywhere.
        std::fs::write(&launcher, "[Desktop Entry]\nType=Application\nName=Nothing\n").unwrap();
        assert!(shortcut_fields(&launcher).is_empty());
    }

    #[test]
    fn a_symlink_reports_both_what_it_says_and_where_that_leads() {
        let dir = std::env::temp_dir().join("auradefs-api-symlink");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("sub")).unwrap();
        std::fs::write(dir.join("real.txt"), b"x").unwrap();
        std::os::unix::fs::symlink("../real.txt", dir.join("sub/rel.link")).unwrap();
        std::os::unix::fs::symlink("/nope/missing", dir.join("bad.link")).unwrap();

        let good: std::collections::HashMap<_, _> =
            shortcut_fields(&dir.join("sub/rel.link")).into_iter().collect();
        assert_eq!(good["linkKind"], "symlink");
        assert_eq!(good["linkTarget"], "../real.txt", "the raw text of the link");
        assert_eq!(good["linkResolved"], dir.join("real.txt").display().to_string());
        assert_eq!(good["linkBroken"], false);

        let bad: std::collections::HashMap<_, _> =
            shortcut_fields(&dir.join("bad.link")).into_iter().collect();
        assert_eq!(bad["linkBroken"], true);
        assert_eq!(bad["linkTarget"], "/nope/missing");
    }

    #[test]
    fn an_empty_password_box_is_no_password_rather_than_a_short_one() {
        assert_eq!(body_password(&json!({"password": "hunter2"})), Some("hunter2".into()));
        //: What a password box sends when nobody typed in it.
        assert_eq!(body_password(&json!({"password": ""})), None);
        assert_eq!(body_password(&json!({})), None);
        //: Not a string is not a password.
        assert_eq!(body_password(&json!({"password": 1234})), None);
        assert_eq!(body_password(&json!({"password": null})), None);
        //: Spaces are a password. Trimming one would quietly change it into a
        //: different password and the archive would not open.
        assert_eq!(body_password(&json!({"password": "  "})), Some("  ".into()));
    }

    #[test]
    fn no_thumbnail_is_an_answer_and_not_an_error() {
        let out = no_thumb(Path::new("/tmp/notes.txt"), "not an image");
        assert_eq!(out["supported"], false);
        assert_eq!(out["reason"], "not an image");
        assert_eq!(out["path"], "/tmp/notes.txt");
        //: No uri key at all, rather than an empty one: a caller that reads
        //: `j.supported && j.uri` must not be handed something to render.
        assert!(out.get("uri").is_none());
    }

    #[test]
    fn the_archive_options_a_request_names_are_the_ones_used() {
        //: The names the dialog sends, and a refusal for one it does not.
        assert_eq!(archive::Level::from_name("ultra"), Some(archive::Level::Ultra));
        assert_eq!(archive::Level::from_name("STORE"), Some(archive::Level::Store));
        assert_eq!(archive::Level::from_name("extreme"), None);
        //: The turn names the menu items carry.
        assert_eq!(imageops::Turn::from_name("left"), Some(imageops::Turn::Left));
        assert_eq!(imageops::Turn::from_name("right"), Some(imageops::Turn::Right));
        assert_eq!(imageops::Turn::from_name("sideways"), None);
        //: And what the page reads to decide which controls to show.
        let formats = archive_formats();
        assert_eq!(formats["encrypt"], json!(["zip", "7z"]));
        assert_eq!(formats["levels"][0], "ultra");
        assert_eq!(formats["levels"].as_array().unwrap().len(), 6);
        //: The split box: which formats can honour it, and the sizes it
        //: offers, each with the label to show and the bytes it stands for.
        assert_eq!(formats["split"], json!(["7z"]));
        //: The LZMA2 knobs the Create archive dialog offers, and where each
        //: reaches a codec.
        assert_eq!(formats["dictionary"], json!(["7z"]));
        assert_eq!(formats["word_size"], json!(["7z"]));
        assert_eq!(formats["threads"], json!(["7z"]));
        assert_eq!(formats["dictionaries"][0], 64 * 1024);
        assert_eq!(formats["dictionaries"][12], 1024 * 1024 * 1024);
        assert_eq!(formats["word_sizes"], json!([8, 16, 32, 64, 128, 256, 273]));
        //: And the Extract dialog's encodings, the reference's sixteen.
        let encodings = formats["encodings"].as_array().unwrap();
        assert_eq!(encodings.len(), 16);
        assert_eq!(encodings[0], json!({"name": "utf-8", "label": "Unicode (UTF-8)"}));
        assert_eq!(encodings[1]["name"], "shift_jis");
        assert_eq!(encodings[15]["label"], "Western European (Mac)");
        let splits = formats["splits"].as_array().unwrap();
        assert_eq!(splits.len(), 12);
        assert_eq!(splits[0]["name"], "none");
        assert_eq!(splits[0]["bytes"], Value::Null);
        assert_eq!(splits[1]["name"], "10m");
        assert_eq!(splits[1]["label"], "10 MB");
        assert_eq!(splits[1]["bytes"], 10 * 1024 * 1024);
        //: And the names the page sends come back as the sizes they name.
        assert_eq!(volume::Split::from_name("none").unwrap().bytes(), None);
        assert_eq!(
            volume::Split::from_name("650m").unwrap().bytes(),
            Some(650 * 1024 * 1024)
        );
        assert!(volume::Split::from_name("dvd").is_none());
    }

    #[test]
    fn a_file_key_is_the_shape_the_page_already_uses() {
        assert_eq!(file_key(Path::new("/home/cam/a b.txt")), "file:///home/cam/a b.txt");
    }

    #[test]
    fn a_remote_is_named_or_left_to_the_repository() {
        assert_eq!(remote_param(&json!({"remote": "upstream"})), Some("upstream".into()));
        //: An empty box is not a remote called "", which would be a 404 from
        //: git; it is the person not naming one.
        assert_eq!(remote_param(&json!({"remote": ""})), None);
        assert_eq!(remote_param(&json!({})), None);
    }

    #[test]
    fn a_fetch_answers_with_the_counts_the_header_shows() {
        let got = fetched_json(&git::Fetched {
            remote: "origin".into(),
            objects: 12,
            bytes: 4096,
            branch: Some("main".into()),
            ahead: 2,
            behind: 0,
        });
        assert_eq!(got["remote"], "origin");
        assert_eq!(got["objects"], 12);
        assert_eq!(got["bytes"], 4096);
        assert_eq!(got["branch"], "main");
        assert_eq!(got["ahead"], 2);
        assert_eq!(got["behind"], 0);
        //: A repository with no branch checked out says so rather than
        //: sending a name the header would print.
        let detached = fetched_json(&git::Fetched::default());
        assert_eq!(detached["branch"], Value::Null);
    }
}
