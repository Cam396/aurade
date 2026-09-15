#!/usr/bin/env python3
"""A real directory, expressed in the AuraDE port vocabulary.

This deliberately speaks the same shapes as
`ui/file_manager/file_manager/aurade/port/types.ts` rather than inventing its
own: EntryDto, Metadata, Volume and EntryPage. The prototype has been drawing a
hardcoded list, which hides everything that goes wrong with real data. Reading a
real directory through the real vocabulary means the eventual TypeScript wiring
is a swap of this one module, not a redesign of the view.

Two things are borrowed exactly from the port and are not incidental:

- A key is not a path. `FileKey` is branded in TypeScript precisely so a POSIX
  path cannot be passed where a key belongs, because ChromeOS cannot address
  Recent, Trash, Drive, MTP or an archive by path. Here it is a `file://` URL
  for the same reason: it is an opaque identity that happens to be resolvable.
- Metadata is separate from the entry and fetched for a whole page at once,
  because ChromeOS resolves it through several asynchronous providers.
"""
from __future__ import annotations

import errno
import mimetypes
import os
import re
import shutil
import stat

# ---------------------------------------------------------------- entries ----

def as_file_key(path: str) -> str:
    """The stand-in for FileKey. Opaque to the view by contract."""
    return "file://" + os.path.abspath(path)


def key_path(key: str) -> str:
    return key[len("file://"):] if key.startswith("file://") else key


def list_dir(path: str, show_hidden: bool = False, page_size: int = 0) -> dict:
    """One EntryPage. `revision` is the directory mtime, which is the cheapest
    honest answer: it changes when the listing changes, which is what the
    revision is for."""
    parent = as_file_key(path)
    entries = []
    # os.scandir raises here on a missing or unreadable directory, deliberately.
    with os.scandir(path) as it:
        for e in it:
            if not show_hidden and e.name.startswith("."):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            try:
                is_link = e.is_symlink()
            except OSError:
                is_link = False
            link_target = None
            if is_link:
                try:
                    link_target = os.readlink(e.path)
                except OSError:
                    link_target = None
            entries.append({
                "key": as_file_key(e.path),
                "name": e.name,
                "isDirectory": is_dir,
                "isLink": is_link,
                "linkTarget": link_target,
                #: A link whose far end is gone. Files cannot put one in an
                #: archive and asks before leaving it out, so the page has
                #: to know which rows those are before it starts.
                "broken": bool(is_link and not os.path.exists(e.path)),
                "parent": parent,
            })
    # Folders first, then case-insensitive by name. This is the view's default
    # sort and belongs here only because the port has no opinion on order.
    entries.sort(key=lambda x: (not x["isDirectory"], x["name"].lower()))
    done = True
    if page_size and len(entries) > page_size:
        entries, done = entries[:page_size], False
    try:
        revision = int(os.stat(path).st_mtime_ns)
    except OSError:
        revision = 0
    return {"revision": revision, "entries": entries, "done": done}


def metadata(keys) -> dict:
    """A MetadataSnapshot: one batched call for the whole page, never per file."""
    out = {}
    for key in keys:
        p = key_path(key)
        try:
            st = os.lstat(p)
        except OSError:
            out[key] = {}
            continue
        meta = {"modificationTime": int(st.st_mtime * 1000)}
        if not stat.S_ISDIR(st.st_mode):
            meta["size"] = st.st_size
            guessed = mimetypes.guess_type(p)[0]
            if guessed:
                meta["mimeType"] = guessed
        is_link = stat.S_ISLNK(st.st_mode)
        meta["isLink"] = is_link
        link_target = None
        if is_link:
            try:
                link_target = os.readlink(p)
            except OSError:
                link_target = None
        meta["linkTarget"] = link_target
        meta["hidden"] = os.path.basename(p).startswith(".")
        try:
            parent = os.path.dirname(p) or "."
            meta["readonly"] = (not os.access(p, os.W_OK)) or (
                not os.access(parent, os.W_OK))
        except Exception:
            meta["readonly"] = False
        try:
            meta["onDisk"] = int(getattr(st, "st_blocks", 0)) * 512
        except Exception:
            meta["onDisk"] = 0
        out[key] = meta
    return out


