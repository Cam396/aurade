//! Searching a folder and everything under it.
//!
//! Three things make this different from a recursive walk with a filter:
//!
//! * **It is bounded.** A deadline, a result cap and a depth limit, all
//!   enforced, because a search that has to be waited out is a search nobody
//!   uses twice.
//! * **It does not leave the device it started on.** A folder can contain a
//!   mount point, and following one leads into a network share where a single
//!   `stat` can block for minutes with no way to interrupt it. Crossing is
//!   possible, but only when the caller asks for it.
//! * **It answers as it goes.** Results arrive through a callback so the list
//!   fills in rather than appearing all at once at the end.

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use rustix::fs::FileType;

use crate::error::Result;
use crate::root::Root;

/// What a query is looking for. Built by [`Query::parse`] from what the user
/// typed, or constructed directly.
#[derive(Debug, Clone, Default)]
pub struct Query {
    /// Substrings the name must contain, all of them.
    pub terms: Vec<String>,
    /// Substrings the name must not contain.
    pub excluded: Vec<String>,
    /// Text the file's contents must contain.
    pub content: Option<String>,
    pub extensions: Vec<String>,
    pub kinds: Vec<Kind>,
    pub tags: Vec<String>,
    pub min_size: Option<u64>,
    pub max_size: Option<u64>,
    pub modified_after: Option<i64>,
    pub modified_before: Option<i64>,
    /// Match case exactly. Off by default, which is what a search box does.
    pub case_sensitive: bool,
}

/// The coarse categories the search box offers, each a set of extensions
/// rather than a mime lookup, because a search must not open every file to
/// decide whether to consider it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Folder,
    File,
    Image,
    Video,
    Audio,
    Document,
    Archive,
    Code,
}

impl Kind {
    fn parse(name: &str) -> Option<Kind> {
        Some(match name {
            "folder" | "dir" | "directory" => Kind::Folder,
            "file" => Kind::File,
            "image" | "picture" | "photo" => Kind::Image,
            "video" | "movie" => Kind::Video,
            "audio" | "music" => Kind::Audio,
            "document" | "doc" => Kind::Document,
            "archive" | "zip" => Kind::Archive,
            "code" | "source" => Kind::Code,
            _ => return None,
        })
    }

    fn extensions(self) -> &'static [&'static str] {
        match self {
            Kind::Folder | Kind::File => &[],
            Kind::Image => &["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "avif", "heic", "tif", "tiff", "ico"],
            Kind::Video => &["mp4", "mkv", "webm", "mov", "avi", "m4v", "mpg", "mpeg", "wmv"],
            Kind::Audio => &["mp3", "flac", "ogg", "opus", "wav", "m4a", "aac", "wma"],
            Kind::Document => &["pdf", "txt", "md", "rtf", "doc", "docx", "odt", "xls", "xlsx", "ods", "ppt", "pptx", "odp", "epub"],
            Kind::Archive => &["zip", "7z", "tar", "gz", "xz", "zst", "bz2", "rar", "tgz", "txz"],
            Kind::Code => &["rs", "py", "js", "ts", "tsx", "jsx", "c", "h", "cc", "cpp", "hpp", "java", "go", "rb", "sh", "html", "css", "json", "toml", "yaml", "yml", "xml", "sql"],
        }
    }
}

impl Query {
    /// Read what the user typed. Bare words match the name; a prefixed word is
    /// a filter; a leading dash excludes; and a quoted run is one term even
    /// with spaces in it.
    pub fn parse(input: &str) -> Query {
        let mut query = Query::default();
        for token in tokenize(input) {
            let (negated, token) = match token.strip_prefix('-') {
                Some(rest) if !rest.is_empty() => (true, rest.to_string()),
                _ => (false, token),
            };
            let Some((key, value)) = token.split_once(':') else {
                if negated {
                    query.excluded.push(token);
                } else if !token.is_empty() {
                    query.terms.push(token);
                }
                continue;
            };
            if value.is_empty() {
                continue;
            }
            match key.to_ascii_lowercase().as_str() {
                "ext" | "extension" => {
                    query.extensions.push(value.trim_start_matches('.').to_ascii_lowercase())
                }
                "kind" | "type" => {
                    if let Some(k) = Kind::parse(&value.to_ascii_lowercase()) {
                        query.kinds.push(k);
                    }
                }
                "tag" => query.tags.push(value.to_string()),
                "content" | "text" | "in" => query.content = Some(value.to_string()),
                "size" => apply_size(&mut query, &value),
                "modified" | "date" | "since" => apply_date(&mut query, &value),
                //: An unrecognised prefix is not a filter, so the whole token
                //: is a name term. Searching for "note:2" should find
                //: "note:2.txt".
                _ => {
                    if negated {
                        query.excluded.push(token);
                    } else {
                        query.terms.push(token);
                    }
                }
            }
        }
        query
    }

