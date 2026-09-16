//! Copying, moving, renaming and the shapes of those the file manager offers.
//!
//! The interesting parts are not the syscalls. They are:
//!
//! * **Conflicts.** A copy that lands on an existing name has four honest
//!   answers, and the caller picks one for the whole job or per item. There is
//!   no fifth answer where the data quietly goes away.
//! * **Progress.** A copy of forty gigabytes has to be interruptible, so the
//!   callback runs inside the byte loop and its answer is obeyed at once.
//! * **Not following links.** Every resolution is fd relative through [`Root`],
//!   and a symlink in the source is recreated as a symlink rather than walked.
//!   Copying a tree must not be a way to read something outside it.

use std::fs::File;
use std::io::{Read, Write};
use std::os::fd::AsFd;
use std::path::{Path, PathBuf};

use rustix::fs::{FileType, Timespec, Timestamps};

use crate::error::{Error, Result};
use crate::root::Root;

/// What to do when the destination name is taken.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Conflict {
    /// Stop and report. The default, because it is the only one that cannot
    /// lose data by accident.
    Fail,
    /// Leave what is there and move on.
    Skip,
    /// Overwrite it.
    Replace,
    /// Copy alongside under a free name.
    KeepBoth,
}

impl Default for Conflict {
    fn default() -> Self {
        Conflict::Fail
    }
}

/// The answer a progress callback gives back.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Flow {
    Continue,
    Cancel,
}

/// Where a job has got to. `total_*` are zero when the job was started without
/// a measuring pass, which is what a caller does when it would rather start
/// immediately than count first.
#[derive(Debug, Clone, Default)]
pub struct Progress {
    pub total_bytes: u64,
    pub done_bytes: u64,
    pub total_items: u64,
    pub done_items: u64,
    pub current: PathBuf,
}

/// A progress sink. `&mut dyn` rather than a generic so the daemon can hold
/// one behind a trait object without the whole module going generic.
pub type Reporter<'a> = &'a mut dyn FnMut(&Progress) -> Flow;

/// A do-nothing reporter, for callers that do not care.
pub fn silent(_p: &Progress) -> Flow {
    Flow::Continue
}

/// What a finished job did.
#[derive(Debug, Clone, Default)]
pub struct Outcome {
    /// Destination paths that now exist because of this job.
    pub written: Vec<PathBuf>,
    /// Sources left alone because their name was taken.
    pub skipped: Vec<PathBuf>,
    /// Sources that had to be given a different name, as (source, destination).
    pub renamed: Vec<(PathBuf, PathBuf)>,
    pub bytes: u64,
    pub items: u64,
    /// True when the reporter asked to stop. Whatever had already been written
    /// stays written; a half copied file is removed.
    pub cancelled: bool,
}

const BUF: usize = 1 << 20;

// ----------------------------------------------------------------- helpers ---

/// Open the parent of an absolute path as a root, and hand back the leaf name.
/// Every operation in this module goes through here, so a path is turned into
/// descriptors once and never re-resolved by name.
fn split(path: &Path) -> Result<(Root, PathBuf)> {
    let parent = path
        .parent()
        .ok_or_else(|| Error::BadRequest(format!("{} has no parent", path.display())))?;
    let name = path
        .file_name()
        .ok_or_else(|| Error::BadRequest(format!("{} has no name", path.display())))?;
    Ok((Root::open(parent)?, PathBuf::from(name)))
}

fn file_type(stat: &rustix::fs::Stat) -> FileType {
    FileType::from_raw_mode(stat.st_mode as _)
}

/// `report.txt` and `2` become `report (2).txt`. A leading dot is part of the
/// name, not an extension, so `.bashrc` becomes `.bashrc (2)`.
pub fn numbered(name: &str, n: u32) -> String {
    let dot = name.rfind('.').filter(|i| *i > 0);
    match dot {
        Some(i) => format!("{} ({}){}", &name[..i], n, &name[i..]),
        None => format!("{name} ({n})"),
    }
}

/// The first free name in `dir` based on `name`. Racy by nature: the caller
/// still creates exclusively and retries, this only picks a good first guess.
pub fn unique_name(dir: &Root, name: &str) -> Result<String> {
    if !dir.exists(name) {
        return Ok(name.to_string());
    }
    for n in 2..10_000 {
        let candidate = numbered(name, n);
        if !dir.exists(&candidate) {
            return Ok(candidate);
        }
    }
    Err(Error::Exists(dir.display_path(name).display().to_string()))
}

/// Total item count and byte count for a set of paths, following nothing.
/// Directories count as items but contribute no bytes, which is what makes the
/// percentage match what a person expects.
pub fn measure(paths: &[PathBuf]) -> Result<(u64, u64)> {
    let mut items = 0;
    let mut bytes = 0;
    for path in paths {
        let (root, name) = split(path)?;
        measure_one(&root, &name, &mut items, &mut bytes)?;
    }
    Ok((items, bytes))
}

fn measure_one(root: &Root, name: &Path, items: &mut u64, bytes: &mut u64) -> Result<()> {
    let stat = root.metadata(name)?;
    *items += 1;
    match file_type(&stat) {
        FileType::Directory => {
            let sub = root.sub(name)?;
            for child in sub.read_dir()? {
                measure_one(&sub, &child, items, bytes)?;
            }
        }
        FileType::RegularFile => *bytes += stat.st_size.max(0) as u64,
        _ => {}
    }
    Ok(())
}

