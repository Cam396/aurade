//! Extended attributes: tags, comments, where a download came from, custom
//! icons, and the sidecar data Windows would put in an alternate data stream.
//!
//! Files on Windows keeps its tags in its own database. That is the wrong shape
//! here, because a tag stored beside the file travels with it: copy it to a
//! stick, and a tag in a private database does not go, while an extended
//! attribute does. The names used are the ones other desktops already read.
//!
//! Two limits are real and are surfaced rather than hidden. A FAT or exFAT
//! volume has no extended attributes at all, which is [`Error::Unsupported`]
//! and not a failure. And a value has to fit in one filesystem block, which is
//! why a stream here is for small sidecar data rather than for a second copy of
//! the file.

use std::path::Path;

use crate::error::{Error, Result};

/// Comma separated labels, the spelling tracker and tmsu also use.
pub const TAGS: &str = "user.xdg.tags";
/// A free text note about the file.
pub const COMMENT: &str = "user.xdg.comment";
/// Where a download came from. Browsers write these, so Files can show a
/// downloaded file's source without keeping its own record.
pub const ORIGIN_URL: &str = "user.xdg.origin.url";
pub const REFERRER_URL: &str = "user.xdg.referrer.url";
/// The per folder icon override the customization tab sets.
pub const ICON: &str = "user.aurade.icon";
/// Named sidecar data. The prefix keeps them apart from everything else, so
/// listing streams cannot accidentally show a tag.
pub const STREAM_PREFIX: &str = "user.aurade.stream.";

/// Values above this are refused with an explanation rather than an errno.
/// Most filesystems cap a single attribute at one block, commonly four
/// kilobytes on ext4 and sixteen on Btrfs with larger nodes.
pub const MAX_VALUE: usize = 60 * 1024;

const ENODATA: i32 = 61;
const ENOATTR: i32 = ENODATA;
//: ENOTSUP and EOPNOTSUPP are the same number on Linux, and this is the one
//: a filesystem without extended attributes returns.
const ENOTSUP: i32 = 95;
const ERANGE: i32 = 34;

fn map(path: &Path, e: rustix::io::Errno) -> Error {
    match e.raw_os_error() {
        ENOTSUP => Error::Unsupported(format!(
            "{} is on a filesystem without extended attributes",
            path.display()
        )),
        _ => Error::io(
            path.display().to_string(),
            std::io::Error::from_raw_os_error(e.raw_os_error()),
        ),
    }
}

/// Read one attribute. A missing attribute is `None`, not an error: asking
/// whether a file has tags is a normal thing to do.
///
/// Symlinks are never followed, so an attribute read is always about the file
/// the user clicked on.
pub fn get(path: &Path, name: &str) -> Result<Option<Vec<u8>>> {
    let size = match rustix::fs::lgetxattr(path, name, &mut [][..] as &mut [u8]) {
        Ok(n) => n,
        Err(e) if e.raw_os_error() == ENOATTR => return Ok(None),
        Err(e) => return Err(map(path, e)),
    };
    let mut buf = vec![0u8; size];
    match rustix::fs::lgetxattr(path, name, &mut buf[..]) {
        Ok(n) => {
            buf.truncate(n);
            Ok(Some(buf))
        }
        Err(e) if e.raw_os_error() == ENOATTR => Ok(None),
        //: It grew between the two calls. One retry with the new size, and if
        //: it is still moving the caller is better off being told.
        Err(e) if e.raw_os_error() == ERANGE => {
            let size = rustix::fs::lgetxattr(path, name, &mut [][..] as &mut [u8]).map_err(|e| map(path, e))?;
            let mut buf = vec![0u8; size];
            let n = rustix::fs::lgetxattr(path, name, &mut buf[..]).map_err(|e| map(path, e))?;
            buf.truncate(n);
            Ok(Some(buf))
        }
        Err(e) => Err(map(path, e)),
    }
}

/// The same, for the attributes that hold text.
pub fn get_string(path: &Path, name: &str) -> Result<Option<String>> {
    Ok(get(path, name)?.map(|v| String::from_utf8_lossy(&v).into_owned()))
}

/// Write one attribute, replacing whatever was there.
pub fn set(path: &Path, name: &str, value: &[u8]) -> Result<()> {
    if value.len() > MAX_VALUE {
        return Err(Error::BadRequest(format!(
            "{} bytes is more than an extended attribute can hold",
            value.len()
        )));
    }
    rustix::fs::lsetxattr(path, name, value, rustix::fs::XattrFlags::empty())
        .map_err(|e| map(path, e))
}

