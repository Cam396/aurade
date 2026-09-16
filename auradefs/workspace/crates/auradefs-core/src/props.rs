//! What the properties window shows: ownership, permissions, access control
//! lists, how much room a folder really takes, and the file's hashes.
//!
//! Files' Security tab and its Advanced dialog map onto POSIX permissions and
//! POSIX access control lists. The mode bits are the same three by three grid
//! Windows draws differently, and an ACL is the extra entries beyond it, which
//! is exactly what the Advanced dialog exists for.

use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::error::{Error, Result};

/// Owner, group and mode.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ownership {
    pub uid: u32,
    pub gid: u32,
    pub user: Option<String>,
    pub group: Option<String>,
    pub mode: u32,
}

impl Ownership {
    /// `rwxr-xr-x`, with the setuid, setgid and sticky bits shown where they
    /// change what a letter means, the way `ls` writes them.
    pub fn symbolic(&self) -> String {
        let m = self.mode;
        let mut out = String::with_capacity(9);
        for (shift, special, upper, lower) in
            [(6u32, 0o4000u32, 'S', 's'), (3, 0o2000, 'S', 's'), (0, 0o1000, 'T', 't')]
        {
            let bits = (m >> shift) & 0o7;
            out.push(if bits & 0o4 != 0 { 'r' } else { '-' });
            out.push(if bits & 0o2 != 0 { 'w' } else { '-' });
            out.push(match (bits & 0o1 != 0, m & special != 0) {
                (true, true) => lower,
                (false, true) => upper,
                (true, false) => 'x',
                (false, false) => '-',
            });
        }
        out
    }
}

pub fn ownership(path: &Path) -> Result<Ownership> {
    let stat = rustix::fs::statat(
        rustix::fs::CWD,
        path,
        rustix::fs::AtFlags::SYMLINK_NOFOLLOW,
    )
    .map_err(|e| {
        Error::io(path.display().to_string(), std::io::Error::from_raw_os_error(e.raw_os_error()))
    })?;
    let uid = stat.st_uid as u32;
    let gid = stat.st_gid as u32;
    Ok(Ownership {
        uid,
        gid,
        user: user_name(uid),
        group: group_name(gid),
        mode: stat.st_mode as u32 & 0o7777,
    })
}

/// Change the mode. Only the permission and special bits; the file type is not
/// something a properties dialog gets to edit.
pub fn set_mode(path: &Path, mode: u32) -> Result<()> {
    rustix::fs::chmodat(
        rustix::fs::CWD,
        path,
        rustix::fs::Mode::from_bits_truncate(mode & 0o7777),
        //: Not on the link itself: the kernel has no lchmod, and the mode of a
        //: symlink means nothing anyway.
        rustix::fs::AtFlags::empty(),
    )
    .map_err(|e| {
        Error::io(path.display().to_string(), std::io::Error::from_raw_os_error(e.raw_os_error()))
    })
}

/// Look a uid up. `/etc/passwd` answers for a local account without a process;
/// `getent` answers for everything else, including an account that comes from
/// a directory service.
fn user_name(uid: u32) -> Option<String> {
    lookup("/etc/passwd", uid).or_else(|| getent("passwd", uid))
}

fn group_name(gid: u32) -> Option<String> {
    lookup("/etc/group", gid).or_else(|| getent("group", gid))
}

fn lookup(file: &str, id: u32) -> Option<String> {
    let text = std::fs::read_to_string(file).ok()?;
    for line in text.lines() {
        let mut fields = line.split(':');
        let name = fields.next()?;
        let _password = fields.next();
        let found: u32 = fields.next()?.parse().ok()?;
        if found == id {
            return Some(name.to_string());
        }
    }
    None
}

fn getent(database: &str, id: u32) -> Option<String> {
    let out = Command::new("getent").arg(database).arg(id.to_string()).output().ok()?;
    if !out.status.success() {
        return None;
    }
    String::from_utf8_lossy(&out.stdout).split(':').next().map(str::to_string)
}

