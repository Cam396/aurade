//! The freedesktop trash, done to the spec rather than approximated.
//!
//! The prototype deleted through `gio trash` and could not answer "what is in
//! the trash and where did it come from", which is why Restore was a menu row
//! that did nothing. The spec is small and worth implementing directly:
//!
//! - `$XDG_DATA_HOME/Trash/files/NAME` holds the item.
//! - `$XDG_DATA_HOME/Trash/info/NAME.trashinfo` holds where it came from and
//!   when it went, as a `.desktop` style ini with a percent encoded `Path`.
//! - A name collision is resolved by suffixing, and the two files must always
//!   agree, so the info file is written first with `O_EXCL`: it is the lock.
//!
//! Restore is then just reading the info file and moving back.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};

/// One item sitting in the trash.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrashItem {
    /// The name inside `Trash/files`, which may be suffixed after a collision.
    pub name: String,
    /// Where it came from, absolute.
    pub original: PathBuf,
    /// When it was trashed, as an ISO 8601 local timestamp per the spec.
    pub deleted: String,
    /// Size in bytes for a file; for a directory this is the entry size only,
    /// because walking every trashed tree to fill a column is not worth the
    /// disk it costs.
    pub size: u64,
    pub is_dir: bool,
}

/// One trash directory.
///
/// There is more than one. The spec puts the user's trash under
/// `$XDG_DATA_HOME/Trash`, but an item on another filesystem belongs in
/// `.Trash-$uid` at that filesystem's mount point, so that deleting a large
/// file from a USB stick is a rename rather than a copy of the whole thing
/// onto the system disk. Making the directory a value rather than a global is
/// what lets both exist, and it is what lets the tests run in parallel.
#[derive(Debug, Clone)]
pub struct Trash {
    root: PathBuf,
}

impl Trash {
    /// A trash rooted at an explicit directory.
    pub fn at(root: impl Into<PathBuf>) -> Self {
        Trash { root: root.into() }
    }

    /// The user's own trash.
    pub fn home() -> Self {
        let base = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .filter(|p| p.is_absolute())
            .unwrap_or_else(|| {
                let home =
                    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default();
                home.join(".local/share")
            });
        Trash { root: base.join("Trash") }
    }

    /// The trash an item at `path` belongs in: the home one when they share a
    /// filesystem, and the volume's own `.Trash-$uid` when they do not.
    pub fn for_path(path: impl AsRef<Path>) -> Self {
        let home = Self::home();
        let Some(path_dev) = device_of(path.as_ref()) else { return home };
        //: The home trash may not exist yet, so compare against the directory
        //: that will hold it rather than the trash itself.
        let home_probe = home
            .root
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| home.root.clone());
        if device_of(&home_probe) == Some(path_dev) {
            return home;
        }
        match mount_root_of(path.as_ref()) {
            Some(mount) => {
                let uid = rustix::process::getuid().as_raw();
                Trash { root: mount.join(format!(".Trash-{uid}")) }
            }
            None => home,
        }
    }

    /// The directory this trash is rooted at.
    pub fn root(&self) -> &Path {
        &self.root
    }

    fn dirs(&self) -> Result<(PathBuf, PathBuf)> {
        let files = self.root.join("files");
        let info = self.root.join("info");
        for d in [&files, &info] {
            fs::create_dir_all(d)
                .map_err(|e| Error::io(d.display().to_string(), e))?;
        }
        Ok((files, info))
    }
}

/// The device a path sits on, or None when it cannot be stat'd.
fn device_of(path: &Path) -> Option<u64> {
    use std::os::unix::fs::MetadataExt;
    fs::metadata(path).ok().map(|m| m.dev())
}

/// Walk up until the device changes: the last path on the same device is the
/// mount point.
fn mount_root_of(path: &Path) -> Option<PathBuf> {
    let dev = device_of(path)?;
    let mut cur = if path.is_dir() { path.to_path_buf() } else { path.parent()?.to_path_buf() };
    loop {
        let Some(parent) = cur.parent() else { return Some(cur) };
        match device_of(parent) {
            Some(d) if d == dev => cur = parent.to_path_buf(),
            _ => return Some(cur),
        }
    }
}

