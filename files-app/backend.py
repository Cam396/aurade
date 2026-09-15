#!/usr/bin/env python3
"""AuraDE Files backend for the proto export. Localhost only, always.

Wraps localfs (volumes, listing, metadata) and adds the mutating
operations the static export cannot do: mkdir, rename, trash, restore,
copy, move, plus search and hashing. Speaks JSON over HTTP so the page
can fetch it; CORS is open because this socket never leaves 127.0.0.1
and binding any other interface is refused outright.

Trash follows the freedesktop spec: ~/.local/share/Trash/files plus
info, with Path as a percent encoded file URI and DeletionDate in UTC.
Supports copy and move conflict modes, read only volume enforcement,
ENOSPC preflight, permanent delete endpoints, and errno in errors.
Wave C adds threaded serving, copy/move jobs with progress and cancel,
archive compress/extract, trash query and restore-all, symlinks,
streaming hashes, thumbnails, upgraded search, xattr and recent.
"""
import datetime as _dt
import base64 as _b64
import errno as _errno
import io as _io
import hashlib as _hl
import json as _json
import os as _os
import shutil as _shutil
import stat as _statmod
import subprocess as _subprocess
import sys as _sys
import tarfile as _tarfile
import tempfile as _tempfile
import threading as _threading
import time as _time
import urllib.parse as _up
import uuid as _uuid
import zipfile as _zipfile
import zlib as _zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_sys.path.insert(0, _HERE)
import localfs

HOST = "127.0.0.1"
PORT = 8902
_HASH_MAX = 2 * 1024 * 1024 * 1024
_HASH_CHUNK = 1024 * 1024
_HASH_ALGOS = ("md5", "sha1", "sha256", "sha384", "sha512", "crc32")
_PREVIEW_MAX_BYTES = 8192
_PREVIEW_MAX_CHARS = 2000
_SEARCH_MAX = 300
_SEARCH_DEPTH = 5
_SEARCH_HARD_MAX = 2000
_SEARCH_HARD_DEPTH = 12
_CONTENT_MAX = 256 * 1024
_RECENT_DEPTH = 6
_JOBS_MAX = 50
_FORBIDDEN_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/snap")


class _Raw(object):
    def __init__(self, data, ctype):
        self.data = data
        self.ctype = ctype


_JOBS = {}
_JOBS_LOCK = _threading.Lock()
_JOBS_ORDER = []


class _Err(Exception):
    def __init__(self, code, message, err_no=None):
        super().__init__(message)
        self.code = code
        self.message = message
        if err_no is None:
            if code == 404:
                err_no = _errno.ENOENT
            elif code == 409:
                err_no = _errno.EEXIST
            else:
                err_no = _errno.EINVAL
        self.err_no = err_no


def _abs(path):
    ap = _os.path.abspath(localfs.key_path(path or ""))
    for prefix in _FORBIDDEN_PREFIXES:
        if ap == prefix or ap.startswith(prefix + "/"):
            raise _Err(400, f"refusing {prefix} tree")
    return ap


def _trash_dirs():
    base = _os.path.join(_os.path.expanduser("~"), ".local", "share", "Trash")
    files = _os.path.join(base, "files")
    info = _os.path.join(base, "info")
    _os.makedirs(files, exist_ok=True)
    _os.makedirs(info, exist_ok=True)
    return files, info


def _numbered(name, n):
    """`report (2).pdf`, which is what Windows and the Rust backend both make
    of a name that is taken. It was `report.pdf.1`, which loses the extension
    and every association that hangs off it, and disagreed with the other
    backend about what the same copy is called."""
    dot = name.rfind(".")
    if dot > 0:
        return f"{name[:dot]} ({n}){name[dot:]}"
    return f"{name} ({n})"


def _unique(parent, name):
    cand = _os.path.join(parent, name)
    if not _os.path.lexists(cand):
        return cand
    i = 2
    while True:
        cand = _os.path.join(parent, _numbered(name, i))
        if not _os.path.lexists(cand):
            return cand
        i += 1


def _volume_for(path):
    ap = _os.path.abspath(path)
    best = None
    best_len = -1
    try:
        vols = localfs.volumes(_os.path.expanduser("~"))
    except Exception:
        return None
    for v in vols:
        try:
            root = localfs.key_path(v.get("root", ""))
        except Exception:
            continue
        if not root:
            continue
        rp = _os.path.abspath(root)
        if ap == rp or ap.startswith(rp + "/"):
            if len(rp) > best_len:
                best = v
                best_len = len(rp)
    return best


def _check_writable(path):
    v = _volume_for(path)
    if v is not None and v.get("readOnly"):
        raise _Err(403, f"read only volume: {path}", _errno.EROFS)


def _typed_names(body, srcs):
    """The names typed in the conflict dialog: a body object from source
    path to the name it should land under, lined up with srcs. A name that
    is not one path component, or for a path not among the sources, is a
    400: nothing is moved on a request the page and the backend disagree
    about."""
    raw = (body or {}).get("names")
    names = [None] * len(srcs)
    if raw is None:
        return names
    if not isinstance(raw, dict):
        raise _Err(400, "names must map each path to a name")
    for key, name in raw.items():
        if not isinstance(name, str) or not name or name in (".", "..") \
                or "/" in name or "\0" in name:
            raise _Err(400, f"{name!r} is not a name")
        path = _abs(key)
        if path not in srcs:
            raise _Err(400, f"{key} is not among the paths")
        names[srcs.index(path)] = name
    return names


def _leaf_for(src, names, i):
    """Where a source lands: the typed name where there is one, its own
    otherwise."""
    typed = names[i] if names and i < len(names) else None
    return typed or _os.path.basename(src.rstrip("/"))


def _conflict_asked(q, body, default="keep-both"):
    """The conflict rule from the query string or the body, whichever the
    caller used. The Rust backend reads both; this one read only the query,
    so a page that put `conflict` in the body of a copy was quietly answered
    with the default and every Replace existing became a second copy."""
    asked = dict(q or {})
    if body and body.get("conflict"):
        asked["conflict"] = body["conflict"]
    if not asked.get("conflict"):
        asked["conflict"] = default
    return _conflict_mode(asked)


def _conflict_mode(q):
    raw = ((q or {}).get("conflict") or "keep-both").strip().lower()
    raw = raw.replace("_", "-").replace(" ", "-")
    if raw in ("fail-if-exists", "fail", "none"):
        return "fail-if-exists"
    if raw == "skip":
        return "skip"
    if raw in ("replace", "replace-existing"):
        return "replace"
    if raw in ("keep-both", "keepboth", "keep-both-new-name",
               "generate-new-name", ""):
        return "keep-both"
    raise _Err(400, "unknown conflict mode: " + raw)


def _resolve_dest(dst, conflict):
    exists = _os.path.lexists(dst)
    if not exists:
        return ("proceed", dst)
    if conflict == "keep-both":
        return ("proceed", _unique(_os.path.dirname(dst),
                                   _os.path.basename(dst)))
    if conflict == "replace":
        return ("proceed", dst)
    if conflict == "skip":
        return ("skip", dst)
    raise _Err(409, f"already exists: {dst}", _errno.EEXIST)


def _remove_for_replace(dst):
    if not _os.path.lexists(dst):
        return
    if _os.path.isdir(dst) and not _os.path.islink(dst):
        _shutil.rmtree(dst)
    else:
        _os.unlink(dst)


def _tree_size(path):
    try:
        if _os.path.islink(path):
            return 0
        if not _os.path.isdir(path):
            return _os.path.getsize(path)
    except OSError:
        return 0
    total = 0
    for root, _dirs, files in _os.walk(path, followlinks=False):
        for n in files:
            fp = _os.path.join(root, n)
            try:
                if not _os.path.islink(fp):
                    total += _os.path.getsize(fp)
            except OSError:
                continue
    return total


def _dest_free(dest):
    v = _volume_for(dest)
    if v is not None:
        cap = v.get("capacity")
        if isinstance(cap, dict) and cap.get("free") is not None:
            return cap["free"]
    try:
        st = _os.statvfs(dest if _os.path.isdir(dest) else
                          _os.path.dirname(dest) or "/")
        return st.f_bavail * st.f_frsize
    except OSError:
        return None


def _preflight_space(srcs, dest):
    need = 0
    for s in srcs:
        need += _tree_size(s)
    free = _dest_free(dest)
    if free is not None and need > free:
        raise _Err(400, f"ENOSPC: need {need} bytes but only "
                   f"{free} free at {dest}", _errno.ENOSPC)


def _job_evict_locked():
    while len(_JOBS) > _JOBS_MAX:
        oldest = None
        for jid in list(_JOBS_ORDER):
            j = _JOBS.get(jid)
            if j is not None and j.get("done"):
                oldest = jid
                break
        if oldest is None:
            break
        _JOBS.pop(oldest, None)
        try:
            _JOBS_ORDER.remove(oldest)
        except ValueError:
            pass