def readlink(path: str) -> str:
    """Target of a symlink, never followed. Raises FileNotFoundError."""
    p = key_path(path) if path.startswith("file://") else path
    try:
        return os.readlink(p)
    except FileNotFoundError:
        raise
    except OSError as e:
        raise FileNotFoundError(str(e) or p) from e


def is_under_trash(path: str, trash_dir: str) -> bool:
    """True when path lives inside trash_dir, via realpath prefix compare."""
    try:
        p = key_path(path) if path.startswith("file://") else path
        t = key_path(trash_dir) if trash_dir.startswith("file://") else trash_dir
        rp = os.path.realpath(p)
        rt = os.path.realpath(t)
        return rp == rt or rp.startswith(rt + os.sep)
    except Exception:
        return False


def xattr_set(path: str, name: str, value: str) -> bool:
    """Write one xattr. An empty value removes it. False on any refusal."""
    try:
        p = key_path(path) if path.startswith("file://") else path
    except Exception:
        return False
    raw = value.encode("utf-8")
    try:
        if value == "":
            try:
                os.removexattr(p, name, follow_symlinks=False)  # type: ignore[call-arg]
            except TypeError:
                os.removexattr(p, name)
            return True
        try:
            os.setxattr(p, name, raw, follow_symlinks=False)  # type: ignore[call-arg]
        except TypeError:
            os.setxattr(p, name, raw)
        return True
    except OSError as exc:
        # No such attribute is the expected answer when clearing an unset tag.
        clearing = (value == "")
        gone = exc.errno in (errno.ENODATA,
                             getattr(errno, "ENOATTR", errno.ENODATA))
        return clearing and gone
    except Exception:
        return False


def xattr_list(path: str) -> dict:
    """Best effort xattr names to string values. Returns {} on any error."""
    try:
        p = key_path(path) if path.startswith("file://") else path
    except Exception:
        return {}
    try:
        try:
            names = os.listxattr(p, follow_symlinks=False)  # type: ignore[call-arg]
        except TypeError:
            names = os.listxattr(p)
    except Exception:
        return {}
    out = {}
    for name in names:
        try:
            try:
                val = os.getxattr(p, name, follow_symlinks=False)  # type: ignore[call-arg]
            except TypeError:
                val = os.getxattr(p, name)
        except Exception:
            continue
        try:
            out[name] = val.decode("utf-8", errors="replace") if isinstance(
                val, bytes) else val
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- volumes ----

_PURPOSE_DIRS = ("desktop", "downloads", "documents", "pictures", "music",
                 "videos")


def _disk_numbers(path: str) -> tuple:
    """Numeric (total, used, free) bytes via shutil.disk_usage, guarded."""
    try:
        u = shutil.disk_usage(path)
        return int(u.total), int(u.used), int(u.free)
    except Exception:
        return 0, 0, 0


def volumes(home: str) -> list:
    """The places this machine actually has, as Volume records.

    Only the ones that exist. A missing Music folder is not a Music place, and
    inventing one is the sort of thing that made the last design look fake.
    """
    out = []
    try:
        st = os.statvfs(home)
        capacity = {"total": st.f_blocks * st.f_frsize,
                    "free": st.f_bavail * st.f_frsize}
    except OSError:
        capacity = None
    out.append({
        "id": "local_root:home", "root": as_file_key(home),
        "label": "Home", "kind": "system", "removable": False,
        "readOnly": False, "capacity": capacity, "purpose": "home",
        "totalBytes": _disk_numbers(home)[0],
        "usedBytes": _disk_numbers(home)[1],
        "freeBytes": _disk_numbers(home)[2],
    })
    for purpose in _PURPOSE_DIRS:
        path = os.path.join(home, purpose.capitalize())
        if not os.path.isdir(path):
            continue
        _p_total, _p_used, _p_free = _disk_numbers(path)
        out.append({
            "id": f"local_root:{purpose.capitalize()}",
            "root": as_file_key(path),
            "label": purpose.capitalize(), "kind": "system",
            "removable": False, "readOnly": False,
            "capacity": None, "purpose": purpose,
            "totalBytes": _p_total, "usedBytes": _p_used,
            "freeBytes": _p_free,
        })
    trash = os.path.join(home, ".local", "share", "Trash")
    if os.path.isdir(trash):
        _trash_total, _trash_used, _trash_free = _disk_numbers(trash)
        out.append({
            "id": "trash", "root": as_file_key(trash), "label": "Trash",
            "kind": "trash", "removable": False, "readOnly": False,
            "capacity": None,
            "totalBytes": _trash_total, "usedBytes": _trash_used,
            "freeBytes": _trash_free,
        })
    out.extend(_mounts())
    return out


