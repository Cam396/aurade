#!/usr/bin/env python3
"""Compare the Rust backend's answers against the Python one it replaces.

Both are started against the same scratch tree and the same XDG_DATA_HOME, and
every shared route is asked the same question. What matters is the *shape*: the
page reads keys, so a key that one side has and the other does not is a page
that breaks on the swap. Values are compared only where they are deterministic.

Run it from anywhere:  python3 tools/parity.py
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
PROTO = "/mnt/build/aurade-work/proto"
SCRATCH = "/mnt/build/aurade-work/parity-scratch"
PY_PORT = 8902
RS_PORT = 8903


def build_tree():
    shutil.rmtree(SCRATCH, ignore_errors=True)
    os.makedirs(os.path.join(SCRATCH, "files", "sub"))
    os.makedirs(os.path.join(SCRATCH, "xdg-data"))
    w = lambda p, b: open(os.path.join(SCRATCH, "files", p), "wb").write(b)
    w("note.txt", b"a line with needle in it\nand another\n")
    w("sub/deep.md", b"# heading\n")
    w("data.bin", bytes([0, 1, 2, 3, 4]))
    try:
        from PIL import Image
        Image.new("RGB", (300, 200), (40, 90, 160)).save(
            os.path.join(SCRATCH, "files", "shot.png"))
    except Exception:
        pass
    os.symlink(os.path.join(SCRATCH, "files", "note.txt"),
               os.path.join(SCRATCH, "files", "link-to-note"))
    return os.path.join(SCRATCH, "files")


def wait_for(port, tries=30):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                json.load(r)
                return True
        except Exception:
            time.sleep(0.4)
    return False


def get(port, route, params=None):
    url = f"http://127.0.0.1:{port}{route}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, None
    except Exception as e:
        return 0, {"__transport": str(e)}


def post(port, route, body):
    url = f"http://127.0.0.1:{port}{route}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, None
    except Exception as e:
        return 0, {"__transport": str(e)}


def shape(value, depth=0):
    """A description of the structure, ignoring the values themselves."""
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    if value is None:
        return "null"
    return type(value).__name__


def diff_shape(a, b, path=""):
    """Keys the Python has that the Rust does not, and type mismatches."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                out.append(f"missing {path}{k}")
            else:
                out.extend(diff_shape(a[k], b[k], f"{path}{k}."))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if a and b:
            out.extend(diff_shape(a[0], b[0], f"{path}[]."))
        elif a and not b:
            out.append(f"empty {path}(python had rows)")
        return out
    if a != b and not (a == "null" or b == "null"):
        out.append(f"type {path.rstrip('.')}: python={a} rust={b}")
    return out


#: Differences that are deliberate. Each one is a place the Rust backend was
#: not made to match, with the reason, so a reader can tell an intended change
#: from a regression.
ACCEPTED = {
    "copy-keep-both":
        "naming: python writes solo.txt.1, which changes the file's type. "
        "The Rust backend writes solo (2).txt and keeps the extension.",
}


def make_pair(name):
    """Two identical trees, one for each backend to act on."""
    out = []
    for side in ("py", "rs"):
        root = os.path.join(SCRATCH, "post", name, side)
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(os.path.join(root, "src", "inner"))
        os.makedirs(os.path.join(root, "dest"))
        open(os.path.join(root, "src", "top.txt"), "wb").write(b"top")
        open(os.path.join(root, "src", "inner", "deep.txt"), "wb").write(b"deep")
        open(os.path.join(root, "solo.txt"), "wb").write(b"solo")
        out.append(root)
    return out


def snapshot(root):
    """Every path under a tree, relative, with what it is and how big."""
    out = []
    for base, dirs, files in os.walk(root):
        dirs.sort()
        rel = os.path.relpath(base, root)
        if rel != ".":
            out.append((rel, "dir", 0))
        for f in sorted(files):
            full = os.path.join(base, f)
            kind = "link" if os.path.islink(full) else "file"
            size = 0 if kind == "link" else os.path.getsize(full)
            out.append((os.path.relpath(full, root), kind, size))
    return sorted(out)