def _job_create(total):
    jid = _uuid.uuid4().hex
    job = {"id": jid, "done": False, "processed": 0, "total": total,
           "copied": [], "error": None, "cancel": False,
           "cancelled": False, "created": _time.time()}
    with _JOBS_LOCK:
        _JOBS[jid] = job
        _JOBS_ORDER.append(jid)
        _job_evict_locked()
    return job


def _job_snapshot(jid):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j is None:
            return None
        return {"done": j["done"], "processed": j["processed"],
                "total": j["total"], "copied": list(j["copied"]),
                "error": j["error"], "cancelled": j.get("cancelled", False)}


def _job_run_copy(jid, srcs, dest, conflict, names=None):
    with _JOBS_LOCK:
        job = _JOBS.get(jid)
    if job is None:
        return
    try:
        for i, src in enumerate(srcs):
            with _JOBS_LOCK:
                if job.get("cancel"):
                    job["cancelled"] = True
                    job["done"] = True
                    if job["error"] is None:
                        job["error"] = {"error": "cancelled",
                                        "errno": 125}
                    break
            try:
                out = _copy_one(src, _os.path.join(
                    dest, _leaf_for(src, names, i)), conflict)
            except _Err as e:
                with _JOBS_LOCK:
                    job["error"] = {"error": e.message,
                                    "errno": e.err_no}
                    job["done"] = True
                break
            except OSError as e:
                with _JOBS_LOCK:
                    job["error"] = {
                        "error": e.strerror or type(e).__name__,
                        "errno": getattr(e, "errno", None) or _errno.EIO}
                    job["done"] = True
                break
            with _JOBS_LOCK:
                if out is not None:
                    job["copied"].append(out)
                job["processed"] += 1
                if job["processed"] >= job["total"] and not job["done"]:
                    job["done"] = True
    finally:
        with _JOBS_LOCK:
            if not job["done"]:
                job["done"] = True


def _job_run_move(jid, srcs, dest, conflict, names=None):
    with _JOBS_LOCK:
        job = _JOBS.get(jid)
    if job is None:
        return
    try:
        for i, src in enumerate(srcs):
            with _JOBS_LOCK:
                if job.get("cancel"):
                    job["cancelled"] = True
                    job["done"] = True
                    if job["error"] is None:
                        job["error"] = {"error": "cancelled",
                                        "errno": 125}
                    break
            try:
                dst = _os.path.join(dest, _leaf_for(src, names, i))
                action, final = _resolve_dest(dst, conflict)
                if action == "skip":
                    with _JOBS_LOCK:
                        job["processed"] += 1
                        if job["processed"] >= job["total"]:
                            job["done"] = True
                    continue
                dst = final
                if conflict == "replace":
                    _remove_for_replace(dst)
                _shutil.move(src, dst)
                out = dst
            except _Err as e:
                with _JOBS_LOCK:
                    job["error"] = {"error": e.message,
                                    "errno": e.err_no}
                    job["done"] = True
                break
            except OSError as e:
                with _JOBS_LOCK:
                    job["error"] = {
                        "error": e.strerror or type(e).__name__,
                        "errno": getattr(e, "errno", None) or _errno.EIO}
                    job["done"] = True
                break
            with _JOBS_LOCK:
                job["copied"].append(out)
                job["processed"] += 1
                if job["processed"] >= job["total"] and not job["done"]:
                    job["done"] = True
    finally:
        with _JOBS_LOCK:
            if not job["done"]:
                job["done"] = True


def _trash_encode(src):
    return "file://" + _up.quote(src, safe="/")


def _trash_decode(val):
    if val.startswith("file://"):
        return _up.unquote(val[len("file://"):])
    return _up.unquote(val) if "%" in val else val