    /// Is this query asking for nothing? An empty query would match every file
    /// under the folder, which is a walk rather than a search.
    pub fn is_empty(&self) -> bool {
        self.terms.is_empty()
            && self.excluded.is_empty()
            && self.content.is_none()
            && self.extensions.is_empty()
            && self.kinds.is_empty()
            && self.tags.is_empty()
            && self.min_size.is_none()
            && self.max_size.is_none()
            && self.modified_after.is_none()
            && self.modified_before.is_none()
    }

    /// Does it need to open files? Content search is much slower, so the caller
    /// can warn or ask first.
    pub fn reads_contents(&self) -> bool {
        self.content.is_some()
    }
}

/// Split on whitespace, keeping a quoted run together.
fn tokenize(input: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    let mut in_quotes = false;
    let mut quoted = false;
    for c in input.chars() {
        match c {
            '"' => {
                in_quotes = !in_quotes;
                quoted = true;
            }
            c if c.is_whitespace() && !in_quotes => {
                if !current.is_empty() || quoted {
                    out.push(std::mem::take(&mut current));
                    quoted = false;
                }
            }
            c => current.push(c),
        }
    }
    if !current.is_empty() || quoted {
        out.push(current);
    }
    out
}

/// `size:>1MB`, `size:<500K`, `size:1MB..4MB`.
fn apply_size(query: &mut Query, value: &str) {
    if let Some((low, high)) = value.split_once("..") {
        query.min_size = parse_size(low);
        query.max_size = parse_size(high);
        return;
    }
    if let Some(rest) = value.strip_prefix('>') {
        query.min_size = parse_size(rest.trim_start_matches('='));
        return;
    }
    if let Some(rest) = value.strip_prefix('<') {
        query.max_size = parse_size(rest.trim_start_matches('='));
        return;
    }
    //: A bare size means about that size, which is the only reading that is
    //: ever useful: an exact byte count is never what someone types.
    if let Some(n) = parse_size(value) {
        query.min_size = Some(n.saturating_mul(9) / 10);
        query.max_size = Some(n.saturating_mul(11) / 10);
    }
}

/// `1MB`, `1 mb`, `500k`, `1024`. Decimal units, because that is what a file
/// manager displays and so what a person will type back.
pub fn parse_size(value: &str) -> Option<u64> {
    let value = value.trim().to_ascii_lowercase();
    let digits: String = value.chars().take_while(|c| c.is_ascii_digit() || *c == '.').collect();
    if digits.is_empty() {
        return None;
    }
    let number: f64 = digits.parse().ok()?;
    let unit = value[digits.len()..].trim().trim_end_matches('b');
    let scale: f64 = match unit {
        "" => 1.0,
        "k" => 1_000.0,
        "m" => 1_000_000.0,
        "g" => 1_000_000_000.0,
        "t" => 1_000_000_000_000.0,
        "ki" => 1024.0,
        "mi" => 1024.0 * 1024.0,
        "gi" => 1024.0 * 1024.0 * 1024.0,
        "ti" => 1024.0 * 1024.0 * 1024.0 * 1024.0,
        _ => return None,
    };
    Some((number * scale) as u64)
}

