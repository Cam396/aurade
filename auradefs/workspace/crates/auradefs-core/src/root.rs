//! Resolving a path exactly once.
//!
//! A file manager is handed paths by an untrusted page and acts on them as the
//! user. The dangerous shape is check-then-open: `abspath()`, decide it is
//! inside the allowed tree, then `open()` by name. Between those two calls a
//! component can become a symlink to somewhere else, and the open follows it.
//!
//! [`Root`] closes that by walking the path one component at a time from an
//! open directory descriptor, refusing symlinked directories and `..` that
//! would leave the root, and handing back a descriptor rather than a name.

use std::ffi::OsStr;
use std::fs::File;
use std::os::fd::{AsFd, OwnedFd};
use std::os::unix::ffi::OsStringExt;
use std::path::{Component, Path, PathBuf};

use rustix::fs::{Mode, OFlags, openat};

use crate::error::{Error, Result};

/// An open handle to a directory that operations are resolved against.
#[derive(Debug)]
pub struct Root {
    dir: OwnedFd,
    path: PathBuf,
}

impl Root {
    /// Open a directory as a resolution root.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let file = File::open(path)
            .map_err(|e| Error::io(path.display().to_string(), e))?;
        if !file
            .metadata()
            .map_err(|e| Error::io(path.display().to_string(), e))?
            .is_dir()
        {
            return Err(Error::BadRequest(format!(
                "{} is not a directory",
                path.display()
            )));
        }
        Ok(Root { dir: file.into(), path: path.to_path_buf() })
    }

    /// The directory this root was opened on.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Split a relative path into components, refusing anything that could
    /// leave the root before a single syscall is made. `..` is rejected
    /// outright rather than resolved: a file manager always knows the parent
    /// it means, so it can name it directly, and allowing `..` here would put
    /// the escape check back into string handling where it does not belong.
    fn components<'a>(&self, rel: &'a Path) -> Result<Vec<&'a OsStr>> {
        let mut out = Vec::new();
        for part in rel.components() {
            match part {
                Component::Normal(p) => out.push(p),
                Component::CurDir => {}
                Component::ParentDir => {
                    return Err(Error::Escapes(rel.display().to_string()));
                }
                Component::RootDir | Component::Prefix(_) => {
                    return Err(Error::BadRequest(format!(
                        "{} must be relative to the root",
                        rel.display()
                    )));
                }
            }
        }
        Ok(out)
    }

    /// Open the directory that holds `rel`, and return it with the final
    /// component. This is what every mutating operation wants: the parent as a
    /// descriptor, so the write is `*at()` relative and cannot be redirected.
    pub fn parent_of(&self, rel: impl AsRef<Path>) -> Result<(OwnedFd, PathBuf)> {
        let rel = rel.as_ref();
        let parts = self.components(rel)?;
        let (last, dirs) = parts
            .split_last()
            .ok_or_else(|| Error::BadRequest("empty path".into()))?;

        let mut cur: OwnedFd = self
            .dir
            .as_fd()
            .try_clone_to_owned()
            .map_err(|e| Error::io("dup root", e))?;
        for part in dirs {
            //: NOFOLLOW on every intermediate directory. A component that
            //: became a symlink since the caller looked stops the walk here
            //: rather than redirecting the operation.
            let next = openat(
                &cur,
                *part,
                OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|e| match e {
                rustix::io::Errno::NOTDIR => Error::Escapes(rel.display().to_string()),
                other => errno_to_error(rel, other),
            })?;
            cur = next;
        }
        Ok((cur, PathBuf::from(last)))
    }

    /// The absolute path `rel` names, for reporting only. Never pass the
    /// result back to an open: that would reintroduce the race this type
    /// exists to close.
    pub fn display_path(&self, rel: impl AsRef<Path>) -> PathBuf {
        self.path.join(rel)
    }

    /// Descend into a subdirectory and get a root for it. Recursive work
    /// walks with these rather than re-resolving a longer path each time,
    /// so the cost of the walk is paid once per level and the NOFOLLOW
    /// guarantee still holds at every level.
    pub fn sub(&self, rel: impl AsRef<Path>) -> Result<Root> {
        let rel = rel.as_ref();
        let (parent, name) = self.parent_of(rel)?;
        let dir = openat(
            &parent,
            name.as_os_str(),
            OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )
        .map_err(|e| errno_to_error(rel, e))?;
        Ok(Root { dir, path: self.path.join(rel) })
    }

    /// Create a file under the root and return it open for writing.
    /// `exclusive` is the difference between "new file" (which must not
    /// clobber) and "replace on conflict" (which must).
    pub fn create_file(&self, rel: impl AsRef<Path>, mode: u32, exclusive: bool) -> Result<File> {
        let rel = rel.as_ref();
        let (parent, name) = self.parent_of(rel)?;
        let mut flags = OFlags::CREATE | OFlags::WRONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW;
        if exclusive {
            flags |= OFlags::EXCL;
        } else {
            flags |= OFlags::TRUNC;
        }
        let fd = openat(&parent, name.as_os_str(), flags, Mode::from_bits_truncate(mode))
            .map_err(|e| errno_to_error(rel, e))?;
        Ok(File::from(fd))
    }

    /// Open a file under the root for reading, refusing a symlink at the leaf.
    pub fn open_file(&self, rel: impl AsRef<Path>) -> Result<File> {
        let rel = rel.as_ref();
        let (parent, name) = self.parent_of(rel)?;
        let fd = openat(
            &parent,
            name.as_os_str(),
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|e| errno_to_error(rel, e))?;
        Ok(File::from(fd))
    }

    /// Make a directory under the root. `existing_is_fine` is what a
    /// recursive copy wants, since the shape of the tree is the point and an
    /// already present directory is not a conflict.
    pub fn mkdir(&self, rel: impl AsRef<Path>, mode: u32, existing_is_fine: bool) -> Result<()> {
        let rel = rel.as_ref();
        let (parent, name) = self.parent_of(rel)?;
        match rustix::fs::mkdirat(&parent, name.as_os_str(), Mode::from_bits_truncate(mode)) {
            Ok(()) => Ok(()),
            Err(rustix::io::Errno::EXIST) if existing_is_fine => Ok(()),
            Err(e) => Err(errno_to_error(rel, e)),
        }
    }

    /// Create every missing directory along `rel`.
    pub fn mkdir_all(&self, rel: impl AsRef<Path>, mode: u32) -> Result<()> {
        let rel = rel.as_ref();
        let mut so_far = PathBuf::new();
        for part in self.components(rel)? {
            so_far.push(part);
            self.mkdir(&so_far, mode, true)?;
        }
        Ok(())
    }

    /// Point a new symlink at `target`. The target is stored verbatim and is
    /// never resolved here, which is what makes a shortcut to a path that does
    /// not exist yet possible.
    pub fn symlink(&self, target: impl AsRef<Path>, rel: impl AsRef<Path>) -> Result<()> {
        let rel = rel.as_ref();
        let (parent, name) = self.parent_of(rel)?;
        rustix::fs::symlinkat(target.as_ref(), &parent, name.as_os_str())
            .map_err(|e| errno_to_error(rel, e))
    }

    /// Metadata for the root directory itself. `metadata(".")` cannot answer
    /// this: the component walk drops `.` and is then left with no leaf, which
    /// is a bad request rather than a stat of the directory.
    pub fn stat(&self) -> Result<rustix::fs::Stat> {
        rustix::fs::fstat(&self.dir)
            .map_err(|e| errno_to_error(Path::new("."), e))
    }

    /// Set the root directory's own timestamps.
    pub fn set_times(&self, times: &rustix::fs::Timestamps) -> Result<()> {
        rustix::fs::futimens(&self.dir, times)
            .map_err(|e| errno_to_error(Path::new("."), e))
    }

    /// Metadata for `rel` without following a symlink at the leaf.
    pub fn metadata(&self, rel: impl AsRef<Path>) -> Result<rustix::fs::Stat> {
        let rel = rel.as_ref();
        let (parent, name) = self.parent_of(rel)?;
        rustix::fs::statat(&parent, name.as_os_str(), rustix::fs::AtFlags::SYMLINK_NOFOLLOW)
            .map_err(|e| errno_to_error(rel, e))
    }

    /// Whether anything at all is at `rel`, a dangling symlink included.
    pub fn exists(&self, rel: impl AsRef<Path>) -> bool {
        self.metadata(rel).is_ok()
    }

    /// Unlink a file, or with `dir` an empty directory.
    pub fn remove(&self, rel: impl AsRef<Path>, dir: bool) -> Result<()> {
        let rel = rel.as_ref();
        let (parent, name) = self.parent_of(rel)?;
        let flags = if dir {
            rustix::fs::AtFlags::REMOVEDIR
        } else {
            rustix::fs::AtFlags::empty()
        };
        rustix::fs::unlinkat(&parent, name.as_os_str(), flags)
            .map_err(|e| errno_to_error(rel, e))
    }

    /// Rename inside the root, or into another root's directory.
    pub fn rename_to(&self, rel: impl AsRef<Path>, dest: &Root, dest_rel: impl AsRef<Path>) -> Result<()> {
        let rel = rel.as_ref();
        let dest_rel = dest_rel.as_ref();
        let (from_dir, from_name) = self.parent_of(rel)?;
        let (to_dir, to_name) = dest.parent_of(dest_rel)?;
        rustix::fs::renameat(&from_dir, from_name.as_os_str(), &to_dir, to_name.as_os_str())
            .map_err(|e| errno_to_error(rel, e))
    }

    /// The names directly under the root, in whatever order the filesystem
    /// gives them, with `.` and `..` dropped.
    pub fn read_dir(&self) -> Result<Vec<PathBuf>> {
        //: A fresh descriptor, because reading the directory moves a shared
        //: offset and the root is long lived.
        let dup = self
            .dir
            .as_fd()
            .try_clone_to_owned()
            .map_err(|e| Error::io("dup root", e))?;
        let mut iter = rustix::fs::Dir::read_from(&dup)
            .map_err(|e| errno_to_error(Path::new("."), e))?;
        let mut out = Vec::new();
        while let Some(entry) = iter.read() {
            let entry = entry.map_err(|e| errno_to_error(Path::new("."), e))?;
            let name = entry.file_name().to_bytes();
            if name == b"." || name == b".." {
                continue;
            }
            out.push(PathBuf::from(std::ffi::OsString::from_vec(name.to_vec())));
        }
        Ok(out)
    }
}

/// A rustix errno turned into the shared error, keeping the number so the UI
/// can still tell EACCES from EROFS. ELOOP and ENOTDIR at a component we
/// asked not to follow mean a symlink appeared where a directory was, which
/// is a refusal rather than a failure.
fn errno_to_error(rel: &Path, e: rustix::io::Errno) -> Error {
    match e {
        rustix::io::Errno::LOOP => Error::Escapes(rel.display().to_string()),
        other => Error::io(
            rel.display().to_string(),
            std::io::Error::from_raw_os_error(other.raw_os_error()),
        ),
    }
}