// -------------------------------------------------------------------- ACL ---

/// One access control entry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AclEntry {
    /// `user`, `group`, `mask` or `other`.
    pub kind: String,
    /// The named user or group, empty for the owning one and for mask/other.
    pub who: String,
    pub read: bool,
    pub write: bool,
    pub execute: bool,
    /// A default entry, which a new file in this directory inherits. This is
    /// the closest thing POSIX has to Windows' inheritance flags.
    pub default: bool,
}

impl AclEntry {
    pub fn perms(&self) -> String {
        format!(
            "{}{}{}",
            if self.read { "r" } else { "-" },
            if self.write { "w" } else { "-" },
            if self.execute { "x" } else { "-" }
        )
    }

    fn to_spec(&self) -> String {
        let body = format!("{}:{}:{}", self.kind, self.who, self.perms());
        if self.default { format!("default:{body}") } else { body }
    }
}

/// Read the access control list. An empty list means the file has only the
/// ordinary mode bits, which is the common case and not an error.
pub fn acl(path: &Path) -> Result<Vec<AclEntry>> {
    let out = Command::new("getfacl")
        .args(["--absolute-names", "--omit-header", "--"])
        .arg(path)
        .output()
        .map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => {
                Error::NotFound("the acl tools are not installed".into())
            }
            _ => Error::io("running getfacl", e),
        })?;
    if !out.status.success() {
        let message = String::from_utf8_lossy(&out.stderr);
        let line = message.lines().next().unwrap_or("failed").trim();
        if line.contains("Operation not supported") {
            return Err(Error::Unsupported(format!(
                "{} is on a filesystem without access control lists",
                path.display()
            )));
        }
        return Err(Error::Tool { tool: "getfacl".into(), message: line.to_string() });
    }
    Ok(parse_acl(&String::from_utf8_lossy(&out.stdout)))
}

fn parse_acl(text: &str) -> Vec<AclEntry> {
    let mut out = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        //: getfacl appends an effective permission comment to entries the mask
        //: cuts down, and that comment is not part of the entry.
        let line = line.split('#').next().unwrap_or(line).trim();
        let (default, body) = match line.strip_prefix("default:") {
            Some(rest) => (true, rest),
            None => (false, line),
        };
        let fields: Vec<&str> = body.split(':').collect();
        if fields.len() < 3 {
            continue;
        }
        let perms = fields[2];
        out.push(AclEntry {
            kind: fields[0].to_string(),
            who: fields[1].to_string(),
            read: perms.contains('r'),
            write: perms.contains('w'),
            execute: perms.contains('x'),
            default,
        });
    }
    out
}

/// Replace the whole list. Passing an empty list removes every extra entry and
/// leaves the file with just its mode bits.
pub fn set_acl(path: &Path, entries: &[AclEntry]) -> Result<()> {
    if entries.is_empty() {
        return run_setfacl(&["--remove-all", "--remove-default", "--"], path);
    }
    let spec = entries.iter().map(AclEntry::to_spec).collect::<Vec<_>>().join(",");
    //: --set replaces rather than merges, so an entry removed in the dialog is
    //: actually gone rather than left behind.
    run_setfacl(&["--set", &spec, "--"], path)
}

fn run_setfacl(args: &[&str], path: &Path) -> Result<()> {
    let out = Command::new("setfacl")
        .args(args)
        .arg(path)
        .output()
        .map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => Error::NotFound("the acl tools are not installed".into()),
            _ => Error::io("running setfacl", e),
        })?;
    if out.status.success() {
        return Ok(());
    }
    let message = String::from_utf8_lossy(&out.stderr);
    let line = message.lines().next().unwrap_or("failed").trim().to_string();
    if line.contains("Operation not supported") {
        return Err(Error::Unsupported(format!(
            "{} is on a filesystem without access control lists",
            path.display()
        )));
    }
    if line.contains("Permission denied") {
        return Err(Error::Denied(path.display().to_string()));
    }
    Err(Error::Tool { tool: "setfacl".into(), message: line })
}

