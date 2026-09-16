//! Reading a folder into rows.
//!
//! This is the hot path. Opening a folder of forty thousand files has to be one
//! pass: read the names, stat each one, and answer. Anything that costs a
//! process per row, or a second walk, shows up immediately as a folder that
//! takes a second to open.
//!
//! So the expensive extras are opt in. Tags cost one `getxattr` per row, git
//! costs one status pass for the whole folder, and neither is done unless the
//! caller says it is drawing that column.

use std::path::{Path, PathBuf};

use rustix::fs::FileType;

use crate::error::Result;
use crate::mime::MimeDb;
use crate::root::Root;

/// What a row is, at the level the UI draws differently.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Folder,
    File,
    /// A symlink, with whether it resolves. A broken link is drawn differently
    /// and is not something to try to open.
    Link { broken: bool, to_folder: bool },
    /// A socket, fifo or device node.
    Other,
}

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Folder => "folder",
            Kind::File => "file",
            Kind::Link { .. } => "link",
            Kind::Other => "other",
        }
    }

    /// Whether the row behaves like a folder when opened, which a link to one
    /// does.
    pub fn opens_as_folder(self) -> bool {
        matches!(self, Kind::Folder | Kind::Link { to_folder: true, broken: false })
    }
}

/// One row.
#[derive(Debug, Clone)]
pub struct Row {
    pub name: String,
    pub kind: Kind,
    /// The file's own size. A folder reports the size of its directory entry,
    /// not of its contents, because counting the contents is a separate and
    /// much slower question.
    pub size: u64,
    pub modified: i64,
    pub accessed: i64,
    /// Creation time, when the filesystem records one. Btrfs and ext4 do; some
    /// do not, and the column is then empty rather than showing a lie.
    pub created: Option<i64>,
    pub mode: u32,
    pub uid: u32,
    pub gid: u32,
    pub hidden: bool,
    pub mime: String,
    pub link_target: Option<PathBuf>,
    pub tags: Vec<String>,
    pub custom_icon: Option<String>,
    pub git: Option<crate::git::Entry>,
}

impl Row {
    pub fn extension(&self) -> Option<&str> {
        let dot = self.name.rfind('.').filter(|i| *i > 0)?;
        Some(&self.name[dot + 1..])
    }
}

/// How to order rows.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Sort {
    Name,
    Size,
    Modified,
    Created,
    Kind,
}

/// What the caller wants read.
#[derive(Debug, Clone)]
pub struct Options {
    pub show_hidden: bool,
    pub include_tags: bool,
    pub include_git: bool,
    pub include_ignored_git: bool,
    /// Stop after this many rows. A folder with a million files still has to
    /// answer, so it answers with a prefix and says it did.
    pub limit: usize,
    pub sort: Sort,
    pub descending: bool,
    pub folders_first: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            show_hidden: false,
            include_tags: false,
            include_git: false,
            include_ignored_git: false,
            limit: 250_000,
            sort: Sort::Name,
            descending: false,
            folders_first: true,
        }
    }
}

/// A folder, read.
#[derive(Debug, Clone)]
pub struct Listing {
    pub path: PathBuf,
    pub rows: Vec<Row>,
    /// How many rows the folder has in total, including hidden ones that were
    /// filtered out, so the status bar can say "12 items, 3 hidden".
    pub total: usize,
    pub hidden_count: usize,
    pub truncated: bool,
    pub git: Option<crate::git::Info>,
}

