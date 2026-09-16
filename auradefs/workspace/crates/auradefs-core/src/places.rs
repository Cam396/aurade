//! The sidebar: the folders the desktop already knows about, the ones the user
//! has pinned, and the files they opened recently.
//!
//! None of this is invented. The special folders come from `user-dirs.dirs`,
//! the pinned ones from the same bookmarks file every GTK file chooser reads
//! and writes, and the recent list from `recently-used.xbel`. A file manager
//! that kept its own copies of these would show a sidebar that disagreed with
//! every Open dialog on the system.

use std::path::{Path, PathBuf};

use crate::error::{Error, Result};
use crate::mime::{xdg_config_home, xdg_data_home};

/// One of the folders the desktop gives a name and an icon to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum UserDir {
    Home,
    Desktop,
    Documents,
    Downloads,
    Music,
    Pictures,
    Videos,
    Templates,
    PublicShare,
}

impl UserDir {
    /// The key in `user-dirs.dirs`. Home has none: it is always `$HOME`.
    fn key(self) -> Option<&'static str> {
        Some(match self {
            UserDir::Home => return None,
            UserDir::Desktop => "XDG_DESKTOP_DIR",
            UserDir::Documents => "XDG_DOCUMENTS_DIR",
            UserDir::Downloads => "XDG_DOWNLOAD_DIR",
            UserDir::Music => "XDG_MUSIC_DIR",
            UserDir::Pictures => "XDG_PICTURES_DIR",
            UserDir::Videos => "XDG_VIDEOS_DIR",
            UserDir::Templates => "XDG_TEMPLATES_DIR",
            UserDir::PublicShare => "XDG_PUBLICSHARE_DIR",
        })
    }

    /// What the sidebar calls it when the system has no other name.
    pub fn label(self) -> &'static str {
        match self {
            UserDir::Home => "Home",
            UserDir::Desktop => "Desktop",
            UserDir::Documents => "Documents",
            UserDir::Downloads => "Downloads",
            UserDir::Music => "Music",
            UserDir::Pictures => "Pictures",
            UserDir::Videos => "Videos",
            UserDir::Templates => "Templates",
            UserDir::PublicShare => "Public",
        }
    }

    /// The default location, used when `user-dirs.dirs` says nothing.
    fn fallback(self, home: &Path) -> PathBuf {
        match self {
            UserDir::Home => home.to_path_buf(),
            other => home.join(other.label()),
        }
    }

    pub const ALL: [UserDir; 9] = [
        UserDir::Home,
        UserDir::Desktop,
        UserDir::Documents,
        UserDir::Downloads,
        UserDir::Music,
        UserDir::Pictures,
        UserDir::Videos,
        UserDir::Templates,
        UserDir::PublicShare,
    ];
}

/// Where each of the special folders is, and whether it is really there. A
/// configuration can point one at a folder that has been deleted, and the
/// sidebar should not offer a row that leads nowhere.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Place {
    pub kind: Option<UserDir>,
    pub label: String,
    pub path: PathBuf,
    pub exists: bool,
}

pub fn home() -> Result<PathBuf> {
    std::env::var("HOME")
        .ok()
        .filter(|h| !h.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| Error::NotFound("HOME is not set".into()))
}

/// Read `user-dirs.dirs` and resolve every special folder.
pub fn user_dirs() -> Result<Vec<Place>> {
    let home = home()?;
    let text = xdg_config_home()
        .map(|c| c.join("user-dirs.dirs"))
        .and_then(|p| std::fs::read_to_string(p).ok())
        .unwrap_or_default();
    Ok(parse_user_dirs(&text, &home))
}

fn parse_user_dirs(text: &str, home: &Path) -> Vec<Place> {
    let mut found = std::collections::HashMap::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else { continue };
        let value = value.trim().trim_matches('"');
        //: The file writes paths as $HOME/Name, and that is the only expansion
        //: it is allowed: this is configuration, not a shell script.
        let path = match value.strip_prefix("$HOME/") {
            Some(rest) => home.join(rest),
            None if value == "$HOME" => home.to_path_buf(),
            None => PathBuf::from(value),
        };
        found.insert(key.trim().to_string(), path);
    }
    UserDir::ALL
        .iter()
        .map(|kind| {
            let path = kind
                .key()
                .and_then(|k| found.get(k).cloned())
                .unwrap_or_else(|| kind.fallback(home));
            Place {
                kind: Some(*kind),
                label: kind.label().to_string(),
                exists: path.is_dir(),
                path,
            }
        })
        .collect()
}