// ------------------------------------------------------------ folder size ---

/// What a folder actually takes up.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Size {
    pub files: u64,
    pub folders: u64,
    /// The sum of the file sizes.
    pub bytes: u64,
    /// The sum of the blocks allocated, which is the honest "size on disk" and
    /// is smaller than `bytes` for a sparse or compressed file and larger for a
    /// small one.
    pub on_disk: u64,
    /// True when the walk stopped early. The numbers are then a floor, and the
    /// dialog should say so rather than showing them as final.
    pub partial: bool,
}

/// Add up a tree, with a ceiling on how long it may take.
///
/// A properties window opened on the home directory must not become an
/// unbounded walk, so the caller gives a limit and gets back whatever was
/// counted along with the fact that it stopped.
pub fn size_of(path: &Path, max_entries: u64) -> Result<Size> {
    let mut total = Size::default();
    let mut seen: std::collections::HashSet<(u64, u64)> = std::collections::HashSet::new();
    walk_size(path, max_entries, &mut total, &mut seen)?;
    Ok(total)
}

fn walk_size(
    path: &Path,
    max_entries: u64,
    total: &mut Size,
    seen: &mut std::collections::HashSet<(u64, u64)>,
) -> Result<()> {
    if total.partial {
        return Ok(());
    }
    let stat = match rustix::fs::statat(rustix::fs::CWD, path, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(s) => s,
        //: A file that vanished while we were counting is not a failure; the
        //: number is simply about what was there.
        Err(_) => return Ok(()),
    };
    let kind = rustix::fs::FileType::from_raw_mode(stat.st_mode as _);
    if kind == rustix::fs::FileType::Symlink {
        return Ok(());
    }
    if kind == rustix::fs::FileType::Directory {
        total.folders += 1;
        if total.files + total.folders >= max_entries {
            total.partial = true;
            return Ok(());
        }
        let Ok(read) = std::fs::read_dir(path) else { return Ok(()) };
        for entry in read.flatten() {
            walk_size(&entry.path(), max_entries, total, seen)?;
            if total.partial {
                return Ok(());
            }
        }
        return Ok(());
    }
    //: A hard link counted twice would make a folder look bigger than the disk
    //: it is on, which is exactly the case `du` gets right and a naive sum does
    //: not.
    if stat.st_nlink > 1 && !seen.insert((stat.st_dev as u64, stat.st_ino as u64)) {
        return Ok(());
    }
    total.files += 1;
    total.bytes += stat.st_size.max(0) as u64;
    total.on_disk += stat.st_blocks as u64 * 512;
    if total.files + total.folders >= max_entries {
        total.partial = true;
    }
    Ok(())
}

// ----------------------------------------------------------------- hashes ---

/// The digests Files' Hashes tab offers.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Algorithm {
    Crc32,
    Md5,
    Sha1,
    Sha256,
    Sha384,
    Sha512,
}

impl Algorithm {
    pub fn name(self) -> &'static str {
        match self {
            Algorithm::Crc32 => "crc32",
            Algorithm::Md5 => "md5",
            Algorithm::Sha1 => "sha1",
            Algorithm::Sha256 => "sha256",
            Algorithm::Sha384 => "sha384",
            Algorithm::Sha512 => "sha512",
        }
    }

    pub fn parse(name: &str) -> Option<Algorithm> {
        Some(match name.to_ascii_lowercase().as_str() {
            "crc32" => Algorithm::Crc32,
            "md5" => Algorithm::Md5,
            "sha1" => Algorithm::Sha1,
            "sha256" => Algorithm::Sha256,
            "sha384" => Algorithm::Sha384,
            "sha512" => Algorithm::Sha512,
            _ => return None,
        })
    }
}