/// Remove one attribute. Removing one that is not there is a success, because
/// the caller wanted it gone and it is gone.
pub fn remove(path: &Path, name: &str) -> Result<()> {
    match rustix::fs::lremovexattr(path, name) {
        Ok(()) => Ok(()),
        Err(e) if e.raw_os_error() == ENOATTR => Ok(()),
        Err(e) => Err(map(path, e)),
    }
}

/// Every attribute name on the file.
pub fn list(path: &Path) -> Result<Vec<String>> {
    let size = match rustix::fs::llistxattr(path, &mut [][..] as &mut [u8]) {
        Ok(n) => n,
        Err(e) if e.raw_os_error() == ENOATTR => return Ok(Vec::new()),
        Err(e) => return Err(map(path, e)),
    };
    if size == 0 {
        return Ok(Vec::new());
    }
    let mut buf = vec![0u8; size];
    let n = rustix::fs::llistxattr(path, &mut buf[..]).map_err(|e| map(path, e))?;
    buf.truncate(n);
    Ok(buf
        .split(|b| *b == 0)
        .filter(|s| !s.is_empty())
        .map(|s| String::from_utf8_lossy(s).into_owned())
        .collect())
}

// ------------------------------------------------------------------- tags ---

/// The tags on a file, in the order they were stored.
pub fn tags(path: &Path) -> Result<Vec<String>> {
    Ok(get_string(path, TAGS)?.map(|v| decode_tags(&v)).unwrap_or_default())
}

/// Replace the whole set. An empty set removes the attribute rather than
/// storing an empty string, so a file with no tags looks the same to every
/// other program as one that never had any.
///
/// A name with a comma in it is refused, not escaped. This attribute is a
/// plain comma separated list that other file managers read and write, and an
/// escape invented here would be legible in this one program and nowhere else.
/// Refusing keeps what is on the file true.
pub fn set_tags(path: &Path, tags: &[String]) -> Result<()> {
    let mut clean: Vec<String> = Vec::new();
    for tag in tags {
        let tag = tag.trim();
        if tag.is_empty() {
            continue;
        }
        if tag.contains(',') {
            return Err(Error::BadRequest(format!("a tag cannot contain a comma: {tag}")));
        }
        if !clean.iter().any(|t| t == tag) {
            clean.push(tag.to_string());
        }
    }
    if clean.is_empty() {
        return remove(path, TAGS);
    }
    set(path, TAGS, encode_tags(&clean).as_bytes())
}

/// Add one tag, keeping the rest. Adding a tag that is already there changes
/// nothing, which is what a checkbox in a menu needs.
pub fn add_tag(path: &Path, tag: &str) -> Result<Vec<String>> {
    let mut current = tags(path)?;
    let tag = tag.trim();
    if !tag.is_empty() && !current.iter().any(|t| t == tag) {
        current.push(tag.to_string());
        set_tags(path, &current)?;
    }
    Ok(current)
}

pub fn remove_tag(path: &Path, tag: &str) -> Result<Vec<String>> {
    let mut current = tags(path)?;
    let before = current.len();
    current.retain(|t| t != tag);
    if current.len() != before {
        set_tags(path, &current)?;
    }
    Ok(current)
}

/// A comma separates tags and nothing quotes one, which is the whole format.
/// Names are checked on the way in so that this stays true.
fn encode_tags(tags: &[String]) -> String {
    tags.join(",")
}

/// Spaces around a name are dropped and an empty run is skipped, because a
/// list written by hand or by another program will have both.
fn decode_tags(value: &str) -> Vec<String> {
    value
        .split(',')
        .map(str::trim)
        .filter(|t| !t.is_empty())
        .map(str::to_string)
        .collect()
}

// ---------------------------------------------------------------- streams ---

/// One named piece of sidecar data.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Stream {
    pub name: String,
    pub size: usize,
}

/// Windows calls these alternate data streams and Files lists them on the
/// properties window. The honest equivalent here is a named extended
/// attribute, which behaves the same way in the ways that matter: it belongs
/// to the file, it is invisible to a program that does not ask, and it is lost
/// on a filesystem that cannot hold it.
pub fn streams(path: &Path) -> Result<Vec<Stream>> {
    let mut out = Vec::new();
    for name in list(path)? {
        let Some(short) = name.strip_prefix(STREAM_PREFIX) else { continue };
        let size = get(path, &name)?.map(|v| v.len()).unwrap_or(0);
        out.push(Stream { name: short.to_string(), size });
    }
    out.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(out)
}

