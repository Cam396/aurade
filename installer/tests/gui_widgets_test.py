"""Every toolkit symbol the graphical installer uses, checked against the
toolkit's own introspection data.

The widget layer is the one part of this front end that cannot be driven
without a compositor, so the failure it is most exposed to is a name that does
not exist: a class that was renamed, a property that belongs to a different
widget, an enum member spelled the way another toolkit spells it, a method
remembered from GTK 3. None of that shows up in a syntax check, and all of it
shows up as a traceback on the one machine that has no other installer left to
fall back to by then.

GIR files answer all of it without a display. They are XML, they ship with the
packages the image installs, and they list every class, property, method,
signal and enum member the bindings expose. So this walks the source, collects
what it asks the toolkit for, and looks each one up.

It skips when the introspection data is not installed, which is the ordinary
case on a build host. That skip is honest: it records that this check did not
run, and the file it checks is the one file in this front end whose mistakes a
headless test cannot otherwise see.
"""

from __future__ import annotations

import ast
import os
import sys
import xml.etree.ElementTree as ET

NS = {
    "core": "http://www.gtk.org/introspection/core/1.0",
    "glib": "http://www.gtk.org/introspection/glib/1.0",
}

TESTS = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(TESTS, "..", ".."))
SOURCE = os.path.join(ROOT, "installer", "lib", "aurade_gui", "app.py")

GIR_DIRS = [os.environ.get("AURADE_GIR_DIR", ""), "/usr/share/gir-1.0"]

#: Namespaces the widget layer may use, and the GIR that defines each. A
#: namespace with no GIR installed is not checked rather than assumed wrong.
NAMESPACES = {
    "Gtk": "Gtk-4.0.gir",
    "Adw": "Adw-1.gir",
    "Gio": "Gio-2.0.gir",
    "GLib": "GLib-2.0.gir",
    "GObject": "GObject-2.0.gir",
}

#: Namespaces without which this test proves nothing worth reporting.
REQUIRED = ("Gtk", "Adw")

#: Receivers that are this project's own objects, not toolkit ones. ``gi`` is
#: the binding module rather than a namespace it exposes.
OURS = {"flow", "model", "manifest", "widgets", "enum_values", "probe", "F", "gi"}

#: Python's own methods, called on Python's own objects. Listed rather than
#: inferred, so a name added here is a deliberate statement that it is not
#: meant to be a toolkit call.
PYTHON_METHODS = {
    "index", "items", "keys", "values", "join", "split", "strip", "rstrip",
    "lower", "upper", "startswith", "endswith", "replace", "format", "pop",
    "setdefault", "readline", "flush", "require_version", "discard",
}

FAILURES: list[str] = []


def fail(message: str) -> None:
    FAILURES.append(message)


def find_gir(filename: str) -> str | None:
    for directory in GIR_DIRS:
        if directory and os.path.exists(os.path.join(directory, filename)):
            return os.path.join(directory, filename)
    return None


class Namespace:
    def __init__(self, path: str) -> None:
        node = ET.parse(path).getroot().find("core:namespace", NS)
        assert node is not None
        self.types: dict[str, ET.Element] = {}
        for tag in ("class", "interface", "record", "enumeration", "bitfield",
                    "callback", "alias", "union"):
            for element in node.findall(f"core:{tag}", NS):
                name = element.get("name")
                if name:
                    self.types[name] = element
        self.enum_members = {
            name: {
                (member.get("name") or "").upper().replace("-", "_")
                for member in element.findall("core:member", NS)
            }
            for name, element in self.types.items()
        }
        self.functions = {e.get("name") for e in node.findall("core:function", NS)}
        self.constants = {e.get("name") for e in node.findall("core:constant", NS)}
        self.any_method: set[str] = set()
        self.any_signal: set[str] = set()
        for element in self.types.values():
            for tag in ("method", "function", "constructor", "virtual-method"):
                for member in element.findall(f"core:{tag}", NS):
                    if member.get("name"):
                        self.any_method.add(member.get("name") or "")
            for signal in element.findall("glib:signal", NS):
                if signal.get("name"):
                    self.any_signal.add(signal.get("name") or "")