# Pseudo filesystems and the snap loop mounts are not places a person navigates
# to, and listing forty of them is how a sidebar stops being useful.
_SKIP_FS = {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2",
            "securityfs", "pstore", "bpf", "debugfs", "tracefs", "configfs",
            "fusectl", "mqueue", "hugetlbfs", "squashfs", "autofs", "binfmt_misc",
            "efivarfs", "ramfs", "overlay", "nsfs", "rpc_pipefs"}


#: The filesystems that are somewhere else. Files calls these Network
#: locations and gives them their own widget and their own context menu, and
#: what makes one is the protocol rather than the path: a 9p share from the
#: host and a mounted SMB share are the same kind of place.
_NET_FS = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "9p", "afs", "davfs",
           "fuse.sshfs", "fuse.davfs", "fuse.gvfsd-fuse", "fuse.rclone",
           "ncpfs", "coda", "afpfs"}

#: Mounts that are a network filesystem by protocol and not a place a person
#: goes: the driver share WSL mounts for its own use is plumbing.
_NET_SKIP = ("/usr/lib/wsl", "/run/", "/proc/", "/sys/")


#: A source that names a place rather than a device: a UNC path, a drive
#: letter, or a `user@host:/path` the way sshfs writes one.
_REMOTE = re.compile(r"^(\\\\|//|[A-Za-z]:\\|[^/\s]+@[^/\s]+:)")


def _unescape(field: str) -> str:
    """/proc/mounts writes a space, a tab, a newline and a backslash in octal.

    Left as they come, a share mounted at `/mnt/Design Team` reads as
    `/mnt/Design\\040Team` and opens nothing.
    """
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def network_mounts() -> list:
    """The network locations this machine has mounted, as Volume records.

    Read from the kernel's own table and nothing else. No `statvfs` and no
    `listdir`: a network mount whose far end has gone away blocks the caller
    uninterruptibly, and a widget that hangs the build is worse than a widget
    that does not say how full the share is. Files makes the same choice, and
    shows its space bar only for a location that already reported its size.
    """
    out, seen = [], set()
    try:
        with open("/proc/mounts") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, point, fstype = _unescape(parts[0]), _unescape(parts[1]), parts[2]
        if fstype not in _NET_FS or point in seen:
            continue
        if point.startswith(_NET_SKIP):
            continue
        seen.add(point)
        #: The name is the far end, not the near one. `/mnt/c` says "c" and
        #: `C:\` says which machine's disk this is, which is the thing a
        #: person picked when they mounted it.
        label = dev if _REMOTE.match(dev) else (
            os.path.basename(point.rstrip("/")) or point)
        out.append({
            "id": f"network:{point}", "root": as_file_key(point),
            "label": label, "kind": "network", "removable": False,
            "readOnly": "ro" in parts[3].split(",") if len(parts) > 3 else False,
            "capacity": None, "source": dev, "protocol": fstype,
        })
    return sorted(out, key=lambda v: v["label"].lower())


def _mounts() -> list:
    """Real block device mounts, as Volume records."""
    seen, out = set(), []
    try:
        with open("/proc/mounts") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, point, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype in _SKIP_FS or not dev.startswith("/dev/"):
            continue
        if dev.startswith("/dev/loop") or point.startswith("/snap"):
            continue
        if dev in seen:
            continue
        seen.add(dev)
        removable = point.startswith(("/media", "/run/media", "/mnt"))
        try:
            st = os.statvfs(point)
            capacity = {"total": st.f_blocks * st.f_frsize,
                        "free": st.f_bavail * st.f_frsize}
        except OSError:
            capacity = None
        label = os.path.basename(point.rstrip("/")) or "System"
        _m_total, _m_used, _m_free = _disk_numbers(point)
        out.append({
            "id": f"mount:{dev}", "root": as_file_key(point),
            "label": "System (/)" if point == "/" else label,
            "kind": "removable" if removable else "system",
            "removable": removable, "readOnly": "ro" in parts[3].split(",") if len(parts) > 3 else False,
            "capacity": capacity,
            "totalBytes": _m_total, "usedBytes": _m_used,
            "freeBytes": _m_free,
        })
    return out


