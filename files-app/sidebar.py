#!/usr/bin/env python3
"""Geometry and glyphs for the AuraDE Files sidebar."""

# ---------------------------------------------------------------- palette ----
# One family, so the column reads as a set rather than as a pile of logos.
TONES = """
  --pl-blue:#4a9eff; --pl-blue-d:#2f7fd8; --pl-slate:#6f7986; --pl-slate-d:#59626e;
  --pl-paper:#8fa3bd; --pl-paper-l:#cbd7e5; --pl-rose:#dd5f92; --pl-green:#3aa86b;
  --pl-violet:#8b6ce0; --pl-teal:#37a3a3; --pl-amber:#e0a33a; --pl-ink:#fff;
"""

R = 'a2.05 2.05 0 0 1'   # the 2.05 corner used by every rounded body

GLYPH = {

"home": f'''<path fill="var(--pl-blue)" d="M8.52 1.72a.82.82 0 0 0-1.04 0L1.86 6.36a1.05
 1.05 0 0 0-.39.81v5.98A1.35 1.35 0 0 0 2.82 14.5h2.63V9.98a.86.86 0 0 1 .86-.86h3.38a.86.86
 0 0 1 .86.86V14.5h2.63a1.35 1.35 0 0 0 1.35-1.35V7.17a1.05 1.05 0 0 0-.39-.81z"/>''',

"desktop": f'''<path fill="var(--pl-slate)" d="M1.4 3.35A1.85 1.85 0 0 1 3.25 1.5h9.5a1.85
 1.85 0 0 1 1.85 1.85v5.5a1.85 1.85 0 0 1-1.85 1.85h-9.5A1.85 1.85 0 0 1 1.4 8.85z"/>
<path fill="var(--pl-blue)" d="M3.05 3.35h9.9a.3.3 0 0 1 .3.3v4.9a.3.3 0 0 1-.3.3h-9.9a.3.3
 0 0 1-.3-.3v-4.9a.3.3 0 0 1 .3-.3z"/>
<path fill="var(--pl-slate-d)" d="M6.25 10.7h3.5l.32 2.05h1.08a.73.73 0 0 1 0 1.45H4.85a.73.73
 0 0 1 0-1.45h1.08z"/>''',

"downloads": f'''<path fill="var(--pl-slate)" d="M1.5 9.25a.82.82 0 0 1 .82.82v1.62c0 .25.2.45.45.45h10.46a.45.45
 0 0 0 .45-.45v-1.62a.82.82 0 1 1 1.64 0v1.62A2.09 2.09 0 0 1 13.23 13.8H2.77A2.09 2.09 0 0 1 .68
 11.69v-1.62a.82.82 0 0 1 .82-.82z"/>
<path fill="var(--pl-blue)" d="M8 1.35a.85.85 0 0 1 .85.85v5.06l1.6-1.6a.85.85 0 1 1 1.2 1.2L8.6
 9.9a.85.85 0 0 1-1.2 0L4.35 6.86a.85.85 0 0 1 1.2-1.2l1.6 1.6V2.2A.85.85 0 0 1 8 1.35z"/>''',

"documents": f'''<path fill="var(--pl-paper)" d="M3.6 2.8A1.6 1.6 0 0 1 5.2 1.2h3.9l3.3
 3.3v8.3a1.6 1.6 0 0 1-1.6 1.6H5.2a1.6 1.6 0 0 1-1.6-1.6z"/>
<path fill="var(--pl-paper-l)" d="M9.1 1.2l3.3 3.3h-2.3a1 1 0 0 1-1-1z"/>
<g fill="var(--pl-ink)" opacity=".8"><rect x="5.6" y="7.3" width="4.8" height="1.05" rx=".52"/>
<rect x="5.6" y="9.7" width="3.3" height="1.05" rx=".52"/></g>''',

"music": f'''<circle cx="8" cy="8" r="6.6" fill="var(--pl-rose)"/>
<path fill="var(--pl-ink)" d="M10.9 4.35a.42.42 0 0 0-.52-.4L6.85 4.8a.42.42 0 0 0-.33.41v4.02h1.1V6.1l2.62-.6v2.62h1.1z"/>
<ellipse cx="5.85" cy="10.35" rx="1.65" ry="1.42" fill="var(--pl-ink)"/>
<ellipse cx="9.9" cy="9.45" rx="1.65" ry="1.42" fill="var(--pl-ink)"/>''',

"pictures": f'''<rect x="1.6" y="2.45" width="12.8" height="11.1" rx="2.1" fill="none"
 stroke="var(--pl-green)" stroke-width="1.5"/>
<circle cx="5.5" cy="6.25" r="1.15" fill="var(--pl-green)"/>
<path fill="var(--pl-green)" d="M2.55 12.85l2.9-2.86a.85.85 0 0 1 1.2 0l1.55 1.53 1.35-1.33a.85.85
 0 0 1 1.2 0l2.75 2.71z"/>''',

"videos": f'''<rect x="1.6" y="2.45" width="12.8" height="11.1" rx="2.1" fill="none"
 stroke="var(--pl-violet)" stroke-width="1.5"/>
<path fill="var(--pl-violet)" d="M6.55 5.55l3.9 2.19a.3.3 0 0 1 0 .52l-3.9 2.19a.3.3 0 0
 1-.45-.26V5.81a.3.3 0 0 1 .45-.26z"/>''',

"trash": f'''<path fill="var(--pl-blue)" d="M6.15 1.5h3.7a.95.95 0 0 1 .95.95v.62h2.9a.7.7
 0 0 1 0 1.4H2.3a.7.7 0 0 1 0-1.4h2.9v-.62a.95.95 0 0 1 .95-.95zm.72 1.57h2.26v-.37H6.87z"/>
<path fill="none" stroke="var(--pl-slate)" stroke-width="1.35" stroke-linecap="round"
 d="M4.15 5.75l.5 7.05a1.35 1.35 0 0 0 1.35 1.25h4a1.35 1.35 0 0 0 1.35-1.25l.5-7.05"/>''',

"folder": f'''<path fill="var(--pl-amber)" d="M1.4 4.05A1.6 1.6 0 0 1 3 2.45h2.9a1.6 1.6 0
 0 1 1.13.47l1.03 1.03H13A1.6 1.6 0 0 1 14.6 5.55v6.4A1.6 1.6 0 0 1 13 13.55H3a1.6 1.6 0 0
 1-1.6-1.6z"/>''',

"drive": f'''<path fill="var(--pl-slate)" d="M1.4 5.15A1.85 1.85 0 0 1 3.25 3.3h9.5a1.85 1.85
 0 0 1 1.85 1.85v5.7a1.85 1.85 0 0 1-1.85 1.85h-9.5A1.85 1.85 0 0 1 1.4 10.85z"/>
<rect x="3.2" y="5.25" width="5.4" height="1.4" rx=".7" fill="var(--pl-ink)" opacity=".45"/>
<rect x="10.4" y="9.3" width="2.5" height="1.65" rx=".6" fill="var(--pl-blue)"/>''',

"usb": f'''<path fill="var(--pl-blue)" d="M7.2 1.3h1.6v5.2H7.2z"/>
<path fill="var(--pl-slate)" d="M5.4 5.9h5.2a1.5 1.5 0 0 1 1.5 1.5v5.35a1.5 1.5 0 0 1-1.5
 1.5H5.4a1.5 1.5 0 0 1-1.5-1.5V7.4a1.5 1.5 0 0 1 1.5-1.5z"/>
<g fill="var(--pl-ink)" opacity=".55"><rect x="5.6" y="8.4" width="1.5" height="1.5" rx=".45"/>
<rect x="8.9" y="8.4" width="1.5" height="1.5" rx=".45"/></g>''',

"cloud": f'''<path fill="var(--pl-blue)" d="M4.75 13.4a3.55 3.55 0 0 1-.32-7.08 4.35 4.35 0
 1 1 8.19 1.06 2.98 2.98 0 0 1-.55 6.02z"/>''',

"network": f'''<circle cx="8" cy="8" r="6.35" fill="var(--pl-teal)"/>
<g fill="none" stroke="var(--pl-ink)" stroke-width="1.05" opacity=".85">
<path d="M1.75 8h12.5"/><ellipse cx="8" cy="8" rx="3.05" ry="6.3"/></g>''',

"pin": f'''<path fill="var(--pl-amber)" d="M9.72 1.46a1.1 1.1 0 0 1 1.56 0l3.26 3.26a1.1 1.1
 0 0 1-.6 1.86l-1.86.35-3.2 3.2.3 1.2a1.1 1.1 0 0 1-.29 1.05l-.5.5a1.1 1.1 0 0 1-1.56 0L4.4
 10.19l-2.7 2.7a.72.72 0 1 1-1.02-1.02l2.7-2.7-1.7-1.69a1.1 1.1 0 0 1 0-1.56l.5-.5a1.1 1.1 0
 0 1 1.05-.29l1.2.3 3.2-3.2.35-1.86a1.1 1.1 0 0 1 .3-.58z"/>''',

"tag": f'''<path fill="var(--pl-amber)" d="M2.2 3.6a1.4 1.4 0 0 1 1.4-1.4h4.1a1.4 1.4 0 0 1
 .99.41l5 5a1.4 1.4 0 0 1 0 1.98l-4.1 4.1a1.4 1.4 0 0 1-1.98 0l-5-5a1.4 1.4 0 0 1-.41-.99z"/>
<circle cx="5.35" cy="5.35" r="1.25" fill="var(--pl-ink)"/>''',
}