def _trash_utc_now():
    return _dt.datetime.now(_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00")


def _desktop_entry(path):
    """Exec, Path and Name out of a .desktop file, or {} for anything else.

    Only the [Desktop Entry] group, and only the first value for each key,
    because a later group repeating Exec is a different action and not this
    launcher's target.
    """
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            in_entry = False
            for line in fh:
                line = line.strip()
                if line.startswith("["):
                    if in_entry:
                        break
                    in_entry = line == "[Desktop Entry]"
                    continue
                if not in_entry or "=" not in line or line.startswith("#"):
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key in ("Exec", "Path", "Name", "Icon") and key not in out:
                    out[key] = val.strip()
    except OSError:
        return {}
    return out


def _link(path):
    """Where a shortcut points, for the Shortcut properties tab.

    Two shapes count as a shortcut on Linux: a symlink, and a .desktop file.
    Anything else gets an empty dict, which is how the caller knows not to
    offer the tab at all.
    """
    if _os.path.islink(path):
        try:
            target = _os.readlink(path)
        except OSError:
            return {}
        full = target if _os.path.isabs(target) else _os.path.normpath(
            _os.path.join(_os.path.dirname(path), target))
        return {"linkKind": "symlink", "linkTarget": target,
                "linkResolved": full, "linkArgs": "",
                "linkWorkingDir": _os.path.dirname(full),
                "linkBroken": not _os.path.exists(full)}
    if path.endswith(".desktop"):
        entry = _desktop_entry(path)
        exec_line = entry.get("Exec", "")
        if not exec_line:
            return {}
        parts = exec_line.split(" ", 1)
        prog = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        return {"linkKind": "desktop", "linkTarget": prog,
                "linkResolved": _shutil.which(prog) or prog,
                "linkArgs": args,
                "linkWorkingDir": entry.get("Path", ""),
                "linkBroken": not (_shutil.which(prog)
                                   or _os.path.exists(prog))}
    return {}


def _stat(path):
    st = _os.lstat(path)
    return {
        "size": None if _statmod.S_ISDIR(st.st_mode) else st.st_size,
        "onDisk": st.st_blocks * 512,
        "created": int(st.st_ctime * 1000),
        "accessed": int(st.st_atime * 1000),
        "modified": int(st.st_mtime * 1000),
        "mode": oct(_statmod.S_IMODE(st.st_mode)),
        "uid": st.st_uid,
        "isDirectory": _statmod.S_ISDIR(st.st_mode),
        **_link(path),
    }


#: What the Security tab needs: who owns the file, which group it belongs to
#: and what the mode bits say. The same shape the Rust backend answers with,
#: so the page has one reader rather than two. `acl` is null here because
#: this backend does not read POSIX access control lists; null says "not
#: answered", which is not the same as an empty list saying "none set".
def _symbolic(mode):
    """`rwxr-xr-x`, with the special bits where they change a letter."""
    out = []
    for shift, special, upper, lower in ((6, 0o4000, "S", "s"),
                                         (3, 0o2000, "S", "s"),
                                         (0, 0o1000, "T", "t")):
        bits = (mode >> shift) & 0o7
        out.append("r" if bits & 0o4 else "-")
        out.append("w" if bits & 0o2 else "-")
        if bits & 0o1:
            out.append(lower if mode & special else "x")
        else:
            out.append(upper if mode & special else "-")
    return "".join(out)


def _name_of(uid, table, attr):
    try:
        return getattr(table.getpwuid(uid) if attr == "pw_name"
                       else table.getgrgid(uid), attr)
    except (KeyError, OSError):
        return None


def api_props(q, _body):
    path = _abs((q or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    try:
        st = _os.lstat(path)
    except OSError as e:
        raise _Err(404, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.ENOENT)
    import grp as _grp
    import pwd as _pwd
    mode = _statmod.S_IMODE(st.st_mode)
    return {
        "path": path,
        "uid": st.st_uid,
        "gid": st.st_gid,
        "user": _name_of(st.st_uid, _pwd, "pw_name"),
        "group": _name_of(st.st_gid, _grp, "gr_name"),
        "mode": mode,
        "symbolic": _symbolic(mode),
        "acl": None,
        "link": None,
        "isDirectory": _statmod.S_ISDIR(st.st_mode),
    }


def api_chmod(_q, body):
    path = _abs((body or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    mode = (body or {}).get("mode")
    if not isinstance(mode, int):
        raise _Err(400, "mode is required")
    try:
        #: Not on the link itself: there is no lchmod, and the mode of a
        #: symlink means nothing.
        _os.chmod(path, mode & 0o7777)
        st = _os.lstat(path)
    except OSError as e:
        raise _Err(403, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EACCES)
    return {"path": path, "mode": _statmod.S_IMODE(st.st_mode)}


def api_volumes(_q, _body):
    return {"volumes": localfs.volumes(_os.path.expanduser("~"))}


def api_list(q, _body):
    path = _abs(q.get("path", _os.path.expanduser("~")))
    show = q.get("hidden", "") == "1"
    try:
        page = localfs.list_dir(path, show_hidden=show)
    except OSError as e:
        raise _Err(404, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.ENOENT)
    return {"path": path, "revision": page["revision"],
            "entries": page["entries"],
            "meta": localfs.metadata([e["key"] for e in page["entries"]])}


def api_stat(q, _body):
    path = _abs(q.get("path", ""))
    if not path:
        raise _Err(400, "path required")
    try:
        return {"path": path, **_stat(path)}
    except OSError as e:
        raise _Err(404, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.ENOENT)


def api_search(q, _body):
    root = _abs(q.get("root", _os.path.expanduser("~")))
    needle = (q.get("q") or "").lower()
    if not needle:
        raise _Err(400, "q required")
    try:
        depth_lim = int(q.get("depth", "") or _SEARCH_DEPTH)
    except ValueError:
        raise _Err(400, "bad depth")
    try:
        lim = int(q.get("limit", "") or _SEARCH_MAX)
    except ValueError:
        raise _Err(400, "bad limit")
    if depth_lim < 0 or lim < 0:
        raise _Err(400, "bad depth or limit")
    if depth_lim > _SEARCH_HARD_DEPTH:
        depth_lim = _SEARCH_HARD_DEPTH
    if lim > _SEARCH_HARD_MAX:
        lim = _SEARCH_HARD_MAX
    if lim == 0:
        lim = _SEARCH_MAX
    show_hidden = (q.get("hidden", "") == "1")
    content = q.get("content")
    if content == "":
        content = None
    out = []

    def walk(dirpath, depth):
        if len(out) >= lim or depth > depth_lim:
            return
        try:
            with _os.scandir(dirpath) as it:
                entries = list(it)
        except OSError:
            return
        for e in entries:
            if len(out) >= lim:
                return
            if e.name.startswith(".") and not show_hidden:
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            name_hit = needle in e.name.lower()
            content_hit = False
            if content is not None and not is_dir:
                try:
                    st = _os.lstat(e.path)
                    if not _statmod.S_ISDIR(st.st_mode) and \
                            st.st_size <= _CONTENT_MAX:
                        with open(e.path, "rb") as fh:
                            data = fh.read(_CONTENT_MAX + 1)
                        text = data.decode("utf-8", errors="ignore")
                        if content in text:
                            content_hit = True
                except OSError:
                    content_hit = False
            if name_hit or content_hit:
                out.append({"key": localfs.as_file_key(e.path),
                            "name": e.name, "isDirectory": is_dir})
            if is_dir:
                walk(e.path, depth + 1)

    walk(root, 0)
    return {"root": root, "results": out}


def _hash_one(path, algo):
    if algo == "crc32":
        crc = 0
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_HASH_CHUNK)
                if not chunk:
                    break
                crc = _zlib.crc32(chunk, crc)
        return format(crc & 0xFFFFFFFF, "08x")
    h = _hl.new(algo)
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def api_hash(q, _body):
    path = _abs(q.get("path", ""))
    algo = ((q or {}).get("algo") or "").strip().lower()
    if algo:
        if algo not in _HASH_ALGOS:
            raise _Err(400, "unknown algo: " + algo)
        try:
            size = _os.path.getsize(path)
        except OSError as e:
            raise _Err(404, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.ENOENT)
        if size > _HASH_MAX:
            raise _Err(413, "file too large to hash in this export",
                       _errno.EFBIG)
        try:
            hexv = _hash_one(path, algo)
        except OSError as e:
            raise _Err(404, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.ENOENT)
        return {"algo": algo, "hex": hexv}
    try:
        size = _os.path.getsize(path)
    except OSError as e:
        raise _Err(404, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.ENOENT)
    if size > _HASH_MAX:
        raise _Err(413, "file too large to hash in this export",
                   _errno.EFBIG)
    md5, sha1, sha256 = _hl.md5(), _hl.sha1(), _hl.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                md5.update(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
    except OSError as e:
        raise _Err(404, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.ENOENT)
    return {"path": path, "md5": md5.hexdigest(),
            "sha1": sha1.hexdigest(), "sha256": sha256.hexdigest()}


def api_preview(q, _body):
    path = _abs(q.get("path", ""))
    if not path:
        raise _Err(400, "path required")
    try:
        if _os.path.isdir(path):
            raise _Err(400, "is a directory")
        with open(path, "rb") as fh:
            head = fh.read(_PREVIEW_MAX_BYTES)
    except OSError as e:
        raise _Err(404, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.ENOENT)
    if b"\x00" in head:
        return {"path": path, "binary": True, "text": "",
                "truncated": False}
    try:
        text = head.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            text = head.decode("utf-8", errors="replace")
            if text.count("\ufffd") > max(1, len(text) // 10):
                return {"path": path, "binary": True, "text": "",
                        "truncated": False}
        except Exception:
            return {"path": path, "binary": True, "text": "",
                    "truncated": False}
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    truncated = len(text) > _PREVIEW_MAX_CHARS
    if truncated:
        text = text[:_PREVIEW_MAX_CHARS]
    return {"path": path, "binary": False, "text": text,
            "truncated": truncated}


def api_mkdir(_q, body):
    path = _abs((body or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    _check_writable(path)
    if _os.path.lexists(path):
        raise _Err(409, "already exists")
    try:
        _os.makedirs(path)
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    return {"path": path}


def api_mkfile(_q, body):
    path = _abs((body or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    _check_writable(path)
    if _os.path.lexists(path):
        raise _Err(409, "already exists")
    try:
        with open(path, "x"):
            pass
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    return {"path": path}


def api_rename(q, body):
    """Rename one item, with the collision rule the caller asked for.

    Files renames one item with `FailIfExists` and a whole selection with
    `GenerateUniqueName`, so a rename endpoint that can only do one of the
    two cannot serve both. The default stays the strict one: a rename that
    would land on a name already taken is a question, and answering it by
    inventing a name is the wrong answer to give without being asked.
    """
    body = body or {}
    src = _abs(body.get("path", ""))
    name = (body.get("name") or "").strip().strip("/")
    if not src or not name or "/" in name:
        raise _Err(400, "path and plain name required")
    if not _os.path.lexists(src):
        raise _Err(404, "not found")
    _check_writable(src)
    dst = _os.path.join(_os.path.dirname(src), name)
    _check_writable(dst)
    conflict = _conflict_asked(q, body, default="fail-if-exists")
    action, dst = _resolve_dest(dst, conflict)
    if action == "skip":
        return {"path": src, "skipped": True}
    if conflict == "replace" and _os.path.lexists(dst) and dst != src:
        _remove_for_replace(dst)
    try:
        _os.rename(src, dst)
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    return {"path": dst}


def _relocate(src, dst):
    try:
        _os.rename(src, dst)
    except OSError as e:
        if getattr(e, "errno", None) != 18:
            raise
        _shutil.move(src, dst)


def api_trash(_q, body):
    paths = (body or {}).get("paths") or []
    if not paths:
        raise _Err(400, "paths required")
    files, info = _trash_dirs()
    done = []
    for raw in paths:
        src = _abs(raw)
        if not _os.path.lexists(src):
            raise _Err(404, f"not found: {src}")
        _check_writable(src)
        target = _unique(files, _os.path.basename(src.rstrip("/")))
        try:
            _relocate(src, target)
        except OSError as e:
            raise _Err(400, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.EIO)
        iname = _os.path.basename(target) + ".trashinfo"
        with open(_os.path.join(info, iname), "w") as fh:
            fh.write("[Trash Info]\n"
                     f"Path={_trash_encode(src)}\n"
                     "DeletionDate=" + _trash_utc_now() + "\n")
        done.append({"from": src, "trashedAs": _os.path.basename(target)})
    return {"trashed": done}


def _trash_entries():
    files, info = _trash_dirs()
    out = []
    try:
        names = _os.listdir(files)
    except OSError:
        return out
    for name in names:
        orig, date = "", ""
        ipath = _os.path.join(info, name + ".trashinfo")
        try:
            with open(ipath) as fh:
                for line in fh.read().splitlines():
                    if line.startswith("Path="):
                        orig = _trash_decode(line[len("Path="):])
                    elif line.startswith("DeletionDate="):
                        date = line[len("DeletionDate="):]
        except OSError:
            pass
        out.append({"name": name, "originalPath": orig, "date": date})
    return out



#: Thumbnails are capped hard on both ends: the file we are willing to open,
#: and the box we scale into. A file manager preview is a glance, not a viewer,
#: and an uncapped decode is how a 900 megapixel TIFF takes the daemon down.
_THUMB_MAX_BYTES = 40 * 1024 * 1024
_THUMB_BOX = 512
_THUMB_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".ico", ".avif",
})
_PDF_EXTS = frozenset({".pdf"})
_VIDEO_EXTS = frozenset({
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".ogv",
})
#: Both helpers are bounded. A malformed file that makes poppler or ffmpeg sit
#: there is a hung request otherwise, and this daemon is single purpose enough
#: that one stuck worker is felt immediately.
_TOOL_TIMEOUT = 12


def _run_to_png(argv, out_dir, stem):
    """Run a converter that writes into out_dir, and return the PNG it made.

    The tools disagree about the exact output name (pdftoppm appends the page
    number), so the file is found rather than predicted.
    """
    try:
        proc = _subprocess.run(argv, cwd=out_dir, timeout=_TOOL_TIMEOUT,
                               stdout=_subprocess.DEVNULL,
                               stderr=_subprocess.DEVNULL, check=False)
    except (OSError, _subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        pass  # some tools report failure and still write a usable frame
    for entry in sorted(_os.listdir(out_dir)):
        if entry.startswith(stem) and entry.lower().endswith(".png"):
            return _os.path.join(out_dir, entry)
    return None


def _first_page_png(path, out_dir):
    """Page one of a PDF, as a file in out_dir."""
    tool = _shutil.which("pdftoppm")
    if not tool:
        return None
    return _run_to_png(
        [tool, "-png", "-f", "1", "-l", "1", "-r", "72", path, "page"],
        out_dir, "page")


def _video_frame_png(path, out_dir):
    """One frame from a video, as a file in out_dir.

    A second in, because the first frame of a great many videos is black.
    """
    tool = _shutil.which("ffmpeg")
    if not tool:
        return None
    return _run_to_png(
        [tool, "-nostdin", "-loglevel", "error", "-ss", "1", "-i", path,
         "-frames:v", "1", "-f", "image2", "frame.png"],
        out_dir, "frame")


def api_thumb_cache_clear(_q, _body):
    """Empty the XDG thumbnail cache.

    Scoped hard on purpose: only regular files, only one level down inside
    the known size directories, and symlinks are unlinked rather than
    followed, so nothing outside the cache can be reached from inside it.
    """
    base = _os.path.join(
        _os.environ.get("XDG_CACHE_HOME") or _os.path.expanduser("~/.cache"),
        "thumbnails")
    sizes = ("normal", "large", "x-large", "xx-large", "fail")
    removed = 0
    freed = 0
    for size in sizes:
        d = _os.path.join(base, size)
        if not _os.path.isdir(d):
            continue
        try:
            names = _os.listdir(d)
        except OSError:
            continue
        for name in names:
            p = _os.path.join(d, name)
            try:
                st = _os.lstat(p)
                if not (_statmod.S_ISREG(st.st_mode) or _statmod.S_ISLNK(st.st_mode)):
                    continue
                _os.unlink(p)
                removed += 1
                freed += st.st_size
            except OSError:
                continue
    return {"removed": removed, "bytes": freed, "path": base}


#: File tags. The truth for one file is the freedesktop xattr, so a tag
#: survives a move and is readable by anything else on this system. The index
#: exists only to answer "what is tagged Blue" without walking the disk, and
#: it is treated as a cache: every path is checked before it is returned.
_TAGS_ATTR = "user.xdg.tags"


def _tags_index_path():
    base = _os.environ.get("XDG_DATA_HOME") or _os.path.expanduser("~/.local/share")
    return _os.path.join(base, "aurade", "filetags.json")


def _tags_index_read():
    try:
        with open(_tags_index_path(), "r", encoding="utf-8") as fh:
            data = _json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _tags_index_write(data):
    p = _tags_index_path()
    try:
        _os.makedirs(_os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            _json.dump(data, fh)
        _os.replace(tmp, p)
        return True
    except OSError:
        return False


def _tags_read(path):
    raw = localfs.xattr_list(path).get(_TAGS_ATTR, "")
    return [t for t in (s.strip() for s in str(raw).split(",")) if t]


def api_tags_get(q, _body):
    path = _abs((q or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    if not _os.path.lexists(path):
        raise _Err(404, "not found")
    return {"path": path, "tags": _tags_read(path)}


def api_tags_set(_q, body):
    body = body or {}
    path = _abs(body.get("path", ""))
    if not path:
        raise _Err(400, "path required")
    if not _os.path.lexists(path):
        raise _Err(404, "not found")
    tags = body.get("tags")
    if not isinstance(tags, list):
        raise _Err(400, "tags must be a list")
    clean = []
    for t in tags:
        t = str(t).strip()
        #: A comma is the separator, so it cannot be inside a name.
        if t and "," not in t and t not in clean:
            clean.append(t)
    ok = localfs.xattr_set(path, _TAGS_ATTR, ",".join(clean))
    idx = _tags_index_read()
    for name in list(idx.keys()):
        paths = [p for p in idx.get(name, []) if p != path]
        if paths:
            idx[name] = paths
        else:
            del idx[name]
    for name in clean:
        idx.setdefault(name, []).append(path)
    _tags_index_write(idx)
    return {"path": path, "tags": clean, "stored": ok}


def api_tags_all(_q, _body):
    """Every tagged path the index knows, minus the ones that went away."""
    idx = _tags_index_read()
    out = {}
    dirty = False
    for name, paths in idx.items():
        live = [p for p in paths if _os.path.lexists(p)]
        if len(live) != len(paths):
            dirty = True
        if live:
            out[name] = live
    if dirty:
        _tags_index_write(out)
    return {"tags": out}


def api_tags_list(q, _body):
    """Everything carrying one tag, in the shape /api/list returns.

    This is what makes a tag in the sidebar a place you can open rather than a
    label. The index says which paths to look at; each one is stat'd here, so
    a file that moved or went away is dropped rather than listed.
    """
    tag = (q or {}).get("tag", "").strip()
    if not tag:
        raise _Err(400, "tag required")
    idx = _tags_index_read()
    entries = []
    for path in idx.get(tag, []):
        try:
            st = _os.lstat(path)
        except OSError:
            continue
        is_link = _statmod.S_ISLNK(st.st_mode)
        try:
            is_dir = _os.path.isdir(path)
        except OSError:
            is_dir = False
        link_target = None
        if is_link:
            try:
                link_target = _os.readlink(path)
            except OSError:
                link_target = None
        entries.append({
            "key": localfs.as_file_key(path),
            "name": _os.path.basename(path) or path,
            "isDirectory": is_dir,
            "isLink": is_link,
            "linkTarget": link_target,
            "parent": localfs.as_file_key(_os.path.dirname(path)),
        })
    entries.sort(key=lambda x: (not x["isDirectory"], x["name"].lower()))
    return {"path": "tag:" + tag, "revision": 0, "tag": tag,
            "entries": entries,
            "meta": localfs.metadata([e["key"] for e in entries])}


#: Git. The reference reads a repository through libgit2 and shows two things
#: with it: the branch in the status bar, and per file state in the details
#: view. Both come from one request here, because both change at the same
#: moment, and both are answered by asking git rather than parsing .git.
_GIT_TIMEOUT = 5
_GIT_MAX_ENTRIES = 5000
#: Worst first. A folder is shown with the strongest state anything under it
#: is in, which is what makes a collapsed tree still tell the truth.
_GIT_RANK = ["U", "D", "A", "R", "M", "?"]


def _git_root(path):
    """The repository a path is in, or an empty string."""
    root = path if _os.path.isdir(path) else _os.path.dirname(path)
    while True:
        if _os.path.exists(_os.path.join(root, ".git")):
            return root
        parent = _os.path.dirname(root)
        if parent == root:
            return ""
        root = parent


def _git_run(root, args):
    try:
        out = _subprocess.run(["git", "-C", root] + args, capture_output=True,
                              text=True, timeout=_GIT_TIMEOUT)
    except (OSError, _subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def _git_code(xy):
    """One porcelain XY pair reduced to the single letter shown in a column."""
    if "U" in xy or xy in ("AA", "DD"):
        return "U"
    if xy == "??":
        return "?"
    for ch in xy:
        if ch in ("M", "A", "D", "R", "C"):
            return "R" if ch == "C" else ch
    return "M"


def api_git_checkout(_q, body):
    """Switch branches, which is what the reference's flyout does.

    Local only. Nothing here reaches the network: pull, push and sync are the
    reference's other three git commands and they are deliberately not here.
    Git refuses a checkout that would overwrite uncommitted work, and that
    refusal is passed back rather than forced.
    """
    body = body or {}
    path = _abs(body.get("path", ""))
    branch = str(body.get("branch", "")).strip()
    if not path or not branch:
        raise _Err(400, "path and branch required")
    #: A branch name is handed to git as an argument, so it has to be a name
    #: and not an option or a path.
    if (branch.startswith("-") or ".." in branch or
            any(c in branch for c in " \t\n:?*[~^\\")):
        raise _Err(400, "bad branch name")
    root = _git_root(path)
    if not root:
        raise _Err(400, "not a repository")
    _check_writable(root)
    try:
        out = _subprocess.run(["git", "-C", root, "checkout", branch],
                              capture_output=True, text=True,
                              timeout=_GIT_TIMEOUT)
    except (OSError, _subprocess.SubprocessError) as e:
        raise _Err(500, str(e) or "git failed")
    if out.returncode != 0:
        raise _Err(409, (out.stderr or "checkout failed").strip().split("\n")[0])
    head = _git_run(root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    return {"root": root, "branch": head}


def api_git(q, _body):
    path = _abs((q or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    root = _git_root(path)
    if not root:
        return {"repo": False, "path": path}
    head = _git_run(root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if head == "HEAD":
        head = _git_run(root, ["rev-parse", "--short", "HEAD"]).strip()
    ahead = behind = 0
    counts = _git_run(root, ["rev-list", "--left-right", "--count",
                             "@{upstream}...HEAD"]).split()
    if len(counts) == 2:
        try:
            behind, ahead = int(counts[0]), int(counts[1])
        except ValueError:
            behind = ahead = 0
    branches = [b.strip() for b in
                _git_run(root, ["branch", "--format=%(refname:short)"]
                         ).splitlines() if b.strip()][:50]
    #: Statuses arrive relative to the repository root and NUL separated, so a
    #: name with a space or a newline in it survives the trip.
    raw = _git_run(root, ["status", "--porcelain=v1", "-z",
                          "--untracked-files=all"])
    status = {}
    fields = [f for f in raw.split("\0") if f]
    i = 0
    seen = 0
    while i < len(fields) and seen < _GIT_MAX_ENTRIES:
        field = fields[i]
        i += 1
        if len(field) < 4:
            continue
        xy, rel = field[:2], field[3:]
        #: A rename spends a second field on where it came from.
        if "R" in xy or "C" in xy:
            i += 1
        seen += 1
        code = _git_code(xy)
        full = _os.path.join(root, rel.rstrip("/"))
        #: The row that shows this state is the one in the folder being
        #: listed, so a change deep in a tree is carried up to whichever
        #: child of that folder contains it.
        if not full.startswith(path.rstrip("/") + "/"):
            continue
        first = _os.path.relpath(full, path).split(_os.sep)[0]
        if first in (".", ".."):
            continue
        target = _os.path.join(path, first)
        old = status.get(target)
        if old is None or _GIT_RANK.index(code) < _GIT_RANK.index(old):
            status[target] = code
    return {"repo": True, "path": path, "root": root, "branch": head,
            "ahead": ahead, "behind": behind, "branches": branches,
            "status": status}


#: A folder's own icon. The Windows original points at a resource inside a
#: DLL and lists what is in it; there is no such file here, so the sources are
#: the app's own drawn glyphs and any image on disk. Which one is in use is
#: written on the folder itself, as an xattr, so it travels with the folder
#: and needs no database to stay true.
_ICON_ATTR = "user.aurade.icon"
_ICON_MAX = 512


def _icon_read(path):
    raw = localfs.xattr_list(path).get(_ICON_ATTR, "")
    return str(raw).strip()


def _icon_valid(value):
    """glyph:<key> or file:<absolute path>, and nothing else.

    The value is written by this app and read back by the page, so the shape
    is fixed here rather than trusted from either end.
    """
    if value == "":
        return True
    if len(value) > _ICON_MAX or "\n" in value or "\x00" in value:
        return False
    if value.startswith("glyph:"):
        key = value[6:]
        return bool(key) and all(c.isalnum() or c in "._-" for c in key)
    if value.startswith("file:"):
        path = value[5:]
        return path.startswith("/") and ".." not in path.split("/")
    return False


def api_icon_get(q, _body):
    path = _abs((q or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    if not _os.path.lexists(path):
        raise _Err(404, "not found")
    return {"path": path, "icon": _icon_read(path)}


def api_icon_set(_q, body):
    body = body or {}
    path = _abs(body.get("path", ""))
    if not path:
        raise _Err(400, "path required")
    if not _os.path.lexists(path):
        raise _Err(404, "not found")
    _check_writable(path)
    icon = str(body.get("icon", "")).strip()
    if not _icon_valid(icon):
        raise _Err(400, "bad icon")
    ok = localfs.xattr_set(path, _ICON_ATTR, icon)
    return {"path": path, "icon": icon, "stored": ok}


def api_icon_dir(q, _body):
    """Every custom icon in one folder, so a list costs one request.

    Only the entries that carry one are returned, which keeps the answer
    small for the ordinary folder where none of them do.
    """
    path = _abs((q or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    if not _os.path.isdir(path):
        raise _Err(400, "not a directory")
    try:
        names = _os.listdir(path)
    except OSError as e:
        raise _Err(404, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.ENOENT)
    out = {}
    for name in names:
        full = _os.path.join(path, name)
        value = _icon_read(full)
        if value:
            out[full] = value
    return {"path": path, "icons": out}


#: Mica. The window backdrop is the desktop wallpaper, blurred past the point
#: of legibility and tinted, so the surface picks up the colour of what is
#: behind the window without ever showing it. The sample is tiny on purpose:
#: at 64 pixels wide, upscaled and blurred, it is indistinguishable from the
#: full image and costs a few kilobytes instead of a few megabytes.
_WALL_SAMPLE_W = 64
_WALL_MAX_BYTES = 64 * 1024 * 1024


def _wallpaper_candidates():
    """Where a wallpaper might be, most specific first."""
    home = _os.path.expanduser("~")
    env = _os.environ.get("AURADE_WALLPAPER", "").strip()
    if env:
        yield env
    conf = _os.path.join(
        _os.environ.get("XDG_CONFIG_HOME") or _os.path.join(home, ".config"),
        "aurade", "wallpaper")
    try:
        if _os.path.isfile(conf):
            with open(conf, "r", encoding="utf-8", errors="replace") as fh:
                line = fh.readline().strip()
            if line:
                yield line
    except OSError:
        pass
    #: The desktop's own setting, when there is a desktop to ask. Guarded and
    #: time limited, because a missing or hung gsettings must not stall a
    #: request that has a perfectly good answer without it.
    for argv in (["gsettings", "get", "org.gnome.desktop.background",
                  "picture-uri-dark"],
                 ["gsettings", "get", "org.gnome.desktop.background",
                  "picture-uri"]):
        try:
            out = _subprocess.run(argv, capture_output=True, timeout=3,
                                  text=True)
        except (OSError, _subprocess.SubprocessError):
            continue
        val = (out.stdout or "").strip().strip("'\"")
        if val:
            yield val


def _wallpaper_path():
    for cand in _wallpaper_candidates():
        p = cand
        if p.startswith("file://"):
            p = _up.unquote(p[7:])
        p = _os.path.expanduser(p)
        if _os.path.isfile(p):
            return p
    return ""


def api_wallpaper(_q, _body):
    """A tiny blurred sample of the desktop wallpaper, for the Mica backdrop."""
    path = _wallpaper_path()
    if not path:
        return {"found": False, "reason": "no wallpaper set"}
    try:
        if _os.path.getsize(path) > _WALL_MAX_BYTES:
            return {"found": False, "reason": "too large"}
    except OSError:
        return {"found": False, "reason": "unreadable"}
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        return {"found": False, "reason": "no imaging library"}
    try:
        with Image.open(path) as im:
            w, h = im.size
            im = im.convert("RGB")
            sh = max(1, round(_WALL_SAMPLE_W * h / max(1, w)))
            im = im.resize((_WALL_SAMPLE_W, sh), Image.LANCZOS)
            #: A light blur on the sample as well as in CSS, so the upscale
            #: has nothing hard left in it to alias against.
            im = im.filter(ImageFilter.GaussianBlur(1.2))
            buf = _io.BytesIO()
            im.save(buf, "JPEG", quality=82)
    except Exception as exc:
        return {"found": False, "reason": type(exc).__name__}
    raw = buf.getvalue()
    return {
        "found": True,
        "path": path,
        "width": w,
        "height": h,
        "sample_width": _WALL_SAMPLE_W,
        "bytes": len(raw),
        "uri": "data:image/jpeg;base64," + _b64.b64encode(raw).decode(),
    }


def api_system(_q, _body):
    """What this machine is, for the About page. Read, never assumed."""
    os_name = ""
    try:
        with open("/etc/os-release", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"')
                    break
    except OSError:
        pass
    un = _os.uname()
    return {
        "os": os_name or un.sysname,
        "kernel": un.release,
        "arch": un.machine,
        "host": un.nodename,
        # Where Home is, for the page: it no longer assumes the build
        # machine's. The Rust service answers the same key.
        "home": _os.path.expanduser("~"),
    }


def api_thumb(q, _body):
    """One downscaled image, as a data URI.

    A data URI rather than raw bytes because every other route here speaks
    JSON and the page is under Trusted Types: handing back a string the caller
    puts in `img.src` needs no new response plumbing and no blob lifetime to
    manage. The cost is a third more bytes on the wire, which at a 512 pixel
    box is a few tens of kilobytes.

    Returns `supported: False` rather than an error for anything it will not
    decode, because "no thumbnail" is a normal answer for most files and the
    caller should not have to tell it apart from a failure.
    """
    path = _abs(q.get("path", ""))
    if not path:
        raise _Err(400, "path required")
    ext = _os.path.splitext(path)[1].lower()
    if ext not in _THUMB_EXTS and ext not in _PDF_EXTS \
            and ext not in _VIDEO_EXTS:
        return {"path": path, "supported": False, "reason": "not an image"}
    try:
        if _os.path.isdir(path):
            raise _Err(400, "is a directory")
        size = _os.path.getsize(path)
    except OSError as e:
        raise _Err(404, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.ENOENT)
    if size > _THUMB_MAX_BYTES:
        return {"path": path, "supported": False, "reason": "too large"}
    try:
        from PIL import Image
    except ImportError:
        return {"path": path, "supported": False, "reason": "no decoder"}

    # A PDF and a video are not images, so something else has to turn them into
    # one first. The rest of the path is then identical, which is the point:
    # one endpoint, one contract, whatever the caller is looking at.
    tmp = None
    source = path
    kind = "image"
    try:
        if ext in _PDF_EXTS or ext in _VIDEO_EXTS:
            tmp = _tempfile.mkdtemp(prefix="aurade-thumb-")
            made = (_first_page_png(path, tmp) if ext in _PDF_EXTS
                    else _video_frame_png(path, tmp))
            if not made:
                _shutil.rmtree(tmp, ignore_errors=True)
                return {"path": path, "supported": False,
                        "reason": "no converter"}
            source = made
            kind = "pdf" if ext in _PDF_EXTS else "video"
        return _thumb_from(path, source, size, kind)
    finally:
        if tmp:
            _shutil.rmtree(tmp, ignore_errors=True)


def _thumb_from(path, source, size, kind):
    from PIL import Image
    try:
        with Image.open(source) as im:
            im.draft("RGB", (_THUMB_BOX, _THUMB_BOX))
            w, h = im.size
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            im.thumbnail((_THUMB_BOX, _THUMB_BOX), Image.LANCZOS)
            buf = _io.BytesIO()
            if im.mode == "RGB":
                im.save(buf, "JPEG", quality=82, optimize=True)
                mime = "image/jpeg"
            else:
                im.save(buf, "PNG", optimize=True)
                mime = "image/png"
    except Exception as e:  # a corrupt file is not a server error
        return {"path": path, "supported": False,
                "reason": type(e).__name__.lower()}
    data = _b64.b64encode(buf.getvalue()).decode("ascii")
    return {"path": path, "supported": True, "mime": mime, "kind": kind,
            "width": w, "height": h,
            "thumb_width": im.size[0], "thumb_height": im.size[1],
            "bytes": size, "uri": f"data:{mime};base64,{data}"}


def api_trash_list(_q, _body):
    return {"entries": _trash_entries()}


def api_restore(_q, body):
    name = ((body or {}).get("name") or "").strip().strip("/")
    if not name or "/" in name:
        raise _Err(400, "trash name required")
    files, _info = _trash_dirs()
    src = _os.path.join(files, name)
    if not _os.path.lexists(src):
        raise _Err(404, "not in trash")
    orig = ""
    ipath = _os.path.join(_info, name + ".trashinfo")
    try:
        with open(ipath) as fh:
            for line in fh.read().splitlines():
                if line.startswith("Path="):
                    orig = _trash_decode(line[len("Path="):])
    except OSError:
        pass
    dst = _unique(_os.path.dirname(orig) if orig else _os.path.expanduser("~"),
                  _os.path.basename(orig or name)) if orig else \
        _unique(_os.path.expanduser("~"), name)
    _check_writable(dst)
    try:
        _os.makedirs(_os.path.dirname(dst), exist_ok=True)
        _relocate(src, dst)
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    try:
        _os.unlink(ipath)
    except OSError:
        pass
    return {"path": dst}


def _copy_one(src, dst, conflict="keep-both"):
    action, final = _resolve_dest(dst, conflict)
    if action == "skip":
        return None
    dst = final
    if conflict == "replace":
        _remove_for_replace(dst)
    if _os.path.isdir(src) and not _os.path.islink(src):
        if _os.path.lexists(dst):
            dst = _unique(_os.path.dirname(dst), _os.path.basename(dst))
        _shutil.copytree(src, dst, symlinks=True)
    else:
        if _os.path.isdir(dst) and not _os.path.islink(dst):
            inner = _os.path.join(dst, _os.path.basename(src))
            action2, final2 = _resolve_dest(inner, conflict)
            if action2 == "skip":
                return None
            dst = final2
            if conflict == "replace":
                _remove_for_replace(dst)
        _shutil.copy2(src, dst, follow_symlinks=False)
    return dst


def api_copy(q, body):
    body = body or {}
    paths = body.get("paths") or []
    dest = _abs(body.get("dest", ""))
    if not paths or not dest:
        raise _Err(400, "paths and dest required")
    if not _os.path.isdir(dest):
        raise _Err(404, "dest is not a folder")
    conflict = _conflict_asked(q, body)
    _check_writable(dest)
    srcs = [_abs(raw) for raw in paths]
    for src in srcs:
        if not _os.path.lexists(src):
            raise _Err(404, f"not found: {src}")
        real_src = _os.path.realpath(src)
        real_dest = _os.path.realpath(dest)
        if real_dest == real_src or real_dest.startswith(real_src + "/"):
            raise _Err(400, "cannot copy a folder into itself")
    _preflight_space(srcs, dest)
    names = _typed_names(body, srcs)
    if q is not None and "job" in q:
        job = _job_create(len(srcs))
        t = _threading.Thread(target=_job_run_copy,
                              args=(job["id"], srcs, dest, conflict, names),
                              daemon=True)
        t.start()
        return {"job": job["id"]}
    done = []
    for i, src in enumerate(srcs):
        try:
            out = _copy_one(src, _os.path.join(
                dest, _leaf_for(src, names, i)), conflict)
            if out is not None:
                done.append(out)
        except _Err:
            raise
        except OSError as e:
            raise _Err(400, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.EIO)
    return {"copied": done}


def api_move(q, body):
    body = body or {}
    paths = body.get("paths") or []
    dest = _abs(body.get("dest", ""))
    if not paths or not dest:
        raise _Err(400, "paths and dest required")
    if not _os.path.isdir(dest):
        raise _Err(404, "dest is not a folder")
    conflict = _conflict_asked(q, body)
    _check_writable(dest)
    srcs = [_abs(raw) for raw in paths]
    for src in srcs:
        if not _os.path.lexists(src):
            raise _Err(404, f"not found: {src}")
        _check_writable(src)
        real_src = _os.path.realpath(src)
        real_dest = _os.path.realpath(dest)
        if real_dest == real_src or real_dest.startswith(real_src + "/"):
            raise _Err(400, "cannot move a folder into itself")
    _preflight_space(srcs, dest)
    names = _typed_names(body, srcs)
    if q is not None and "job" in q:
        job = _job_create(len(srcs))
        t = _threading.Thread(target=_job_run_move,
                              args=(job["id"], srcs, dest, conflict, names),
                              daemon=True)
        t.start()
        return {"job": job["id"]}
    done = []
    for i, src in enumerate(srcs):
        dst = _os.path.join(dest, _leaf_for(src, names, i))
        action, final = _resolve_dest(dst, conflict)
        if action == "skip":
            continue
        dst = final
        if conflict == "replace":
            try:
                _remove_for_replace(dst)
            except OSError as e:
                raise _Err(400, e.strerror or type(e).__name__,
                           getattr(e, "errno", None) or _errno.EIO)
        try:
            _shutil.move(src, dst)
        except OSError as e:
            raise _Err(400, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.EIO)
        done.append(dst)
    return {"moved": done}


def _safe_unlink(path):
    if _os.path.isdir(path) and not _os.path.islink(path):
        _shutil.rmtree(path)
    else:
        _os.unlink(path)


def api_empty_trash(_q, _body):
    files, info = _trash_dirs()
    try:
        names = _os.listdir(files)
    except OSError:
        names = []
    done = []
    base_real = _os.path.realpath(files)
    info_real = _os.path.realpath(info)
    for name in names:
        if not name or name in (".", "..") or "/" in name:
            continue
        cand = _os.path.join(files, name)
        real = _os.path.realpath(cand)
        if real != base_real and not real.startswith(base_real + "/"):
            if real != cand and not cand.startswith(files + "/"):
                continue
        _check_writable(cand)
        try:
            _safe_unlink(cand)
        except OSError as e:
            raise _Err(400, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.EIO)
        ipath = _os.path.join(info, name + ".trashinfo")
        if _os.path.realpath(ipath).startswith(info_real + "/") or \
                _os.path.dirname(_os.path.realpath(ipath)) == info_real:
            try:
                _os.unlink(ipath)
            except OSError:
                pass
        done.append(name)
    return {"emptied": done}


def api_delete(q, body):
    body = body or {}
    policy = ((q or {}).get("policy") or body.get("policy") or "Always")
    policy = str(policy).strip()
    norm = policy.lower()
    if norm == "never":
        raise _Err(403, "delete refused by policy Never",
                   _errno.EACCES)
    if norm not in ("always", "permanentonly", "permanent-only",
                    "permanent_only"):
        raise _Err(400, "unknown policy: " + policy)
    paths = body.get("paths") or []
    if not paths:
        raise _Err(400, "paths required")
    done = []
    for raw in paths:
        src = _abs(raw)
        if not _os.path.lexists(src):
            raise _Err(404, f"not found: {src}")
        _check_writable(src)
        try:
            _safe_unlink(src)
        except OSError as e:
            raise _Err(400, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.EIO)
        done.append(src)
    return {"deleted": done}


def api_job_get(q, _body):
    jid = ((q or {}).get("id") or "").strip()
    if not jid:
        raise _Err(400, "id required")
    snap = _job_snapshot(jid)
    if snap is None:
        raise _Err(404, "no such job")
    return snap


def api_job_cancel(q, _body):
    jid = ((q or {}).get("id") or "").strip()
    if not jid:
        raise _Err(400, "id required")
    with _JOBS_LOCK:
        job = _JOBS.get(jid)
        if job is None:
            raise _Err(404, "no such job")
        job["cancel"] = True
        done = job["done"]
    return {"job": jid, "cancelled": True, "done": done}


def _strip_archive_suffix(dest, fmt):
    low = dest.lower()
    if fmt == "zip" and low.endswith(".zip"):
        return dest[:-4]
    if fmt == "tar" and low.endswith(".tar"):
        return dest[:-4]
    if fmt == "gztar":
        if low.endswith(".tar.gz"):
            return dest[:-7]
        if low.endswith(".tgz"):
            return dest[:-4]
    for suf in (".zip", ".tar.gz", ".tgz", ".tar"):
        if low.endswith(suf):
            return dest[:-len(suf)]
    return dest


def api_compress(_q, body):
    body = body or {}
    paths = body.get("paths") or []
    dest = (body.get("dest") or "").strip()
    fmt = ((body.get("format") or "").strip().lower())
    if fmt in ("gz-tar", "gz_tar"):
        fmt = "gztar"
    if fmt not in ("zip", "tar", "gztar"):
        raise _Err(400, "format must be zip, tar or gztar")
    if not paths or not dest:
        raise _Err(400, "paths and dest required")
    dest_abs = _abs(dest)
    _check_writable(dest_abs)
    srcs = [_abs(raw) for raw in paths]
    for src in srcs:
        if not _os.path.lexists(src):
            raise _Err(404, f"not found: {src}")
    try:
        parent = _os.path.dirname(dest_abs) or "/"
        _os.makedirs(parent, exist_ok=True)
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    base = _strip_archive_suffix(dest_abs, fmt)
    if fmt == "zip":
        actual = base + ".zip"
    elif fmt == "tar":
        actual = base + ".tar"
    else:
        actual = base + ".tar.gz"
    _check_writable(actual)
    tmp = _tempfile.mkdtemp(prefix="aurade-compress-")
    try:
        for src in srcs:
            name = _os.path.basename(src.rstrip("/")) or "item"
            target = _os.path.join(tmp, name)
            if _os.path.lexists(target):
                target = _unique(tmp, name)
            try:
                if _os.path.isdir(src) and not _os.path.islink(src):
                    _shutil.copytree(src, target, symlinks=True)
                else:
                    _shutil.copy2(src, target, follow_symlinks=False)
            except OSError as e:
                raise _Err(400, e.strerror or type(e).__name__,
                           getattr(e, "errno", None) or _errno.EIO)
        try:
            out = _shutil.make_archive(base, fmt, root_dir=tmp)
        except OSError as e:
            raise _Err(400, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.EIO)
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)
    return {"archive": out}


def api_extract(_q, body):
    body = body or {}
    archive = (body.get("archive") or "").strip()
    dest = (body.get("dest") or "").strip()
    password = body.get("password")
    if not archive or not dest:
        raise _Err(400, "archive and dest required")
    arch_abs = _abs(archive)
    dest_abs = _abs(dest)
    if not _os.path.isfile(arch_abs):
        raise _Err(404, f"not found: {arch_abs}")
    _check_writable(dest_abs)
    try:
        _os.makedirs(dest_abs, exist_ok=True)
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    #: The Extract dialog's Encoding row, for a zip whose names were written
    #: without the UTF-8 flag; absent or "default" reads them the zip way.
    encoding = _zip_encoding(body.get("encoding"))
    if (password is not None or encoding) and _zipfile.is_zipfile(arch_abs):
        try:
            pwd = None
            if password is not None:
                pwd = password.encode() if isinstance(password, str) \
                    else bytes(password)
            with _zipfile.ZipFile(arch_abs, metadata_encoding=encoding) as zf:
                zf.extractall(dest_abs, pwd=pwd if pwd else None)
        except RuntimeError as e:
            raise _Err(400, str(e) or "bad password")
        except OSError as e:
            raise _Err(400, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.EIO)
        return {"extracted": dest_abs, "archive": arch_abs}
    try:
        _shutil.unpack_archive(arch_abs, dest_abs)
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    except Exception as e:
        raise _Err(400, f"{type(e).__name__}: {e}")
    return {"extracted": dest_abs, "archive": arch_abs}


#: The encodings the Extract dialog lists after Default: the reference's
#: sixteen, by the label the page sends and the name it shows.
_ENCODINGS = [
    ("utf-8", "Unicode (UTF-8)"),
    ("shift_jis", "Japanese (Shift-JIS)"),
    ("gb18030", "Chinese Simplified (GB18030)"),
    ("big5", "Chinese Traditional (Big5)"),
    ("euc-kr", "Korean"),
    ("windows-1258", "Vietnamese (Windows)"),
    ("windows-874", "Thai (Windows)"),
    ("windows-1256", "Arabic (Windows)"),
    ("windows-1255", "Hebrew (Windows)"),
    ("windows-1254", "Turkish (Windows)"),
    ("windows-1252", "Western European (Windows)"),
    ("windows-1250", "Central European (Windows)"),
    ("windows-1251", "Cyrillic (Windows)"),
    ("windows-1253", "Greek (Windows)"),
    ("windows-1257", "Baltic (Windows)"),
    ("macintosh", "Western European (Mac)"),
]


def _zip_encoding(label):
    """The codec for an encoding label, or None for the default; a label
    nothing decodes is a 400 rather than quietly the default."""
    import codecs
    label = (label or "").strip()
    if not label or label.lower() == "default":
        return None
    try:
        return codecs.lookup(label.replace("windows-", "cp")
                             if label.lower().startswith("windows-")
                             else label).name
    except LookupError:
        raise _Err(400, f"unknown encoding: {label}")


def _zip_names(path):
    """What a zip says about its names: whether any is neither flagged UTF-8
    nor ASCII, and the guess for those, which here is UTF-8 when the bytes
    are valid UTF-8 and nothing otherwise."""
    if not _zipfile.is_zipfile(path):
        return {"undetermined": False, "detected": None}
    unflagged = []
    with _zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.flag_bits & 0x800:
                continue
            raw = info.filename.encode("cp437", "replace")
            if not raw.isascii():
                unflagged.append(raw)
    if not unflagged:
        return {"undetermined": False, "detected": None}
    try:
        for raw in unflagged:
            raw.decode("utf-8")
        detected = {"name": "utf-8", "label": "Unicode (UTF-8)"}
    except UnicodeDecodeError:
        detected = None
    return {"undetermined": True, "detected": detected}


def api_archive_list(q, _body):
    path = (q or {}).get("path", "")
    if not path:
        raise _Err(400, "path required")
    arch_abs = _abs(path)
    if not _os.path.isfile(arch_abs):
        raise _Err(404, f"not found: {arch_abs}")
    encoding = _zip_encoding((q or {}).get("encoding"))
    entries = []
    if _zipfile.is_zipfile(arch_abs):
        with _zipfile.ZipFile(arch_abs, metadata_encoding=encoding) as zf:
            for info in zf.infolist():
                entries.append({"name": info.filename,
                                "size": info.file_size,
                                "isDirectory": info.is_dir()})
    else:
        import tarfile
        try:
            with tarfile.open(arch_abs) as tf:
                for m in tf.getmembers():
                    entries.append({"name": m.name, "size": m.size,
                                    "isDirectory": m.isdir()})
        except (tarfile.TarError, OSError) as e:
            raise _Err(400, f"{type(e).__name__}: {e}")
    return {"entries": entries, "names": _zip_names(arch_abs)}


def api_archive_formats(_q, _body):
    try:
        unpack = [f[0] for f in _shutil.get_unpack_formats()]
    except Exception:
        unpack = []
    try:
        arch = [f[0] for f in _shutil.get_archive_formats()]
    except Exception:
        arch = []
    return {"unpack": unpack, "archive": arch,
            "encodings": [{"name": n, "label": l} for n, l in _ENCODINGS]}


def _trash_detail_list(drive=None):
    files, _info = _trash_dirs()
    try:
        names = _os.listdir(files)
    except OSError:
        return []
    items = []
    for name in names:
        if not name or name in (".", "..") or "/" in name:
            continue
        tpath = _os.path.join(files, name)
        orig, date = "", ""
        ipath = _os.path.join(_info, name + ".trashinfo")
        try:
            with open(ipath) as fh:
                for line in fh.read().splitlines():
                    if line.startswith("Path="):
                        orig = _trash_decode(line[len("Path="):])
                    elif line.startswith("DeletionDate="):
                        date = line[len("DeletionDate="):]
        except OSError:
            pass
        if drive and orig:
            if not (orig == drive or orig.startswith(drive + "/")):
                continue
        try:
            st = _os.lstat(tpath)
            size = 0 if _statmod.S_ISDIR(st.st_mode) else st.st_size
        except OSError:
            size = 0
        items.append({"name": name, "path": orig,
                      "deletionDate": date, "size": size})
    return items


def api_trash_query(q, _body):
    drive = ((q or {}).get("drive") or "").strip()
    drive_abs = _abs(drive) if drive else None
    items = _trash_detail_list(drive_abs)
    total = 0
    for it in items:
        try:
            total += int(it.get("size") or 0)
        except (TypeError, ValueError):
            continue
    return {"count": len(items), "bytes": total, "items": items}


def _restore_one(name):
    files, info = _trash_dirs()
    src = _os.path.join(files, name)
    if not _os.path.lexists(src):
        raise _Err(404, "not in trash")
    orig = ""
    ipath = _os.path.join(info, name + ".trashinfo")
    try:
        with open(ipath) as fh:
            for line in fh.read().splitlines():
                if line.startswith("Path="):
                    orig = _trash_decode(line[len("Path="):])
    except OSError:
        pass
    dst = _unique(_os.path.dirname(orig) if orig else _os.path.expanduser("~"),
                  _os.path.basename(orig or name)) if orig else \
        _unique(_os.path.expanduser("~"), name)
    _check_writable(dst)
    try:
        _os.makedirs(_os.path.dirname(dst), exist_ok=True)
        _relocate(src, dst)
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    try:
        _os.unlink(ipath)
    except OSError:
        pass
    return dst


def api_restore_all(_q, body):
    body = body or {}
    drive = (body.get("drive") or "").strip()
    drive_abs = _abs(drive) if drive else None
    items = _trash_detail_list(drive_abs)
    restored = []
    failed = []
    for it in items:
        name = it.get("name", "")
        try:
            dst = _restore_one(name)
            restored.append(dst)
        except _Err as e:
            failed.append({"name": name, "error": e.message})
        except OSError as e:
            failed.append({"name": name,
                           "error": e.strerror or type(e).__name__})
    return {"restored": restored, "failed": failed}


def api_mksymlink(q, body):
    body = body or {}
    target = (body.get("target") or "")
    link = (body.get("link") or "").strip()
    if not target or not link:
        raise _Err(400, "target and link required")
    if isinstance(target, str) and target.startswith("file://"):
        target = localfs.key_path(target)
    link_abs = _abs(link)
    parent = _os.path.dirname(link_abs) or "/"
    _check_writable(parent)
    if _os.path.lexists(link_abs):
        conflict = _conflict_mode(q or {})
        if conflict != "replace":
            raise _Err(409, f"already exists: {link_abs}",
                       _errno.EEXIST)
        try:
            _remove_for_replace(link_abs)
        except OSError as e:
            raise _Err(400, e.strerror or type(e).__name__,
                       getattr(e, "errno", None) or _errno.EIO)
    try:
        _os.makedirs(parent, exist_ok=True)
        _os.symlink(target, link_abs)
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    return {"link": link_abs, "target": target}


def api_thumbnail(q, _body):
    path = _abs((q or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    raw_size = ((q or {}).get("size") or "128").strip()
    try:
        size = int(raw_size)
    except ValueError:
        raise _Err(400, "bad size")
    if size not in (64, 128, 256):
        raise _Err(400, "size must be 64, 128 or 256")
    if not _os.path.isfile(path):
        raise _Err(404, "not found")
    try:
        from PIL import Image as _PILImage
    except ImportError:
        raise _Err(501, "no image backend", 38)
    try:
        with _PILImage.open(path) as im:
            im.load()
            has_alpha = ("A" in im.getbands() or
                         im.info.get("transparency") is not None)
            im.thumbnail((size, size))
            import io as _io
            buf = _io.BytesIO()
            if has_alpha:
                im.save(buf, format="PNG")
                return _Raw(buf.getvalue(), "image/png")
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(buf, format="JPEG")
            return _Raw(buf.getvalue(), "image/jpeg")
    except _Err:
        raise
    except OSError as e:
        raise _Err(400, e.strerror or type(e).__name__,
                   getattr(e, "errno", None) or _errno.EIO)
    except Exception as e:
        raise _Err(400, f"{type(e).__name__}: {e}")


def api_xattr(q, _body):
    path = _abs((q or {}).get("path", ""))
    if not path:
        raise _Err(400, "path required")
    if not _os.path.lexists(path):
        raise _Err(404, "not found")
    return {"path": path, "xattrs": localfs.xattr_list(path)}


def api_recent(q, _body):
    q = q or {}
    root = _abs(q.get("root", _os.path.expanduser("~")))
    try:
        lim = int(q.get("limit", "") or 50)
    except ValueError:
        raise _Err(400, "bad limit")
    if lim < 0:
        raise _Err(400, "bad limit")
    if lim > 200:
        lim = 200
    show_hidden = (q.get("hidden", "") == "1")
    found = []

    def walk(dirpath, depth):
        if depth > _RECENT_DEPTH:
            return
        try:
            with _os.scandir(dirpath) as it:
                entries = list(it)
        except OSError:
            return
        for e in entries:
            if e.name.startswith(".") and not show_hidden:
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                walk(e.path, depth + 1)
            else:
                try:
                    st = _os.lstat(e.path)
                    mtime = st.st_mtime
                except OSError:
                    continue
                found.append({"path": e.path, "name": e.name,
                              "modified": int(mtime * 1000)})

    walk(root, 0)
    found.sort(key=lambda r: r["modified"], reverse=True)
    return {"root": root, "recent": found[:lim]}


_ROUTES = {
    ("GET", "/api/health"): lambda q, b: {"ok": True, "backend": "aurade-files"},
    ("GET", "/api/system"): api_system,
    ("GET", "/api/wallpaper"): api_wallpaper,
    ("GET", "/api/git"): api_git,
    ("POST", "/api/git/checkout"): api_git_checkout,
    ("GET", "/api/icon"): api_icon_get,
    ("GET", "/api/icon/dir"): api_icon_dir,
    ("POST", "/api/icon"): api_icon_set,
    ("GET", "/api/tags"): api_tags_get,
    ("GET", "/api/tags/all"): api_tags_all,
    ("GET", "/api/tags/list"): api_tags_list,
    ("GET", "/api/volumes"): api_volumes,
    ("GET", "/api/list"): api_list,
    ("GET", "/api/stat"): api_stat,
    ("GET", "/api/props"): api_props,
    ("GET", "/api/search"): api_search,
    ("GET", "/api/hash"): api_hash,
    ("GET", "/api/preview"): api_preview,
    ("GET", "/api/thumb"): api_thumb,
    ("GET", "/api/trash/list"): api_trash_list,
    ("POST", "/api/thumb-cache/clear"): api_thumb_cache_clear,
    ("POST", "/api/tags"): api_tags_set,
    ("POST", "/api/mkdir"): api_mkdir,
    ("POST", "/api/mkfile"): api_mkfile,
    ("POST", "/api/rename"): api_rename,
    ("POST", "/api/chmod"): api_chmod,
    ("POST", "/api/trash"): api_trash,
    ("POST", "/api/restore"): api_restore,
    ("POST", "/api/copy"): api_copy,
    ("POST", "/api/move"): api_move,
    ("POST", "/api/empty-trash"): api_empty_trash,
    ("POST", "/api/delete"): api_delete,
    ("GET", "/api/job"): api_job_get,
    ("DELETE", "/api/job"): api_job_cancel,
    ("POST", "/api/extract"): api_extract,
    ("POST", "/api/compress"): api_compress,
    ("GET", "/api/archive-formats"): api_archive_formats,
    ("GET", "/api/archive-list"): api_archive_list,
    ("GET", "/api/trash"): api_trash_query,
    ("POST", "/api/restore-all"): api_restore_all,
    ("POST", "/api/mksymlink"): api_mksymlink,
    ("GET", "/api/thumbnail"): api_thumbnail,
    ("GET", "/api/xattr"): api_xattr,
    ("GET", "/api/recent"): api_recent,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "AuradeFilesBackend/0.1"

    def log_message(self, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code, obj):
        body = _json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, code, raw):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", raw.ctype)
        self.send_header("Content-Length", str(len(raw.data)))
        self.end_headers()
        self.wfile.write(raw.data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _handle(self):
        url = _up.urlparse(self.path)
        fn = _ROUTES.get((self.command, url.path))
        if not fn:
            return self._send(404, {"error": "unknown endpoint",
                                    "errno": _errno.ENOENT})
        query = {k: v[0] for k, v in _up.parse_qs(url.query).items()}
        body = None
        if self.command in ("POST", "DELETE"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length else b""
            if raw:
                try:
                    body = _json.loads(raw.decode())
                except ValueError:
                    return self._send(400, {"error": "bad json",
                                            "errno": _errno.EINVAL})
        try:
            res = fn(query, body)
            if isinstance(res, _Raw):
                return self._send_raw(200, res)
            return self._send(200, res)
        except _Err as e:
            return self._send(e.code, {"error": e.message,
                                       "errno": e.err_no})
        except OSError as e:
            return self._send(500, {"error": e.strerror or type(e).__name__,
                                    "errno": getattr(e, "errno", None) or
                                    _errno.EIO})
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}",
                                    "errno": _errno.EIO})

    do_GET = _handle
    do_POST = _handle
    do_DELETE = _handle


def main():
    if HOST != "127.0.0.1":
        raise SystemExit("refusing non-localhost bind")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    print(f"aurade-files backend on http://{HOST}:{PORT} (localhost only)")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