// -------------------------------------------------------------- bookmarks ---

/// The bookmarks file every GTK file chooser reads. Writing here is what makes
/// a folder pinned in this file manager also appear in every Save dialog.
pub fn bookmarks_path() -> Result<PathBuf> {
    Ok(xdg_config_home()
        .ok_or_else(|| Error::NotFound("no config directory".into()))?
        .join("gtk-3.0/bookmarks"))
}

pub fn bookmarks() -> Result<Vec<Place>> {
    let path = bookmarks_path()?;
    let text = std::fs::read_to_string(&path).unwrap_or_default();
    Ok(parse_bookmarks(&text))
}

fn parse_bookmarks(text: &str) -> Vec<Place> {
    let mut out = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        //: The format is a URI, optionally followed by a space and a label
        //: that overrides the folder's own name.
        let (uri, label) = match line.split_once(' ') {
            Some((u, l)) => (u, Some(l.trim().to_string())),
            None => (line, None),
        };
        //: Only local folders. A bookmark to sftp:// or smb:// belongs to
        //: whatever mounts it, and this service does not.
        let Some(path) = from_file_url(uri) else { continue };
        let label = label.unwrap_or_else(|| {
            path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| uri.into())
        });
        out.push(Place { kind: None, exists: path.is_dir(), label, path });
    }
    out
}

/// Pin a folder. Already pinned is a success and changes nothing, so a menu
/// item can be pressed twice without producing two rows.
pub fn add_bookmark(path: &Path, label: Option<&str>) -> Result<()> {
    if !path.is_dir() {
        return Err(Error::BadRequest(format!("{} is not a folder", path.display())));
    }
    let file = bookmarks_path()?;
    let text = std::fs::read_to_string(&file).unwrap_or_default();
    let uri = crate::apps::file_url(path);
    if text.lines().any(|l| l.split(' ').next() == Some(uri.as_str())) {
        return Ok(());
    }
    let mut updated = text;
    if !updated.is_empty() && !updated.ends_with('\n') {
        updated.push('\n');
    }
    updated.push_str(&uri);
    if let Some(label) = label.filter(|l| !l.trim().is_empty()) {
        updated.push(' ');
        updated.push_str(label.trim());
    }
    updated.push('\n');
    write_new(&file, updated.as_bytes())
}

/// Unpin. Removing one that is not there is a success.
pub fn remove_bookmark(path: &Path) -> Result<()> {
    let file = bookmarks_path()?;
    let Ok(text) = std::fs::read_to_string(&file) else { return Ok(()) };
    let uri = crate::apps::file_url(path);
    let kept: Vec<&str> = text
        .lines()
        .filter(|l| l.split(' ').next() != Some(uri.as_str()))
        .collect();
    let mut updated = kept.join("\n");
    if !updated.is_empty() {
        updated.push('\n');
    }
    write_new(&file, updated.as_bytes())
}

/// Reorder, by writing the given paths in the given order. Anything pinned but
/// not named keeps its place at the end, so a stale list from the UI cannot
/// delete a bookmark by omission.
pub fn reorder_bookmarks(order: &[PathBuf]) -> Result<()> {
    let current = bookmarks()?;
    let mut lines: Vec<String> = Vec::new();
    let mut used: Vec<&Place> = Vec::new();
    for wanted in order {
        if let Some(place) = current.iter().find(|p| &p.path == wanted) {
            lines.push(bookmark_line(place));
            used.push(place);
        }
    }
    for place in &current {
        if !used.iter().any(|u| u.path == place.path) {
            lines.push(bookmark_line(place));
        }
    }
    let mut text = lines.join("\n");
    if !text.is_empty() {
        text.push('\n');
    }
    write_new(&bookmarks_path()?, text.as_bytes())
}

fn bookmark_line(place: &Place) -> String {
    let uri = crate::apps::file_url(&place.path);
    let default = place
        .path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default();
    if place.label == default {
        uri
    } else {
        format!("{uri} {}", place.label)
    }
}