fn apply_date(query: &mut Query, value: &str) {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0);
    let day = 86_400;
    let named = |v: &str| -> Option<i64> {
        Some(match v {
            "today" => now - day,
            "yesterday" => now - 2 * day,
            "thisweek" | "week" => now - 7 * day,
            "thismonth" | "month" => now - 30 * day,
            "thisyear" | "year" => now - 365 * day,
            _ => return None,
        })
    };
    let lower = value.to_ascii_lowercase();
    if let Some(after) = named(&lower) {
        query.modified_after = Some(after);
        return;
    }
    if let Some(rest) = lower.strip_prefix('>') {
        query.modified_after = named(rest).or_else(|| parse_date(rest));
        return;
    }
    if let Some(rest) = lower.strip_prefix('<') {
        query.modified_before = named(rest).or_else(|| parse_date(rest));
        return;
    }
    if let Some(at) = parse_date(&lower) {
        query.modified_after = Some(at);
        query.modified_before = Some(at + day);
    }
}

/// `2026-09-08`, as seconds since the epoch at midnight UTC.
pub fn parse_date(value: &str) -> Option<i64> {
    let mut parts = value.split('-');
    let y: i64 = parts.next()?.parse().ok()?;
    let m: i64 = parts.next()?.parse().ok()?;
    let d: i64 = parts.next()?.parse().ok()?;
    if !(1..=12).contains(&m) || !(1..=31).contains(&d) {
        return None;
    }
    //: Days from the civil date, by Howard Hinnant's algorithm: shift the year
    //: so it starts in March and leap days land at the end.
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    Some((era * 146_097 + doe - 719_468) * 86_400)
}

/// One result.
#[derive(Debug, Clone)]
pub struct Hit {
    pub path: PathBuf,
    pub name: String,
    pub is_dir: bool,
    pub size: u64,
    pub modified: i64,
    /// The first matching line, when the query searched contents.
    pub line: Option<(u32, String)>,
}

/// Where to stop.
#[derive(Debug, Clone)]
pub struct Limits {
    pub max_results: usize,
    pub max_depth: usize,
    pub deadline: Duration,
    /// Files larger than this are not opened for a content search.
    pub max_content_bytes: u64,
    pub include_hidden: bool,
    /// Follow a mount point out of the starting filesystem. Off, because a
    /// network mount below the search root can hang the walk.
    pub cross_devices: bool,
}

impl Default for Limits {
    fn default() -> Self {
        Limits {
            max_results: 5_000,
            max_depth: 32,
            deadline: Duration::from_secs(20),
            max_content_bytes: 8 << 20,
            include_hidden: false,
            cross_devices: false,
        }
    }
}

/// Why a search stopped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stopped {
    Finished,
    HitResultLimit,
    RanOutOfTime,
    Cancelled,
}

/// What a search did.
#[derive(Debug, Clone)]
pub struct Report {
    pub hits: usize,
    pub examined: u64,
    pub stopped: Stopped,
}

struct Walk<'a> {
    query: &'a Query,
    limits: &'a Limits,
    started: Instant,
    device: u64,
    hits: usize,
    examined: u64,
    stopped: Stopped,
}

/// Run a search, calling `found` for each hit as it is found. Returning false
/// from the callback stops the search.
pub fn search(
    dir: &Path,
    query: &Query,
    limits: &Limits,
    found: &mut dyn FnMut(Hit) -> bool,
) -> Result<Report> {
    let root = Root::open(dir)?;
    let device = root.stat()?.st_dev as u64;
    let mut walk = Walk {
        query,
        limits,
        started: Instant::now(),
        device,
        hits: 0,
        examined: 0,
        stopped: Stopped::Finished,
    };
    if !query.is_empty() {
        descend(&mut walk, &root, dir, 0, found);
    }
    Ok(Report { hits: walk.hits, examined: walk.examined, stopped: walk.stopped })
}