/// Read a folder.
pub fn list(dir: &Path, options: &Options, mime: &MimeDb) -> Result<Listing> {
    let root = Root::open(dir)?;
    let names = root.read_dir()?;

    //: Nautilus and Thunar both honour a `.hidden` file listing extra names to
    //: keep out of the way. Reading it costs one small file per folder and
    //: makes this agree with the rest of the desktop.
    let extra_hidden = read_dot_hidden(&root);

    let git = if options.include_git {
        crate::git::info(dir, options.include_ignored_git).unwrap_or(None)
    } else {
        None
    };

    let mut rows = Vec::with_capacity(names.len());
    let mut hidden_count = 0;
    let total = names.len();
    let mut truncated = false;

    for name in names {
        let display = name.to_string_lossy().to_string();
        let hidden = display.starts_with('.') || extra_hidden.iter().any(|h| *h == display);
        if hidden {
            hidden_count += 1;
            if !options.show_hidden {
                continue;
            }
        }
        if rows.len() >= options.limit {
            truncated = true;
            break;
        }
        let Ok(stat) = root.metadata(&name) else { continue };
        let raw_type = FileType::from_raw_mode(stat.st_mode as _);

        let (kind, link_target) = match raw_type {
            FileType::Directory => (Kind::Folder, None),
            FileType::RegularFile => (Kind::File, None),
            FileType::Symlink => {
                let target = read_link(&root, &name);
                //: One stat that does follow, only for links, only to decide
                //: how to draw the row.
                let followed = std::fs::metadata(dir.join(&name)).ok();
                (
                    Kind::Link {
                        broken: followed.is_none(),
                        to_folder: followed.map(|m| m.is_dir()).unwrap_or(false),
                    },
                    target,
                )
            }
            _ => (Kind::Other, None),
        };

        let full = dir.join(&name);
        let mime_type = match kind {
            Kind::Folder => crate::mime::DIRECTORY.to_string(),
            Kind::Link { .. } => crate::mime::SYMLINK.to_string(),
            Kind::Other => crate::mime::OCTET_STREAM.to_string(),
            //: By name only. Sniffing every row would mean opening every file
            //: in the folder, and the name is right for all but the
            //: extensionless few.
            Kind::File => mime
                .by_name(&display)
                .unwrap_or_else(|| crate::mime::OCTET_STREAM.to_string()),
        };

        let tags = if options.include_tags {
            crate::xattr::tags(&full).unwrap_or_default()
        } else {
            Vec::new()
        };
        //: Not only a folder's. A shortcut can carry one too, and the
        //: properties dialog offers the tab for both.
        let custom_icon = if options.include_tags {
            crate::xattr::icon(&full).unwrap_or(None)
        } else {
            None
        };

        rows.push(Row {
            name: display,
            kind,
            size: stat.st_size.max(0) as u64,
            modified: stat.st_mtime as i64,
            accessed: stat.st_atime as i64,
            created: created_time(&full),
            mode: stat.st_mode as u32 & 0o7777,
            uid: stat.st_uid as u32,
            gid: stat.st_gid as u32,
            hidden,
            mime: mime_type,
            link_target,
            tags,
            custom_icon,
            git: git.as_ref().map(|g| g.of(&full)),
        });
    }

    sort_rows(&mut rows, options);
    Ok(Listing { path: dir.to_path_buf(), rows, total, hidden_count, truncated, git })
}

/// One recently modified file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Recent {
    pub path: PathBuf,
    pub name: String,
    pub modified: i64,
    pub size: u64,
}

/// The most recently modified files under a folder, newest first.
///
/// This is the Recent view when it is asked about a place rather than about
/// the desktop's own list of opened files. It is a walk, so it is bounded the
/// same way a search is: an entry ceiling, no hidden files unless asked, and
/// symlinks are not followed, because a link back up the tree would make it
/// endless.
pub fn recently_modified(
    dir: &Path,
    limit: usize,
    include_hidden: bool,
    max_entries: usize,
) -> Result<Vec<Recent>> {
    let root = Root::open(dir)?;
    let mut found = Vec::new();
    let mut seen = 0;
    collect_recent(&root, dir, include_hidden, max_entries, &mut seen, &mut found)?;
    //: Newest first, and a tie broken by name so two files written in the same
    //: second do not swap places between two reads.
    found.sort_by(|a, b| b.modified.cmp(&a.modified).then_with(|| a.name.cmp(&b.name)));
    found.truncate(limit);
    Ok(found)
}

fn collect_recent(
    root: &Root,
    here: &Path,
    include_hidden: bool,
    max_entries: usize,
    seen: &mut usize,
    out: &mut Vec<Recent>,
) -> Result<()> {
    let Ok(names) = root.read_dir() else { return Ok(()) };
    let mut subdirs = Vec::new();
    for name in names {
        if *seen >= max_entries {
            return Ok(());
        }
        let display = name.to_string_lossy().to_string();
        if !include_hidden && display.starts_with('.') {
            continue;
        }
        let Ok(stat) = root.metadata(&name) else { continue };
        match FileType::from_raw_mode(stat.st_mode as _) {
            FileType::Directory => subdirs.push(name),
            FileType::RegularFile => {
                *seen += 1;
                out.push(Recent {
                    path: here.join(&name),
                    name: display,
                    modified: stat.st_mtime as i64,
                    size: stat.st_size.max(0) as u64,
                });
            }
            //: A symlink is not followed and is not a recent file in its own
            //: right: what changed is whatever it points at.
            _ => {}
        }
    }
    for name in subdirs {
        if *seen >= max_entries {
            return Ok(());
        }
        let Ok(sub) = root.sub(&name) else { continue };
        collect_recent(&sub, &here.join(&name), include_hidden, max_entries, seen, out)?;
    }
    Ok(())
}