/// Hash a file once for every algorithm asked for, reading it a single time.
///
/// MD5 and SHA1 are here because Files offers them and because they are what a
/// download page usually publishes. They are not offered as evidence that a
/// file has not been tampered with, and nothing in this service treats them
/// that way.
pub fn hashes(path: &Path, want: &[Algorithm]) -> Result<Vec<(Algorithm, String)>> {
    use md5::Digest as _;

    let mut file = std::fs::File::open(path)
        .map_err(|e| Error::io(path.display().to_string(), e))?;
    let mut crc = crc32fast::Hasher::new();
    let mut md5 = md5::Md5::new();
    let mut sha1 = sha1::Sha1::new();
    let mut sha256 = sha2::Sha256::new();
    let mut sha384 = sha2::Sha384::new();
    let mut sha512 = sha2::Sha512::new();

    let mut buf = vec![0u8; 1 << 20];
    loop {
        let n = file.read(&mut buf).map_err(|e| Error::io(path.display().to_string(), e))?;
        if n == 0 {
            break;
        }
        let chunk = &buf[..n];
        for algorithm in want {
            match algorithm {
                Algorithm::Crc32 => crc.update(chunk),
                Algorithm::Md5 => md5.update(chunk),
                Algorithm::Sha1 => sha1.update(chunk),
                Algorithm::Sha256 => sha256.update(chunk),
                Algorithm::Sha384 => sha384.update(chunk),
                Algorithm::Sha512 => sha512.update(chunk),
            }
        }
    }

    let mut out = Vec::with_capacity(want.len());
    for algorithm in want {
        let digest = match algorithm {
            Algorithm::Crc32 => format!("{:08x}", crc.clone().finalize()),
            Algorithm::Md5 => hex(&md5.clone().finalize()),
            Algorithm::Sha1 => hex(&sha1.clone().finalize()),
            Algorithm::Sha256 => hex(&sha256.clone().finalize()),
            Algorithm::Sha384 => hex(&sha384.clone().finalize()),
            Algorithm::Sha512 => hex(&sha512.clone().finalize()),
        };
        out.push((*algorithm, digest));
    }
    Ok(out)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Where a symlink points, and whether that still exists. This is what the
/// Shortcut tab shows.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LinkTarget {
    pub target: PathBuf,
    /// The target with the link's own directory prepended when it is relative,
    /// which is the path that actually gets opened.
    pub resolved: PathBuf,
    pub exists: bool,
}