fn descend(
    walk: &mut Walk<'_>,
    root: &Root,
    here: &Path,
    depth: usize,
    found: &mut dyn FnMut(Hit) -> bool,
) {
    if walk.stopped != Stopped::Finished || depth > walk.limits.max_depth {
        return;
    }
    let Ok(names) = root.read_dir() else { return };
    let mut subdirs: Vec<PathBuf> = Vec::new();

    for name in names {
        if walk.stopped != Stopped::Finished {
            return;
        }
        //: The clock is checked per entry rather than per directory, because a
        //: single directory can hold a hundred thousand of them.
        if walk.started.elapsed() > walk.limits.deadline {
            walk.stopped = Stopped::RanOutOfTime;
            return;
        }
        let display = name.to_string_lossy().to_string();
        if !walk.limits.include_hidden && display.starts_with('.') {
            continue;
        }
        let Ok(stat) = root.metadata(&name) else { continue };
        let kind = FileType::from_raw_mode(stat.st_mode as _);
        //: Symlinks are never followed. A link back up the tree would make the
        //: walk endless, and a link out of it would take the search somewhere
        //: the user did not ask about.
        if kind == FileType::Symlink {
            continue;
        }
        let is_dir = kind == FileType::Directory;
        if skip_for_device(is_dir, walk.limits.cross_devices, stat.st_dev as u64, walk.device) {
            continue;
        }
        walk.examined += 1;
        let full = here.join(&name);

        if let Some(hit) = consider(walk, &full, &display, is_dir, &stat) {
            walk.hits += 1;
            if !found(hit) {
                walk.stopped = Stopped::Cancelled;
                return;
            }
            if walk.hits >= walk.limits.max_results {
                walk.stopped = Stopped::HitResultLimit;
                return;
            }
        }
        if is_dir {
            subdirs.push(name);
        }
    }

    //: Breadth before depth within a directory: every match here is reported
    //: before descending, so the nearest results appear first.
    for name in subdirs {
        if walk.stopped != Stopped::Finished {
            return;
        }
        let Ok(sub) = root.sub(&name) else { continue };
        descend(walk, &sub, &here.join(&name), depth + 1, found);
    }
}

/// Should this entry be skipped because it is on another filesystem?
///
/// Its own function so it can be checked without arranging a real mount point,
/// which a test cannot do without privileges. The rule: a directory on a
/// different device is a mount point, and following one leads somewhere the
/// caller did not ask about and may not answer at all.
fn skip_for_device(is_dir: bool, cross_devices: bool, entry_device: u64, start_device: u64) -> bool {
    is_dir && !cross_devices && entry_device != start_device
}

fn consider(
    walk: &mut Walk<'_>,
    full: &Path,
    name: &str,
    is_dir: bool,
    stat: &rustix::fs::Stat,
) -> Option<Hit> {
    let query = walk.query;
    let haystack = if query.case_sensitive { name.to_string() } else { name.to_lowercase() };
    let fold = |t: &String| if query.case_sensitive { t.clone() } else { t.to_lowercase() };

    if !query.terms.iter().all(|t| haystack.contains(&fold(t))) {
        return None;
    }
    if query.excluded.iter().any(|t| haystack.contains(&fold(t))) {
        return None;
    }
    if !query.kinds.is_empty() && !kind_matches(query, name, is_dir) {
        return None;
    }
    if !query.extensions.is_empty() {
        let ext = name.rsplit_once('.').map(|(_, e)| e.to_ascii_lowercase()).unwrap_or_default();
        if !query.extensions.iter().any(|e| *e == ext) {
            return None;
        }
    }
    let size = stat.st_size.max(0) as u64;
    if query.min_size.is_some() || query.max_size.is_some() {
        //: A directory's own size is the size of its entry, which is not what
        //: anyone means by it, so a size filter is a filter on files.
        if is_dir {
            return None;
        }
        if query.min_size.map(|m| size < m).unwrap_or(false) {
            return None;
        }
        if query.max_size.map(|m| size > m).unwrap_or(false) {
            return None;
        }
    }
    let modified = stat.st_mtime as i64;
    if query.modified_after.map(|t| modified < t).unwrap_or(false) {
        return None;
    }
    if query.modified_before.map(|t| modified > t).unwrap_or(false) {
        return None;
    }
    if !query.tags.is_empty() {
        let tags = crate::xattr::tags(full).unwrap_or_default();
        if !query
            .tags
            .iter()
            .all(|want| tags.iter().any(|t| t.eq_ignore_ascii_case(want)))
        {
            return None;
        }
    }

    let mut line = None;
    if let Some(needle) = &query.content {
        if is_dir || size > walk.limits.max_content_bytes {
            return None;
        }
        line = Some(find_in_file(full, needle, query.case_sensitive)?);
    }

    Some(Hit {
        path: full.to_path_buf(),
        name: name.to_string(),
        is_dir,
        size,
        modified,
        line,
    })
}