fn read_link(root: &Root, name: &Path) -> Option<PathBuf> {
    let (parent, leaf) = root.parent_of(name).ok()?;
    let target = rustix::fs::readlinkat(&parent, leaf.as_os_str(), Vec::new()).ok()?;
    use std::os::unix::ffi::OsStrExt;
    Some(PathBuf::from(std::ffi::OsStr::from_bytes(target.as_bytes())))
}

fn read_dot_hidden(root: &Root) -> Vec<String> {
    let Ok(mut file) = root.open_file(".hidden") else { return Vec::new() };
    let mut text = String::new();
    use std::io::Read;
    if file.read_to_string(&mut text).is_err() {
        return Vec::new();
    }
    text.lines().map(str::trim).filter(|l| !l.is_empty()).map(str::to_string).collect()
}

/// Birth time, where the filesystem keeps one.
fn created_time(path: &Path) -> Option<i64> {
    let stat = rustix::fs::statx(
        rustix::fs::CWD,
        path,
        rustix::fs::AtFlags::SYMLINK_NOFOLLOW,
        rustix::fs::StatxFlags::BTIME,
    )
    .ok()?;
    if stat.stx_mask & rustix::fs::StatxFlags::BTIME.bits() == 0 {
        return None;
    }
    Some(stat.stx_btime.tv_sec)
}

fn sort_rows(rows: &mut [Row], options: &Options) {
    rows.sort_by(|a, b| {
        if options.folders_first {
            let by_kind = b.kind.opens_as_folder().cmp(&a.kind.opens_as_folder());
            if by_kind != std::cmp::Ordering::Equal {
                return by_kind;
            }
        }
        let ord = match options.sort {
            Sort::Name => natural_cmp(&a.name, &b.name),
            Sort::Size => a.size.cmp(&b.size),
            Sort::Modified => a.modified.cmp(&b.modified),
            Sort::Created => a.created.cmp(&b.created),
            Sort::Kind => a
                .extension()
                .unwrap_or("")
                .to_lowercase()
                .cmp(&b.extension().unwrap_or("").to_lowercase()),
        };
        //: Any tie falls back to the name, so a folder of files with the same
        //: size does not shuffle between two reads of the same directory.
        let ord = if ord == std::cmp::Ordering::Equal && options.sort != Sort::Name {
            natural_cmp(&a.name, &b.name)
        } else {
            ord
        };
        if options.descending { ord.reverse() } else { ord }
    });
}

/// Compare names the way a person reads them, so `file10` comes after `file9`
/// and `File` sorts next to `file` rather than before every lowercase name.
pub fn natural_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    use std::cmp::Ordering;
    let mut x = a.chars().peekable();
    let mut y = b.chars().peekable();
    loop {
        match (x.peek().copied(), y.peek().copied()) {
            (None, None) => {
                //: Identical apart from case. Lowercase last, so the order is
                //: still total and stable.
                return a.cmp(b);
            }
            (None, Some(_)) => return Ordering::Less,
            (Some(_), None) => return Ordering::Greater,
            (Some(ca), Some(cb)) => {
                if ca.is_ascii_digit() && cb.is_ascii_digit() {
                    let na = take_number(&mut x);
                    let nb = take_number(&mut y);
                    //: Compare by value, not by text, and only fall back to
                    //: the text when the values match, which is how `01` and
                    //: `1` keep a stable order.
                    match na.0.cmp(&nb.0) {
                        Ordering::Equal => match na.1.cmp(&nb.1) {
                            Ordering::Equal => continue,
                            other => return other,
                        },
                        other => return other,
                    }
                }
                let la = ca.to_lowercase().next().unwrap_or(ca);
                let lb = cb.to_lowercase().next().unwrap_or(cb);
                match la.cmp(&lb) {
                    Ordering::Equal => {
                        x.next();
                        y.next();
                    }
                    other => return other,
                }
            }
        }
    }
}