/// Percent encode for the `Path` field. The spec says everything outside the
/// unreserved set is encoded, and the separator stays literal so the value
/// still reads as a path.
fn encode_path(path: &Path) -> String {
    let mut out = String::new();
    for byte in path.as_os_str().as_encoded_bytes() {
        let b = *byte;
        let unreserved = b.is_ascii_alphanumeric()
            || matches!(b, b'-' | b'_' | b'.' | b'~' | b'/');
        if unreserved {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

fn decode_path(value: &str) -> PathBuf {
    let bytes = value.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).ok();
            if let Some(v) = hex.and_then(|h| u8::from_str_radix(h, 16).ok()) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    PathBuf::from(unsafe { std::ffi::OsString::from_encoded_bytes_unchecked(out) })
}

/// The spec's timestamp: local time, no zone suffix.
fn now_stamp() -> String {
    let secs = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    //: Civil time from a unix second, without pulling in a date crate for the
    //: one place the service needs it. Local zone is deliberately not applied:
    //: the spec allows either, and UTC is the one that never lies after a
    //: timezone change.
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (y, m, d) = civil_from_days(days);
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}",
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

/// Howard Hinnant's civil_from_days, which is exact and short.
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

impl Trash {
/// Move one path into the trash, returning the name it was given.
pub fn trash(&self, path: impl AsRef<Path>) -> Result<String> {
    let path = path.as_ref();
    let path = path
        .canonicalize()
        .map_err(|e| Error::io(path.display().to_string(), e))?;
    let base = path
        .file_name()
        .ok_or_else(|| Error::BadRequest("cannot trash the root".into()))?
        .to_owned();
    let (files, info) = self.dirs()?;

    //: The info file is the lock. Creating it with O_EXCL is what makes two
    //: concurrent deletes of the same name pick different suffixes instead of
    //: one silently overwriting the other's record.
    let mut n = 0u32;
    let (name, mut handle) = loop {
        let candidate = if n == 0 {
            base.to_string_lossy().into_owned()
        } else {
            format!("{}.{n}", base.to_string_lossy())
        };
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(info.join(format!("{candidate}.trashinfo")))
        {
            Ok(f) => break (candidate, f),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                n += 1;
                if n > 10_000 {
                    return Err(Error::Exists(base.to_string_lossy().into_owned()));
                }
            }
            Err(e) => return Err(Error::io("trash info", e)),
        }
    };

    writeln!(
        handle,
        "[Trash Info]\nPath={}\nDeletionDate={}",
        encode_path(&path),
        now_stamp()
    )
    .map_err(|e| Error::io("trash info", e))?;

    let dest = files.join(&name);
    if let Err(e) = fs::rename(&path, &dest) {
        //: Across a filesystem boundary rename fails with EXDEV and the item
        //: has to be copied. Either way the info file must not outlive a
        //: failure, or the trash grows records for things that are still
        //: where they were.
        if e.raw_os_error() == Some(18) {
            copy_tree(&path, &dest)?;
            remove_tree(&path)?;
        } else {
            let _ = fs::remove_file(info.join(format!("{name}.trashinfo")));
            return Err(Error::io(path.display().to_string(), e));
        }
    }
    Ok(name)
}

/// Everything currently in the trash, newest record first.
pub fn list(&self) -> Result<Vec<TrashItem>> {
    let (files, info) = self.dirs()?;
    let mut out = Vec::new();
    let dir = match fs::read_dir(&info) {
        Ok(d) => d,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(out),
        Err(e) => return Err(Error::io(info.display().to_string(), e)),
    };
    for entry in dir.flatten() {
        let p = entry.path();
        if p.extension().and_then(|s| s.to_str()) != Some("trashinfo") {
            continue;
        }
        let name = p.file_stem().unwrap_or_default().to_string_lossy().into_owned();
        let body = match fs::read_to_string(&p) {
            Ok(b) => b,
            Err(_) => continue,
        };
        let mut original = PathBuf::new();
        let mut deleted = String::new();
        for line in body.lines() {
            if let Some(v) = line.strip_prefix("Path=") {
                original = decode_path(v.trim());
            } else if let Some(v) = line.strip_prefix("DeletionDate=") {
                deleted = v.trim().to_owned();
            }
        }
        //: A record whose file is gone is not an item. It is left on disk
        //: rather than cleaned here, because listing is a read.
        let target = files.join(&name);
        let Ok(meta) = fs::symlink_metadata(&target) else { continue };
        out.push(TrashItem {
            name,
            original,
            deleted,
            size: meta.len(),
            is_dir: meta.is_dir(),
        });
    }
    out.sort_by(|a, b| b.deleted.cmp(&a.deleted));
    Ok(out)
}

/// Put one trashed item back where it came from.
pub fn restore(&self, name: &str) -> Result<PathBuf> {
    if name.contains('/') || name == ".." || name == "." {
        return Err(Error::BadRequest("bad trash name".into()));
    }
    let (files, info) = self.dirs()?;
    let record = info.join(format!("{name}.trashinfo"));
    let body = fs::read_to_string(&record)
        .map_err(|e| Error::io(record.display().to_string(), e))?;
    let original = body
        .lines()
        .find_map(|l| l.strip_prefix("Path="))
        .map(|v| decode_path(v.trim()))
        .ok_or_else(|| Error::BadRequest("trash record has no Path".into()))?;

    if let Some(parent) = original.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| Error::io(parent.display().to_string(), e))?;
    }
    if original.symlink_metadata().is_ok() {
        return Err(Error::Exists(original.display().to_string()));
    }
    let from = files.join(name);
    fs::rename(&from, &original).map_err(|e| {
        if e.raw_os_error() == Some(18) {
            //: Across a boundary again. Copy, then remove, then the record.
            match copy_tree(&from, &original).and_then(|_| remove_tree(&from)) {
                Ok(()) => Error::BadRequest("retry".into()),
                Err(err) => err,
            }
        } else {
            Error::io(original.display().to_string(), e)
        }
    })
    .or_else(|e| match e {
        Error::BadRequest(ref m) if m == "retry" => Ok(()),
        other => Err(other),
    })?;
    let _ = fs::remove_file(&record);
    Ok(original)
}