CHEVRON = ('<svg class="chev" width="12" height="12" viewBox="0 0 12 12" fill="none" '
           'stroke="currentColor" stroke-width="1.25" stroke-linecap="round" '
           'stroke-linejoin="round"><path d="M4.4 2.6L7.8 6l-3.4 3.4"/></svg>')

PIN = ('<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" '
       'stroke-width="1.05" stroke-linecap="round" stroke-linejoin="round">'
       '<path d="M7.1 1.3l3.6 3.6M6.3 2.1L4.1 4.3 2 5.1l4.9 4.9.8-2.1 2.2-2.2"/>'
       '<path d="M3.5 8.5L1.3 10.7"/></svg>')

EJECT = ('<svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">'
         '<path d="M6 1.4l4.3 5.1a.5.5 0 0 1-.38.83H2.08a.5.5 0 0 1-.38-.83z"/>'
         '<rect x="1.7" y="9" width="8.6" height="1.6" rx=".8"/></svg>')


def glyph(kind, px=16):
    return (f'<svg class="pg" width="{px}" height="{px}" viewBox="0 0 16 16" '
            f'aria-hidden="true">{GLYPH[kind]}</svg>')


# ------------------------------------------------------------------ model ----
# Built from real `Volume` records rather than a table. The port already draws
# the distinction this needs: `kind` says what the storage is made of and decides
# which group a place files under, `purpose` says what it is for and decides what
# it looks like. Nothing is invented here, so a machine with no Videos folder
# gets no Videos row.