loaded: dict[str, Namespace] = {}
missing: list[str] = []
for prefix, filename in NAMESPACES.items():
    path = find_gir(filename)
    if path is None:
        missing.append(filename)
    else:
        loaded[prefix] = Namespace(path)

if any(prefix not in loaded for prefix in REQUIRED):
    print(
        "installer GUI widget test: SKIP "
        f"(introspection data not installed: {', '.join(missing)})"
    )
    sys.exit(0)


def ancestry(prefix: str, name: str, seen: set[str] | None = None) -> list[ET.Element]:
    """A type and everything it inherits or implements, across namespaces."""
    seen = set() if seen is None else seen
    key = f"{prefix}.{name}"
    namespace = loaded.get(prefix)
    if key in seen or namespace is None or name not in namespace.types:
        return []
    seen.add(key)
    element = namespace.types[name]
    chain = [element]
    related = [element.get("parent") or ""]
    related += [i.get("name") or "" for i in element.findall("core:implements", NS)]
    for target in related:
        if not target:
            continue
        if "." in target:
            other_prefix, other_name = target.split(".", 1)
        else:
            other_prefix, other_name = prefix, target
        chain.extend(ancestry(other_prefix, other_name, seen))
    return chain


def properties_of(prefix: str, name: str) -> set[str]:
    return {
        (p.get("name") or "").replace("-", "_")
        for element in ancestry(prefix, name)
        for p in element.findall("core:property", NS)
    }


def methods_of(prefix: str, name: str) -> set[str]:
    found: set[str] = set()
    for element in ancestry(prefix, name):
        for tag in ("method", "function", "constructor", "virtual-method"):
            found |= {m.get("name") or "" for m in element.findall(f"core:{tag}", NS)}
    return found


def signals_of(prefix: str, name: str) -> set[str]:
    return {
        s.get("name") or ""
        for element in ancestry(prefix, name)
        for s in element.findall("glib:signal", NS)
    }


tree = ast.parse(open(SOURCE).read(), SOURCE)


def dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def namespace_path(node: ast.AST) -> list[str] | None:
    path = dotted(node)
    if path is None:
        return None
    parts = path.split(".")
    return parts if parts[0] in NAMESPACES else None


