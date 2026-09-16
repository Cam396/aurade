//! Working out what a file is.
//!
//! The shared-mime-info database is a set of plain text files that ship with
//! the system, so this reads them directly rather than shelling out to
//! `xdg-mime` for every row in a directory listing. A folder of two thousand
//! files would otherwise be two thousand processes.
//!
//! Matching follows the freedesktop rules, in the order they actually decide
//! things: a literal name wins over a glob, a longer glob wins over a shorter
//! one, a higher weight breaks a tie, and content sniffing only speaks when
//! the name says nothing.

use std::collections::HashMap;
use std::io::Read;
use std::path::{Path, PathBuf};

use crate::error::Result;

/// The generic answer, used when nothing else matches.
pub const OCTET_STREAM: &str = "application/octet-stream";
pub const PLAIN_TEXT: &str = "text/plain";
pub const DIRECTORY: &str = "inode/directory";
pub const SYMLINK: &str = "inode/symlink";

#[derive(Debug, Clone)]
struct Glob {
    pattern: String,
    mime: String,
    weight: u32,
    case_sensitive: bool,
}

/// The system mime database, read once and kept.
#[derive(Debug, Default)]
pub struct MimeDb {
    /// Patterns with no wildcard, keyed by the literal name.
    literals: HashMap<String, String>,
    /// `*.ext` patterns, keyed by the lowercased extension. This is the case
    /// that matters for a directory listing, so it gets a map rather than a
    /// scan.
    extensions: HashMap<String, Glob>,
    /// Everything else, scanned in order.
    globs: Vec<Glob>,
    aliases: HashMap<String, String>,
    parents: HashMap<String, Vec<String>>,
}

impl MimeDb {
    /// Load from every `mime` directory on the XDG data path. A missing
    /// database is not an error: the built in magic table and the extension
    /// fallbacks still answer, which keeps the file manager usable on a
    /// system without shared-mime-info installed.
    pub fn load() -> Self {
        let mut db = MimeDb::default();
        for dir in data_dirs() {
            db.read_globs(&dir.join("mime/globs2"));
            db.read_aliases(&dir.join("mime/aliases"));
            db.read_subclasses(&dir.join("mime/subclasses"));
        }
        db
    }

    fn read_globs(&mut self, path: &Path) {
        let Ok(text) = std::fs::read_to_string(path) else { return };
        for line in text.lines() {
            if line.starts_with('#') || line.is_empty() {
                continue;
            }
            //: weight:mime:glob[:flags]
            let mut parts = line.splitn(4, ':');
            let (Some(w), Some(mime), Some(pattern)) = (parts.next(), parts.next(), parts.next())
            else {
                continue;
            };
            let flags = parts.next().unwrap_or("");
            let glob = Glob {
                pattern: pattern.to_string(),
                mime: mime.to_string(),
                weight: w.parse().unwrap_or(50),
                case_sensitive: flags.contains("cs"),
            };
            if let Some(ext) = plain_extension(&glob.pattern) {
                let key = if glob.case_sensitive { ext.to_string() } else { ext.to_lowercase() };
                //: The database is read most specific last on some systems and
                //: first on others, so keep whichever pattern wins by weight.
                let better = self
                    .extensions
                    .get(&key)
                    .map(|old| glob.weight > old.weight)
                    .unwrap_or(true);
                if better {
                    self.extensions.insert(key, glob);
                }
            } else if !glob.pattern.contains(['*', '?', '[']) {
                self.literals.insert(glob.pattern.clone(), glob.mime.clone());
            } else {
                self.globs.push(glob);
            }
        }
        //: Longest pattern first, so `*.tar.gz` is tried before `*.gz`.
        self.globs.sort_by(|a, b| {
            b.weight
                .cmp(&a.weight)
                .then(b.pattern.len().cmp(&a.pattern.len()))
        });
    }

    fn read_aliases(&mut self, path: &Path) {
        let Ok(text) = std::fs::read_to_string(path) else { return };
        for line in text.lines() {
            if let Some((alias, real)) = line.split_once(' ') {
                self.aliases.insert(alias.to_string(), real.to_string());
            }
        }
    }

    fn read_subclasses(&mut self, path: &Path) {
        let Ok(text) = std::fs::read_to_string(path) else { return };
        for line in text.lines() {
            if let Some((child, parent)) = line.split_once(' ') {
                self.parents
                    .entry(child.to_string())
                    .or_default()
                    .push(parent.to_string());
            }
        }
    }

    /// The canonical name for a type that may be an alias.
    pub fn resolve(&self, mime: &str) -> String {
        self.aliases.get(mime).cloned().unwrap_or_else(|| mime.to_string())
    }

