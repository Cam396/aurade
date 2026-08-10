#!/usr/bin/env python3
"""Smoke-test AuraDE Files local Linux volumes through Chrome DevTools."""

import argparse
import io
import itertools
import json
import os
import pwd
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request

try:
    import websocket
except ImportError as exc:
    print(f"missing python websocket module: {exc}", file=sys.stderr)
    sys.exit(2)


def http_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def open_target(base_url, url):
    request = urllib.request.Request(
        f"{base_url}/json/new?{url}",
        method="PUT",
    )
    try:
        urllib.request.urlopen(request, timeout=10).read()
    except urllib.error.HTTPError:
        # Some chrome:// targets return 500 from /json/new while still opening.
        pass


def find_files_target(base_url):
    targets = http_json(f"{base_url}/json/list")
    for target in targets:
        if (target.get("type") == "page" and
                target.get("url", "").startswith("chrome://file-manager/")):
            return target
    return None


def wait_for_files_target(base_url):
    target = find_files_target(base_url)
    if target:
        return target
    open_target(base_url, "chrome://file-manager/")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        target = find_files_target(base_url)
        if target:
            return target
        time.sleep(0.5)
    raise RuntimeError("Files target did not open through CDP")


class CdpClient:
    def __init__(self, websocket_url):
        self._next_id = itertools.count(1)
        self._ws = websocket.create_connection(
            websocket_url,
            timeout=30,
            suppress_origin=True,
        )

    def close(self):
        self._ws.close()

    def call(self, method, params=None):
        message_id = next(self._next_id)
        self._ws.send(json.dumps({
            "id": message_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            message = json.loads(self._ws.recv())
            if message.get("id") == message_id:
                return message


def run_expression(client, expression):
    response = client.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        },
    )
    result = response.get("result", {})
    if result.get("exceptionDetails"):
        raise RuntimeError(json.dumps(result["exceptionDetails"], indent=2))
    value = result.get("result", {}).get("value")
    if not isinstance(value, dict):
        raise RuntimeError(f"unexpected CDP result: {json.dumps(response)[:1000]}")
    return value


FILE_OPS_BASENAME = "aurade-ci-fileops.txt"
FILE_OPS_CONTENT = "aurade files ops smoke\n"
ARCHIVE_BASENAME = "aurade-ci-archive.tar"
ARCHIVE_DIRECTORY = "aurade-ci-archive"
ARCHIVE_MEMBER = "AURADE_ARCHIVE.txt"
ARCHIVE_CONTENT = "aurade archive extraction smoke\n"

FILE_OPS_HELPERS = """
  const timeout = (label, ms) => new Promise(resolve =>
      setTimeout(() => resolve({ok: false, label, timeout: true}), ms || 15000));
  const getRoot = () => Promise.race([new Promise(resolve => {
    chrome.fileManagerPrivate.getVolumeRoot(
        {volumeId: 'local_root:Downloads'}, entry => {
      const lastError = chrome.runtime.lastError &&
          chrome.runtime.lastError.message;
      if (lastError || !entry) {
        resolve({ok: false, error: lastError || 'missing entry'});
        return;
      }
      resolve({ok: true, entry});
    });
  }), timeout('getVolumeRoot')]);
  const getFile = (rootEntry, name) => Promise.race([new Promise(resolve => {
    rootEntry.getFile(name, {},
        entry => resolve({ok: true, entry}),
        e => resolve({ok: false, error: name + ': ' +
                     (e && (e.message || e.name))}));
  }), timeout('getFile')]);
  const listNames = (rootEntry) => Promise.race([new Promise(resolve => {
    rootEntry.createReader().readEntries(
        entries => resolve({ok: true, names: entries.map(e => e.name).sort()}),
        e => resolve({ok: false, error: 'readEntries: ' +
                     (e && (e.message || e.name))}));
  }), timeout('readEntries')]);
  const runIOTask = (type, entries, params) => Promise.race([
    new Promise(resolve => {
      let taskId = null;
      const listener = status => {
        if (taskId === null || status.taskId !== taskId) return;
        if (status.state === 'success') {
          chrome.fileManagerPrivate.onIOTaskProgressStatus.removeListener(
              listener);
          resolve({ok: true});
        } else if (status.state === 'error' || status.state === 'cancelled' ||
                   status.state === 'need_password') {
          chrome.fileManagerPrivate.onIOTaskProgressStatus.removeListener(
              listener);
          resolve({ok: false,
                   error: type + ' io task state: ' + status.state});
        }
      };
      chrome.fileManagerPrivate.onIOTaskProgressStatus.addListener(listener);
      chrome.fileManagerPrivate.startIOTask(type, entries, params, id => {
        const lastError = chrome.runtime.lastError &&
            chrome.runtime.lastError.message;
        if (lastError) {
          chrome.fileManagerPrivate.onIOTaskProgressStatus.removeListener(
              listener);
          resolve({ok: false, error: type + ': ' + lastError});
          return;
        }
        taskId = id;
      });
    }),
    timeout(type + '-io-task', 30000),
  ]);
"""


def evaluate_file_ops_copy(client):
    """Copy the seeded scratch file through a Files IO task, then read the
    copy back and report its deduplicated name."""
    expression = f"""
(async () => {{
{FILE_OPS_HELPERS}
  const root = await getRoot();
  if (!root.ok) return root;
  const original = await getFile(root.entry, {json.dumps(FILE_OPS_BASENAME)});
  if (!original.ok) return original;

  const before = await listNames(root.entry);
  if (!before.ok) return before;

  const copied = await runIOTask(
      'copy', [original.entry], {{destinationFolder: root.entry}});
  if (!copied.ok) return copied;

  const after = await listNames(root.entry);
  if (!after.ok) return after;
  const added = after.names.filter(name => !before.names.includes(name));
  if (added.length !== 1) {{
    return {{ok: false, error: 'expected one new copy, got: ' +
             JSON.stringify(added)}};
  }}
  const copyName = added[0];

  const copyEntry = await getFile(root.entry, copyName);
  if (!copyEntry.ok) return copyEntry;
  const readBack = await Promise.race([new Promise(resolve => {{
    copyEntry.entry.file(file => {{
      const reader = new FileReader();
      reader.onload = () => resolve({{ok: true, text: reader.result}});
      reader.onerror = () => resolve({{ok: false, error: 'FileReader'}});
      reader.readAsText(file);
    }}, e => resolve({{ok: false, error: 'file(): ' +
                      (e && (e.message || e.name))}}));
  }}), timeout('readBack')]);
  if (!readBack.ok) return readBack;
  if (readBack.text !== {json.dumps(FILE_OPS_CONTENT)}) {{
    return {{ok: false, error: 'copy content mismatch: ' +
             JSON.stringify(readBack.text)}};
  }}
  return {{ok: true, copyName}};
}})()
"""
    return run_expression(client, expression)


def evaluate_file_ops_delete(client, copy_name):
    """Delete the scratch file and its copy through a Files IO task and
    verify both disappear from the directory listing."""
    expression = f"""
(async () => {{
{FILE_OPS_HELPERS}
  const root = await getRoot();
  if (!root.ok) return root;
  const names = [{json.dumps(FILE_OPS_BASENAME)}, {json.dumps(copy_name)}];
  const entries = [];
  for (const name of names) {{
    const found = await getFile(root.entry, name);
    if (!found.ok) return found;
    entries.push(found.entry);
  }}
  const deleted = await runIOTask('delete', entries, {{}});
  if (!deleted.ok) return deleted;

  const after = await listNames(root.entry);
  if (!after.ok) return after;
  const leftover = names.filter(name => after.names.includes(name));
  if (leftover.length) {{
    return {{ok: false, error: 'leftover entries: ' + leftover.join(', ')}};
  }}
  return {{ok: true}};
}})()
"""
    return run_expression(client, expression)


def seed_file_ops_scratch(test_user):
    """Create the scratch file on disk as the desktop user."""
    import subprocess

    path = f"/home/{test_user}/Downloads/{FILE_OPS_BASENAME}"
    write = subprocess.run(
        ["runuser", "-u", test_user, "--", "tee", path],
        input=FILE_OPS_CONTENT, capture_output=True, text=True)
    if write.returncode != 0:
        return f"failed to seed {path}: {write.stderr.strip()}"
    return None


def check_file_ops_copy_on_disk(test_user, copy_name):
    """Verify the Files-app-created copy landed on disk as the desktop
    user with the expected content."""
    import os
    import pwd

    path = f"/home/{test_user}/Downloads/{copy_name}"
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return f"copy missing on disk: {path}"
    try:
        expected_uid = pwd.getpwnam(test_user).pw_uid
    except KeyError:
        return f"unknown test user: {test_user}"
    if stat.st_uid != expected_uid:
        return f"{path} owned by uid {stat.st_uid}, expected {expected_uid}"
    with open(path, "r") as handle:
        content = handle.read()
    if content != FILE_OPS_CONTENT:
        return f"{path} content mismatch: {content!r}"
    return None


def check_file_ops_gone_on_disk(test_user, copy_name):
    for name in (FILE_OPS_BASENAME, copy_name):
        path = f"/home/{test_user}/Downloads/{name}"
        if os.path.exists(path):
            return f"deleted entry still on disk: {path}"
    return None


def seed_archive_scratch(test_user):
    """Create a deterministic user-owned tar archive in Downloads."""
    try:
        account = pwd.getpwnam(test_user)
    except KeyError:
        return f"unknown test user: {test_user}"
    downloads = f"/home/{test_user}/Downloads"
    archive_path = os.path.join(downloads, ARCHIVE_BASENAME)
    extracted_path = os.path.join(downloads, ARCHIVE_DIRECTORY)
    try:
        if os.path.lexists(archive_path):
            os.unlink(archive_path)
        if os.path.isdir(extracted_path) and not os.path.islink(extracted_path):
            shutil.rmtree(extracted_path)
        elif os.path.lexists(extracted_path):
            os.unlink(extracted_path)
        payload = ARCHIVE_CONTENT.encode()
        member = tarfile.TarInfo(ARCHIVE_MEMBER)
        member.size = len(payload)
        member.mode = 0o644
        member.uid = account.pw_uid
        member.gid = account.pw_gid
        member.mtime = 0
        with tarfile.open(archive_path, "w") as archive:
            archive.addfile(member, io.BytesIO(payload))
        os.chown(archive_path, account.pw_uid, account.pw_gid)
    except OSError as exc:
        return f"failed to seed {archive_path}: {exc}"
    return None


def evaluate_archive_extract(client):
    expression = f"""
(async () => {{
{FILE_OPS_HELPERS}
  const getDirectory = (rootEntry, name) => Promise.race([
    new Promise(resolve => {{
      rootEntry.getDirectory(name, {{}},
          entry => resolve({{ok: true, entry}}),
          e => resolve({{ok: false, error: name + ': ' +
                       (e && (e.message || e.name))}}));
    }}),
    timeout('getDirectory'),
  ]);
  const readText = entry => Promise.race([new Promise(resolve => {{
    entry.file(file => {{
      const reader = new FileReader();
      reader.onload = () => resolve({{ok: true, text: reader.result}});
      reader.onerror = () => resolve({{ok: false, error: 'FileReader'}});
      reader.readAsText(file);
    }}, e => resolve({{ok: false, error: 'file(): ' +
                      (e && (e.message || e.name))}}));
  }}), timeout('archive-read')]);

  const root = await getRoot();
  if (!root.ok) return root;
  const source = await getFile(root.entry, {json.dumps(ARCHIVE_BASENAME)});
  if (!source.ok) return source;
  const extracted = await runIOTask(
      'extract', [source.entry], {{destinationFolder: root.entry}});
  if (!extracted.ok) return extracted;
  const directory = await getDirectory(
      root.entry, {json.dumps(ARCHIVE_DIRECTORY)});
  if (!directory.ok) return directory;
  const member = await getFile(
      directory.entry, {json.dumps(ARCHIVE_MEMBER)});
  if (!member.ok) return member;
  const contents = await readText(member.entry);
  if (!contents.ok) return contents;
  if (contents.text !== {json.dumps(ARCHIVE_CONTENT)}) {{
    return {{ok: false, error: 'archive content mismatch: ' +
             JSON.stringify(contents.text)}};
  }}
  return {{ok: true}};
}})()
"""
    return run_expression(client, expression)


def evaluate_archive_delete(client):
    expression = f"""
(async () => {{
{FILE_OPS_HELPERS}
  const getDirectory = (rootEntry, name) => Promise.race([
    new Promise(resolve => {{
      rootEntry.getDirectory(name, {{}},
          entry => resolve({{ok: true, entry}}),
          e => resolve({{ok: false, error: name + ': ' +
                       (e && (e.message || e.name))}}));
    }}),
    timeout('getDirectory'),
  ]);
  const root = await getRoot();
  if (!root.ok) return root;
  const archive = await getFile(root.entry, {json.dumps(ARCHIVE_BASENAME)});
  if (!archive.ok) return archive;
  const directory = await getDirectory(
      root.entry, {json.dumps(ARCHIVE_DIRECTORY)});
  if (!directory.ok) return directory;
  return await runIOTask('delete', [archive.entry, directory.entry], {{}});
}})()
"""
    return run_expression(client, expression)


def check_archive_on_disk(test_user):
    try:
        account = pwd.getpwnam(test_user)
    except KeyError:
        return f"unknown test user: {test_user}"
    member_path = os.path.join(
        f"/home/{test_user}/Downloads", ARCHIVE_DIRECTORY, ARCHIVE_MEMBER)
    try:
        stat = os.stat(member_path)
        with open(member_path, "r", encoding="utf-8") as member:
            content = member.read()
    except OSError as exc:
        return f"cannot read extracted archive member {member_path}: {exc}"
    if stat.st_uid != account.pw_uid:
        return (f"{member_path} owned by uid {stat.st_uid}, "
                f"expected {account.pw_uid}")
    if content != ARCHIVE_CONTENT:
        return f"{member_path} content mismatch: {content!r}"
    return None


def check_archive_gone_on_disk(test_user):
    downloads = f"/home/{test_user}/Downloads"
    for name in (ARCHIVE_BASENAME, ARCHIVE_DIRECTORY):
        path = os.path.join(downloads, name)
        if os.path.lexists(path):
            return f"archive smoke entry still on disk: {path}"
    return None


def cleanup_archive_scratch(test_user):
    downloads = f"/home/{test_user}/Downloads"
    archive_path = os.path.join(downloads, ARCHIVE_BASENAME)
    extracted_path = os.path.join(downloads, ARCHIVE_DIRECTORY)
    if os.path.lexists(archive_path):
        os.unlink(archive_path)
    if os.path.isdir(extracted_path) and not os.path.islink(extracted_path):
        shutil.rmtree(extracted_path)
    elif os.path.lexists(extracted_path):
        os.unlink(extracted_path)


def evaluate_files_smoke(client, expected_ids):
    expression = f"""
(async () => {{
  const expectedIds = {json.dumps(expected_ids)};
  const timeout = (label) => new Promise(resolve =>
      setTimeout(() => resolve({{ok: false, label, timeout: true}}), 15000));
  const metadata = await Promise.race([
    new Promise(resolve => {{
      chrome.fileManagerPrivate.getVolumeMetadataList(items => {{
        resolve({{
          ok: true,
          items: (items || []).map(item => ({{
            volumeId: item.volumeId,
            label: item.label,
            volumeType: item.volumeType,
          }})),
        }});
      }});
    }}),
    timeout('metadata'),
  ]);
  if (!metadata.ok) return metadata;

  const localIds = metadata.items
      .filter(item => String(item.volumeId).startsWith('local_root:'))
      .map(item => item.volumeId)
      .sort();
  const missing = expectedIds.filter(id => !localIds.includes(id));

  const readRoot = async (volumeId) => await Promise.race([
    new Promise(resolve => {{
      chrome.fileManagerPrivate.getVolumeRoot({{volumeId}}, entry => {{
        const lastError = chrome.runtime.lastError &&
            chrome.runtime.lastError.message;
        if (lastError || !entry) {{
          resolve({{ok: false, volumeId, error: lastError || 'missing entry'}});
          return;
        }}
        const reader = entry.createReader();
        reader.readEntries(
            entries => resolve({{
              ok: true,
              volumeId,
              url: entry.toURL(),
              names: entries.map(e => e.name).sort(),
            }}),
            error => resolve({{
              ok: false,
              volumeId,
              error: error && (error.message || error.name),
            }}));
      }});
    }}),
    timeout(volumeId),
  ]);

  const roots = [];
  for (const volumeId of expectedIds) {{
    roots.push(await readRoot(volumeId));
  }}
  return {{ok: true, localIds, missing, roots}};
}})()
"""
    return run_expression(client, expression)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--test-user", default="auratest")
    parser.add_argument(
        "--file-ops-smoke",
        action="store_true",
        help="Also exercise create/write/copy/rename/read/delete in "
        "local_root:Downloads through the live Files page.",
    )
    parser.add_argument(
        "--expect-media-entry",
        help="Require this entry below the live local_root:media volume.",
    )
    parser.add_argument(
        "--archive-smoke",
        action="store_true",
        help="Extract and read a tar archive through a Files IO task, then "
        "delete all test entries.",
    )
    args = parser.parse_args()

    expected_ids = [
        "local_root:Desktop",
        "local_root:Documents",
        "local_root:Downloads",
        "local_root:Music",
        "local_root:Pictures",
        "local_root:Videos",
        f"local_root:{args.test_user}",
        "local_root:home",
        "local_root:local",
        "local_root:media",
        "local_root:mnt",
        "local_root:opt",
        "local_root:root",
    ]

    target = wait_for_files_target(args.cdp.rstrip("/"))
    client = CdpClient(target["webSocketDebuggerUrl"])
    try:
        value = evaluate_files_smoke(client, expected_ids)
    finally:
        client.close()

    if not value.get("ok"):
        print(json.dumps(value, indent=2), file=sys.stderr)
        return 1
    if value.get("missing"):
        print(f"missing local roots: {', '.join(value['missing'])}", file=sys.stderr)
        return 1

    failed_roots = [root for root in value["roots"] if not root.get("ok")]
    if failed_roots:
        print(json.dumps(failed_roots, indent=2), file=sys.stderr)
        return 1

    root_entries = next(
        root for root in value["roots"] if root["volumeId"] == "local_root:root")
    required_root_names = {"etc", "home", "mnt", "usr", "var"}
    missing_names = sorted(required_root_names - set(root_entries["names"]))
    if missing_names:
        print(
            f"local_root:root missing expected entries: {', '.join(missing_names)}",
            file=sys.stderr,
        )
        return 1

    if args.expect_media_entry:
        media_entries = next(
            root for root in value["roots"]
            if root["volumeId"] == "local_root:media")
        if args.expect_media_entry not in media_entries["names"]:
            print(
                "local_root:media missing expected entry: "
                f"{args.expect_media_entry}",
                file=sys.stderr,
            )
            return 1

    print(f"Files local-root smoke passed: {len(value['localIds'])} volumes")
    for root in value["roots"]:
        print(f"  {root['volumeId']} -> {root['url']}")

    if args.file_ops_smoke:
        seed_error = seed_file_ops_scratch(args.test_user)
        if seed_error:
            print(seed_error, file=sys.stderr)
            return 1
        client = CdpClient(target["webSocketDebuggerUrl"])
        try:
            copied = evaluate_file_ops_copy(client)
            if not copied.get("ok"):
                print(json.dumps(copied, indent=2), file=sys.stderr)
                return 1
            copy_name = copied["copyName"]
            disk_error = check_file_ops_copy_on_disk(args.test_user, copy_name)
            if disk_error:
                print(disk_error, file=sys.stderr)
                return 1
            deleted = evaluate_file_ops_delete(client, copy_name)
            if not deleted.get("ok"):
                print(json.dumps(deleted, indent=2), file=sys.stderr)
                return 1
            disk_error = check_file_ops_gone_on_disk(args.test_user, copy_name)
            if disk_error:
                print(disk_error, file=sys.stderr)
                return 1
        finally:
            client.close()
        print("Files file-ops smoke passed: seed/copy/read/delete via IO tasks")
    if args.archive_smoke:
        seed_error = seed_archive_scratch(args.test_user)
        if seed_error:
            print(seed_error, file=sys.stderr)
            return 1
        client = CdpClient(target["webSocketDebuggerUrl"])
        try:
            extracted = evaluate_archive_extract(client)
            if not extracted.get("ok"):
                print(json.dumps(extracted, indent=2), file=sys.stderr)
                return 1
            disk_error = check_archive_on_disk(args.test_user)
            if disk_error:
                print(disk_error, file=sys.stderr)
                return 1
            deleted = evaluate_archive_delete(client)
            if not deleted.get("ok"):
                print(json.dumps(deleted, indent=2), file=sys.stderr)
                return 1
            disk_error = check_archive_gone_on_disk(args.test_user)
            if disk_error:
                print(disk_error, file=sys.stderr)
                return 1
        finally:
            client.close()
            cleanup_archive_scratch(args.test_user)
        print("Files archive smoke passed: tar extract/read/delete via IO tasks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