fn stream_key(name: &str) -> Result<String> {
    if name.is_empty() {
        return Err(Error::BadRequest("a stream needs a name".into()));
    }
    //: The name becomes part of an attribute key, so a null or a leading dot
    //: that would confuse a listing is refused at the door.
    if name.contains('\0') || name.starts_with('.') {
        return Err(Error::BadRequest(format!("{name} is not a usable stream name")));
    }
    Ok(format!("{STREAM_PREFIX}{name}"))
}

pub fn read_stream(path: &Path, name: &str) -> Result<Option<Vec<u8>>> {
    get(path, &stream_key(name)?)
}

pub fn write_stream(path: &Path, name: &str, value: &[u8]) -> Result<()> {
    set(path, &stream_key(name)?, value)
}

pub fn remove_stream(path: &Path, name: &str) -> Result<()> {
    remove(path, &stream_key(name)?)
}

// ------------------------------------------------------- the named fields ---

pub fn comment(path: &Path) -> Result<Option<String>> {
    get_string(path, COMMENT)
}

pub fn set_comment(path: &Path, text: &str) -> Result<()> {
    if text.trim().is_empty() {
        return remove(path, COMMENT);
    }
    set(path, COMMENT, text.as_bytes())
}

/// Where a downloaded file came from, as (source, referrer).
pub fn origin(path: &Path) -> Result<(Option<String>, Option<String>)> {
    Ok((get_string(path, ORIGIN_URL)?, get_string(path, REFERRER_URL)?))
}

/// The icon override for a folder, as the art key the page knows.
pub fn icon(path: &Path) -> Result<Option<String>> {
    get_string(path, ICON)
}