    /// `text/x-python` and everything it is a kind of, nearest first, ending
    /// at `application/octet-stream`. Used to find an application that handles
    /// a type nothing is registered for directly.
    pub fn ancestry(&self, mime: &str) -> Vec<String> {
        let mut out = vec![self.resolve(mime)];
        let mut i = 0;
        while i < out.len() {
            if let Some(parents) = self.parents.get(&out[i]) {
                for p in parents {
                    if !out.contains(p) {
                        out.push(p.clone());
                    }
                }
            }
            i += 1;
        }
        //: Not in the database, but true of everything and useful as a last
        //: resort when looking for a handler.
        if !out.iter().any(|m| m == OCTET_STREAM) {
            out.push(OCTET_STREAM.to_string());
        }
        out
    }

    /// The type suggested by the name alone.
    pub fn by_name(&self, name: &str) -> Option<String> {
        if let Some(mime) = self.literals.get(name) {
            return Some(mime.clone());
        }
        //: Try every suffix, longest first, so `x.tar.gz` finds the
        //: two part pattern before the one part one.
        let lower = name.to_lowercase();
        let mut from = 0;
        while let Some(dot) = lower[from..].find('.') {
            let at = from + dot + 1;
            let ext = &lower[at..];
            if let Some(glob) = self.extensions.get(ext) {
                //: A case sensitive pattern only matches the original spelling.
                if !glob.case_sensitive || name.ends_with(&glob.pattern[1..]) {
                    return Some(glob.mime.clone());
                }
            }
            from = at;
        }
        for glob in &self.globs {
            let hay = if glob.case_sensitive { name } else { &lower };
            let pat = if glob.case_sensitive {
                glob.pattern.clone()
            } else {
                glob.pattern.to_lowercase()
            };
            if glob_match(&pat, hay) {
                return Some(glob.mime.clone());
            }
        }
        None
    }

    /// The type of a real file, using its name, its kind, and its first bytes.
    pub fn of_path(&self, path: &Path) -> Result<String> {
        let meta = std::fs::symlink_metadata(path)
            .map_err(|e| crate::Error::io(path.display().to_string(), e))?;
        if meta.is_symlink() {
            return Ok(SYMLINK.into());
        }
        if meta.is_dir() {
            return Ok(DIRECTORY.into());
        }
        let name = path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
        if let Some(mime) = self.by_name(&name) {
            return Ok(mime);
        }
        Ok(self.sniff(path).unwrap_or_else(|| OCTET_STREAM.into()))
    }

    /// Content sniffing, for the extensionless file. Deliberately small: the
    /// full magic database is large and slow to parse, and the name answers
    /// for nearly everything. What is here are the types where guessing wrong
    /// changes what the file manager offers to do.
    pub fn sniff(&self, path: &Path) -> Option<String> {
        let mut head = [0u8; 512];
        let mut file = std::fs::File::open(path).ok()?;
        let n = file.read(&mut head).ok()?;
        let head = &head[..n];
        if head.is_empty() {
            return Some(PLAIN_TEXT.into());
        }
        for (magic, mime) in MAGIC {
            if head.len() >= magic.len() && &head[..magic.len()] == *magic {
                return Some((*mime).into());
            }
        }
        if head.len() > 4 && &head[..4] == b"RIFF" && head.len() >= 12 {
            return Some(match &head[8..12] {
                b"WAVE" => "audio/x-wav",
                b"AVI " => "video/x-msvideo",
                b"WEBP" => "image/webp",
                _ => OCTET_STREAM,
            }
            .into());
        }
        if looks_like_text(head) {
            //: A shebang is the one text case worth naming, because it decides
            //: whether Run is offered at all.
            if head.starts_with(b"#!") {
                return Some("application/x-shellscript".into());
            }
            return Some(PLAIN_TEXT.into());
        }
        Some(OCTET_STREAM.into())
    }
}