def local_types() -> dict[str, set[tuple[str, str]]]:
    """Local names bound to a toolkit constructor, per enclosing function.

    Enough type information to check a signal or a method against the widget
    it is actually used on, rather than against the whole toolkit. A name
    assigned more than one type in a function keeps all of them, and a member
    found on any is accepted - the aim is to catch names that exist nowhere
    near the receiver, not to prove which branch is live.
    """
    bindings: dict[str, set[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Call):
            continue
        parts = namespace_path(node.value.func)
        if parts is None or parts[0] not in loaded or len(parts) not in (2, 3):
            continue
        if parts[1] not in loaded[parts[0]].types:
            continue
        bindings.setdefault(target.id, set()).add((parts[0], parts[1]))
    return bindings


LOCAL = local_types()


def receiver_types(node: ast.AST) -> set[tuple[str, str]]:
    if isinstance(node, ast.Name):
        return LOCAL.get(node.id, set())
    return set()


counts = {"types": 0, "members": 0, "properties": 0, "calls": 0, "signals": 0}

# -- names taken from a namespace --------------------------------------------

for node in ast.walk(tree):
    if not isinstance(node, ast.Attribute):
        continue
    parts = namespace_path(node)
    if parts is None or len(parts) < 2:
        continue
    prefix, name = parts[0], parts[1]
    namespace = loaded.get(prefix)
    if namespace is None:
        continue
    if name not in namespace.types:
        if name in namespace.functions or name in namespace.constants:
            continue
        fail(f"{prefix}.{name} does not exist in {NAMESPACES[prefix]}")
        continue
    counts["types"] += 1
    if len(parts) < 3:
        continue
    member, kind = parts[2], namespace.types[name].tag.split("}")[-1]
    if kind in ("enumeration", "bitfield"):
        if member.upper() not in namespace.enum_members[name]:
            fail(f"{prefix}.{name}.{member} is not a member of that enum")
            continue
    elif member not in methods_of(prefix, name):
        fail(f"{prefix}.{name}.{member} is not a method of that type")
        continue
    counts["members"] += 1

# -- constructor keyword arguments are real properties -----------------------

for node in ast.walk(tree):
    if not isinstance(node, ast.Call) or not node.keywords:
        continue
    parts = namespace_path(node.func)
    if parts is None or len(parts) != 2 or parts[0] not in loaded:
        continue
    prefix, name = parts
    if name not in loaded[prefix].types:
        continue
    available = properties_of(prefix, name)
    if not available:
        continue
    for keyword in node.keywords:
        if keyword.arg is None:
            continue
        if keyword.arg not in available:
            near = sorted(p for p in available if p[:3] == keyword.arg[:3])
            fail(
                f"{prefix}.{name}({keyword.arg}=...) is not a property of that "
                f"type{'; nearest are ' + ', '.join(near) if near else ''}"
            )
            continue
        counts["properties"] += 1

# -- every method name called exists somewhere in the toolkit ----------------
#
# Deliberately weaker than the checks above: the type of every receiver is not
# inferred. It still catches the mistake that actually happens, which is a
# method invented wholesale or remembered from a different toolkit version.

own = {
    node.name
    for node in ast.walk(tree)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
known_methods = set().union(*(n.any_method for n in loaded.values()))
known_signals = set().union(*(n.any_signal for n in loaded.values()))

for node in ast.walk(tree):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        continue
    name = node.func.attr
    if name in own or name in PYTHON_METHODS or name.startswith("_"):
        continue
    # Namespace-qualified names are the first check's business, and a receiver
    # that is one of this project's own objects is nobody's.
    if namespace_path(node.func) is not None:
        continue
    receiver = node.func.value
    if isinstance(receiver, ast.Name) and receiver.id in OURS:
        continue
    if isinstance(receiver, ast.Attribute) and receiver.attr in OURS:
        continue
    if isinstance(receiver, ast.Subscript):
        # self.widgets["..."] - a toolkit object, but which one is not tracked.
        pass
    if name not in known_methods:
        fail(f"{name}() is not a method anywhere in {', '.join(sorted(loaded))}")
        continue
    counts["calls"] += 1

# -- signals connected exist -------------------------------------------------

for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "connect":
        continue
    if not node.args or not isinstance(node.args[0], ast.Constant):
        continue
    signal = node.args[0].value
    if not isinstance(signal, str):
        continue
    base = signal.split("::")[0]
    known_receiver = receiver_types(node.func.value)
    if base == "notify":
        # notify::<property> is defined by GObject, whose GIR may not be here,
        # so the detail is what carries the meaning and what gets checked.
        detail = signal.split("::", 1)[1] if "::" in signal else ""
        if detail:
            scope = known_receiver or {
                (prefix, name)
                for prefix, namespace in loaded.items()
                for name in namespace.types
            }
            if not any(detail in properties_of(prefix, name) for prefix, name in scope):
                where = (
                    ", ".join(f"{p}.{n}" for p, n in sorted(known_receiver))
                    if known_receiver
                    else "any type in the toolkit"
                )
                fail(f"notify::{detail} names a property {where} does not have")
                continue
        counts["signals"] += 1
        continue
    if known_receiver:
        if not any(base in signals_of(prefix, name) for prefix, name in known_receiver):
            where = ", ".join(f"{p}.{n}" for p, n in sorted(known_receiver))
            fail(f"the signal '{base}' is not emitted by {where}")
            continue
    elif base not in known_signals:
        fail(f"the signal '{base}' is not defined by any type in the toolkit")
        continue
    counts["signals"] += 1


if FAILURES:
    for failure in sorted(set(FAILURES)):
        print(f"test-gui-widgets: {failure}", file=sys.stderr)
    sys.exit(1)
print(
    "installer GUI widget test: PASS ("
    + ", ".join(f"{value} {label}" for label, value in counts.items())
    + f"; namespaces {', '.join(sorted(loaded))})"
)