fn kind_matches(query: &Query, name: &str, is_dir: bool) -> bool {
    let ext = name.rsplit_once('.').map(|(_, e)| e.to_ascii_lowercase()).unwrap_or_default();
    query.kinds.iter().any(|k| match k {
        Kind::Folder => is_dir,
        Kind::File => !is_dir,
        other => !is_dir && other.extensions().contains(&ext.as_str()),
    })
}

/// The first line containing `needle`, or nothing. A file with a null byte in
/// its first block is binary and is not searched, which is the call `grep`
/// makes and for the same reason: the matches would be noise.
fn find_in_file(path: &Path, needle: &str, case_sensitive: bool) -> Option<(u32, String)> {
    use std::io::{BufRead, BufReader, Read};
    let mut file = std::fs::File::open(path).ok()?;
    let mut head = [0u8; 1024];
    let n = file.read(&mut head).ok()?;
    if head[..n].contains(&0) {
        return None;
    }
    file = std::fs::File::open(path).ok()?;
    let needle = if case_sensitive { needle.to_string() } else { needle.to_lowercase() };
    for (index, line) in BufReader::new(file).lines().enumerate() {
        let Ok(line) = line else { return None };
        let hay = if case_sensitive { line.clone() } else { line.to_lowercase() };
        if hay.contains(&needle) {
            //: A very long line would be a wall of text in the results, so it
            //: is cut at something a row can show.
            let shown = if line.chars().count() > 300 {
                line.chars().take(300).collect::<String>() + "…"
            } else {
                line
            };
            return Some((index as u32 + 1, shown));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn tree(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("auradefs-search-{tag}"));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("notes/deep")).unwrap();
        fs::create_dir_all(dir.join("pictures")).unwrap();
        fs::write(dir.join("readme.md"), b"the word needle is here\nand more\n").unwrap();
        fs::write(dir.join("notes/todo.txt"), b"nothing to see\n").unwrap();
        fs::write(dir.join("notes/deep/buried.txt"), b"needle again\n").unwrap();
        fs::write(dir.join("pictures/holiday.jpg"), vec![b'x'; 2048]).unwrap();
        fs::write(dir.join("pictures/.secret.jpg"), b"hidden").unwrap();
        fs::write(dir.join("archive.tar.gz"), vec![b'z'; 4096]).unwrap();
        dir
    }

    fn run(dir: &Path, q: &str, limits: Limits) -> (Vec<String>, Report) {
        let mut names = Vec::new();
        let report = search(dir, &Query::parse(q), &limits, &mut |hit| {
            names.push(hit.name);
            true
        })
        .unwrap();
        names.sort();
        (names, report)
    }

    #[test]
    fn a_bare_word_matches_the_name_anywhere_in_the_tree() {
        let dir = tree("name");
        let (names, report) = run(&dir, "buried", Limits::default());
        assert_eq!(names, ["buried.txt"]);
        assert_eq!(report.stopped, Stopped::Finished);
    }

    #[test]
    fn matching_ignores_case_unless_told_not_to() {
        let dir = tree("case");
        let (names, _) = run(&dir, "README", Limits::default());
        assert_eq!(names, ["readme.md"]);

        let mut query = Query::parse("README");
        query.case_sensitive = true;
        let mut hits = Vec::new();
        search(&dir, &query, &Limits::default(), &mut |h| {
            hits.push(h.name);
            true
        })
        .unwrap();
        assert!(hits.is_empty(), "a case sensitive search matched anyway");
    }

    #[test]
    fn every_term_has_to_match_and_a_dash_excludes() {
        let dir = tree("terms");
        assert_eq!(run(&dir, "holiday jpg", Limits::default()).0, ["holiday.jpg"]);
        assert!(run(&dir, "holiday png", Limits::default()).0.is_empty());
        let (names, _) = run(&dir, "txt -todo", Limits::default());
        assert_eq!(names, ["buried.txt"]);
    }

    #[test]
    fn the_filters_read_the_way_the_search_box_writes_them() {
        let q = Query::parse("report ext:PDF kind:document size:>1MB modified:today tag:Work -draft");
        assert_eq!(q.terms, ["report"]);
        assert_eq!(q.excluded, ["draft"]);
        assert_eq!(q.extensions, ["pdf"]);
        assert_eq!(q.kinds, [Kind::Document]);
        assert_eq!(q.tags, ["Work"]);
        assert_eq!(q.min_size, Some(1_000_000));
        assert!(q.modified_after.is_some());
        assert!(!q.is_empty());
    }

    #[test]
    fn an_unknown_prefix_stays_part_of_the_name_being_searched_for() {
        let q = Query::parse("note:2 colour:red");
        assert_eq!(q.terms, ["note:2", "colour:red"]);
        assert!(q.extensions.is_empty());
    }

    #[test]
    fn a_quoted_run_is_one_term() {
        let q = Query::parse(r#""my holiday photos" ext:jpg"#);
        assert_eq!(q.terms, ["my holiday photos"]);
        assert_eq!(q.extensions, ["jpg"]);
    }

    #[test]
    fn sizes_read_in_the_units_a_person_types() {
        assert_eq!(parse_size("1024"), Some(1024));
        assert_eq!(parse_size("1k"), Some(1_000));
        assert_eq!(parse_size("1KB"), Some(1_000));
        assert_eq!(parse_size("1KiB"), Some(1024));
        assert_eq!(parse_size("1.5MB"), Some(1_500_000));
        assert_eq!(parse_size("2 GB"), Some(2_000_000_000));
        assert_eq!(parse_size("huge"), None);

        let range = Query::parse("size:1KB..3KB");
        assert_eq!((range.min_size, range.max_size), (Some(1_000), Some(3_000)));
        //: A bare size is read as "about this big", within a tenth either way.
        let about = Query::parse("size:1000");
        assert_eq!((about.min_size, about.max_size), (Some(900), Some(1100)));
    }

    #[test]
    fn a_size_filter_selects_the_right_files() {
        let dir = tree("size");
        //: Folders are not part of a size filter's answer, however big their
        //: own directory entry happens to be.
        let (names, _) = run(&dir, "size:>3KB", Limits::default());
        assert_eq!(names, ["archive.tar.gz"]);
        let (names, _) = run(&dir, "size:<100 ext:txt", Limits::default());
        assert_eq!(names, ["buried.txt", "todo.txt"]);
    }

    #[test]
    fn a_date_parses_to_midnight_utc() {
        assert_eq!(parse_date("1970-01-01"), Some(0));
        assert_eq!(parse_date("2000-03-01"), Some(951_868_800));
        assert_eq!(parse_date("2026-09-08"), Some(1_788_825_600));
        assert_eq!(parse_date("not-a-date"), None);
        assert_eq!(parse_date("2026-13-01"), None);
    }

    #[test]
    fn kind_selects_folders_or_a_family_of_extensions() {
        let dir = tree("kind");
        let (names, _) = run(&dir, "kind:folder", Limits::default());
        assert_eq!(names, ["deep", "notes", "pictures"]);
        let (names, _) = run(&dir, "kind:image", Limits::default());
        assert_eq!(names, ["holiday.jpg"], "a hidden image should stay hidden");
    }

    #[test]
    fn hidden_files_are_left_out_unless_they_are_asked_for() {
        let dir = tree("hidden");
        let (names, _) = run(&dir, "secret", Limits::default());
        assert!(names.is_empty());
        let limits = Limits { include_hidden: true, ..Default::default() };
        assert_eq!(run(&dir, "secret", limits).0, [".secret.jpg"]);
    }

    #[test]
    fn a_content_search_finds_the_line_and_skips_what_it_should() {
        let dir = tree("content");
        fs::write(dir.join("binary.dat"), [0x00, b'n', b'e', b'e', b'd', b'l', b'e']).unwrap();
        let mut hits: Vec<(String, Option<(u32, String)>)> = Vec::new();
        search(
            &dir,
            &Query::parse("content:needle"),
            &Limits::default(),
            &mut |h| {
                hits.push((h.name, h.line));
                true
            },
        )
        .unwrap();
        hits.sort();
        assert_eq!(hits.len(), 2, "got {hits:?}");
        assert_eq!(hits[0].0, "buried.txt");
        assert_eq!(hits[0].1, Some((1, "needle again".to_string())));
        assert_eq!(hits[1].1, Some((1, "the word needle is here".to_string())));
        assert!(
            !hits.iter().any(|(n, _)| n == "binary.dat"),
            "a binary file was searched"
        );
    }

    #[test]
    fn a_file_larger_than_the_content_limit_is_not_opened() {
        let dir = tree("content-limit");
        fs::write(dir.join("large.log"), b"needle\n").unwrap();
        let limits = Limits { max_content_bytes: 3, ..Default::default() };
        let mut count = 0;
        search(&dir, &Query::parse("content:needle"), &limits, &mut |_| {
            count += 1;
            true
        })
        .unwrap();
        assert_eq!(count, 0, "the size cap was not honoured");
    }

    #[test]
    fn the_result_cap_stops_the_walk_and_says_which_limit_was_hit() {
        let dir = tree("cap");
        let limits = Limits { max_results: 2, ..Default::default() };
        let (names, report) = run(&dir, "kind:file", limits);
        assert_eq!(names.len(), 2);
        assert_eq!(report.stopped, Stopped::HitResultLimit);
    }

    #[test]
    fn a_callback_that_says_stop_stops_it() {
        let dir = tree("cancel");
        let mut seen = 0;
        let report = search(&dir, &Query::parse("kind:file"), &Limits::default(), &mut |_| {
            seen += 1;
            false
        })
        .unwrap();
        assert_eq!(seen, 1);
        assert_eq!(report.stopped, Stopped::Cancelled);
        assert_eq!(report.hits, 1);
    }

    #[test]
    fn depth_is_bounded() {
        let dir = tree("depth");
        let limits = Limits { max_depth: 0, ..Default::default() };
        let (names, _) = run(&dir, "kind:file", limits);
        //: Only the top level, so nothing under notes/ or pictures/.
        assert_eq!(names, ["archive.tar.gz", "readme.md"]);
    }

    #[test]
    fn an_empty_query_searches_nothing_rather_than_everything() {
        let dir = tree("empty");
        let (names, report) = run(&dir, "   ", Limits::default());
        assert!(names.is_empty());
        assert_eq!(report.examined, 0);
        assert!(Query::parse("").is_empty());
    }

    #[test]
    fn a_mount_point_below_the_search_root_is_not_entered() {
        //: Same device, so nothing is skipped whatever the setting.
        assert!(!skip_for_device(true, false, 42, 42));
        assert!(!skip_for_device(true, true, 42, 42));
        //: A directory on another device is a mount point, and the default is
        //: to stop there. A network share below the search root is the case
        //: this exists for: a single stat inside one can block for minutes.
        assert!(skip_for_device(true, false, 99, 42));
        //: Unless the caller asked to cross.
        assert!(!skip_for_device(true, true, 99, 42));
        //: A file is never a mount point, so its device is not a reason to
        //: skip it.
        assert!(!skip_for_device(false, false, 99, 42));
    }

    #[test]
    fn a_symlink_is_not_followed_so_a_loop_cannot_hang_it() {
        let dir = tree("loop");
        std::os::unix::fs::symlink(&dir, dir.join("notes/back")).unwrap();
        let (names, report) = run(&dir, "kind:file", Limits::default());
        assert_eq!(report.stopped, Stopped::Finished, "the walk did not finish");
        assert!(!names.iter().any(|n| n == "back"));
    }
}