const MAGIC: &[(&[u8], &str)] = &[
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b", "application/gzip"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"\xfd7zXZ\x00", "application/x-xz"),
    (b"\x28\xb5\x2f\xfd", "application/zstd"),
    (b"BZh", "application/x-bzip2"),
    (b"\x7fELF", "application/x-executable"),
    (b"SQLite format 3\x00", "application/vnd.sqlite3"),
    (b"OggS", "application/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"\x1a\x45\xdf\xa3", "video/x-matroska"),
    (b"\x00\x01\x00\x00\x00", "font/ttf"),
    (b"OTTO", "font/otf"),
    (b"wOFF", "font/woff"),
    (b"wOF2", "font/woff2"),
    (b"<?xml", "application/xml"),
    (b"\xed\xab\xee\xdb", "application/x-rpm"),
];

/// Valid UTF-8 with no control characters other than the usual whitespace.
/// A NUL anywhere is taken as binary, which is the same call `grep` makes.
fn looks_like_text(bytes: &[u8]) -> bool {
    if bytes.contains(&0) {
        return false;
    }
    let text = match std::str::from_utf8(bytes) {
        Ok(t) => t,
        //: A cut multibyte character at the end of the buffer is not evidence
        //: of binary, so judge the part that did decode.
        Err(e) if e.valid_up_to() > 0 => &std::str::from_utf8(&bytes[..e.valid_up_to()]).unwrap(),
        Err(_) => return false,
    };
    !text
        .chars()
        .any(|c| c.is_control() && !matches!(c, '\n' | '\r' | '\t' | '\x0c'))
}

/// `*.txt` gives `txt`; anything with another wildcard in it gives nothing.
fn plain_extension(pattern: &str) -> Option<&str> {
    let rest = pattern.strip_prefix("*.")?;
    if rest.contains(['*', '?', '[', '/']) {
        return None;
    }
    Some(rest)
}

/// The subset of shell globbing the mime database actually uses: `*`, `?` and
/// `[...]` character classes.
pub fn glob_match(pattern: &str, name: &str) -> bool {
    let p: Vec<char> = pattern.chars().collect();
    let n: Vec<char> = name.chars().collect();
    matches_from(&p, 0, &n, 0)
}

fn matches_from(p: &[char], mut pi: usize, n: &[char], mut ni: usize) -> bool {
    while pi < p.len() {
        match p[pi] {
            '*' => {
                //: Collapse runs of stars, then try every split point. Patterns
                //: here are short, so the simple form is the right one.
                while pi < p.len() && p[pi] == '*' {
                    pi += 1;
                }
                if pi == p.len() {
                    return true;
                }
                for k in ni..=n.len() {
                    if matches_from(p, pi, n, k) {
                        return true;
                    }
                }
                return false;
            }
            '?' => {
                if ni >= n.len() {
                    return false;
                }
                pi += 1;
                ni += 1;
            }
            '[' => {
                if ni >= n.len() {
                    return false;
                }
                let close = match p[pi..].iter().position(|c| *c == ']') {
                    Some(k) => pi + k,
                    None => return false,
                };
                let mut set = &p[pi + 1..close];
                let negate = set.first() == Some(&'!');
                if negate {
                    set = &set[1..];
                }
                let c = n[ni];
                let mut hit = false;
                let mut i = 0;
                while i < set.len() {
                    if i + 2 < set.len() && set[i + 1] == '-' {
                        if c >= set[i] && c <= set[i + 2] {
                            hit = true;
                        }
                        i += 3;
                    } else {
                        if c == set[i] {
                            hit = true;
                        }
                        i += 1;
                    }
                }
                if hit == negate {
                    return false;
                }
                pi = close + 1;
                ni += 1;
            }
            other => {
                if ni >= n.len() || n[ni] != other {
                    return false;
                }
                pi += 1;
                ni += 1;
            }
        }
    }
    ni == n.len()
}

/// `$XDG_DATA_HOME` then `$XDG_DATA_DIRS`, most specific first, which is the
/// order the spec says a lookup must use.
pub fn data_dirs() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Some(home) = xdg_data_home() {
        out.push(home);
    }
    let dirs = std::env::var("XDG_DATA_DIRS")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "/usr/local/share:/usr/share".into());
    for d in dirs.split(':').filter(|s| !s.is_empty()) {
        out.push(PathBuf::from(d));
    }
    out
}

pub fn xdg_data_home() -> Option<PathBuf> {
    if let Ok(v) = std::env::var("XDG_DATA_HOME") {
        if !v.is_empty() {
            return Some(PathBuf::from(v));
        }
    }
    std::env::var("HOME").ok().map(|h| PathBuf::from(h).join(".local/share"))
}

pub fn xdg_config_home() -> Option<PathBuf> {
    if let Ok(v) = std::env::var("XDG_CONFIG_HOME") {
        if !v.is_empty() {
            return Some(PathBuf::from(v));
        }
    }
    std::env::var("HOME").ok().map(|h| PathBuf::from(h).join(".config"))
}