/// `file:///home/cam/x` back to a path, undoing the percent encoding. Anything
/// that is not a local file gives nothing.
pub fn from_file_url(uri: &str) -> Option<PathBuf> {
    let rest = uri.strip_prefix("file://")?;
    //: file://host/path is someone else's host. Only an empty authority, which
    //: means this machine, is a path here.
    let rest = if let Some(stripped) = rest.strip_prefix('/') {
        format!("/{stripped}")
    } else {
        return None;
    };
    let bytes = rest.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(byte) = u8::from_str_radix(&rest[i + 1..i + 3], 16) {
                out.push(byte);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    use std::os::unix::ffi::OsStringExt;
    Some(PathBuf::from(std::ffi::OsString::from_vec(out)))
}

/// Write through a temporary file and rename, and make the directory first.
fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| Error::io(dir.display().to_string(), e))?;
    }
    let tmp = path.with_extension(format!("tmp{}", std::process::id()));
    std::fs::write(&tmp, bytes).map_err(|e| Error::io(tmp.display().to_string(), e))?;
    std::fs::rename(&tmp, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        Error::io(path.display().to_string(), e)
    })
}

// ----------------------------------------------------------------- recent ---

/// One entry in the recent list.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Recent {
    pub path: PathBuf,
    pub mime: Option<String>,
    /// The `visited` timestamp as written, in the file's own format.
    pub visited: Option<String>,
    pub exists: bool,
}

pub fn recent_path() -> Result<PathBuf> {
    Ok(xdg_data_home()
        .ok_or_else(|| Error::NotFound("no data directory".into()))?
        .join("recently-used.xbel"))
}

/// Read the recent list, newest first, dropping anything that is no longer
/// there. A row that cannot be opened is worse than a shorter list.
pub fn recent(limit: usize) -> Result<Vec<Recent>> {
    let text = std::fs::read_to_string(recent_path()?).unwrap_or_default();
    let mut out: Vec<Recent> = parse_recent(&text)
        .into_iter()
        .filter(|r| r.exists)
        .collect();
    //: The file is written oldest first by GTK, and the sidebar wants the
    //: other way round.
    out.reverse();
    out.truncate(limit);
    Ok(out)
}

fn parse_recent(text: &str) -> Vec<Recent> {
    let mut out = Vec::new();
    for raw in split_bookmarks(text) {
        let Some(href) = attribute(&raw, "href") else { continue };
        let Some(path) = from_file_url(&unescape_xml(&href)) else { continue };
        out.push(Recent {
            exists: path.exists(),
            path,
            mime: attribute(&raw, "type"),
            visited: attribute(&raw, "visited"),
        });
    }
    out
}

/// Each `<bookmark ...>...</bookmark>` block, kept as raw text. Keeping the
/// text rather than a parse tree is what lets an entry be rewritten without
/// losing the application registrations other programs put inside it.
fn split_bookmarks(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut rest = text;
    while let Some(start) = rest.find("<bookmark") {
        let after = &rest[start..];
        let end = match after.find("</bookmark>") {
            Some(e) => e + "</bookmark>".len(),
            //: A self closing entry, which is legal and which some writers use.
            None => match after.find("/>") {
                Some(e) => e + 2,
                None => break,
            },
        };
        //: A self closing tag before the next close tag belongs to this entry.
        let self_close = after[..end].find("/>").filter(|i| {
            after[..*i].find('>').is_none()
        });
        let end = match self_close {
            Some(i) => i + 2,
            None => end,
        };
        out.push(after[..end].to_string());
        rest = &after[end..];
    }
    out
}

fn attribute(tag: &str, name: &str) -> Option<String> {
    let needle = format!("{name}=\"");
    let at = tag.find(&needle)? + needle.len();
    let end = tag[at..].find('"')? + at;
    Some(tag[at..end].to_string())
}

fn unescape_xml(value: &str) -> String {
    value
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&apos;", "'")
}

