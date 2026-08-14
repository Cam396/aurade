"""Static lifecycle contract for the GTK installer.

The widget module cannot be imported on the source/build host without GTK4
introspection data.  Keep this check dependency-free and assert the small
ordering contract that matters when a worker is still using the bridge:
window close and application shutdown must mark the window closing before GTK
returns control to the caller that closes the bridge.
"""

from __future__ import annotations

import ast
import os


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOURCE = os.path.join(ROOT, "installer", "lib", "aurade_gui", "app.py")
TREE = ast.parse(open(SOURCE, encoding="utf-8").read(), filename=SOURCE)


def cls(name: str) -> ast.ClassDef:
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"missing {class_node.name}.{name}")


def calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        item
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and ((isinstance(item.func, ast.Name) and item.func.id == name)
             or (isinstance(item.func, ast.Attribute) and item.func.attr == name))
    ]


window = cls("InstallerWindow")
init = method(window, "__init__")
mark = method(window, "_mark_closing")
close_request = method(window, "_on_close_request")
assert any(
    isinstance(call.args[0], ast.Constant)
    and call.args[0].value == "close-request"
    for call in calls(init, "connect")
), "window must connect close-request"
assert any(
    isinstance(call.func, ast.Attribute)
    and call.func.attr == "_mark_closing"
    for call in calls(close_request, "_mark_closing")
), "close-request must mark the window closing"
assert any(
    isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Attribute) and target.attr == "_closing" for target in node.targets)
    for node in ast.walk(mark)
), "close marker must invalidate callback state"
assert any(
    isinstance(call.func, ast.Attribute) and call.func.attr == "source_remove"
    for call in calls(mark, "source_remove")
), "close marker must remove the progress source"

application = cls("InstallerApplication")
shutdown = method(application, "do_shutdown")
assert any(
    isinstance(call.func, ast.Attribute) and call.func.attr == "_mark_closing"
    for call in calls(shutdown, "_mark_closing")
), "application shutdown must mark the window closing"
assert any(
    isinstance(call.func, ast.Attribute) and call.func.attr == "do_shutdown"
    for call in calls(shutdown, "do_shutdown")
), "application shutdown must chain to GTK"

run_async = method(window, "_run_async")
assert any(
    isinstance(node, ast.Attribute) and node.attr == "_closing"
    for node in ast.walk(run_async)
), "async delivery must inspect the closing marker"

retry = method(window, "_retry_network")
assert any(
    isinstance(node, ast.Assign)
    and any(
        isinstance(target, ast.Attribute) and target.attr == "_network_report"
        for target in node.targets
    )
    for node in ast.walk(retry)
), "network retry must clear the previous report"
assert any(
    isinstance(call.func, ast.Attribute) and call.func.attr == "refresh"
    for call in calls(retry, "refresh")
), "network retry must return through the normal refresh path"

network_builder = method(window, "_build_network")
assert any(
    isinstance(node, ast.Constant) and node.value == "network.retry"
    for node in ast.walk(network_builder)
), "network page must expose the retry control"

keymap = method(window, "_on_keymap_selected")
assert any(
    isinstance(call.func, ast.Attribute) and call.func.attr == "set"
    for call in calls(keymap, "set")
), "keymap selection must apply through the shared model"
assert any(
    isinstance(call.func, ast.Attribute) and call.func.attr == "_flag"
    for call in calls(keymap, "_flag")
), "keymap refusal must be surfaced by the renderer"
assert any(
    isinstance(node, ast.Constant) and node.value == "feedback.keymap"
    for node in ast.walk(keymap)
), "keymap selection must have an inline feedback target"

done = method(window, "_refresh_done")
assert not any(
    isinstance(node, ast.Constant) and node.value == "/dev/sda"
    for node in ast.walk(done)
), "completion screen must not invent a target disk"

print("installer GUI lifecycle test: PASS")