_GLYPH_BY_PURPOSE = {
    "home": "home", "desktop": "desktop", "documents": "documents",
    "downloads": "downloads", "music": "music", "pictures": "pictures",
    "videos": "videos",
}
_GLYPH_BY_KIND = {
    "removable": "usb", "system": "drive", "trash": "trash",
    "drive": "cloud", "provided": "cloud", "mtp": "usb",
    "archive": "drive", "android": "usb", "crostini": "drive",
    "recent": "documents",
}


def _glyph_for(volume):
    purpose = volume.get("purpose")
    if purpose in _GLYPH_BY_PURPOSE:
        return _GLYPH_BY_PURPOSE[purpose]
    return _GLYPH_BY_KIND.get(volume["kind"], "drive")


SECTION_GLYPH = {"Pinned": "pin", "Drives": "drive", "Cloud Drives": "cloud",
                 "Network": "network", "Tags": "tag"}


def _group_for(volume):
    """Which section a volume files under. Home is its own row above them all."""
    if volume.get("purpose") == "home":
        return "home"
    if volume["kind"] in ("drive", "provided"):
        return "Cloud Drives"
    if volume["kind"] == "trash" or volume.get("purpose"):
        return "Pinned"
    return "Drives"


def build(volumes, children_for=None):
    """Volumes to a sidebar tree. Sections appear only when something is in them.

    A section is a node with children rather than a flat header row, because the
    real app indents everything under its section by one level and lets a drive
    carry children of its own.
    """
    groups = {"Pinned": [], "Drives": [], "Cloud Drives": []}
    rows = []
    for v in volumes:
        group = _group_for(v)
        node = {"t": "item", "label": v["label"], "glyph": _glyph_for(v),
                "trail": None, "root": v["root"], "sec": group, "vol": v,
                "kids": [], "open": False}
        if group == "home":
            node["sec"] = "home"
            rows.append(node)
            continue
        node["trail"] = "eject" if v.get("removable") else (
            "pin" if group == "Pinned" and v["kind"] != "trash" else None)
        if group == "Drives" and children_for:
            node["kids"] = [
                {"t": "item", "label": name, "glyph": "folder", "trail": None,
                 "root": root, "sec": group, "vol": None, "kids": [], "open": False}
                for name, root in children_for(v)]
        groups[group].append(node)
    for name in ("Pinned", "Drives", "Cloud Drives"):
        if not groups[name]:
            continue
        rows.append({"t": "head", "label": name, "glyph": SECTION_GLYPH[name],
                     "sec": name, "kids": groups[name], "open": True})
    # Real Files sections that hold nothing on this machine. They stay, closed,
    # because they are places the app can reach, not decoration.
    for name in ("Network", "Tags"):
        rows.append({"t": "head", "label": name, "glyph": SECTION_GLYPH[name],
                     "sec": name, "kids": [], "open": False})
    return rows