fn escape_xml(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

/// Note that a file was opened.
///
/// The existing entries are carried across as the exact text they were written
/// as, so the applications each one registers survive. Only the entry for this
/// path is rewritten, and it moves to the end, which is where the newest entry
/// goes.
pub fn add_recent(path: &Path, mime: &str, app: &str) -> Result<()> {
    let file = recent_path()?;
    let text = std::fs::read_to_string(&file).unwrap_or_default();
    let uri = escape_xml(&crate::apps::file_url(path));
    let now = timestamp();

    let mut kept: Vec<String> = split_bookmarks(&text)
        .into_iter()
        .filter(|b| attribute(b, "href").as_deref() != Some(uri.as_str()))
        .collect();
    //: A recent list is a list, not an archive. Two hundred is what GTK keeps.
    while kept.len() >= 200 {
        kept.remove(0);
    }
    kept.push(format!(
        concat!(
            "<bookmark href=\"{uri}\" added=\"{now}\" modified=\"{now}\" visited=\"{now}\">\n",
            "    <info>\n",
            "      <metadata owner=\"http://freedesktop.org\">\n",
            "        <mime:mime-type type=\"{mime}\"/>\n",
            "        <bookmark:applications>\n",
            "          <bookmark:application name=\"{app}\" exec=\"&apos;{app} %u&apos;\" modified=\"{now}\" count=\"1\"/>\n",
            "        </bookmark:applications>\n",
            "      </metadata>\n",
            "    </info>\n",
            "  </bookmark>"
        ),
        uri = uri,
        now = now,
        mime = escape_xml(mime),
        app = escape_xml(app),
    ));

    let body = kept.join("\n  ");
    let out = format!(
        concat!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n",
            "<xbel version=\"1.0\"\n",
            "      xmlns:bookmark=\"http://www.freedesktop.org/standards/desktop-bookmarks\"\n",
            "      xmlns:mime=\"http://www.freedesktop.org/standards/shared-mime-info\">\n",
            "  {body}\n",
            "</xbel>\n"
        ),
        body = body
    );
    write_new(&file, out.as_bytes())
}

/// Empty the recent list.
pub fn clear_recent() -> Result<()> {
    let out = concat!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n",
        "<xbel version=\"1.0\"\n",
        "      xmlns:bookmark=\"http://www.freedesktop.org/standards/desktop-bookmarks\"\n",
        "      xmlns:mime=\"http://www.freedesktop.org/standards/shared-mime-info\">\n",
        "</xbel>\n"
    );
    write_new(&recent_path()?, out.as_bytes())
}

/// `2026-09-08T12:00:00Z`, which is what the file uses.
fn timestamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let days = secs.div_euclid(86_400);
    let rest = secs.rem_euclid(86_400);
    let (y, m, d) = civil_from_days(days);
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        (rest % 3600) / 60,
        rest % 60
    )
}