if __name__ == "__main__":
    import json, sys
    target = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    page = list_dir(target)
    meta = metadata([e["key"] for e in page["entries"]])
    print(json.dumps({"page": page, "metadata": meta,
                      "volumes": volumes(os.path.expanduser("~"))},
                     indent=1)[:1200])


# ------------------------------------------------------- wave C helpers ----

_SNAP_MAX_ENTRIES = 50000
_RECENT_MAX_SCAN = 100000
_DEPTH_HARD_CAP = 6


def snapshot(root, depth=1):
    """Map relpath -> (mtime_ns, size) under root, lstat only.

    Never follows symlinks. Symlinked dirs are listed but not descended.
    Unreadable dirs are skipped silently. depth is clamped to 6 hard.
    Stops at 50000 entries; the returned dict simply stops growing.
    """
    out = {}
    try:
        top = os.path.abspath(root)
    except Exception:
        return out
    try:
        eff = int(depth)
    except Exception:
        eff = 1
    if eff < 0:
        eff = 0
    if eff > _DEPTH_HARD_CAP:
        eff = _DEPTH_HARD_CAP
    if eff == 0:
        return out
    try:
        stack = [(top, 0)]
    except Exception:
        return out
    while stack:
        cur, lvl = stack.pop()
        if lvl >= eff:
            continue
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError:
            continue
        except Exception:
            continue
        for e in entries:
            if len(out) >= _SNAP_MAX_ENTRIES:
                return out
            try:
                rel = os.path.relpath(e.path, top)
            except Exception:
                continue
            try:
                st = os.lstat(e.path)
            except OSError:
                continue
            except Exception:
                continue
            try:
                out[rel] = (int(st.st_mtime_ns), int(st.st_size))
            except Exception:
                continue
            if lvl + 1 < eff:
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                except Exception:
                    is_dir = False
                if is_dir:
                    stack.append((e.path, lvl + 1))
    return out


def diff_snapshots(old, new):
    """Diff two snapshot dicts into sorted added/removed/changed lists.

    changed means the path is in both but (mtime_ns, size) differs.
    Never raises on ordinary dict input; bad input yields empty lists.
    """
    try:
        o = dict(old) if old else {}
    except Exception:
        o = {}
    try:
        n = dict(new) if new else {}
    except Exception:
        n = {}
    try:
        o_keys = set(o.keys())
    except Exception:
        return {"added": [], "removed": [], "changed": []}
    try:
        n_keys = set(n.keys())
    except Exception:
        return {"added": [], "removed": [], "changed": []}
    try:
        added = sorted([k for k in n_keys if k not in o_keys])
    except Exception:
        added = []
    try:
        removed = sorted([k for k in o_keys if k not in n_keys])
    except Exception:
        removed = []
    changed = []
    try:
        for k in sorted(o_keys & n_keys):
            try:
                if tuple(o[k]) != tuple(n[k]):
                    changed.append(k)
            except Exception:
                try:
                    if o[k] != n[k]:
                        changed.append(k)
                except Exception:
                    continue
    except Exception:
        changed = []
    return {"added": added, "removed": removed, "changed": changed}