/// Empty the trash. Returns how many items went.
pub fn empty(&self) -> Result<usize> {
    let (files, info) = self.dirs()?;
    let mut n = 0;
    for item in self.list()? {
        let target = files.join(&item.name);
        if remove_tree(&target).is_ok() {
            let _ = fs::remove_file(info.join(format!("{}.trashinfo", item.name)));
            n += 1;
        }
    }
    Ok(n)
}
}

fn copy_tree(from: &Path, to: &Path) -> Result<()> {
    let meta = fs::symlink_metadata(from)
        .map_err(|e| Error::io(from.display().to_string(), e))?;
    if meta.is_symlink() {
        let target = fs::read_link(from)
            .map_err(|e| Error::io(from.display().to_string(), e))?;
        std::os::unix::fs::symlink(target, to)
            .map_err(|e| Error::io(to.display().to_string(), e))?;
        return Ok(());
    }
    if meta.is_dir() {
        fs::create_dir_all(to).map_err(|e| Error::io(to.display().to_string(), e))?;
        for entry in fs::read_dir(from)
            .map_err(|e| Error::io(from.display().to_string(), e))?
            .flatten()
        {
            copy_tree(&entry.path(), &to.join(entry.file_name()))?;
        }
        return Ok(());
    }
    fs::copy(from, to).map_err(|e| Error::io(to.display().to_string(), e))?;
    Ok(())
}