pub fn link_target(path: &Path) -> Result<Option<LinkTarget>> {
    let meta = std::fs::symlink_metadata(path)
        .map_err(|e| Error::io(path.display().to_string(), e))?;
    if !meta.file_type().is_symlink() {
        return Ok(None);
    }
    let target = std::fs::read_link(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    let resolved = if target.is_absolute() {
        target.clone()
    } else {
        path.parent().unwrap_or(Path::new("/")).join(&target)
    };
    Ok(Some(LinkTarget { exists: resolved.exists(), target, resolved }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn scratch(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("auradefs-props-{tag}"));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn the_mode_reads_the_way_ls_writes_it() {
        let o = |mode| Ownership { uid: 0, gid: 0, user: None, group: None, mode };
        assert_eq!(o(0o755).symbolic(), "rwxr-xr-x");
        assert_eq!(o(0o644).symbolic(), "rw-r--r--");
        assert_eq!(o(0o000).symbolic(), "---------");
        //: setuid with execute is a lowercase s; without it, an uppercase S,
        //: because the bit is set but cannot do anything.
        assert_eq!(o(0o4755).symbolic(), "rwsr-xr-x");
        assert_eq!(o(0o4655).symbolic(), "rwSr-xr-x");
        assert_eq!(o(0o2755).symbolic(), "rwxr-sr-x");
        assert_eq!(o(0o1777).symbolic(), "rwxrwxrwt");
    }

    #[test]
    fn ownership_reads_and_the_mode_can_be_changed() {
        let dir = scratch("mode");
        let file = dir.join("f.txt");
        fs::write(&file, b"x").unwrap();
        let before = ownership(&file).unwrap();
        assert_eq!(before.uid, rustix::process::getuid().as_raw());
        //: The name is looked up, and on any normal system the running user
        //: has one.
        assert!(before.user.is_some(), "no name for the running user");

        set_mode(&file, 0o600).unwrap();
        assert_eq!(ownership(&file).unwrap().mode, 0o600);
        assert_eq!(ownership(&file).unwrap().symbolic(), "rw-------");
    }

    #[test]
    fn an_acl_listing_drops_the_effective_comment_and_reads_defaults() {
        let text = concat!(
            "user::rwx\n",
            "user:cam:rw-\t\t\t#effective:r--\n",
            "group::r-x\n",
            "mask::r--\n",
            "other::---\n",
            "default:user::rwx\n",
            "default:group::r-x\n",
        );
        let got = parse_acl(text);
        assert_eq!(got.len(), 7);
        let named = got.iter().find(|e| e.who == "cam").unwrap();
        assert_eq!(named.kind, "user");
        assert_eq!(named.perms(), "rw-", "the effective comment was read as the entry");
        assert!(!named.default);
        assert_eq!(got.iter().filter(|e| e.default).count(), 2);
        assert_eq!(got[5].to_spec(), "default:user::rwx");
    }

    #[test]
    fn an_entry_turns_back_into_the_spelling_setfacl_takes() {
        let e = AclEntry {
            kind: "user".into(),
            who: "cam".into(),
            read: true,
            write: true,
            execute: false,
            default: false,
        };
        assert_eq!(e.to_spec(), "user:cam:rw-");
        assert_eq!(AclEntry { default: true, ..e }.to_spec(), "default:user:cam:rw-");
    }

    #[test]
    fn a_folder_size_counts_files_and_folders_and_stops_when_told() {
        let dir = scratch("size");
        fs::create_dir_all(dir.join("a/b")).unwrap();
        fs::write(dir.join("a/one.txt"), vec![b'x'; 1000]).unwrap();
        fs::write(dir.join("a/b/two.txt"), vec![b'y'; 2000]).unwrap();

        let got = size_of(&dir, 1_000_000).unwrap();
        assert_eq!(got.files, 2);
        assert_eq!(got.folders, 3, "the folder itself, a, and a/b");
        assert_eq!(got.bytes, 3000);
        assert!(got.on_disk >= 3000, "blocks should cover the bytes");
        assert!(!got.partial);

        let capped = size_of(&dir, 2).unwrap();
        assert!(capped.partial, "the cap was not reported");
        assert!(capped.files + capped.folders <= 3);
    }

    #[test]
    fn a_hard_link_is_only_counted_once() {
        let dir = scratch("hardlink");
        fs::write(dir.join("original"), vec![b'x'; 4096]).unwrap();
        fs::hard_link(dir.join("original"), dir.join("same-file")).unwrap();
        let got = size_of(&dir, 1_000_000).unwrap();
        assert_eq!(got.files, 1, "the same inode was counted twice");
        assert_eq!(got.bytes, 4096);
    }

    #[test]
    fn a_symlink_adds_nothing_and_is_not_followed() {
        let dir = scratch("size-link");
        fs::create_dir_all(dir.join("real")).unwrap();
        fs::write(dir.join("real/file"), vec![b'x'; 100]).unwrap();
        std::os::unix::fs::symlink(dir.join("real"), dir.join("loop-back")).unwrap();
        let got = size_of(&dir, 1_000_000).unwrap();
        assert_eq!(got.files, 1);
        assert_eq!(got.bytes, 100);
        assert!(!got.partial, "a link followed back into the tree would never end");
    }

    #[test]
    fn the_digests_are_the_published_ones() {
        let dir = scratch("hash");
        let file = dir.join("abc");
        fs::write(&file, b"abc").unwrap();
        let got = hashes(
            &file,
            &[
                Algorithm::Crc32,
                Algorithm::Md5,
                Algorithm::Sha1,
                Algorithm::Sha256,
                Algorithm::Sha512,
            ],
        )
        .unwrap();
        let by = |a: Algorithm| got.iter().find(|(x, _)| *x == a).unwrap().1.clone();
        assert_eq!(by(Algorithm::Crc32), "352441c2");
        assert_eq!(by(Algorithm::Md5), "900150983cd24fb0d6963f7d28e17f72");
        assert_eq!(by(Algorithm::Sha1), "a9993e364706816aba3e25717850c26c9cd0d89d");
        assert_eq!(
            by(Algorithm::Sha256),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(by(Algorithm::Sha512).len(), 128);
    }

    #[test]
    fn hashing_reads_the_file_once_however_many_digests_are_asked_for() {
        let dir = scratch("hash-multi");
        let file = dir.join("big");
        //: Bigger than the read buffer, so the streaming path runs more than
        //: one round and a mistake in it would change the answer.
        fs::write(&file, vec![b'z'; (1 << 20) + 7]).unwrap();
        let one = hashes(&file, &[Algorithm::Sha256]).unwrap()[0].1.clone();
        let many = hashes(&file, &[Algorithm::Md5, Algorithm::Sha256]).unwrap();
        assert_eq!(many.iter().find(|(a, _)| *a == Algorithm::Sha256).unwrap().1, one);
        assert_eq!(many.len(), 2);
    }

    #[test]
    fn an_empty_file_still_has_the_known_empty_digest() {
        let dir = scratch("hash-empty");
        let file = dir.join("nothing");
        fs::write(&file, b"").unwrap();
        let got = hashes(&file, &[Algorithm::Sha256]).unwrap();
        assert_eq!(
            got[0].1,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn an_algorithm_name_round_trips() {
        for a in [
            Algorithm::Crc32,
            Algorithm::Md5,
            Algorithm::Sha1,
            Algorithm::Sha256,
            Algorithm::Sha384,
            Algorithm::Sha512,
        ] {
            assert_eq!(Algorithm::parse(a.name()), Some(a));
        }
        assert_eq!(Algorithm::parse("SHA256"), Some(Algorithm::Sha256));
        assert_eq!(Algorithm::parse("md4"), None);
    }

    #[test]
    fn the_shortcut_tab_shows_where_a_link_goes_and_whether_it_is_there() {
        let dir = scratch("link");
        fs::write(dir.join("real.txt"), b"x").unwrap();
        std::os::unix::fs::symlink("real.txt", dir.join("relative")).unwrap();
        std::os::unix::fs::symlink(dir.join("gone.txt"), dir.join("broken")).unwrap();

        let good = link_target(&dir.join("relative")).unwrap().unwrap();
        assert_eq!(good.target, Path::new("real.txt"));
        assert_eq!(good.resolved, dir.join("real.txt"), "a relative link was not resolved");
        assert!(good.exists);

        let bad = link_target(&dir.join("broken")).unwrap().unwrap();
        assert!(!bad.exists);

        assert_eq!(link_target(&dir.join("real.txt")).unwrap(), None);
    }
}

// -------------------------------------------------------------- attributes ---

/// The two checkboxes on the General tab.
///
/// Windows keeps these as bits on the file. Linux has neither bit, so each one
/// is the nearest true thing: read only is the write permission, and hidden is
/// the two ways a desktop actually hides a file.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Attributes {
    pub read_only: bool,
    pub hidden: bool,
    /// True when the name itself is what hides it. A file called `.bashrc` is
    /// hidden everywhere, by every program, and the only way to show it is to
    /// rename it, which is not what a checkbox should do on its own.
    pub hidden_by_name: bool,
}

pub fn attributes(path: &Path) -> Result<Attributes> {
    use std::os::unix::fs::MetadataExt;
    let meta = std::fs::symlink_metadata(path)
        .map_err(|e| Error::io(path.display().to_string(), e))?;
    let name = path.file_name().unwrap_or_default().to_string_lossy().into_owned();
    let hidden_by_name = name.starts_with('.');
    Ok(Attributes {
        //: The owner's write bit. Not whether this user could write it, which
        //: is a different question with a different answer for root and on a
        //: read only mount, and not something a checkbox can change.
        read_only: meta.mode() & 0o200 == 0,
        hidden: hidden_by_name || dot_hidden(path).contains(&name),
        hidden_by_name,
    })
}

/// Turn the read only box on or off.
pub fn set_read_only(path: &Path, read_only: bool) -> Result<u32> {
    use std::os::unix::fs::MetadataExt;
    let meta = std::fs::metadata(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    let mode = meta.mode() & 0o7777;
    let wanted = if read_only {
        //: Every write bit, not just the owner's: a file the group can still
        //: write is not read only, whatever the box says.
        mode & !0o222
    } else {
        //: Only the owner's comes back. Group and world write are a decision
        //: somebody made once, and this has no way to know whether they are
        //: what was there before.
        mode | 0o200
    };
    set_mode(path, wanted)?;
    Ok(wanted)
}

/// Turn the hidden box on or off, through the folder's `.hidden` file.
///
/// Never by renaming. Putting a dot in front of a name is how Unix hides
/// things, but it changes the path, and every bookmark, link and open document
/// pointing at the old one stops working. `.hidden` is what a file manager
/// uses for exactly this reason, and it is already what the lister reads.
pub fn set_hidden(path: &Path, hidden: bool) -> Result<Attributes> {
    let name = path.file_name().unwrap_or_default().to_string_lossy().into_owned();
    if name.is_empty() {
        return Err(Error::BadRequest("no name to hide".into()));
    }
    if name.starts_with('.') {
        return Err(Error::Unsupported(format!(
            "{name} is hidden by its name, so showing it means renaming it"
        )));
    }
    let dir = path.parent().ok_or_else(|| Error::BadRequest("no folder to write in".into()))?;
    let listed = dot_hidden(path);
    let mut kept: Vec<String> = listed.iter().filter(|n| **n != name).cloned().collect();
    if hidden {
        kept.push(name.clone());
    }
    let file = dir.join(".hidden");
    if kept.is_empty() {
        //: An empty .hidden is a file that says nothing. Removed rather than
        //: left behind, so a folder that has nothing hidden looks like one.
        match std::fs::remove_file(&file) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(Error::io(file.display().to_string(), e)),
        }
    } else {
        let mut text = kept.join("\n");
        text.push('\n');
        std::fs::write(&file, text).map_err(|e| Error::io(file.display().to_string(), e))?;
    }
    attributes(path)
}

/// The names a folder's `.hidden` lists.
fn dot_hidden(path: &Path) -> Vec<String> {
    let Some(dir) = path.parent() else { return Vec::new() };
    let Ok(text) = std::fs::read_to_string(dir.join(".hidden")) else { return Vec::new() };
    text.lines().map(str::trim).filter(|l| !l.is_empty()).map(str::to_string).collect()
}

#[cfg(test)]
mod attribute_tests {
    use super::*;

    fn scratch(tag: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!("auradefs-attrs-{tag}"));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        base
    }

    #[test]
    fn read_only_is_the_write_permission_and_comes_back_off() {
        use std::os::unix::fs::PermissionsExt;
        let base = scratch("readonly");
        let file = base.join("note.txt");
        std::fs::write(&file, b"x").unwrap();
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o664)).unwrap();
        assert!(!attributes(&file).unwrap().read_only);

        let mode = set_read_only(&file, true).unwrap();
        //: Every write bit, not only the owner's: a file the group can still
        //: write is not read only.
        assert_eq!(mode & 0o222, 0, "left as {mode:o}");
        assert!(attributes(&file).unwrap().read_only);
        assert!(std::fs::OpenOptions::new().write(true).open(&file).is_err() || is_root());

        let mode = set_read_only(&file, false).unwrap();
        assert_eq!(mode & 0o200, 0o200);
        //: Group write is not restored, because nothing here knows whether it
        //: was ever meant to be there.
        assert_eq!(mode & 0o022, 0, "gave away write it was not asked to");
        assert!(!attributes(&file).unwrap().read_only);
    }

    fn is_root() -> bool {
        rustix::process::getuid().is_root()
    }

    #[test]
    fn hidden_goes_through_the_folders_own_list_and_never_renames() {
        let base = scratch("hidden");
        let file = base.join("note.txt");
        let other = base.join("second.txt");
        std::fs::write(&file, b"x").unwrap();
        std::fs::write(&other, b"y").unwrap();
        assert!(!attributes(&file).unwrap().hidden);

        let attrs = set_hidden(&file, true).unwrap();
        assert!(attrs.hidden && !attrs.hidden_by_name);
        assert!(file.exists(), "hiding it renamed it");
        assert_eq!(std::fs::read_to_string(base.join(".hidden")).unwrap(), "note.txt\n");

        //: A second file joins the list rather than replacing it.
        set_hidden(&other, true).unwrap();
        let listed = std::fs::read_to_string(base.join(".hidden")).unwrap();
        assert!(listed.contains("note.txt") && listed.contains("second.txt"), "got {listed:?}");
        assert!(attributes(&file).unwrap().hidden);

        set_hidden(&file, false).unwrap();
        assert!(!attributes(&file).unwrap().hidden);
        assert!(attributes(&other).unwrap().hidden, "showing one showed the other");
        assert_eq!(std::fs::read_to_string(base.join(".hidden")).unwrap(), "second.txt\n");

        //: And the last one out takes the file with it.
        set_hidden(&other, false).unwrap();
        assert!(!base.join(".hidden").exists(), "an empty list was left behind");

        //: Hiding twice is not two lines.
        set_hidden(&file, true).unwrap();
        set_hidden(&file, true).unwrap();
        assert_eq!(std::fs::read_to_string(base.join(".hidden")).unwrap(), "note.txt\n");
    }

    #[test]
    fn a_file_hidden_by_its_name_says_so_rather_than_being_renamed() {
        let base = scratch("dotfile");
        let file = base.join(".bashrc");
        std::fs::write(&file, b"x").unwrap();
        let attrs = attributes(&file).unwrap();
        assert!(attrs.hidden && attrs.hidden_by_name);

        //: Unchecking the box would have to rename it, which would break every
        //: link and bookmark pointing at it. So it is refused, with the reason.
        let err = set_hidden(&file, false).unwrap_err();
        assert_eq!(err.code(), "unsupported");
        assert!(err.to_string().contains("renaming"), "got {err}");
        assert!(file.exists());
        assert!(!base.join(".hidden").exists(), "a dotfile was added to the list as well");
    }

    #[test]
    fn the_listing_and_the_dialog_agree_about_what_is_hidden() {
        //: Two readers of one file. If they disagree, a file shows in the list
        //: while the dialog says it is hidden, which is how a setting becomes
        //: untrustworthy.
        let base = scratch("agree");
        let file = base.join("note.txt");
        std::fs::write(&file, b"x").unwrap();
        set_hidden(&file, true).unwrap();

        let listing = crate::ops::list::list(
            &base,
            &crate::ops::list::Options { show_hidden: true, ..Default::default() },
            &crate::mime::MimeDb::load(),
        )
        .unwrap();
        let row = listing.rows.iter().find(|r| r.name == "note.txt").expect("row missing");
        assert!(row.hidden, "the lister does not think it is hidden");
        assert!(attributes(&file).unwrap().hidden);
    }
}