def post_cases():
    """The mutating routes, each against its own copy of the same tree.

    Two things are compared: the answer's shape, and what the filesystem looks
    like afterwards. The second is the one that matters. A route can answer in
    the right shape and have done something different on disk.
    """
    cases = [
        ("mkdir", "/api/mkdir", "",
         lambda t: {"path": os.path.join(t, "Made")}),
        ("mkfile", "/api/mkfile", "",
         lambda t: {"path": os.path.join(t, "made.txt")}),
        ("rename", "/api/rename", "",
         lambda t: {"path": os.path.join(t, "solo.txt"), "name": "renamed.txt"}),
        ("mksymlink", "/api/mksymlink", "",
         lambda t: {"target": os.path.join(t, "solo.txt"),
                    "link": os.path.join(t, "pointer")}),
        ("copy", "/api/copy", "",
         lambda t: {"paths": [os.path.join(t, "src")], "dest": os.path.join(t, "dest")}),
        ("copy-keep-both", "/api/copy", "conflict=keep-both",
         lambda t: {"paths": [os.path.join(t, "solo.txt")], "dest": t}),
        ("move", "/api/move", "",
         lambda t: {"paths": [os.path.join(t, "solo.txt")], "dest": os.path.join(t, "dest")}),
        ("delete", "/api/delete", "",
         lambda t: {"paths": [os.path.join(t, "solo.txt")]}),
        ("delete-never", "/api/delete", "policy=Never",
         lambda t: {"paths": [os.path.join(t, "solo.txt")]}),
        ("compress", "/api/compress", "",
         lambda t: {"paths": [os.path.join(t, "src")],
                    "dest": os.path.join(t, "bundle.zip"), "format": "zip"}),
    ]
    rows = []
    for name, route, query, build in cases:
        py_tree, rs_tree = make_pair(name)
        target = route + ("?" + query if query else "")
        py_status, py_body = post(PY_PORT, target, build(py_tree))
        rs_status, rs_body = post(RS_PORT, target, build(rs_tree))
        label = f"POST {route}" + (f" [{query}]" if query else "")

        problems = []
        if py_status != rs_status:
            problems.append(f"status: python {py_status}, rust {rs_status}")
        else:
            problems.extend(diff_shape(shape(py_body), shape(rs_body)))
        py_after, rs_after = snapshot(py_tree), snapshot(rs_tree)
        if py_after != rs_after:
            only_py = [p for p in py_after if p not in rs_after]
            only_rs = [p for p in rs_after if p not in py_after]
            if only_py:
                problems.append(f"on disk only after python: {only_py[:4]}")
            if only_rs:
                problems.append(f"on disk only after rust: {only_rs[:4]}")
        if name in ACCEPTED:
            rows.append((label, "NOTED", [ACCEPTED[name]] + problems))
            continue
        rows.append((label, "SAME" if not problems else "DIFFERS", problems))
    return rows


def main():
    files = build_tree()
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = os.path.join(SCRATCH, "xdg-data")
    env["HOME"] = env.get("HOME", "/root")

    binary = os.path.join(WORKSPACE, "target", "debug", "auradefs")
    if not os.path.exists(binary):
        print("build the daemon first: cargo build -p auradefs-daemon")
        return 2

    python = subprocess.Popen([sys.executable, "backend.py"], cwd=PROTO, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rust = subprocess.Popen([binary, "--port", str(RS_PORT)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_for(PY_PORT):
            print("the python backend did not start")
            return 2
        if not wait_for(RS_PORT):
            print("the rust backend did not start")
            return 2

        note = os.path.join(files, "note.txt")
        shot = os.path.join(files, "shot.png")

        # Tag one file through each backend, so the tag routes have something
        # to answer with on both sides.
        post(PY_PORT, "/api/tags", {"path": note, "tags": ["Blue"]})
        post(RS_PORT, "/api/tags", {"path": note, "tags": ["Blue"]})

        cases = [
            ("/api/health", {}),
            ("/api/system", {}),
            ("/api/archive-formats", {}),
            ("/api/list", {"path": files}),
            ("/api/list", {"path": files, "hidden": "1"}),
            ("/api/stat", {"path": note}),
            ("/api/preview", {"path": note}),
            ("/api/hash", {"path": note, "algo": "sha256"}),
            ("/api/search", {"root": files, "q": "deep"}),
            ("/api/thumb", {"path": shot}),
            ("/api/tags", {"path": note}),
            ("/api/tags/all", {}),
            ("/api/tags/list", {"tag": "Blue"}),
            ("/api/icon", {"path": files}),
            ("/api/icon/dir", {"path": files}),
            ("/api/xattr", {"path": note}),
            ("/api/volumes", {}),
            ("/api/git", {"path": files}),
            ("/api/trash/list", {}),
            ("/api/recent", {"root": files}),
            ("/api/wallpaper", {}),
        ]

        rows = []
        for route, params in cases:
            py_status, py_body = get(PY_PORT, route, params)
            rs_status, rs_body = get(RS_PORT, route, params)
            label = route + ("?" + urllib.parse.urlencode(params) if params else "")
            if py_status == 0 or rs_status == 0:
                rows.append((label, "TRANSPORT", [str(py_body), str(rs_body)]))
                continue
            if rs_status == 404 and py_status == 200:
                rows.append((label, "MISSING", ["the rust backend has no such route"]))
                continue
            if py_status != rs_status:
                rows.append((label, "STATUS", [f"python {py_status}, rust {rs_status}"]))
                continue
            problems = diff_shape(shape(py_body), shape(rs_body))
            rows.append((label, "SAME" if not problems else "SHAPE", problems))

        rows.extend(post_cases())

        same = 0
        noted = 0
        for label, verdict, problems in rows:
            if verdict == "SAME":
                same += 1
                print(f"  ok   {label}")
                continue
            if verdict == "NOTED":
                noted += 1
                print(f"  note {label}")
                print(f"       {problems[0]}")
                continue
            print(f"  {verdict:<5} {label}")
            for p in problems[:8]:
                print(f"       {p}")
            if len(problems) > 8:
                print(f"       and {len(problems) - 8} more")
        print()
        print(f"{same} of {len(rows)} match, {noted} differ on purpose, "
              f"{len(rows) - same - noted} to fix")
        return 0 if same + noted == len(rows) else 1
    finally:
        for p in (python, rust):
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