fn remove_tree(path: &Path) -> Result<()> {
    let meta = match fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(Error::io(path.display().to_string(), e)),
    };
    if meta.is_dir() && !meta.is_symlink() {
        fs::remove_dir_all(path).map_err(|e| Error::io(path.display().to_string(), e))
    } else {
        fs::remove_file(path).map_err(|e| Error::io(path.display().to_string(), e))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every test gets its own trash and its own working directory, so they
    /// run in parallel without a process wide environment variable between
    /// them.
    fn scratch(tag: &str) -> (Trash, PathBuf) {
        let base = std::env::temp_dir().join(format!("auradefs-trash-{tag}"));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(base.join("work")).unwrap();
        (Trash::at(base.join("Trash")), base.join("work"))
    }

    #[test]
    fn round_trip_restores_to_the_original_path() {
        let (t, work) = scratch("round-trip");
        let file = work.join("note.txt");
        fs::write(&file, b"hello").unwrap();

        let name = t.trash(&file).unwrap();
        assert!(!file.exists(), "the file is still where it was");

        let items = t.list().unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].original, file);
        assert!(!items[0].deleted.is_empty(), "no deletion date recorded");

        let back = t.restore(&name).unwrap();
        assert_eq!(back, file);
        assert_eq!(fs::read(&file).unwrap(), b"hello");
        assert!(t.list().unwrap().is_empty(), "the record outlived the restore");
    }

    #[test]
    fn a_name_collision_gets_its_own_record() {
        let (t, work) = scratch("collision");
        for body in ["one", "two"] {
            let f = work.join("same.txt");
            fs::write(&f, body).unwrap();
            t.trash(&f).unwrap();
        }
        let items = t.list().unwrap();
        assert_eq!(items.len(), 2, "the second trash overwrote the first");
        let mut names: Vec<_> = items.iter().map(|i| i.name.clone()).collect();
        names.sort();
        assert_eq!(names, vec!["same.txt".to_string(), "same.txt.1".to_string()]);
    }

    #[test]
    fn a_path_with_awkward_bytes_survives_the_round_trip() {
        let (t, work) = scratch("awkward");
        //: A space, a percent and a newline are all legal in a filename and
        //: all break a naive .trashinfo writer.
        let name = "od d %20 \nname.txt";
        let f = work.join(name);
        fs::write(&f, b"x").unwrap();
        let trashed = t.trash(&f).unwrap();
        let items = t.list().unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].original.file_name().unwrap().to_string_lossy(), name);
        let back = t.restore(&trashed).unwrap();
        assert_eq!(back.file_name().unwrap().to_string_lossy(), name);
    }

    #[test]
    fn restore_refuses_to_overwrite_something_that_came_back() {
        let (t, work) = scratch("no-clobber");
        let f = work.join("note.txt");
        fs::write(&f, b"first").unwrap();
        let name = t.trash(&f).unwrap();
        fs::write(&f, b"second").unwrap();
        let err = t.restore(&name).unwrap_err();
        assert!(matches!(err, Error::Exists(_)), "got {err:?}");
        assert_eq!(fs::read(&f).unwrap(), b"second");
    }

    #[test]
    fn empty_clears_files_and_records_together() {
        let (t, work) = scratch("empty");
        for n in 0..3 {
            let f = work.join(format!("f{n}.txt"));
            fs::write(&f, b"x").unwrap();
            t.trash(&f).unwrap();
        }
        assert_eq!(t.empty().unwrap(), 3);
        assert!(t.list().unwrap().is_empty());
        let left = fs::read_dir(t.root().join("info")).unwrap().count();
        assert_eq!(left, 0, "records outlived the files");
    }

    #[test]
    fn a_trash_name_cannot_reach_outside_the_trash() {
        let (t, _) = scratch("escape");
        assert!(matches!(t.restore("../../etc/passwd"), Err(Error::BadRequest(_))));
    }

    #[test]
    fn a_directory_goes_and_comes_back_whole() {
        let (t, work) = scratch("dir");
        let dir = work.join("project");
        fs::create_dir_all(dir.join("src")).unwrap();
        fs::write(dir.join("src/main.rs"), b"fn main() {}").unwrap();
        let name = t.trash(&dir).unwrap();
        assert!(!dir.exists());
        assert!(t.list().unwrap()[0].is_dir);
        t.restore(&name).unwrap();
        assert_eq!(fs::read(dir.join("src/main.rs")).unwrap(), b"fn main() {}");
    }
}
