#!/usr/bin/env python3
"""Smoke-test ChromeVox and Select-to-Speak through the live AuraDE session."""

import argparse
import json
import os
import time
import urllib.error
import urllib.request

import websocket


CHROMEVOX_MARKER = "chromevox/mv3/chromevox_loader.js"
SELECT_TO_SPEAK_MARKER = "select_to_speak/select_to_speak_main.rollup.js"
SPEECH_MARKER = "AuraDE TTS: speaking utterance"


def http_json(url, method=None):
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def targets(base_url):
    return http_json(f"{base_url}/json/list")


def close_target(base_url, target):
    try:
        urllib.request.urlopen(
            f"{base_url}/json/close/{target['id']}", timeout=5).read()
    except Exception:
        pass


def wait_for_target(base_url, marker, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for target in targets(base_url):
            if marker in target.get("url", ""):
                return target
        time.sleep(0.5)
    raise RuntimeError(f"CDP target did not appear: {marker}")


def wait_for_target_gone(base_url, marker, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(marker in target.get("url", "")
                   for target in targets(base_url)):
            return
        time.sleep(0.5)
    raise RuntimeError(f"CDP target did not stop: {marker}")


def wait_for_page(base_url, url, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for target in targets(base_url):
            if target.get("type") == "page" and target.get("url") == url:
                return target
        time.sleep(0.5)
    raise RuntimeError(f"CDP page did not appear: {url}")


class Cdp:
    def __init__(self, target):
        self.ws = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        self.message_id = 0

    def close(self):
        self.ws.close()

    def call(self, method, params=None):
        self.message_id += 1
        message_id = self.message_id
        self.ws.send(json.dumps({
            "id": message_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == message_id:
                return message

    def evaluate(self, expression, await_promise=False):
        response = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        })
        result = response["result"]["result"]
        if result.get("subtype") == "error":
            raise RuntimeError(result.get("description", "CDP evaluation failed"))
        return result.get("value")


def speech_count(log_path):
    with open(log_path, errors="replace") as log:
        return sum(SPEECH_MARKER in line for line in log)


def wait_for_speech(log_path, previous, label, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = speech_count(log_path)
        if current > previous:
            print(f"{label}: native TTS utterance observed ({previous} -> {current})")
            return current
        time.sleep(0.5)
    raise RuntimeError(f"{label} produced no native TTS utterance")


def set_accessibility_toggle(settings, pref_key, enabled):
    expression = f"""
(() => {{
  const find = root => {{
    for (const element of root.querySelectorAll('settings-toggle-button')) {{
      if (element.pref?.key === {json.dumps(pref_key)}) return element;
    }}
    for (const element of root.querySelectorAll('*')) {{
      if (element.shadowRoot) {{
        const match = find(element.shadowRoot);
        if (match) return match;
      }}
    }}
  }};
  const toggle = find(document);
  if (!toggle) return 'MISSING';
  if (toggle.checked !== {str(enabled).lower()}) toggle.click();
  return JSON.stringify({{checked: toggle.checked, pref: toggle.pref}});
}})()
"""
    result = settings.evaluate(expression)
    if result == "MISSING":
        raise RuntimeError(f"Settings toggle not found: {pref_key}")


def open_text_to_speech(settings):
    settings.call("Page.navigate", {"url": "chrome://os-settings/osAccessibility"})
    time.sleep(2)
    result = settings.evaluate("""
(() => {
  const find = root => {
    const match = root.querySelector('#textToSpeechSubpageTrigger');
    if (match) return match;
    for (const element of root.querySelectorAll('*')) {
      if (element.shadowRoot) {
        const nested = find(element.shadowRoot);
        if (nested) return nested;
      }
    }
  };
  const link = find(document);
  if (!link) return false;
  link.click();
  return true;
})()
""")
    if not result:
        raise RuntimeError("Text-to-Speech Settings link did not render")
    time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--chrome-log", required=True)
    args = parser.parse_args()
    base_url = args.cdp.rstrip("/")

    if not os.path.isfile(args.chrome_log):
        raise RuntimeError(f"Chrome log is unavailable: {args.chrome_log}")

    for target in targets(base_url):
        if (target.get("type") == "page" and
                target.get("url", "").startswith("chrome://os-settings/")):
            close_target(base_url, target)
    time.sleep(2)

    settings_url = "chrome://os-settings/osAccessibility"
    try:
        settings_target = http_json(
            f"{base_url}/json/new?{settings_url}", method="PUT")
    except urllib.error.HTTPError:
        settings_target = wait_for_page(base_url, settings_url)

    settings = Cdp(settings_target)
    test_target = None
    try:
        open_text_to_speech(settings)
        set_accessibility_toggle(settings, "settings.accessibility", False)
        set_accessibility_toggle(
            settings, "settings.a11y.select_to_speak", False)
        wait_for_target_gone(base_url, SELECT_TO_SPEAK_MARKER)
        wait_for_target_gone(base_url, CHROMEVOX_MARKER)
        time.sleep(2)

        before = speech_count(args.chrome_log)
        set_accessibility_toggle(
            settings, "settings.a11y.select_to_speak", True)
        worker_target = wait_for_target(base_url, SELECT_TO_SPEAK_MARKER)
        worker = Cdp(worker_target)
        try:
            test_target = http_json(
                f"{base_url}/json/new?about:blank", method="PUT")
            page = Cdp(test_target)
            try:
                page.call("Page.navigate", {"url": (
                    "data:text/html,<title>AuraDE Accessibility Smoke</title>"
                    "<main>AuraDE select to speak live validation</main>")})
                time.sleep(1)
                selection_expression = """
(() => {
  const element = document.querySelector('main');
  element.tabIndex = 0;
  element.focus();
  const range = document.createRange();
  range.selectNodeContents(element.firstChild);
  const selection = getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  return selection.toString();
})()
"""
                trigger_expression = """
(async () => {
  const selectToSpeak = TestImportManager.getImports().selectToSpeak;
  await selectToSpeak.readyForTestingPromise;
  selectToSpeak.getFocusedNodeAndSpeakSelectedText_();
  return 'triggered';
})()
"""
                for attempt in range(3):
                    page.call("Page.bringToFront")
                    selected = page.evaluate(selection_expression)
                    if selected != "AuraDE select to speak live validation":
                        raise RuntimeError(
                            f"unexpected selected text: {selected!r}")
                    time.sleep(1)
                    worker.evaluate(trigger_expression, await_promise=True)
                    try:
                        before = wait_for_speech(
                            args.chrome_log, before, "Select-to-Speak",
                            timeout=8)
                        break
                    except RuntimeError:
                        if attempt == 2:
                            raise
                        time.sleep(2)
            finally:
                page.close()
        finally:
            worker.close()

        set_accessibility_toggle(
            settings, "settings.a11y.select_to_speak", False)
        wait_for_target_gone(base_url, SELECT_TO_SPEAK_MARKER)
        time.sleep(2)

        set_accessibility_toggle(settings, "settings.accessibility", True)
        wait_for_target(base_url, CHROMEVOX_MARKER)
        wait_for_speech(args.chrome_log, before, "ChromeVox")

        print("Accessibility smoke passed: ChromeVox and Select-to-Speak")
        return 0
    finally:
        if test_target:
            close_target(base_url, test_target)
        try:
            set_accessibility_toggle(
                settings, "settings.a11y.select_to_speak", False)
            wait_for_target_gone(base_url, SELECT_TO_SPEAK_MARKER)
            set_accessibility_toggle(settings, "settings.accessibility", False)
            wait_for_target_gone(base_url, CHROMEVOX_MARKER)
        except Exception:
            pass
        settings.close()
        close_target(base_url, settings_target)


if __name__ == "__main__":
    raise SystemExit(main())