pub fn set_icon(path: &Path, key: Option<&str>) -> Result<()> {
    match key {
        Some(k) if !k.is_empty() => set(path, ICON, k.as_bytes()),
        _ => remove(path, ICON),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn scratch(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("auradefs-xattr-{tag}"));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("subject.txt");
        std::fs::write(&file, b"contents").unwrap();
        file
    }

    /// Extended attributes need a filesystem that has them. On one that does
    /// not, the tests would fail for a reason that is not a defect, so they say
    /// so and stop.
    fn supported(path: &Path) -> bool {
        match set(path, "user.auradefs.probe", b"1") {
            Ok(()) => {
                let _ = remove(path, "user.auradefs.probe");
                true
            }
            Err(Error::Unsupported(_)) => {
                eprintln!("skipped: {} has no extended attributes", path.display());
                false
            }
            Err(e) => panic!("probe failed for a reason that is not support: {e:?}"),
        }
    }

    #[test]
    fn tags_round_trip_and_an_empty_set_leaves_nothing_behind() {
        let file = scratch("tags");
        if !supported(&file) { return }
        assert_eq!(tags(&file).unwrap(), Vec::<String>::new());
        set_tags(&file, &["Work".into(), "Urgent".into()]).unwrap();
        assert_eq!(tags(&file).unwrap(), ["Work", "Urgent"]);
        set_tags(&file, &[]).unwrap();
        assert_eq!(tags(&file).unwrap(), Vec::<String>::new());
        assert!(
            !list(&file).unwrap().iter().any(|n| n == TAGS),
            "an empty tag set left an empty attribute behind"
        );
    }

    #[test]
    fn a_tag_with_a_comma_in_it_is_refused_rather_than_written() {
        let file = scratch("tag-comma");
        if !supported(&file) { return }
        set_tags(&file, &["plain".into()]).unwrap();
        let Err(err) = set_tags(&file, &["Smith, Jane".into(), "plain".into()]) else {
            panic!("a comma went into the list that a comma separates");
        };
        assert_eq!(err.code(), "bad-request");
        //: And the refusal changed nothing. A rejected write that had already
        //: replaced half the set would be worse than either outcome.
        assert_eq!(tags(&file).unwrap(), ["plain"]);

        //: A backslash is an ordinary character now that nothing escapes.
        set_tags(&file, &["back\\slash".into()]).unwrap();
        assert_eq!(tags(&file).unwrap(), ["back\\slash"]);
    }

    #[test]
    fn tag_encoding_is_what_another_reader_would_see() {
        assert_eq!(encode_tags(&["a".into(), "b".into()]), "a,b");
        assert_eq!(encode_tags(&["back\\slash".into()]), "back\\slash");
        assert_eq!(decode_tags("a,b"), ["a", "b"]);
        assert_eq!(decode_tags("a, b ,, c"), ["a", "b", "c"]);
        assert_eq!(decode_tags(""), Vec::<String>::new());
        //: Written by something that did try to escape: two names, which is
        //: what any other reader of this attribute would also see.
        assert_eq!(decode_tags("Smith\\, Jane"), ["Smith\\", "Jane"]);
    }

    #[test]
    fn adding_a_tag_twice_changes_nothing() {
        let file = scratch("tag-twice");
        if !supported(&file) { return }
        add_tag(&file, "Work").unwrap();
        let after = add_tag(&file, "Work").unwrap();
        assert_eq!(after, ["Work"]);
        assert_eq!(remove_tag(&file, "Work").unwrap(), Vec::<String>::new());
        //: Removing one that was never there is a success.
        assert_eq!(remove_tag(&file, "Work").unwrap(), Vec::<String>::new());
    }

    #[test]
    fn a_missing_attribute_reads_as_nothing_rather_than_an_error() {
        let file = scratch("missing");
        if !supported(&file) { return }
        assert_eq!(get(&file, "user.nothing.here").unwrap(), None);
        assert_eq!(comment(&file).unwrap(), None);
        assert_eq!(origin(&file).unwrap(), (None, None));
        //: And removing one is a success, so a clear button never fails.
        remove(&file, "user.nothing.here").unwrap();
    }

    #[test]
    fn streams_are_listed_apart_from_everything_else() {
        let file = scratch("streams");
        if !supported(&file) { return }
        set_tags(&file, &["Work".into()]).unwrap();
        set_comment(&file, "a note").unwrap();
        write_stream(&file, "Zone.Identifier", b"[ZoneTransfer]\r\nZoneId=3\r\n").unwrap();
        write_stream(&file, "notes", b"second").unwrap();

        let found = streams(&file).unwrap();
        assert_eq!(
            found,
            [
                Stream { name: "Zone.Identifier".into(), size: 26 },
                Stream { name: "notes".into(), size: 6 },
            ],
            "a tag or a comment was counted as a stream"
        );
        assert_eq!(read_stream(&file, "notes").unwrap().unwrap(), b"second");
        remove_stream(&file, "notes").unwrap();
        assert_eq!(read_stream(&file, "notes").unwrap(), None);
        assert_eq!(streams(&file).unwrap().len(), 1);
        //: The tag is still there, untouched by the stream work.
        assert_eq!(tags(&file).unwrap(), ["Work"]);
    }

    #[test]
    fn a_stream_name_that_would_confuse_the_key_is_refused() {
        let file = scratch("stream-name");
        if !supported(&file) { return }
        for bad in ["", ".hidden", "with\0null"] {
            assert!(write_stream(&file, bad, b"x").is_err(), "{bad:?} allowed");
        }
    }

    #[test]
    fn a_value_too_large_to_store_is_refused_before_the_syscall() {
        let file = scratch("too-big");
        if !supported(&file) { return }
        let err = write_stream(&file, "huge", &vec![b'x'; MAX_VALUE + 1]).unwrap_err();
        assert!(matches!(err, Error::BadRequest(_)), "got {err:?}");
    }

    #[test]
    fn a_comment_cleared_removes_the_attribute() {
        let file = scratch("comment");
        if !supported(&file) { return }
        set_comment(&file, "remember this").unwrap();
        assert_eq!(comment(&file).unwrap().as_deref(), Some("remember this"));
        set_comment(&file, "   ").unwrap();
        assert_eq!(comment(&file).unwrap(), None);
    }

    #[test]
    fn a_custom_icon_is_set_and_cleared() {
        let dir = std::env::temp_dir().join("auradefs-xattr-icon");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        if !supported(&dir) { return }
        set_icon(&dir, Some("folder-music")).unwrap();
        assert_eq!(icon(&dir).unwrap().as_deref(), Some("folder-music"));
        set_icon(&dir, None).unwrap();
        assert_eq!(icon(&dir).unwrap(), None);
    }

    #[test]
    fn an_attribute_is_read_from_the_link_and_not_its_target() {
        let file = scratch("nofollow");
        if !supported(&file) { return }
        let link = file.with_file_name("pointer");
        std::os::unix::fs::symlink(&file, &link).unwrap();
        set_tags(&file, &["Target".into()]).unwrap();
        //: The link itself carries no user attributes, and the kernel will not
        //: let it. What matters is that reading through it does not silently
        //: report the target's.
        assert_eq!(tags(&link).unwrap(), Vec::<String>::new());
    }
}