def _drive_data(vol):
    cap = (vol or {}).get("capacity") or {}
    total = cap.get("total", 0)
    free = cap.get("free", 0)
    used = max(0, total - free)
    pct = int((used / total) * 100) if total > 0 else 0
    return (f' data-kind="drive" data-total="{total}" data-free="{free}"'
            f' data-used="{used}" data-pct="{pct}" data-fs="ext4"')


def _render_node(node, level, selected_root, href_for, out):
    kids = node.get("kids") or []
    is_open = bool(node.get("open"))
    lv = f" lv{level}"
    chev = (f'<span class="cslot">{CHEVRON}</span>' if kids
            else '<span class="cslot"></span>')

    if node["t"] == "head":
        state = "" if is_open else " shut"
        out.append(f'<div class="sgrp{state}" data-sec="{node["sec"]}">'
                   f'<div class="srow head{lv}" role="button" tabindex="0">'
                   f'{chev}{glyph(node["glyph"])}'
                   f'<span class="lbl">{node["label"]}</span></div>')
    else:
        sel = " sel" if node["root"] and node["root"] == selected_root else ""
        vol = node.get("vol")
        dat = f' data-root="{node["root"]}" data-n="{node["label"]}"'
        if node["sec"] == "Drives" and vol:
            dat += _drive_data(vol)
        else:
            dat += ' data-kind="folder"'
        trail = ""
        if node["trail"] == "pin":
            trail = f'<span class="trail">{PIN}</span>'
        elif node["trail"] == "eject":
            trail = f'<span class="trail">{EJECT}</span>'
        href = href_for(node["root"]) if href_for else None
        open_tag = (f'<a class="srow item{lv}{sel}" href="{href}"{dat}>' if href
                    else f'<div class="srow item{lv}{sel}"{dat}>')
        close = "</a>" if href else "</div>"
        state = "" if is_open else " shut"
        if kids:
            out.append(f'<div class="sgrp{state}" data-sec="{node["label"]}">')
        out.append(f'{open_tag}<span class="ind"></span>{chev}'
                   f'{glyph(node["glyph"])}<span class="lbl">{node["label"]}</span>'
                   f'{trail}{close}')

    if kids:
        out.append('<div class="skids">')
        for kid in kids:
            _render_node(kid, level + 1, selected_root, href_for, out)
        out.append('</div></div>')