/// Consume a run of digits, returning its value and its written length. The
/// value is capped rather than overflowing: a hundred digit number in a file
/// name is not a number anyone is counting with.
fn take_number(it: &mut std::iter::Peekable<std::str::Chars<'_>>) -> (u128, usize) {
    let mut value: u128 = 0;
    let mut len = 0;
    while let Some(c) = it.peek().copied() {
        if !c.is_ascii_digit() {
            break;
        }
        it.next();
        len += 1;
        value = value.saturating_mul(10).saturating_add((c as u8 - b'0') as u128);
    }
    (value, len)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn scratch(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("auradefs-list-{tag}"));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("folder")).unwrap();
        fs::write(dir.join("b.txt"), b"bb").unwrap();
        fs::write(dir.join("a.md"), b"a").unwrap();
        fs::write(dir.join(".dotfile"), b"hidden").unwrap();
        dir
    }

    #[test]
    fn natural_order_reads_numbers_as_numbers() {
        use std::cmp::Ordering;
        assert_eq!(natural_cmp("file2", "file10"), Ordering::Less);
        assert_eq!(natural_cmp("file10", "file9"), Ordering::Greater);
        assert_eq!(natural_cmp("a", "B"), Ordering::Less, "case split the alphabet");
        assert_eq!(natural_cmp("img001", "img1"), Ordering::Greater, "same value, longer text last");
        assert_eq!(natural_cmp("same", "same"), Ordering::Equal);
        assert_eq!(natural_cmp("a", "ab"), Ordering::Less);
        //: A number longer than any integer type still orders sensibly.
        assert_eq!(natural_cmp(&format!("x{}", "9".repeat(60)), "x1"), Ordering::Greater);
    }

    #[test]
    fn a_listing_sorts_folders_first_and_then_naturally() {
        let dir = scratch("order");
        fs::write(dir.join("file10.txt"), b"x").unwrap();
        fs::write(dir.join("file9.txt"), b"x").unwrap();
        let db = MimeDb::default();
        let got = list(&dir, &Options::default(), &db).unwrap();
        let names: Vec<&str> = got.rows.iter().map(|r| r.name.as_str()).collect();
        assert_eq!(names, ["folder", "a.md", "b.txt", "file9.txt", "file10.txt"]);
    }

    #[test]
    fn hidden_rows_are_counted_even_when_they_are_not_shown() {
        let dir = scratch("hidden");
        let db = MimeDb::default();
        let got = list(&dir, &Options::default(), &db).unwrap();
        assert!(!got.rows.iter().any(|r| r.name == ".dotfile"));
        assert_eq!(got.hidden_count, 1);
        assert_eq!(got.total, 4);

        let shown = list(&dir, &Options { show_hidden: true, ..Default::default() }, &db).unwrap();
        let row = shown.rows.iter().find(|r| r.name == ".dotfile").unwrap();
        assert!(row.hidden);
    }

    #[test]
    fn a_dot_hidden_file_hides_what_it_names() {
        let dir = scratch("dot-hidden");
        fs::write(dir.join(".hidden"), "b.txt\n\nfolder\n").unwrap();
        let db = MimeDb::default();
        let got = list(&dir, &Options::default(), &db).unwrap();
        let names: Vec<&str> = got.rows.iter().map(|r| r.name.as_str()).collect();
        assert_eq!(names, ["a.md"], "a name in .hidden was still shown");
        //: And they are still counted, so the status bar adds up: .dotfile and
        //: .hidden itself, plus the two names .hidden lists.
        assert_eq!(got.hidden_count, 4);
    }

    #[test]
    fn a_link_says_whether_it_leads_anywhere() {
        let dir = scratch("links");
        std::os::unix::fs::symlink(dir.join("b.txt"), dir.join("to-file")).unwrap();
        std::os::unix::fs::symlink(dir.join("folder"), dir.join("to-folder")).unwrap();
        std::os::unix::fs::symlink(dir.join("nothing"), dir.join("to-nowhere")).unwrap();
        let db = MimeDb::default();
        let got = list(&dir, &Options::default(), &db).unwrap();
        let by = |n: &str| got.rows.iter().find(|r| r.name == n).unwrap().clone();

        assert_eq!(by("to-file").kind, Kind::Link { broken: false, to_folder: false });
        assert_eq!(by("to-folder").kind, Kind::Link { broken: false, to_folder: true });
        assert_eq!(by("to-nowhere").kind, Kind::Link { broken: true, to_folder: false });
        assert_eq!(by("to-file").link_target.unwrap(), dir.join("b.txt"));
        //: A link to a folder sorts with the folders, because that is what
        //: opening it does.
        let names: Vec<&str> = got.rows.iter().map(|r| r.name.as_str()).collect();
        assert_eq!(&names[..2], ["folder", "to-folder"]);
    }

    #[test]
    fn sorting_by_size_still_has_a_stable_order_for_ties() {
        let dir = scratch("size");
        fs::write(dir.join("z.txt"), b"xx").unwrap();
        let db = MimeDb::default();
        let opts = Options { sort: Sort::Size, folders_first: false, ..Default::default() };
        let names: Vec<String> = list(&dir, &opts, &db)
            .unwrap()
            .rows
            .into_iter()
            .map(|r| r.name)
            .collect();
        //: a.md is one byte; b.txt and z.txt are two and tie, so the name
        //: decides. The folder's own size is whatever the filesystem says, so
        //: it is not asserted.
        let files: Vec<&String> = names.iter().filter(|n| *n != "folder").collect();
        assert_eq!(files, ["a.md", "b.txt", "z.txt"]);
    }

    #[test]
    fn descending_reverses_the_rows_but_not_folders_first() {
        let dir = scratch("descending");
        let db = MimeDb::default();
        let opts = Options { descending: true, ..Default::default() };
        let names: Vec<String> =
            list(&dir, &opts, &db).unwrap().rows.into_iter().map(|r| r.name).collect();
        assert_eq!(names, ["folder", "b.txt", "a.md"]);
    }

    #[test]
    fn a_limit_answers_with_a_prefix_and_says_so() {
        let dir = scratch("limit");
        let db = MimeDb::default();
        let opts = Options { limit: 2, ..Default::default() };
        let got = list(&dir, &opts, &db).unwrap();
        assert_eq!(got.rows.len(), 2);
        assert!(got.truncated);
        assert_eq!(got.total, 4, "the total is what the folder holds, not what was returned");
    }

    #[test]
    fn the_expensive_columns_are_only_read_when_asked_for() {
        let dir = scratch("opt-in");
        let db = MimeDb::default();
        let _ = crate::xattr::set_tags(&dir.join("b.txt"), &["Work".into()]);
        let plain = list(&dir, &Options::default(), &db).unwrap();
        assert!(plain.rows.iter().all(|r| r.tags.is_empty()));
        assert!(plain.rows.iter().all(|r| r.git.is_none()));

        let full = list(&dir, &Options { include_tags: true, ..Default::default() }, &db).unwrap();
        let row = full.rows.iter().find(|r| r.name == "b.txt").unwrap();
        //: Only assert the tag when the filesystem could store it.
        if crate::xattr::tags(&dir.join("b.txt")).unwrap_or_default().is_empty() {
            eprintln!("skipped the tag half: no extended attributes here");
        } else {
            assert_eq!(row.tags, ["Work"]);
        }
    }

    #[test]
    fn the_recent_walk_is_newest_first_and_bounded() {
        let dir = scratch("recent");
        //: Deliberately out of order on disk, and one of them buried.
        let when = |secs| std::time::SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(secs);
        for (name, at) in [("a.md", 1_000_000_100u64), ("b.txt", 1_000_000_300)] {
            let f = std::fs::File::options().write(true).open(dir.join(name)).unwrap();
            f.set_times(std::fs::FileTimes::new().set_modified(when(at))).unwrap();
        }
        fs::write(dir.join("folder/buried.txt"), b"x").unwrap();
        let f = std::fs::File::options().write(true).open(dir.join("folder/buried.txt")).unwrap();
        f.set_times(std::fs::FileTimes::new().set_modified(when(1_000_000_200))).unwrap();

        let got = recently_modified(&dir, 10, false, 1000).unwrap();
        let names: Vec<&str> = got.iter().map(|r| r.name.as_str()).collect();
        assert_eq!(names, ["b.txt", "buried.txt", "a.md"], "not newest first");
        assert_eq!(got[1].path, dir.join("folder/buried.txt"));
        //: A hidden file stays hidden.
        assert!(!names.contains(&".dotfile"));
        assert_eq!(recently_modified(&dir, 10, true, 1000).unwrap().len(), 4);

        //: And both ceilings hold.
        assert_eq!(recently_modified(&dir, 2, false, 1000).unwrap().len(), 2);
        assert!(recently_modified(&dir, 10, false, 1).unwrap().len() <= 1);
    }

    #[test]
    fn the_recent_walk_does_not_follow_a_link_back_into_itself() {
        let dir = scratch("recent-loop");
        std::os::unix::fs::symlink(&dir, dir.join("folder/back")).unwrap();
        let got = recently_modified(&dir, 100, false, 10_000).unwrap();
        //: It finished, which is the assertion: a followed link would recurse
        //: until the entry ceiling stopped it.
        assert_eq!(got.len(), 2, "{:?}", got.iter().map(|r| &r.name).collect::<Vec<_>>());
    }

    #[test]
    fn a_row_knows_its_own_extension() {
        let dir = scratch("ext");
        let db = MimeDb::default();
        let got = list(&dir, &Options::default(), &db).unwrap();
        let row = got.rows.iter().find(|r| r.name == "a.md").unwrap();
        assert_eq!(row.extension(), Some("md"));
        assert_eq!(got.rows.iter().find(|r| r.name == "folder").unwrap().extension(), None);
    }
}