def query_trash(trash_dir):
    """Count and size the trashed files. Never raises.

    Sums lstat sizes of regular files under <trash_dir>/files when that
    subdir exists, else under trash_dir itself. Missing dir gives zeros.
    Symlinks are never followed.
    """
    empty = {"count": 0, "bytes": 0}
    try:
        base = trash_dir
    except Exception:
        return dict(empty)
    try:
        if base is None:
            return dict(empty)
        base = os.fspath(base)
    except Exception:
        return dict(empty)
    try:
        files_dir = os.path.join(base, "files")
        try:
            is_d = os.path.isdir(files_dir)
        except Exception:
            is_d = False
        top = files_dir if is_d else base
        if not os.path.isdir(top):
            return dict(empty)
    except Exception:
        return dict(empty)
    count, total = 0, 0
    try:
        stack = [top]
    except Exception:
        return dict(empty)
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError:
            continue
        except Exception:
            continue
        for e in entries:
            try:
                st = os.lstat(e.path)
            except OSError:
                continue
            except Exception:
                continue
            try:
                is_dir = stat.S_ISDIR(st.st_mode)
            except Exception:
                is_dir = False
            if is_dir:
                try:
                    stack.append(e.path)
                except Exception:
                    continue
                continue
            try:
                is_reg = stat.S_ISREG(st.st_mode)
            except Exception:
                is_reg = False
            if is_reg:
                count += 1
                try:
                    total += int(st.st_size)
                except Exception:
                    continue
            else:
                try:
                    is_lnk = stat.S_ISLNK(st.st_mode)
                except Exception:
                    is_lnk = False
                if is_lnk:
                    count += 1
                    try:
                        total += int(st.st_size)
                    except Exception:
                        continue
    return {"count": int(count), "bytes": int(total)}


def mksymlink(target, link):
    """Create a symlink at link pointing at target. Returns link as str.

    Raises FileExistsError when link already exists (lexists), raises
    FileNotFoundError when target is missing or itself dangling (no
    dangling links are created), raises PermissionError when the parent
    dir of link is not writable. Never follows symlinks for the checks.
    """
    t = os.fspath(target) if not isinstance(target, str) else target
    l = os.fspath(link) if not isinstance(link, str) else link
    if os.path.lexists(l):
        raise FileExistsError(l)
    if not os.path.lexists(t):
        raise FileNotFoundError(t)
    if not os.path.exists(t):
        raise FileNotFoundError(t)
    try:
        parent = os.path.dirname(os.path.abspath(l)) or "."
    except Exception:
        parent = "."
    try:
        if not os.path.isdir(parent):
            raise FileNotFoundError(parent)
    except (FileNotFoundError, PermissionError):
        raise
    except Exception:
        pass
    try:
        writable = os.access(parent, os.W_OK | os.X_OK)
    except Exception:
        writable = True
    if not writable:
        raise PermissionError(parent)
    os.symlink(t, l)
    return l


def recent_files(root, limit=50, max_depth=6, include_hidden=False):
    """Newest regular files under root, newest first. Never follows symlinks.

    Files only via lstat (symlinks, dirs, and specials excluded). Hidden
    names are skipped unless include_hidden is True (hidden dirs are then
    also descended). Scan stops after 100000 visited entries. Returns at
    most limit dicts with path, mtime_ns, and size.
    """
    try:
        top = os.path.abspath(root)
    except Exception:
        return []
    try:
        lim = int(limit)
    except Exception:
        lim = 50
    if lim <= 0:
        return []
    try:
        md = int(max_depth)
    except Exception:
        md = _DEPTH_HARD_CAP
    if md < 0:
        md = 0
    if md > _DEPTH_HARD_CAP:
        md = _DEPTH_HARD_CAP
    found = []
    scanned = 0
    try:
        stack = [(top, 0)]
    except Exception:
        return []
    stop = False
    while stack and not stop:
        cur, lvl = stack.pop()
        if lvl > md:
            continue
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError:
            continue
        except Exception:
            continue
        for e in entries:
            scanned += 1
            if scanned > _RECENT_MAX_SCAN:
                stop = True
                break
            try:
                name = e.name
            except Exception:
                continue
            if not include_hidden and name.startswith("."):
                continue
            try:
                st = os.lstat(e.path)
            except OSError:
                continue
            except Exception:
                continue
            try:
                is_reg = stat.S_ISREG(st.st_mode)
            except Exception:
                is_reg = False
            if is_reg:
                try:
                    found.append({
                        "path": e.path,
                        "mtime_ns": int(st.st_mtime_ns),
                        "size": int(st.st_size),
                    })
                except Exception:
                    continue
                continue
            try:
                is_dir = stat.S_ISDIR(st.st_mode)
            except Exception:
                is_dir = False
            if is_dir and lvl < md:
                if not include_hidden and name.startswith("."):
                    continue
                try:
                    stack.append((e.path, lvl + 1))
                except Exception:
                    continue
    try:
        found.sort(key=lambda d: d.get("mtime_ns", 0), reverse=True)
    except Exception:
        pass
    try:
        return found[:lim]
    except Exception:
        return []
