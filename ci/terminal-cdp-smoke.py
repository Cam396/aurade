#!/usr/bin/env python3
"""Smoke-test the AuraDE terminal end to end through Chrome DevTools.

Opens (or reuses) the terminal system web app, sends a real shell command
through the xterm.js input path, and verifies the command executed as the
desktop user by checking its filesystem side effect.
"""

import argparse
import getpass
import json
import os
import pwd
import sys
import time
import urllib.error
import urllib.request

try:
    import websocket
except ImportError as exc:
    print(f"missing python websocket module: {exc}", file=sys.stderr)
    sys.exit(2)

TERMINAL_URL = "chrome-untrusted://terminal/html/terminal.html"
MARKER_PATH = "/tmp/aurade-terminal-smoke.txt"


def http_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def find_terminal_target(base_url):
    for target in http_json(f"{base_url}/json/list"):
        if (target.get("type") == "page" and
                target.get("url", "").startswith("chrome-untrusted://terminal/")):
            return target
    return None


def wait_for_terminal_target(base_url):
    target = find_terminal_target(base_url)
    if target:
        return target
    request = urllib.request.Request(
        f"{base_url}/json/new?{TERMINAL_URL}", method="PUT")
    try:
        urllib.request.urlopen(request, timeout=10).read()
    except urllib.error.HTTPError:
        pass
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        target = find_terminal_target(base_url)
        if target:
            return target
        time.sleep(0.5)
    raise RuntimeError("terminal target did not open through CDP")


def call(ws, method, params, message_id):
    ws.send(json.dumps({
        "id": message_id,
        "method": method,
        "params": params,
    }))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == message_id:
            if message.get("error"):
                raise RuntimeError(json.dumps(message["error"]))
            return message.get("result", {})


def evaluate(ws, expression, message_id):
    result = call(ws, "Runtime.evaluate", {
        "expression": expression,
        "awaitPromise": True,
        "returnByValue": True,
    }, message_id)
    return result.get("result", {}).get("value")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--test-user", default="auratest")
    args = parser.parse_args()

    if os.path.exists(MARKER_PATH):
        os.unlink(MARKER_PATH)

    target = wait_for_terminal_target(args.cdp.rstrip("/"))
    ws = websocket.create_connection(
        target["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
    try:
        # A reused terminal may be intensively background-throttled. Activating
        # it keeps the promise-based readiness loop below from waiting for the
        # browser's once-per-minute background timer budget.
        call(ws, "Page.bringToFront", {}, 1)
        ready = evaluate(ws, """
(async () => {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (window.auradeTerminalDebug &&
        window.auradeTerminalDebug.size().cols > 0) {
      return JSON.stringify(window.auradeTerminalDebug.size());
    }
    await new Promise(r => setTimeout(r, 500));
  }
  return 'NOT-READY';
})()
""", 2)
        if ready == "NOT-READY" or not ready:
            print("terminal debug hook never became ready", file=sys.stderr)
            return 1
        print(f"terminal ready, size {ready}")

        marker = f"echo aurade-terminal-smoke-$USER > {MARKER_PATH}\r"
        evaluate(
            ws,
            f"window.auradeTerminalDebug.send({json.dumps(marker)}); 'sent'",
            3)
    finally:
        ws.close()

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if os.path.exists(MARKER_PATH):
            break
        time.sleep(1)
    else:
        print("terminal command produced no filesystem side effect",
              file=sys.stderr)
        return 1

    with open(MARKER_PATH) as handle:
        content = handle.read().strip()
    owner = pwd.getpwuid(os.stat(MARKER_PATH).st_uid).pw_name
    os.unlink(MARKER_PATH)

    expected = f"aurade-terminal-smoke-{args.test_user}"
    if content != expected:
        print(f"unexpected marker content: {content!r} (want {expected!r})",
              file=sys.stderr)
        return 1
    if owner != args.test_user:
        print(f"marker owned by {owner}, expected {args.test_user}",
              file=sys.stderr)
        return 1

    print(f"Terminal smoke passed: shell executed as {owner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