def render(volumes=None, selected_root=None, href_for=None, children_for=None):
    out = []
    for node in build(volumes if volumes is not None else [], children_for):
        _render_node(node, 0, selected_root, href_for, out)
    return "\n".join(out)


CSS = """
.sidebar {{ width:255px; flex:none; display:flex; flex-direction:column;
  background:var(--sidebar-bg, var(--layer-mica-alt));
  border-radius:0 8px 0 8px; {tones} }}
.slist {{ flex:1; overflow:auto; padding:4px 0 8px; }}
/* flex columns, not blocks: adjacent .srow margins collapse in a block
   container and the 32px pitch comes out as 30. */
.slist, .sgrp, .skids {{ display:flex; flex-direction:column; }}

/* 28px fill on a 32px pitch, 8px in from each edge, one 16px indent per level.
   Measured off the running app at 150% scale: chevron column at 12, glyph at
   34, label at 58, each +16 per level down the tree. */
.srow {{ position:relative; height:28px; margin:2px 8px; padding-left:4px;
  border-radius:var(--r-ctl); display:flex; align-items:center; cursor:default;
  border:1px solid transparent; box-sizing:border-box;
  transition:background-color 83ms ease-out, border-color 83ms ease-out; }}
.srow.lv1 {{ padding-left:20px; }}
.srow.lv2 {{ padding-left:36px; }}
.srow.lv3 {{ padding-left:52px; }}

.srow .cslot {{ flex:none; width:12px; height:12px; margin-right:10px;
  display:grid; place-items:center; color:var(--text-2); }}
.srow .pg {{ flex:none; }}
.srow .lbl {{ flex:1; min-width:0; margin-left:8px; font-size:14px; line-height:20px;
  color:var(--text-1); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}

.srow .ind {{ position:absolute; left:1px; top:50%; transform:translateY(-50%);
  width:3px; height:0; border-radius:1.5px; background:var(--accent); opacity:0;
  transition:height 167ms cubic-bezier(0.1,0.9,0.2,1.0), opacity 167ms ease-out; }}
.srow:hover {{ background:var(--subtle-2); }}
.srow:active {{ background:var(--subtle-3); }}
.srow.sel {{ background:var(--sel-fill); border-color:var(--sel-stroke); }}
.srow.sel .ind {{ opacity:1; height:16px; }}

/* the pin and the eject are hover affordances, not decoration */
.trail {{ flex:none; margin-left:8px; margin-right:4px; display:grid;
  place-items:center; color:var(--text-3); opacity:0;
  transition:opacity 83ms ease-out; }}
.srow:hover .trail, .srow.sel .trail, .trail:focus-visible {{ opacity:1; }}

/* a section is a group, so its children indent under its header */
.sgrp {{ margin-top:12px; }}
.sgrp + .sgrp {{ margin-top:12px; }}
.slist > .srow:first-child + .sgrp {{ margin-top:12px; }}
.slist > .sgrp:first-child {{ margin-top:2px; }}
.skids .sgrp {{ margin-top:0; }}
.sgrp.shut > .skids {{ display:none; }}
.srow .chev {{ transition:transform 200ms cubic-bezier(0.1,0.9,0.2,1.0); }}
.sgrp:not(.shut) > .srow .chev {{ transform:rotate(90deg); }}

.sfoot {{ flex:none; padding:2px 4px; }}
.sfoot .sfdiv {{ height:1px; background:var(--control-stroke); }}
.sfoot .srow {{ margin:2px 8px; padding-left:4px; }}
.sfoot .srow .pg, .sfoot .srow > svg {{ flex:none; width:16px; height:16px;
  margin-left:22px; }}
.sfoot .srow .lbl {{ flex:1; margin-left:8px; font-size:14px; color:var(--text-1); }}
"""


def css():
    return CSS.format(tones=TONES.strip())