/// Days since the epoch back to a calendar date, by Howard Hinnant's algorithm.
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_special_folders_come_from_the_configuration_and_fall_back_when_it_is_silent() {
        let home = Path::new("/home/cam");
        let text = concat!(
            "# generated\n",
            "XDG_DESKTOP_DIR=\"$HOME/Desktop\"\n",
            "XDG_DOWNLOAD_DIR=\"$HOME/Inbox\"\n",
            "XDG_MUSIC_DIR=\"/media/library/music\"\n",
        );
        let got = parse_user_dirs(text, home);
        let by = |k: UserDir| got.iter().find(|p| p.kind == Some(k)).unwrap().path.clone();
        assert_eq!(by(UserDir::Home), home);
        assert_eq!(by(UserDir::Desktop), Path::new("/home/cam/Desktop"));
        assert_eq!(by(UserDir::Downloads), Path::new("/home/cam/Inbox"), "the override was ignored");
        assert_eq!(by(UserDir::Music), Path::new("/media/library/music"), "an absolute path");
        assert_eq!(by(UserDir::Pictures), Path::new("/home/cam/Pictures"), "the fallback");
        assert_eq!(got.len(), 9);
    }

    #[test]
    fn only_home_is_expanded_and_nothing_else_is() {
        let got = parse_user_dirs("XDG_DESKTOP_DIR=\"$OTHER/x\"\n", Path::new("/home/cam"));
        let desktop = got.iter().find(|p| p.kind == Some(UserDir::Desktop)).unwrap();
        assert_eq!(desktop.path, Path::new("$OTHER/x"), "a second variable was expanded");
    }

    #[test]
    fn a_bookmark_line_is_a_uri_and_an_optional_label() {
        let text = concat!(
            "file:///home/cam/Projects\n",
            "file:///home/cam/Client%20Work Client\n",
            "sftp://server/share Remote\n",
            "\n",
        );
        let got = parse_bookmarks(text);
        assert_eq!(got.len(), 2, "a remote bookmark was kept: {got:?}");
        assert_eq!(got[0].path, Path::new("/home/cam/Projects"));
        assert_eq!(got[0].label, "Projects", "no label, so the folder's own name");
        assert_eq!(got[1].path, Path::new("/home/cam/Client Work"), "percent encoding survived");
        assert_eq!(got[1].label, "Client");
    }

    #[test]
    fn a_file_url_only_answers_for_this_machine() {
        assert_eq!(from_file_url("file:///a/b"), Some(PathBuf::from("/a/b")));
        assert_eq!(from_file_url("file:///a/b%20c"), Some(PathBuf::from("/a/b c")));
        assert_eq!(from_file_url("file://otherhost/a"), None);
        assert_eq!(from_file_url("sftp://host/a"), None);
        assert_eq!(from_file_url("/a/b"), None);
        //: A stray percent that is not an escape stays a percent.
        assert_eq!(from_file_url("file:///a/100%"), Some(PathBuf::from("/a/100%")));
    }

    #[test]
    fn a_bookmark_survives_a_round_trip_through_the_line_form() {
        let named = Place {
            kind: None,
            label: "Client".into(),
            path: PathBuf::from("/home/cam/Client Work"),
            exists: true,
        };
        assert_eq!(bookmark_line(&named), "file:///home/cam/Client%20Work Client");
        let plain = Place { label: "Projects".into(), path: "/home/cam/Projects".into(), ..named };
        //: A label that is only the folder's own name is not written, which is
        //: what every other writer of this file does.
        assert_eq!(bookmark_line(&plain), "file:///home/cam/Projects");
    }

    const XBEL: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<xbel version="1.0" xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks" xmlns:mime="http://www.freedesktop.org/standards/shared-mime-info">
  <bookmark href="file:///etc/hostname" added="2026-01-01T00:00:00Z" modified="2026-01-01T00:00:00Z" visited="2026-01-01T00:00:00Z">
    <info>
      <metadata owner="http://freedesktop.org">
        <mime:mime-type type="text/plain"/>
        <bookmark:applications>
          <bookmark:application name="gedit" exec="&apos;gedit %u&apos;" modified="2026-01-01T00:00:00Z" count="3"/>
        </bookmark:applications>
      </metadata>
    </info>
  </bookmark>
  <bookmark href="file:///nowhere/gone.txt" added="2026-01-02T00:00:00Z" modified="2026-01-02T00:00:00Z" visited="2026-01-02T00:00:00Z"/>
  <bookmark href="sftp://host/remote.txt" added="2026-01-03T00:00:00Z" modified="2026-01-03T00:00:00Z" visited="2026-01-03T00:00:00Z"/>