/// Is `inner` the same directory as `outer` or below it? Used to refuse
/// copying a folder into itself. This one check resolves by name, because the
/// question is about the shape of the tree rather than about a single open;
/// the work that follows is still fd relative.
fn is_inside(inner: &Path, outer: &Path) -> bool {
    let (Ok(a), Ok(b)) = (inner.canonicalize(), outer.canonicalize()) else {
        return false;
    };
    a.starts_with(b)
}

// -------------------------------------------------------------------- copy ---

/// Copy `sources` into the directory `dest_dir`.
pub fn copy(
    sources: &[PathBuf],
    dest_dir: &Path,
    conflict: Conflict,
    report: Reporter<'_>,
) -> Result<Outcome> {
    run(sources, &[], dest_dir, conflict, false, report)
}

/// Move `sources` into `dest_dir`, by rename where the volume allows it and by
/// copy then delete where it does not.
pub fn move_items(
    sources: &[PathBuf],
    dest_dir: &Path,
    conflict: Conflict,
    report: Reporter<'_>,
) -> Result<Outcome> {
    run(sources, &[], dest_dir, conflict, true, report)
}

/// [`copy`], with a name of the user's own for any source: the conflict
/// dialog lets a clashing item be typed a new name in place of the generated
/// one, and this is where that name lands. `names` runs alongside `sources`;
/// None keeps the source's own name.
pub fn copy_as(
    sources: &[PathBuf],
    names: &[Option<String>],
    dest_dir: &Path,
    conflict: Conflict,
    report: Reporter<'_>,
) -> Result<Outcome> {
    run(sources, names, dest_dir, conflict, false, report)
}

/// [`move_items`], with names of the user's own; see [`copy_as`].
pub fn move_as(
    sources: &[PathBuf],
    names: &[Option<String>],
    dest_dir: &Path,
    conflict: Conflict,
    report: Reporter<'_>,
) -> Result<Outcome> {
    run(sources, names, dest_dir, conflict, true, report)
}

/// A name typed for an item: one path component, and not one of the two
/// that mean somewhere else.
fn check_name(name: &str) -> Result<()> {
    if name.is_empty() || name == "." || name == ".." || name.contains('/') || name.contains('\0')
    {
        return Err(Error::BadRequest(format!("{name:?} is not a name")));
    }
    Ok(())
}

fn run(
    sources: &[PathBuf],
    names: &[Option<String>],
    dest_dir: &Path,
    conflict: Conflict,
    remove_source: bool,
    report: Reporter<'_>,
) -> Result<Outcome> {
    if sources.is_empty() {
        return Ok(Outcome::default());
    }
    //: Checked before anything moves, so a bad name in the third row does
    //: not leave the first two done and the rest not.
    for name in names.iter().flatten() {
        check_name(name)?;
    }
    let dest = Root::open(dest_dir)?;
    let (total_items, total_bytes) = measure(sources)?;
    //: Asked before anything is written. Running out of space halfway leaves a
    //: tree that is neither the old one nor the new one, and the person then
    //: has to work out which files arrived.
    if let Ok(usage) = crate::volumes::usage(dest_dir) {
        if total_bytes > usage.available {
            return Err(Error::no_space(format!(
                "{} needs {total_bytes} bytes and {} has {} free",
                sources.len(),
                dest_dir.display(),
                usage.available
            )));
        }
    }
    let mut progress = Progress { total_bytes, total_items, ..Default::default() };
    let mut out = Outcome::default();

    for (i, src) in sources.iter().enumerate() {
        let (src_root, name) = split(src)?;
        let stat = src_root.metadata(&name)?;
        if file_type(&stat) == FileType::Directory && is_inside(dest_dir, src) {
            return Err(Error::BadRequest(format!(
                "{} is inside {}",
                dest_dir.display(),
                src.display()
            )));
        }
        //: The typed name where there is one, and the conflict rule then
        //: applies to that name: a typed name that is itself taken is
        //: numbered, replaced or skipped the same as any other.
        let leaf = match names.get(i).and_then(Option::as_deref) {
            Some(typed) => typed.to_string(),
            None => name.to_string_lossy().to_string(),
        };
        let target = match resolve_conflict(&dest, &leaf, conflict, src, &mut out)? {
            Some(t) => t,
            None => continue,
        };
        if target != leaf {
            out.renamed.push((src.clone(), dest.display_path(&target)));
        }

        //: A rename across the same filesystem moves a whole tree for the cost
        //: of one syscall, so it is always worth trying first. EXDEV is the
        //: filesystem saying no, which is a fall back rather than an error.
        if remove_source {
            match src_root.rename_to(&name, &dest, &target) {
                Ok(()) => {
                    //: The whole subtree moved at once, so its share of the
                    //: totals lands in one step. Counting the grand total here
                    //: would finish the bar on the first of several sources.
                    let (n, b) = measure(&[dest.display_path(&target)])?;
                    out.written.push(dest.display_path(&target));
                    out.items += n;
                    progress.done_items += n;
                    progress.done_bytes += b;
                    if report(&progress) == Flow::Cancel {
                        out.cancelled = true;
                        return Ok(out);
                    }
                    continue;
                }
                Err(Error::Io { source, .. }) if source.raw_os_error() == Some(18) => {}
                Err(e) => return Err(e),
            }
        }

        let flow = copy_node(&src_root, &name, &dest, Path::new(&target), &mut progress, report, &mut out)?;
        if flow == Flow::Cancel {
            out.cancelled = true;
            return Ok(out);
        }
        out.written.push(dest.display_path(&target));
        if remove_source {
            remove_tree(&src_root, &name)?;
        }
    }
    Ok(out)
}