/// `$XDG_CONFIG_HOME` then `$XDG_CONFIG_DIRS`.
pub fn config_dirs() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Some(home) = xdg_config_home() {
        out.push(home);
    }
    let dirs = std::env::var("XDG_CONFIG_DIRS")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "/etc/xdg".into());
    for d in dirs.split(':').filter(|s| !s.is_empty()) {
        out.push(PathBuf::from(d));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_glob_matcher_handles_what_the_database_uses() {
        assert!(glob_match("*.txt", "notes.txt"));
        assert!(!glob_match("*.txt", "notes.txt.bak"));
        assert!(glob_match("*.tar.*", "a.tar.gz"));
        assert!(glob_match("makefile", "makefile"));
        assert!(glob_match("?akefile", "makefile"));
        assert!(glob_match("[Mm]akefile", "makefile"));
        assert!(glob_match("[Mm]akefile", "Makefile"));
        assert!(!glob_match("[!Mm]akefile", "makefile"));
        assert!(glob_match("*.[ch]", "main.c"));
        assert!(!glob_match("*.[ch]", "main.rs"));
        assert!(glob_match("*", "anything"));
        assert!(glob_match("**.log", "a.log"));
    }

    #[test]
    fn a_two_part_extension_beats_the_one_part_one() {
        let mut db = MimeDb::default();
        db.extensions.insert(
            "gz".into(),
            Glob { pattern: "*.gz".into(), mime: "application/gzip".into(), weight: 50, case_sensitive: false },
        );
        db.extensions.insert(
            "tar.gz".into(),
            Glob { pattern: "*.tar.gz".into(), mime: "application/x-compressed-tar".into(), weight: 50, case_sensitive: false },
        );
        assert_eq!(db.by_name("backup.tar.gz").as_deref(), Some("application/x-compressed-tar"));
        assert_eq!(db.by_name("backup.gz").as_deref(), Some("application/gzip"));
    }

    #[test]
    fn a_literal_name_wins_over_a_pattern() {
        let mut db = MimeDb::default();
        db.literals.insert("Makefile".into(), "text/x-makefile".into());
        db.extensions.insert(
            "txt".into(),
            Glob { pattern: "*.txt".into(), mime: PLAIN_TEXT.into(), weight: 50, case_sensitive: false },
        );
        assert_eq!(db.by_name("Makefile").as_deref(), Some("text/x-makefile"));
    }

    #[test]
    fn sniffing_separates_text_from_binary() {
        let dir = std::env::temp_dir().join("auradefs-mime-sniff");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = MimeDb::default();

        let png = dir.join("noext");
        std::fs::write(&png, b"\x89PNG\r\n\x1a\n rest").unwrap();
        assert_eq!(db.of_path(&png).unwrap(), "image/png");

        let script = dir.join("runme");
        std::fs::write(&script, b"#!/bin/sh\necho hi\n").unwrap();
        assert_eq!(db.of_path(&script).unwrap(), "application/x-shellscript");

        let text = dir.join("plain");
        std::fs::write(&text, "a line of text\nand another\n").unwrap();
        assert_eq!(db.of_path(&text).unwrap(), PLAIN_TEXT);

        let bin = dir.join("binary");
        std::fs::write(&bin, [0x00, 0x01, 0x02, 0xff, 0xfe]).unwrap();
        assert_eq!(db.of_path(&bin).unwrap(), OCTET_STREAM);

        //: A cut multibyte character at the buffer edge is not evidence of
        //: binary content.
        let cut = dir.join("utf8-cut");
        let mut bytes = "e".repeat(510).into_bytes();
        bytes.extend_from_slice(&[0xc3]);
        bytes.extend_from_slice("©tail".as_bytes());
        std::fs::write(&cut, &bytes).unwrap();
        assert_eq!(db.of_path(&cut).unwrap(), PLAIN_TEXT);
    }

    #[test]
    fn a_directory_and_a_link_are_their_own_types() {
        let dir = std::env::temp_dir().join("auradefs-mime-kinds");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("folder")).unwrap();
        std::fs::write(dir.join("target.txt"), b"x").unwrap();
        std::os::unix::fs::symlink(dir.join("target.txt"), dir.join("link")).unwrap();
        let db = MimeDb::default();
        assert_eq!(db.of_path(&dir.join("folder")).unwrap(), DIRECTORY);
        //: Not followed: the row is about the link, and the UI draws it
        //: differently.
        assert_eq!(db.of_path(&dir.join("link")).unwrap(), SYMLINK);
    }

    #[test]
    fn ancestry_walks_up_and_always_ends_somewhere() {
        let mut db = MimeDb::default();
        db.parents.insert("text/x-python".into(), vec![PLAIN_TEXT.into()]);
        db.parents.insert(PLAIN_TEXT.into(), vec![OCTET_STREAM.into()]);
        assert_eq!(
            db.ancestry("text/x-python"),
            vec!["text/x-python", PLAIN_TEXT, OCTET_STREAM]
        );
        assert_eq!(db.ancestry("image/png"), vec!["image/png", OCTET_STREAM]);
    }
}