</xbel>
"#;

    #[test]
    fn the_recent_list_reads_entries_and_their_types() {
        let got = parse_recent(XBEL);
        assert_eq!(got.len(), 2, "a remote entry was kept: {got:?}");
        assert_eq!(got[0].path, Path::new("/etc/hostname"));
        assert_eq!(got[0].mime.as_deref(), Some("text/plain"));
        assert_eq!(got[0].visited.as_deref(), Some("2026-01-01T00:00:00Z"));
        assert!(got[0].exists);
        assert!(!got[1].exists, "a file that is gone was reported as present");
    }

    #[test]
    fn each_entry_is_kept_whole_so_another_programs_registration_survives() {
        let blocks = split_bookmarks(XBEL);
        assert_eq!(blocks.len(), 3);
        assert!(
            blocks[0].contains("bookmark:application name=\"gedit\""),
            "the application registration was lost"
        );
        assert!(blocks[0].ends_with("</bookmark>"));
        assert!(blocks[1].ends_with("/>"), "a self closing entry was not recognised");
        assert!(!blocks[1].contains("sftp"), "two entries ran together");
    }

    #[test]
    fn an_attribute_is_read_from_the_tag_it_belongs_to() {
        let tag = r#"<bookmark href="file:///a" added="1" visited="2">"#;
        assert_eq!(attribute(tag, "href").as_deref(), Some("file:///a"));
        assert_eq!(attribute(tag, "visited").as_deref(), Some("2"));
        assert_eq!(attribute(tag, "missing"), None);
    }

    #[test]
    fn xml_escaping_goes_both_ways() {
        assert_eq!(escape_xml("a&b<c>\"d\""), "a&amp;b&lt;c&gt;&quot;d&quot;");
        assert_eq!(unescape_xml("a&amp;b&lt;c&gt;&apos;"), "a&b<c>'");
    }

    #[test]
    fn a_timestamp_is_the_form_the_file_uses() {
        let now = timestamp();
        assert_eq!(now.len(), 20, "{now}");
        assert!(now.ends_with('Z'));
        assert_eq!(&now[4..5], "-");
        assert_eq!(&now[10..11], "T");
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        //: The two directions are separate implementations of the same
        //: calendar, so each is the other's check.
        for date in ["1970-01-01", "2000-03-01", "2026-09-08", "2100-12-31"] {
            let seconds = crate::ops::search::parse_date(date).unwrap();
            let (y, m, d) = civil_from_days(seconds / 86_400);
            assert_eq!(format!("{y:04}-{m:02}-{d:02}"), date);
        }
    }

    /// The writing side, against a real directory, by pointing the XDG
    /// variables at a scratch tree. These run in one test because they share
    /// process wide environment, and two of them in parallel would fight.
    #[test]
    fn pinning_unpinning_reordering_and_the_recent_list_all_write_correctly() {
        let base = std::env::temp_dir().join("auradefs-places-write");
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(base.join("config")).unwrap();
        std::fs::create_dir_all(base.join("data")).unwrap();
        for name in ["Projects", "Client Work", "Third"] {
            std::fs::create_dir_all(base.join(name)).unwrap();
        }
        unsafe {
            std::env::set_var("XDG_CONFIG_HOME", base.join("config"));
            std::env::set_var("XDG_DATA_HOME", base.join("data"));
        }

        add_bookmark(&base.join("Projects"), None).unwrap();
        add_bookmark(&base.join("Client Work"), Some("Client")).unwrap();
        add_bookmark(&base.join("Third"), None).unwrap();
        //: Twice is not two rows.
        add_bookmark(&base.join("Projects"), None).unwrap();
        let got = bookmarks().unwrap();
        assert_eq!(got.len(), 3, "{got:?}");
        assert_eq!(got[1].label, "Client");

        //: A folder that is not one cannot be pinned.
        assert!(add_bookmark(&base.join("Projects/nothing"), None).is_err());

        reorder_bookmarks(&[base.join("Third")]).unwrap();
        let order: Vec<String> = bookmarks().unwrap().into_iter().map(|p| p.label).collect();
        assert_eq!(
            order,
            ["Third", "Projects", "Client"],
            "a bookmark left out of the new order was dropped"
        );

        remove_bookmark(&base.join("Projects")).unwrap();
        assert_eq!(bookmarks().unwrap().len(), 2);
        //: Removing one that is already gone is still a success.
        remove_bookmark(&base.join("Projects")).unwrap();

        let file = base.join("Projects.txt");
        std::fs::write(&file, b"x").unwrap();
        add_recent(&file, "text/plain", "auradefs").unwrap();
        add_recent(&base.join("Client Work"), "inode/directory", "auradefs").unwrap();
        let recent_now = recent(10).unwrap();
        assert_eq!(recent_now.len(), 2);
        assert_eq!(recent_now[0].path, base.join("Client Work"), "not newest first");
        assert_eq!(recent_now[1].mime.as_deref(), Some("text/plain"));

        //: Opening the same file again moves it to the front rather than
        //: adding a second row.
        add_recent(&file, "text/plain", "auradefs").unwrap();
        let recent_now = recent(10).unwrap();
        assert_eq!(recent_now.len(), 2);
        assert_eq!(recent_now[0].path, file);

        //: A file that has been deleted drops out of the list.
        std::fs::remove_file(&file).unwrap();
        assert_eq!(recent(10).unwrap().len(), 1);

        clear_recent().unwrap();
        assert!(recent(10).unwrap().is_empty());
    }
}