/// Decide the destination name, or `None` to skip this source entirely.
fn resolve_conflict(
    dest: &Root,
    leaf: &str,
    conflict: Conflict,
    src: &Path,
    out: &mut Outcome,
) -> Result<Option<String>> {
    if !dest.exists(leaf) {
        return Ok(Some(leaf.to_string()));
    }
    match conflict {
        Conflict::Fail => Err(Error::Exists(dest.display_path(leaf).display().to_string())),
        Conflict::Skip => {
            out.skipped.push(src.to_path_buf());
            Ok(None)
        }
        Conflict::Replace => {
            remove_tree(dest, Path::new(leaf))?;
            Ok(Some(leaf.to_string()))
        }
        Conflict::KeepBoth => Ok(Some(unique_name(dest, leaf)?)),
    }
}

/// Copy one node, recursing for a directory. Returns `Flow::Cancel` if the
/// reporter asked to stop, with everything already written left in place.
fn copy_node(
    src_root: &Root,
    src_name: &Path,
    dest: &Root,
    dest_name: &Path,
    progress: &mut Progress,
    report: Reporter<'_>,
    out: &mut Outcome,
) -> Result<Flow> {
    let stat = src_root.metadata(src_name)?;
    progress.current = src_root.display_path(src_name);
    match file_type(&stat) {
        FileType::Directory => {
            dest.mkdir(dest_name, stat.st_mode as u32 & 0o7777, true)?;
            progress.done_items += 1;
            out.items += 1;
            if report(progress) == Flow::Cancel {
                return Ok(Flow::Cancel);
            }
            let sub_src = src_root.sub(src_name)?;
            let sub_dest = dest.sub(dest_name)?;
            for child in sub_src.read_dir()? {
                let flow =
                    copy_node(&sub_src, &child, &sub_dest, &child, progress, report, out)?;
                if flow == Flow::Cancel {
                    return Ok(Flow::Cancel);
                }
            }
            //: The directory's own timestamp last, because writing its children
            //: bumps it.
            let _ = sub_dest.set_times(&times_of(&stat));
            Ok(Flow::Continue)
        }
        FileType::Symlink => {
            //: Recreated, never followed. Following would copy whatever the
            //: link points at, which is how a tree copy turns into a way to
            //: read a file the caller never named.
            let (parent, name) = src_root.parent_of(src_name)?;
            let target = rustix::fs::readlinkat(&parent, name.as_os_str(), Vec::new())
                .map_err(|e| Error::io(src_name.display().to_string(), std::io::Error::from(e)))?;
            let target = PathBuf::from(std::os::unix::ffi::OsStrExt::from_bytes(
                target.as_bytes(),
            ) as &std::ffi::OsStr);
            dest.symlink(&target, dest_name)?;
            progress.done_items += 1;
            out.items += 1;
            Ok(report(progress))
        }
        FileType::RegularFile => {
            let flow = copy_file(src_root, src_name, dest, dest_name, &stat, progress, report, out)?;
            progress.done_items += 1;
            out.items += 1;
            if flow == Flow::Cancel {
                return Ok(Flow::Cancel);
            }
            Ok(report(progress))
        }
        //: Sockets, fifos and devices are not the file manager's to reproduce.
        //: Skipping them is deliberate, and it is counted so the summary adds
        //: up.
        _ => {
            progress.done_items += 1;
            Ok(Flow::Continue)
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn copy_file(
    src_root: &Root,
    src_name: &Path,
    dest: &Root,
    dest_name: &Path,
    stat: &rustix::fs::Stat,
    progress: &mut Progress,
    report: Reporter<'_>,
    out: &mut Outcome,
) -> Result<Flow> {
    let mut input = src_root.open_file(src_name)?;
    let mut output = dest.create_file(dest_name, stat.st_mode as u32 & 0o7777, true)?;
    let size = stat.st_size.max(0) as u64;

    //: On Btrfs, which is what AuraDE installs, a whole file clone is a
    //: metadata operation: a twenty gigabyte copy finishes instantly and costs
    //: no space. It fails on anything else, and the byte loop below is then the
    //: real path.
    if rustix::fs::ioctl_ficlone(output.as_fd(), input.as_fd()).is_ok() {
        progress.done_bytes += size;
        out.bytes += size;
        finish_file(&output, stat);
        return Ok(report(progress));
    }

    let mut buf = vec![0u8; BUF];
    loop {
        let n = input
            .read(&mut buf)
            .map_err(|e| Error::io(src_name.display().to_string(), e))?;
        if n == 0 {
            break;
        }
        output
            .write_all(&buf[..n])
            .map_err(|e| Error::io(dest_name.display().to_string(), e))?;
        progress.done_bytes += n as u64;
        out.bytes += n as u64;
        if report(progress) == Flow::Cancel {
            //: A half written file is worse than no file, so it goes. The
            //: sources and everything finished before this stay untouched.
            drop(output);
            let _ = dest.remove(dest_name, false);
            return Ok(Flow::Cancel);
        }
    }
    output
        .flush()
        .map_err(|e| Error::io(dest_name.display().to_string(), e))?;
    finish_file(&output, stat);
    Ok(Flow::Continue)
}

/// Mode and modification time, copied onto the new file. Best effort: a
/// destination that will not take them is still a successful copy of the
/// contents, which is what the caller asked for.
fn finish_file(file: &File, stat: &rustix::fs::Stat) {
    let _ = rustix::fs::fchmod(
        file.as_fd(),
        rustix::fs::Mode::from_bits_truncate(stat.st_mode as u32 & 0o7777),
    );
    let _ = rustix::fs::futimens(file.as_fd(), &times_of(stat));
}

fn times_of(stat: &rustix::fs::Stat) -> Timestamps {
    Timestamps {
        last_access: Timespec { tv_sec: stat.st_atime as _, tv_nsec: stat.st_atime_nsec as _ },
        last_modification: Timespec { tv_sec: stat.st_mtime as _, tv_nsec: stat.st_mtime_nsec as _ },
    }
}

/// Delete a file, or a directory and everything under it.
pub fn remove_tree(root: &Root, name: &Path) -> Result<()> {
    let stat = root.metadata(name)?;
    if file_type(&stat) == FileType::Directory {
        let sub = root.sub(name)?;
        for child in sub.read_dir()? {
            remove_tree(&sub, &child)?;
        }
        return root.remove(name, true);
    }
    root.remove(name, false)
}

/// Delete these paths outright, with no trash involved. The caller is expected
/// to have asked first.
pub fn delete(paths: &[PathBuf], report: Reporter<'_>) -> Result<Outcome> {
    let (total_items, total_bytes) = measure(paths)?;
    let mut progress = Progress { total_items, total_bytes, ..Default::default() };
    let mut out = Outcome::default();
    for path in paths {
        let (root, name) = split(path)?;
        progress.current = path.clone();
        remove_tree(&root, &name)?;
        progress.done_items += 1;
        out.items += 1;
        out.written.push(path.clone());
        if report(&progress) == Flow::Cancel {
            out.cancelled = true;
            return Ok(out);
        }
    }
    Ok(out)
}

// ------------------------------------------------------------- single items ---

/// Rename in place. A rename to the same name is a success and does nothing,
/// because that is what an editor that commits an unchanged field should get.
pub fn rename(path: &Path, new_name: &str, conflict: Conflict) -> Result<PathBuf> {
    validate_name(new_name)?;
    let (root, name) = split(path)?;
    if name.as_os_str() == new_name {
        return Ok(path.to_path_buf());
    }
    let mut target = new_name.to_string();
    if root.exists(&target) {
        match conflict {
            Conflict::Fail | Conflict::Skip => {
                return Err(Error::Exists(root.display_path(&target).display().to_string()));
            }
            Conflict::Replace => remove_tree(&root, Path::new(&target))?,
            Conflict::KeepBoth => target = unique_name(&root, &target)?,
        }
    }
    root.rename_to(&name, &root, &target)?;
    Ok(root.display_path(&target))
}

/// What a new item is. Files offers a folder, an empty file, and a file seeded
/// from a template.
#[derive(Debug, Clone)]
pub enum NewItem {
    Folder,
    File,
    FromTemplate(PathBuf),
}

/// Create one new item in `dir`, never overwriting: the name is made unique
/// first, and the create is exclusive so a race loses rather than clobbers.
pub fn create(dir: &Path, name: &str, kind: NewItem) -> Result<PathBuf> {
    validate_name(name)?;
    let root = Root::open(dir)?;
    let target = unique_name(&root, name)?;
    match kind {
        NewItem::Folder => root.mkdir(&target, 0o755, false)?,
        NewItem::File => {
            root.create_file(&target, 0o644, true)?;
        }
        NewItem::FromTemplate(template) => {
            let (t_root, t_name) = split(&template)?;
            let stat = t_root.metadata(&t_name)?;
            let mut progress = Progress::default();
            let mut out = Outcome::default();
            copy_node(
                &t_root,
                &t_name,
                &root,
                Path::new(&target),
                &mut progress,
                &mut silent,
                &mut out,
            )?;
            let _ = stat;
        }
    }
    Ok(root.display_path(&target))
}

/// A name the filesystem and the user can both live with. The empty name, `.`,
/// `..` and anything with a separator in it are refused here rather than
/// producing a confusing errno later.
pub fn validate_name(name: &str) -> Result<()> {
    if name.is_empty() {
        return Err(Error::BadRequest("the name is empty".into()));
    }
    if name == "." || name == ".." {
        return Err(Error::BadRequest(format!("{name} is not a usable name")));
    }
    if name.contains('/') || name.contains('\0') {
        return Err(Error::BadRequest(
            "a name cannot contain a slash or a null".into(),
        ));
    }
    if name.len() > 255 {
        return Err(Error::BadRequest("the name is longer than 255 bytes".into()));
    }
    Ok(())
}

/// Copy each path next to itself under a free name. This is Files' Duplicate.
pub fn duplicate(paths: &[PathBuf], report: Reporter<'_>) -> Result<Outcome> {
    let (total_items, total_bytes) = measure(paths)?;
    let mut progress = Progress { total_items, total_bytes, ..Default::default() };
    let mut out = Outcome::default();
    for path in paths {
        let (root, name) = split(path)?;
        let target = unique_name(&root, &name.to_string_lossy())?;
        let flow = copy_node(
            &root,
            &name,
            &root,
            Path::new(&target),
            &mut progress,
            report,
            &mut out,
        )?;
        out.written.push(root.display_path(&target));
        out.renamed.push((path.clone(), root.display_path(&target)));
        if flow == Flow::Cancel {
            out.cancelled = true;
            return Ok(out);
        }
    }
    Ok(out)
}

/// Files' Create shortcut. On Windows that writes a `.lnk`; the honest Linux
/// equivalent is a symlink, which every other program on the system also
/// understands.
pub fn make_shortcut(target: &Path, dest_dir: &Path, name: Option<&str>) -> Result<PathBuf> {
    let dest = Root::open(dest_dir)?;
    let base = match name {
        Some(n) => n.to_string(),
        None => format!(
            "{} link",
            target
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| "link".into())
        ),
    };
    validate_name(&base)?;
    let leaf = unique_name(&dest, &base)?;
    dest.symlink(target, &leaf)?;
    Ok(dest.display_path(&leaf))
}

/// Files' New folder with selection: make the folder, then move the selection
/// into it. The move is a rename when it can be, so this is nearly free.
pub fn folder_with_selection(
    sources: &[PathBuf],
    dest_dir: &Path,
    name: &str,
    report: Reporter<'_>,
) -> Result<PathBuf> {
    if sources.is_empty() {
        return Err(Error::BadRequest("nothing selected".into()));
    }
    let folder = create(dest_dir, name, NewItem::Folder)?;
    //: If the move fails the empty folder would be litter, so it goes back.
    match move_items(sources, &folder, Conflict::KeepBoth, report) {
        Ok(_) => Ok(folder),
        Err(e) => {
            let (root, leaf) = split(&folder)?;
            let _ = root.remove(&leaf, true);
            Err(e)
        }
    }
}

/// Files' Flatten folder: everything under `dir`, at any depth, ends up
/// directly in `dir`, and the emptied subdirectories go.
pub fn flatten(dir: &Path, conflict: Conflict, report: Reporter<'_>) -> Result<Outcome> {
    let root = Root::open(dir)?;
    let mut out = Outcome::default();
    let mut progress = Progress::default();
    let top: Vec<PathBuf> = root.read_dir()?;
    for entry in &top {
        let stat = root.metadata(entry)?;
        if file_type(&stat) != FileType::Directory {
            continue;
        }
        let sub = root.sub(entry)?;
        lift(&sub, &root, conflict, &mut progress, report, &mut out)?;
        //: Only now is it certain to be empty.
        remove_tree(&root, entry)?;
    }
    Ok(out)
}

fn lift(
    from: &Root,
    to: &Root,
    conflict: Conflict,
    progress: &mut Progress,
    report: Reporter<'_>,
    out: &mut Outcome,
) -> Result<()> {
    for child in from.read_dir()? {
        let stat = from.metadata(&child)?;
        if file_type(&stat) == FileType::Directory {
            let sub = from.sub(&child)?;
            lift(&sub, to, conflict, progress, report, out)?;
            continue;
        }
        let leaf = child.to_string_lossy().to_string();
        let src_display = from.display_path(&child);
        let Some(target) = resolve_conflict(to, &leaf, conflict, &src_display, out)? else {
            continue;
        };
        if target != leaf {
            out.renamed.push((src_display.clone(), to.display_path(&target)));
        }
        from.rename_to(&child, to, &target)?;
        out.written.push(to.display_path(&target));
        out.items += 1;
        progress.done_items += 1;
        progress.current = src_display;
        if report(progress) == Flow::Cancel {
            out.cancelled = true;
            return Ok(());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs as sfs;

    fn scratch(tag: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!("auradefs-fs-{tag}"));
        let _ = sfs::remove_dir_all(&base);
        sfs::create_dir_all(base.join("src/inner")).unwrap();
        sfs::write(base.join("src/top.txt"), b"top").unwrap();
        sfs::write(base.join("src/inner/deep.txt"), b"deep").unwrap();
        sfs::create_dir_all(base.join("dest")).unwrap();
        base
    }

    fn go() -> impl FnMut(&Progress) -> Flow {
        |_: &Progress| Flow::Continue
    }

    #[test]
    fn a_typed_name_is_where_the_item_lands_and_the_conflict_rule_still_applies() {
        let base = scratch("typed-name");
        sfs::write(base.join("dest/top.txt"), b"old").unwrap();
        //: The clash is answered with a name, and that name is what lands;
        //: nothing is numbered and the old file is left alone.
        let out = copy_as(
            &[base.join("src/top.txt")],
            &[Some("mine.txt".into())],
            &base.join("dest"),
            Conflict::KeepBoth,
            &mut go(),
        )
        .unwrap();
        assert_eq!(out.written, vec![base.join("dest/mine.txt")]);
        assert!(out.renamed.is_empty());
        assert_eq!(sfs::read(base.join("dest/mine.txt")).unwrap(), b"top");
        assert_eq!(sfs::read(base.join("dest/top.txt")).unwrap(), b"old");
        //: A typed name that is itself taken goes through the same rule as
        //: any other: keep both numbers it.
        let out = copy_as(
            &[base.join("src/inner/deep.txt")],
            &[Some("mine.txt".into())],
            &base.join("dest"),
            Conflict::KeepBoth,
            &mut go(),
        )
        .unwrap();
        assert_eq!(out.written, vec![base.join("dest/mine (2).txt")]);
        assert_eq!(out.renamed.len(), 1);
        //: A move takes the typed name too, and a folder as well as a file.
        let out = move_as(
            &[base.join("src/inner")],
            &[Some("moved-inner".into())],
            &base.join("dest"),
            Conflict::Fail,
            &mut go(),
        )
        .unwrap();
        assert_eq!(out.written, vec![base.join("dest/moved-inner")]);
        assert!(base.join("dest/moved-inner/deep.txt").exists());
        assert!(!base.join("src/inner").exists());
    }

    #[test]
    fn a_typed_name_that_is_not_a_name_is_refused_before_anything_moves() {
        let base = scratch("bad-typed-name");
        for bad in ["", ".", "..", "up/there", "with\0nul"] {
            let err = copy_as(
                &[base.join("src/top.txt")],
                &[Some(bad.into())],
                &base.join("dest"),
                Conflict::KeepBoth,
                &mut go(),
            )
            .unwrap_err();
            assert_eq!(err.code(), "bad-request", "{bad:?}");
            assert!(!base.join("dest/top.txt").exists(), "{bad:?} copied anyway");
        }
        //: And fewer names than sources is fine: the rest keep their own.
        let out = copy_as(
            &[base.join("src/top.txt"), base.join("src/inner")],
            &[None],
            &base.join("dest"),
            Conflict::Fail,
            &mut go(),
        )
        .unwrap();
        assert_eq!(out.written.len(), 2);
        assert!(base.join("dest/inner/deep.txt").exists());
    }

    #[test]
    fn a_number_goes_before_the_extension() {
        assert_eq!(numbered("report.txt", 2), "report (2).txt");
        assert_eq!(numbered("archive.tar.gz", 3), "archive.tar (3).gz");
        assert_eq!(numbered("README", 2), "README (2)");
        //: A leading dot is the name, not an extension.
        assert_eq!(numbered(".bashrc", 2), ".bashrc (2)");
    }

    #[test]
    fn a_tree_arrives_whole() {
        let base = scratch("tree");
        let out = copy(&[base.join("src")], &base.join("dest"), Conflict::Fail, &mut go()).unwrap();
        assert_eq!(sfs::read(base.join("dest/src/top.txt")).unwrap(), b"top");
        assert_eq!(sfs::read(base.join("dest/src/inner/deep.txt")).unwrap(), b"deep");
        assert_eq!(out.items, 4, "src, top.txt, inner, deep.txt");
        assert_eq!(out.bytes, 7);
        assert!(base.join("src/top.txt").exists(), "a copy is not a move");
    }

    #[test]
    fn a_copy_that_would_not_fit_is_refused_before_it_starts() {
        let base = scratch("nospace");
        //: /proc is a filesystem with no room at all, which is the honest way
        //: to ask this without filling a real disk.
        let err = copy(
            &[base.join("src")],
            std::path::Path::new("/proc"),
            Conflict::Fail,
            &mut go(),
        )
        .unwrap_err();
        //: Either the space check or the read only filesystem refuses it. What
        //: must not happen is a partial copy, and nothing was written either
        //: way.
        assert!(
            matches!(err, Error::Io { .. } | Error::Denied(_) | Error::ReadOnly(_)),
            "got {err:?}"
        );
        assert!(!std::path::Path::new("/proc/src").exists());
    }

    #[test]
    fn a_copy_that_fits_is_not_refused() {
        let base = scratch("space-ok");
        let out = copy(&[base.join("src")], &base.join("dest"), Conflict::Fail, &mut go()).unwrap();
        assert_eq!(out.items, 4);
    }

    #[test]
    fn a_copied_tree_keeps_its_timestamps() {
        use std::os::unix::fs::MetadataExt;
        let base = scratch("times");
        //: Well in the past, so a copy that simply used "now" would not match.
        let when = std::time::SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(1_000_000_000);
        for p in ["src", "src/top.txt", "src/inner"] {
            let f = std::fs::File::open(base.join(p)).unwrap();
            f.set_times(std::fs::FileTimes::new().set_accessed(when).set_modified(when)).unwrap();
        }
        copy(&[base.join("src")], &base.join("dest"), Conflict::Fail, &mut go()).unwrap();
        assert_eq!(sfs::metadata(base.join("dest/src/top.txt")).unwrap().mtime(), 1_000_000_000);
        assert_eq!(
            sfs::metadata(base.join("dest/src")).unwrap().mtime(),
            1_000_000_000,
            "the folder's own time was left at the moment of the copy"
        );
        assert_eq!(sfs::metadata(base.join("dest/src/inner")).unwrap().mtime(), 1_000_000_000);
    }

    #[test]
    fn measuring_counts_directories_as_items_and_not_as_bytes() {
        let base = scratch("measure");
        let (items, bytes) = measure(&[base.join("src")]).unwrap();
        assert_eq!((items, bytes), (4, 7));
    }

    #[test]
    fn the_four_answers_to_a_taken_name() {
        let base = scratch("conflict");
        sfs::write(base.join("dest/top.txt"), b"already here").unwrap();
        let src = vec![base.join("src/top.txt")];
        let dest = base.join("dest");

        let err = copy(&src, &dest, Conflict::Fail, &mut go()).unwrap_err();
        assert!(matches!(err, Error::Exists(_)), "got {err:?}");
        assert_eq!(sfs::read(base.join("dest/top.txt")).unwrap(), b"already here");

        let out = copy(&src, &dest, Conflict::Skip, &mut go()).unwrap();
        assert_eq!(out.skipped, src);
        assert_eq!(sfs::read(base.join("dest/top.txt")).unwrap(), b"already here");

        let out = copy(&src, &dest, Conflict::KeepBoth, &mut go()).unwrap();
        assert_eq!(sfs::read(base.join("dest/top (2).txt")).unwrap(), b"top");
        assert_eq!(sfs::read(base.join("dest/top.txt")).unwrap(), b"already here");
        assert_eq!(out.renamed.len(), 1);

        copy(&src, &dest, Conflict::Replace, &mut go()).unwrap();
        assert_eq!(sfs::read(base.join("dest/top.txt")).unwrap(), b"top");
    }

    #[test]
    fn replacing_a_folder_does_not_leave_the_old_contents_behind() {
        let base = scratch("replace-dir");
        sfs::create_dir_all(base.join("dest/src")).unwrap();
        sfs::write(base.join("dest/src/stale.txt"), b"old").unwrap();
        copy(&[base.join("src")], &base.join("dest"), Conflict::Replace, &mut go()).unwrap();
        assert!(base.join("dest/src/top.txt").exists());
        assert!(!base.join("dest/src/stale.txt").exists(), "the old tree survived");
    }

    #[test]
    fn a_move_on_one_filesystem_keeps_the_same_inode() {
        use std::os::unix::fs::MetadataExt;
        let base = scratch("move-rename");
        let before = sfs::metadata(base.join("src/top.txt")).unwrap().ino();
        move_items(
            &[base.join("src/top.txt")],
            &base.join("dest"),
            Conflict::Fail,
            &mut go(),
        )
        .unwrap();
        let after = sfs::metadata(base.join("dest/top.txt")).unwrap().ino();
        assert_eq!(before, after, "it copied when it could have renamed");
        assert!(!base.join("src/top.txt").exists());
    }

    #[test]
    fn a_symlink_is_recreated_and_never_walked() {
        use std::os::unix::fs::symlink;
        let base = scratch("symlink");
        sfs::write(base.join("secret.txt"), b"not yours").unwrap();
        symlink(base.join("secret.txt"), base.join("src/peek")).unwrap();

        copy(&[base.join("src")], &base.join("dest"), Conflict::Fail, &mut go()).unwrap();
        let landed = base.join("dest/src/peek");
        let meta = sfs::symlink_metadata(&landed).unwrap();
        assert!(meta.file_type().is_symlink(), "the link was followed and the file copied");
        assert_eq!(sfs::read_link(&landed).unwrap(), base.join("secret.txt"));
    }

    #[test]
    fn copying_a_folder_into_itself_is_refused() {
        let base = scratch("into-itself");
        let err = copy(
            &[base.join("src")],
            &base.join("src/inner"),
            Conflict::Fail,
            &mut go(),
        )
        .unwrap_err();
        assert!(matches!(err, Error::BadRequest(_)), "got {err:?}");
    }

    #[test]
    fn cancelling_mid_file_leaves_no_half_file() {
        let base = scratch("cancel");
        let big = vec![b'x'; BUF * 3];
        sfs::write(base.join("src/big.bin"), &big).unwrap();
        let mut seen = 0;
        let mut report = |_p: &Progress| {
            seen += 1;
            if seen >= 2 { Flow::Cancel } else { Flow::Continue }
        };
        let out = copy(
            &[base.join("src/big.bin")],
            &base.join("dest"),
            Conflict::Fail,
            &mut report,
        )
        .unwrap();
        assert!(out.cancelled);
        assert!(
            !base.join("dest/big.bin").exists(),
            "a partial file was left on disk"
        );
    }

    #[test]
    fn deleting_takes_the_whole_tree() {
        let base = scratch("delete");
        delete(&[base.join("src")], &mut go()).unwrap();
        assert!(!base.join("src").exists());
    }

    #[test]
    fn duplicate_lands_beside_the_original() {
        let base = scratch("duplicate");
        let out = duplicate(&[base.join("src/top.txt")], &mut go()).unwrap();
        assert_eq!(sfs::read(base.join("src/top (2).txt")).unwrap(), b"top");
        assert_eq!(sfs::read(base.join("src/top.txt")).unwrap(), b"top");
        assert_eq!(out.renamed.len(), 1);
    }

    #[test]
    fn a_shortcut_is_a_symlink_that_can_outlive_its_target() {
        let base = scratch("shortcut");
        let link = make_shortcut(&base.join("src/top.txt"), &base.join("dest"), None).unwrap();
        assert_eq!(sfs::read(&link).unwrap(), b"top");
        sfs::remove_file(base.join("src/top.txt")).unwrap();
        assert!(sfs::symlink_metadata(&link).unwrap().file_type().is_symlink());
    }

    #[test]
    fn new_folder_with_selection_moves_the_selection_in() {
        let base = scratch("with-selection");
        let folder = folder_with_selection(
            &[base.join("src/top.txt"), base.join("src/inner")],
            &base.join("dest"),
            "Grouped",
            &mut go(),
        )
        .unwrap();
        assert_eq!(folder, base.join("dest/Grouped"));
        assert!(base.join("dest/Grouped/top.txt").exists());
        assert!(base.join("dest/Grouped/inner/deep.txt").exists());
        assert!(!base.join("src/top.txt").exists());
    }

    #[test]
    fn flatten_lifts_every_depth_and_removes_the_folders() {
        let base = scratch("flatten");
        sfs::create_dir_all(base.join("src/inner/deeper")).unwrap();
        sfs::write(base.join("src/inner/deeper/buried.txt"), b"buried").unwrap();
        let out = flatten(&base.join("src"), Conflict::KeepBoth, &mut go()).unwrap();
        assert_eq!(sfs::read(base.join("src/deep.txt")).unwrap(), b"deep");
        assert_eq!(sfs::read(base.join("src/buried.txt")).unwrap(), b"buried");
        assert!(!base.join("src/inner").exists(), "the emptied folder stayed");
        assert!(base.join("src/top.txt").exists(), "a file already at the top moved");
        assert_eq!(out.items, 2);
    }

    #[test]
    fn flatten_keeps_both_when_two_names_collide() {
        let base = scratch("flatten-collide");
        sfs::write(base.join("src/inner/top.txt"), b"other top").unwrap();
        flatten(&base.join("src"), Conflict::KeepBoth, &mut go()).unwrap();
        assert_eq!(sfs::read(base.join("src/top.txt")).unwrap(), b"top");
        assert_eq!(sfs::read(base.join("src/top (2).txt")).unwrap(), b"other top");
    }

    #[test]
    fn renaming_is_checked_before_it_reaches_the_filesystem() {
        let base = scratch("rename");
        let target = base.join("src/top.txt");
        for bad in ["", ".", "..", "a/b", "with\0null"] {
            let err = rename(&target, bad, Conflict::Fail).unwrap_err();
            //: The path walk would refuse most of these too, but with an errno
            //: that reads as a filesystem failure. A name the user typed is a
            //: bad request, and the dialog says a different thing for each.
            assert_eq!(err.code(), "bad-request", "{bad:?} gave {err:?}");
        }
        //: The one that is not refused by anything else: `inner` exists, so
        //: without the name check this would quietly move the file into it
        //: instead of renaming it, and the rename field would be a path editor.
        let err = rename(&target, "inner/moved.txt", Conflict::Fail).unwrap_err();
        assert_eq!(err.code(), "bad-request", "got {err:?}");
        assert!(!base.join("src/inner/moved.txt").exists(), "it moved instead");
        assert!(target.exists());
        let moved = rename(&target, "renamed.txt", Conflict::Fail).unwrap();
        assert_eq!(moved, base.join("src/renamed.txt"));
        assert_eq!(sfs::read(&moved).unwrap(), b"top");
        //: Committing an unchanged field is a success, not a conflict.
        assert_eq!(rename(&moved, "renamed.txt", Conflict::Fail).unwrap(), moved);
    }

    #[test]
    fn renaming_onto_a_taken_name_is_refused_by_default() {
        let base = scratch("rename-conflict");
        let err = rename(&base.join("src/top.txt"), "inner", Conflict::Fail).unwrap_err();
        assert!(matches!(err, Error::Exists(_)), "got {err:?}");
        assert!(base.join("src/inner/deep.txt").exists(), "the folder was clobbered");
    }

    #[test]
    fn new_items_never_take_a_name_that_is_in_use() {
        let base = scratch("create");
        let dir = base.join("dest");
        assert_eq!(create(&dir, "Notes", NewItem::Folder).unwrap(), dir.join("Notes"));
        assert_eq!(
            create(&dir, "Notes", NewItem::Folder).unwrap(),
            dir.join("Notes (2)")
        );
        let file = create(&dir, "empty.txt", NewItem::File).unwrap();
        assert_eq!(sfs::read(&file).unwrap(), b"");
        let seeded = create(
            &dir,
            "from-template.txt",
            NewItem::FromTemplate(base.join("src/top.txt")),
        )
        .unwrap();
        assert_eq!(sfs::read(&seeded).unwrap(), b"top");
    }
}
