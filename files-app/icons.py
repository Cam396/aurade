#!/usr/bin/env python3
"""File type icons and icon theme selection for AuraDE Files."""
from __future__ import annotations

import os
import re

# ------------------------------------------------------------------ tints ----
# One family. The letter badges borrow the language's own colour where there is
# a widely recognised one, and stay in the family where there is not.
TINTS = {
    "t-md": "#4b7fd4", "t-py": "#2f7f6a", "t-zip": "#8a6bbd",
    "t-cfg": "#6d6f78", "t-img": "#3f8f5e",
    "t-code": "#4a7fb5", "t-web": "#c98a3e", "t-style": "#3f8fa8",
    "t-data": "#7a8b3f", "t-shell": "#4d5560", "t-pdf": "#c0392b",
    "t-doc": "#2b5797", "t-sheet": "#1e7145", "t-slides": "#c0562b",
    "t-font": "#a98add", "t-cert": "#b8862b", "t-db": "#3f7fa8",
    "t-book": "#a8593f", "t-patch": "#5f8a3f",
}

# ------------------------------------------------------------------ paper ----
DOC_BODY = ('<path d="M4 4a3 3 0 0 1 3-3h17l12 12v31a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3z"'
            ' fill="var(--doc-face)" stroke="var(--doc-edge)" stroke-width="1"/>'
            '<path d="M24 1l12 12H27a3 3 0 0 1-3-3z" fill="var(--doc-fold)"/>')

RULES = ('<g fill="var(--doc-rule)">'
         '<rect x="10" y="18" width="20" height="1.6" rx=".8"/>'
         '<rect x="10" y="23" width="20" height="1.6" rx=".8"/>'
         '<rect x="10" y="28" width="13" height="1.6" rx=".8"/></g>')

DOC_BODY_SM = ('<path d="M3.5 1h5l5 5v7.5c0 .83-.67 1.5-1.5 1.5h-8.5c-.83 0-1.5-.67'
               '-1.5-1.5V2.5c0-.83.67-1.5 1.5-1.5z" fill="var(--doc-face)"'
               ' stroke="var(--doc-edge)" stroke-width="1"/>'
               '<path d="M8.5 1v4c0 .55.45 1 1 1h4z" fill="var(--doc-fold)"/>')

RULES_SM = ('<path d="M5.5 7.5h5M5.5 10h3" stroke="var(--doc-rule)"'
            ' stroke-width="1" stroke-linecap="round"/>')
RULES_TXT_SM = ('<path d="M5.5 6.5h5M5.5 9h5M5.5 11.5h3.5" stroke="var(--doc-rule)"'
                ' stroke-width="1" stroke-linecap="round"/>')


def _obj(inner):
    """An object glyph. Square viewBox, because a photo or a disc is not a page.

    .art is a fixed square and SVG letterboxes on the short axis, so a 48x48
    object draws to the full box while a 40x48 page draws narrower and a 48x40
    folder draws shorter. That difference is deliberate and matches the
    reference, where a folder is wider than it is tall.
    """
    return f'<svg class="art" viewBox="0 0 48 48" aria-hidden="true">{inner}</svg>'


def _small(inner):
    return f'<svg class="art" viewBox="0 0 16 16" aria-hidden="true">{inner}</svg>'


def paper(tint="", letter="", rules=RULES, size=13, extra=""):
    """A page with an optional coloured tab. The tab is what carries the type,
    which is how the reference does it for every office and source format."""
    tab = ""
    if tint:
        tab = (f'<rect x="2" y="26" width="26" height="16" rx="3" fill="{tint}"/>'
               f'<text x="15" y="39" text-anchor="middle" font-size="{size}"'
               f' font-weight="600" fill="#fff"'
               f' font-family="var(--font)">{letter}</text>')
    return (f'<svg class="art" viewBox="0 0 40 48" aria-hidden="true">'
            f'{DOC_BODY}{rules}{tab}{extra}</svg>')


def paper_sm(tint="", letter="", rules=RULES_SM, size=5, extra=""):
    tab = ""
    if tint:
        tab = (f'<rect x="1" y="8.5" width="9.5" height="6.5" rx="1.5" fill="{tint}"/>'
               f'<text x="5.75" y="13.5" text-anchor="middle" font-size="{size}"'
               f' font-weight="700" fill="#fff"'
               f' font-family="var(--font)">{letter}</text>')
    return _small(f"{DOC_BODY_SM}{rules}{tab}{extra}")


# ----------------------------------------------------------------- shapes ----
# The kinds that are not paper. Each is an object, so a folder of photos does
# not read as a folder of documents.

FOLDER = ('<svg class="art" viewBox="0 0 48 40" aria-hidden="true">'
          '<path d="M1 6a4 4 0 0 1 4-4h12.3a4 4 0 0 1 2.9 1.2L24 7h19a4 4 0 0 1 4 4v3H1z"'
          ' fill="var(--folder-back)"/>'
          '<path d="M1 12h46v22a4 4 0 0 1-4 4H5a4 4 0 0 1-4-4z" fill="url(#fg)"/>'
          '<defs><linearGradient id="fg" x1="0" y1="12" x2="10" y2="40"'
          ' gradientUnits="userSpaceOnUse"><stop stop-color="var(--folder-a)"/>'
          '<stop offset="1" stop-color="var(--folder-b)"/></linearGradient></defs></svg>')

FOLDER_SM = _small(
    '<path d="M1 3.5C1 2.67 1.67 2 2.5 2h3.2c.45 0 .88.2 1.17.55L8.1 4H13.5c.83 0'
    ' 1.5.67 1.5 1.5V7H1V3.5z" fill="var(--folder-back)"/>'
    '<path d="M1 5.5h14v7c0 .83-.67 1.5-1.5 1.5h-11C1.67 14 1 13.33 1 12.5v-7z"'
    ' fill="url(#fg-sm)"/>'
    '<defs><linearGradient id="fg-sm" x1="0" y1="5" x2="0" y2="14"'
    ' gradientUnits="userSpaceOnUse"><stop stop-color="var(--folder-a)"/>'
    '<stop offset="1" stop-color="var(--folder-b)"/></linearGradient></defs>')

# A photograph, not a page with IMG on it: sky, sun, two ridges.
IMAGE = _obj(
    '<rect x="4" y="8" width="40" height="32" rx="4" fill="#2f6f4e"/>'
    '<rect x="6" y="10" width="36" height="28" rx="2.5" fill="#8fd0a8"/>'
    '<circle cx="16" cy="19" r="4" fill="#fff6c4"/>'
    '<path d="M6 33l9-9 6.5 6.5L28 24l14 14H6z" fill="#3f8f5e"/>'
    '<path d="M22 38l6-6 8 6z" fill="#2f6f4e" opacity=".55"/>')

IMAGE_SM = _small(
    '<rect x="1" y="3" width="14" height="10" rx="1.6" fill="#2f6f4e"/>'
    '<rect x="2" y="4" width="12" height="8" rx="1" fill="#8fd0a8"/>'
    '<circle cx="5.2" cy="6.6" r="1.3" fill="#fff6c4"/>'
    '<path d="M2 12v-1.6l3-3 2.4 2.4L10 7.3l4 4.2V12z" fill="#3f8f5e"/>')

# A pen nib path with its bezier handles, which is what a vector file is.
VECTOR = _obj(
    '<rect x="4" y="8" width="40" height="32" rx="4" fill="#37506b"/>'
    '<rect x="6" y="10" width="36" height="28" rx="2.5" fill="#5b7ea6"/>'
    '<path d="M12 32c8-2 10-14 24-16" fill="none" stroke="#fff" stroke-width="2"'
    ' stroke-linecap="round" opacity=".9"/>'
    '<rect x="8" y="28" width="7" height="7" rx="1.4" fill="#fff"/>'
    '<rect x="33" y="12" width="7" height="7" rx="1.4" fill="#fff"/>')

VECTOR_SM = _small(
    '<rect x="1" y="3" width="14" height="10" rx="1.6" fill="#37506b"/>'
    '<rect x="2" y="4" width="12" height="8" rx="1" fill="#5b7ea6"/>'
    '<path d="M4 10.5c2.6-.6 3.2-4.4 8-5.2" fill="none" stroke="#fff"'
    ' stroke-width="1.1" stroke-linecap="round"/>'
    '<rect x="2.6" y="9.4" width="2.6" height="2.6" rx=".7" fill="#fff"/>'
    '<rect x="11" y="4.1" width="2.6" height="2.6" rx=".7" fill="#fff"/>')

AUDIO = _obj(
    '<rect x="4" y="6" width="40" height="36" rx="8" fill="#b03a6a"/>'
    '<path d="M31 12.5a1.6 1.6 0 0 0-2-1.55l-11.5 2.6A1.6 1.6 0 0 0 16.2 15v13.6h3.6'
    'V19.4l7.6-1.7v8.9H31z" fill="#fff"/>'
    '<ellipse cx="14.4" cy="30.4" rx="4.6" ry="4" fill="#fff"/>'
    '<ellipse cx="26" cy="27.9" rx="4.6" ry="4" fill="#fff"/>')

AUDIO_SM = _small(
    '<rect x="1.5" y="2" width="13" height="12" rx="2.6" fill="#b03a6a"/>'
    '<path d="M10.6 4.6a.5.5 0 0 0-.62-.48l-3.6.8a.5.5 0 0 0-.38.49V9.4h1.1V6.4l2.4-.53'
    'v2.8h1.1z" fill="#fff"/>'
    '<ellipse cx="5.4" cy="10.3" rx="1.5" ry="1.3" fill="#fff"/>'
    '<ellipse cx="9.4" cy="9.5" rx="1.5" ry="1.3" fill="#fff"/>')

VIDEO = _obj(
    '<rect x="4" y="8" width="40" height="32" rx="4" fill="#4a3b74"/>'
    '<g fill="#241d3d">'
    '<rect x="6" y="11" width="5" height="4" rx="1"/><rect x="6" y="19" width="5"'
    ' height="4" rx="1"/><rect x="6" y="27" width="5" height="4" rx="1"/>'
    '<rect x="6" y="35" width="5" height="3" rx="1"/>'
    '<rect x="37" y="11" width="5" height="4" rx="1"/><rect x="37" y="19" width="5"'
    ' height="4" rx="1"/><rect x="37" y="27" width="5" height="4" rx="1"/>'
    '<rect x="37" y="35" width="5" height="3" rx="1"/></g>'
    '<rect x="13" y="11" width="22" height="27" rx="2" fill="#8b6ce0"/>'
    '<path d="M20.5 17.5l9.5 6.5-9.5 6.5z" fill="#fff"/>')

VIDEO_SM = _small(
    '<rect x="1" y="3" width="14" height="10" rx="1.6" fill="#4a3b74"/>'
    '<g fill="#241d3d"><rect x="1.7" y="4.1" width="1.6" height="1.5" rx=".4"/>'
    '<rect x="1.7" y="7.3" width="1.6" height="1.5" rx=".4"/>'
    '<rect x="1.7" y="10.5" width="1.6" height="1.4" rx=".4"/>'
    '<rect x="12.7" y="4.1" width="1.6" height="1.5" rx=".4"/>'
    '<rect x="12.7" y="7.3" width="1.6" height="1.5" rx=".4"/>'
    '<rect x="12.7" y="10.5" width="1.6" height="1.4" rx=".4"/></g>'
    '<rect x="4.2" y="4.1" width="7.6" height="7.8" rx=".8" fill="#8b6ce0"/>'
    '<path d="M6.9 6.2l3 1.8-3 1.8z" fill="#fff"/>')

# A folder that has been zipped shut, which is what the reference draws.
ARCHIVE = ('<svg class="art" viewBox="0 0 48 40" aria-hidden="true">'
           '<path d="M1 6a4 4 0 0 1 4-4h12.3a4 4 0 0 1 2.9 1.2L24 7h19a4 4 0 0 1 4 4v3H1z"'
           ' fill="#6b4f96"/>'
           '<path d="M1 12h46v22a4 4 0 0 1-4 4H5a4 4 0 0 1-4-4z" fill="#8a6bbd"/>'
           '<rect x="20.5" y="12" width="7" height="16" rx="1.4" fill="#efe6ff"/>'
           '<g fill="#6b4f96"><rect x="22.4" y="14" width="3.2" height="2" rx=".6"/>'
           '<rect x="22.4" y="18" width="3.2" height="2" rx=".6"/>'
           '<rect x="22.4" y="22" width="3.2" height="2" rx=".6"/></g>'
           '<rect x="21.6" y="27" width="4.8" height="6" rx="1.6" fill="#efe6ff"/>'
           '<circle cx="24" cy="30" r="1.2" fill="#6b4f96"/></svg>')

ARCHIVE_SM = _small(
    '<path d="M1 3.5C1 2.67 1.67 2 2.5 2h3.2c.45 0 .88.2 1.17.55L8.1 4H13.5c.83 0'
    ' 1.5.67 1.5 1.5V7H1V3.5z" fill="#6b4f96"/>'
    '<path d="M1 5.5h14v7c0 .83-.67 1.5-1.5 1.5h-11C1.67 14 1 13.33 1 12.5v-7z"'
    ' fill="#8a6bbd"/>'
    '<rect x="6.8" y="5.5" width="2.4" height="4.4" rx=".5" fill="#efe6ff"/>'
    '<rect x="6.6" y="9.9" width="2.8" height="3.2" rx=".9" fill="#efe6ff"/>'
    '<circle cx="8" cy="11.4" r=".65" fill="#6b4f96"/>')

DISK = _obj(
    '<circle cx="24" cy="24" r="19" fill="#5b6470"/>'
    '<circle cx="24" cy="24" r="19" fill="none" stroke="#7d8794" stroke-width="1.6"/>'
    '<g fill="none" stroke="#c4d4e4" stroke-linecap="round" opacity=".5">'
    '<path d="M10.6 10.6a19 19 0 0 1 13.4-5.6" stroke-width="3.4"/>'
    '<path d="M13.6 13.6a14.7 14.7 0 0 1 10.4-4.3" stroke-width="2"/></g>'
    '<circle cx="24" cy="24" r="6.5" fill="var(--doc-face)"/>'
    '<circle cx="24" cy="24" r="2.6" fill="#5b6470"/>')

DISK_SM = _small(
    '<circle cx="8" cy="8" r="6.4" fill="#5b6470"/>'
    '<path d="M3.5 3.5A6.4 6.4 0 0 1 8 1.6" fill="none" stroke="#c4d4e4"'
    ' stroke-width="1.5" stroke-linecap="round" opacity=".55"/>'
    '<circle cx="8" cy="8" r="2.2" fill="var(--doc-face)"/>'
    '<circle cx="8" cy="8" r=".9" fill="#5b6470"/>')

PACKAGE = _obj(
    '<path d="M24 4l18 8v24l-18 8-18-8V12z" fill="#a8703f"/>'
    '<path d="M24 4l18 8-18 8-18-8z" fill="#c98a3e"/>'
    '<path d="M24 20v24l18-8V12z" fill="#8a5a30"/>'
    '<path d="M14 8.5l18 8v6l-4 1.8v-6l-18-8z" fill="#e0b070"/>')

PACKAGE_SM = _small(
    '<path d="M8 1.4l6 2.7v7.8L8 14.6l-6-2.7V4.1z" fill="#a8703f"/>'
    '<path d="M8 1.4l6 2.7-6 2.7-6-2.7z" fill="#c98a3e"/>'
    '<path d="M8 6.8v7.8l6-2.7V4.1z" fill="#8a5a30"/>')

# An application, drawn as its window rather than as a cog.
APP = _obj(
    '<rect x="5" y="7" width="38" height="34" rx="5" fill="#2f4f7a"/>'
    '<path d="M5 12a5 5 0 0 1 5-5h28a5 5 0 0 1 5 5v4H5z" fill="#3f6ba8"/>'
    '<g fill="#cfe0f5"><circle cx="11" cy="11.5" r="1.6"/>'
    '<circle cx="16.4" cy="11.5" r="1.6"/><circle cx="21.8" cy="11.5" r="1.6"/></g>'
    '<path fill="#8fb8e8" d="M21.71 17.24L26.29 17.24L25.38 20.53L28.3 21.74'
    'L29.99 18.77L33.23 22.01L30.26 23.7L31.47 26.62L34.76 25.71L34.76 30.29'
    'L31.47 29.38L30.26 32.3L33.23 33.99L29.99 37.23L28.3 34.26L25.38 35.47'
    'L26.29 38.76L21.71 38.76L22.62 35.47L19.7 34.26L18.01 37.23L14.77 33.99'
    'L17.74 32.3L16.53 29.38L13.24 30.29L13.24 25.71L16.53 26.62L17.74 23.7'
    'L14.77 22.01L18.01 18.77L19.7 21.74L22.62 20.53z"/>'
    '<circle cx="24" cy="28" r="3.6" fill="#2f4f7a"/>')

APP_SM = _small(
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.8" fill="#2f4f7a"/>'
    '<path d="M1.5 4.3a1.8 1.8 0 0 1 1.8-1.8h9.4a1.8 1.8 0 0 1 1.8 1.8v1.2h-13z"'
    ' fill="#3f6ba8"/>'
    '<g fill="#cfe0f5"><circle cx="3.4" cy="4" r=".6"/><circle cx="5.2" cy="4" r=".6"/>'
    '<circle cx="7" cy="4" r=".6"/></g>'
    '<path fill="#8fb8e8" d="M7.03 5.52L8.97 5.52L8.74 6.8L9.88 7.46L10.88 6.62'
    'L11.85 8.3L10.62 8.75L10.62 10.05L11.85 10.5L10.88 12.18L9.88 11.34'
    'L8.74 12L8.97 13.28L7.03 13.28L7.26 12L6.12 11.34L5.12 12.18L4.15 10.5'
    'L5.38 10.05L5.38 8.75L4.15 8.3L5.12 6.62L6.12 7.46L7.26 6.8z"/>'
    '<circle cx="8" cy="9.4" r="1.35" fill="#2f4f7a"/>')

FONT = paper(extra='<text x="20" y="36" text-anchor="middle" font-size="24"'
                   ' font-weight="600" fill="var(--t-font)"'
                   ' font-family="Georgia, serif">Aa</text>', rules="")

FONT_SM = paper_sm(extra='<text x="8" y="12.4" text-anchor="middle" font-size="8"'
                         ' font-weight="600" fill="var(--t-font)"'
                         ' font-family="Georgia, serif">A</text>', rules="")

CERT = _obj(
    '<path d="M24 3l16 5v16c0 10-7 18-16 21-9-3-16-11-16-21V8z" fill="#b8862b"/>'
    '<path d="M24 3l16 5v16c0 10-7 18-16 21z" fill="#8f6820"/>'
    '<path d="M22 25.5h4l-.9 8.5-1.1 1.4-1.1-1.4z" fill="#fff3d6"/>'
    '<circle cx="24" cy="21" r="5.5" fill="#fff3d6"/>'
    '<circle cx="24" cy="21" r="2" fill="#8f6820"/>')

CERT_SM = _small(
    '<path d="M8 1.2l5.4 1.7v5.3c0 3.4-2.3 6-5.4 7-3.1-1-5.4-3.6-5.4-7V2.9z"'
    ' fill="#b8862b"/>'
    '<path d="M8 1.2l5.4 1.7v5.3c0 3.4-2.3 6-5.4 7z" fill="#8f6820"/>'
    '<path d="M7.3 8.2h1.4l-.35 3-.35.4-.35-.4z" fill="#fff3d6"/>'
    '<circle cx="8" cy="6.6" r="1.9" fill="#fff3d6"/>')

DATABASE = _obj(
    '<path d="M8 11v26c0 3.3 7.2 6 16 6s16-2.7 16-6V11z" fill="#3f7fa8"/>'
    '<ellipse cx="24" cy="11" rx="16" ry="6" fill="#7fc4e4"/>'
    '<path d="M8 21c0 3.3 7.2 6 16 6s16-2.7 16-6" fill="none" stroke="#2c6183"'
    ' stroke-width="2"/>'
    '<path d="M8 31c0 3.3 7.2 6 16 6s16-2.7 16-6" fill="none" stroke="#2c6183"'
    ' stroke-width="2"/>')

DATABASE_SM = _small(
    '<path d="M2.5 4v8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2V4z" fill="#3f7fa8"/>'
    '<ellipse cx="8" cy="4" rx="5.5" ry="2.1" fill="#7fc4e4"/>'
    '<path d="M2.5 8c0 1.16 2.46 2.1 5.5 2.1S13.5 9.16 13.5 8" fill="none"'
    ' stroke="#2c6183" stroke-width="1"/>')

EBOOK = _obj(
    '<path d="M13 4h24a4 4 0 0 1 4 4v32a4 4 0 0 1-4 4H13z" fill="#c97a5e"/>'
    '<rect x="7" y="4" width="6" height="40" fill="#8a4530"/>'
    '<g fill="#ffe8dc"><rect x="19" y="16" width="16" height="2.4" rx="1.2"/>'
    '<rect x="19" y="22" width="16" height="2.4" rx="1.2"/>'
    '<rect x="19" y="28" width="10" height="2.4" rx="1.2"/></g>')

EBOOK_SM = _small(
    '<path d="M2.5 2.6A1.6 1.6 0 0 1 4.1 1h8.3A1.6 1.6 0 0 1 14 2.6v10.8A1.6 1.6 0 0 1'
    ' 12.4 15H4.1a1.6 1.6 0 0 1-1.6-1.6z" fill="#c97a5e"/>'
    '<rect x="2.5" y="1" width="2.2" height="14" fill="#8a4530"/>'
    '<g fill="#ffe8dc"><rect x="6.2" y="5" width="5.8" height="1" rx=".5"/>'
    '<rect x="6.2" y="7.4" width="5.8" height="1" rx=".5"/>'
    '<rect x="6.2" y="9.8" width="3.6" height="1" rx=".5"/></g>')

CONTACT = paper(rules="", extra='<circle cx="20" cy="23" r="6" fill="#4a9eff"/>'
                                '<path d="M9 40c0-6.1 4.9-11 11-11s11 4.9 11 11z"'
                                ' fill="#4a9eff"/>')

CONTACT_SM = paper_sm(rules="", extra='<circle cx="8" cy="8" r="2" fill="#4a9eff"/>'
                                      '<path d="M4.6 14c0-1.9 1.5-3.4 3.4-3.4'
                                      's3.4 1.5 3.4 3.4z" fill="#4a9eff"/>')

LINK = paper(extra='<circle cx="29" cy="37" r="9" fill="var(--accent)"/>'
                   '<path d="M25.4 40.6l7.2-7.2M26.6 33.4h6v6" fill="none"'
                   ' stroke="var(--on-accent)" stroke-width="2"'
                   ' stroke-linecap="round" stroke-linejoin="round"/>')

LINK_SM = paper_sm(extra='<circle cx="11.4" cy="11.6" r="3.8" fill="var(--accent)"/>'
                         '<path d="M9.9 13.1l3-3M10.4 10.1h2.5v2.5" fill="none"'
                         ' stroke="var(--on-accent)" stroke-width="1.1"'
                         ' stroke-linecap="round" stroke-linejoin="round"/>')


# ------------------------------------------------------------- categories ----
# key -> (label, large, small). The label is what the Type column prints when
# the extension table has nothing more specific to say.
def _cats():
    return {
        "folder":   ("Folder", FOLDER, FOLDER_SM),
        "txt":      ("Text", paper(rules=RULES), paper_sm(rules=RULES_TXT_SM)),
        "md":       ("Markdown", paper("var(--t-md)", "M"),
                     paper_sm("var(--t-md)", "M", size=5.5)),
        "code":     ("Source", paper("var(--t-code)", "{ }", size=11),
                     paper_sm("var(--t-code)", "{}", size=4.4)),
        "py":       ("Python", paper("var(--t-py)", "PY", size=11),
                     paper_sm("var(--t-py)", "PY", size=4.2)),
        "web":      ("Web", paper("var(--t-web)", "< >", size=11),
                     paper_sm("var(--t-web)", "<>", size=4.2)),
        "style":    ("Stylesheet", paper("var(--t-style)", "#", size=13),
                     paper_sm("var(--t-style)", "#", size=5.5)),
        "cfg":      ("Config", paper("var(--t-cfg)", "{}", size=13),
                     paper_sm("var(--t-cfg)", "{}", size=4.2)),
        "data":     ("Data", paper("var(--t-data)", "{;}", size=10),
                     paper_sm("var(--t-data)", "{;}", size=3.6)),
        "shell":    ("Script", paper("var(--t-shell)", "$_", size=12),
                     paper_sm("var(--t-shell)", "$_", size=4.4)),
        "patch":    ("Patch", paper("var(--t-patch)", "+-", size=12),
                     paper_sm("var(--t-patch)", "+-", size=4.4)),
        "pdf":      ("PDF", paper("var(--t-pdf)", "PDF", size=9),
                     paper_sm("var(--t-pdf)", "PDF", size=3.4)),
        "doc":      ("Document", paper("var(--t-doc)", "W", size=13),
                     paper_sm("var(--t-doc)", "W", size=5.5)),
        "sheet":    ("Spreadsheet", paper("var(--t-sheet)", "X", size=13),
                     paper_sm("var(--t-sheet)", "X", size=5.5)),
        "slides":   ("Presentation", paper("var(--t-slides)", "P", size=13),
                     paper_sm("var(--t-slides)", "P", size=5.5)),
        "img":      ("Image", IMAGE, IMAGE_SM),
        "vector":   ("Vector image", VECTOR, VECTOR_SM),
        "audio":    ("Audio", AUDIO, AUDIO_SM),
        "video":    ("Video", VIDEO, VIDEO_SM),
        "zip":      ("Archive", ARCHIVE, ARCHIVE_SM),
        "disk":     ("Disk image", DISK, DISK_SM),
        "package":  ("Package", PACKAGE, PACKAGE_SM),
        "app":      ("Application", APP, APP_SM),
        "font":     ("Font", FONT, FONT_SM),
        "cert":     ("Certificate", CERT, CERT_SM),
        "db":       ("Database", DATABASE, DATABASE_SM),
        "book":     ("Book", EBOOK, EBOOK_SM),
        "contact":  ("Contact", CONTACT, CONTACT_SM),
        "link":     ("Shortcut", LINK, LINK_SM),
    }


CATEGORIES = _cats()

# ------------------------------------------------------------- extensions ----
# Only where the extension says more than the category does. Anything not here
# gets the plain page, which is what every icon theme does with .mojom too.
_EXT_SPEC = {
    "txt": "txt text log nfo rst me readme",
    "md": "md markdown mdx",
    "code": ("c h cc cpp hpp cxx go rs java kt swift cs rb php pl lua r jl scala "
             "hs ml s asm m mm zig nim d v"),
    "py": "py pyc pyo pyi ipynb",
    "web": "html htm xhtml xml js ts jsx tsx mjs cjs cts mts vue svelte astro",
    "style": "css scss sass less styl",
    "cfg": "ini conf cfg toml properties env plist gn gni cmake mk",
    "data": "json jsonl yaml yml csv tsv proto graphql xtb mojom idl",
    "shell": "sh bash zsh fish bat cmd ps1 ksh",
    "patch": "patch diff rej orig",
    "pdf": "pdf",
    "doc": "doc docx odt rtf pages tex wpd",
    "sheet": "xls xlsx ods numbers",
    "slides": "ppt pptx odp key",
    "img": "png jpg jpeg gif bmp webp tiff tif ico heic avif raw cr2 nef psd xcf",
    "vector": "svg ai eps sketch fig",
    "audio": "mp3 wav flac ogg m4a aac opus wma mid midi aiff",
    "video": "mp4 mkv avi mov webm wmv flv m4v mpg mpeg ogv",
    "zip": "zip tar gz bz2 xz zst 7z rar lz lzma tgz txz tbz cab ar",
    "disk": "iso img dmg vhd vhdx qcow2 vdi vmdk squashfs",
    "package": "deb rpm pkg apk msi snap flatpak appimage whl gem crate xpi crx",
    "app": "exe dll so dylib bin o a lib elf com wasm",
    "font": "ttf otf woff woff2 eot pfb",
    "cert": "pem crt cer key pub gpg asc p12 pfx sig",
    "db": "db sqlite sqlite3 sql mdb accdb",
    "book": "epub mobi azw azw3 djvu fb2",
    "contact": "vcf ics ical",
    "link": "lnk desktop url webloc",
}

# Where an extension deserves its own words in the Type column.
_LABEL = {
    "md": "Markdown", "py": "Python", "ts": "TypeScript", "js": "JavaScript",
    "html": "HTML", "css": "Stylesheet", "json": "JSON", "yaml": "YAML",
    "yml": "YAML", "toml": "TOML", "sh": "Shell script", "png": "PNG image",
    "jpg": "JPEG image", "jpeg": "JPEG image", "gif": "GIF image",
    "webp": "WebP image", "svg": "SVG image", "zip": "Zip archive",
    "gz": "Gzip archive", "xz": "Xz archive", "tar": "Tar archive",
    "7z": "7z archive", "zst": "Zstd archive", "pdf": "PDF document",
    "mp3": "MP3 audio", "mp4": "MP4 video", "txt": "Text", "log": "Log",
    "c": "C source", "h": "C header", "cc": "C++ source", "go": "Go source",
    "rs": "Rust source", "xaml": "XAML", "patch": "Patch", "diff": "Patch",
}

ART_BY_EXT = {}
for _cat, _exts in _EXT_SPEC.items():
    for _e in _exts.split():
        ART_BY_EXT["." + _e] = (_cat, _LABEL.get(_e, CATEGORIES[_cat][0]))

# xaml is not a category of its own, it is markup
ART_BY_EXT[".xaml"] = ("web", "XAML")


# ---------------------------------------------------------------- the sets ---
def aurade():
    """The drawn set. Always available, because it is in this file."""
    return ({k: v[1] for k, v in CATEGORIES.items()},
            {k: v[2] for k, v in CATEGORIES.items()})


# Icon names per category, best first. A theme that has none of them keeps the
# drawn glyph, so a partial theme is a partial substitution rather than a hole.
_THEME_NAMES = {
    "folder":  ["folder", "inode-directory"],
    "txt":     ["text-x-generic", "text-plain"],
    "md":      ["text-markdown", "text-x-markdown", "text-x-generic"],
    "code":    ["text-x-csrc", "text-x-c++src", "text-x-source"],
    "py":      ["text-x-python", "application-x-python-bytecode"],
    "web":     ["text-html", "text-xml", "application-javascript"],
    "style":   ["text-css"],
    "cfg":     ["application-x-wine-extension-ini", "text-x-generic"],
    "data":    ["application-json", "application-x-yaml", "text-csv"],
    "shell":   ["application-x-shellscript", "text-x-script"],
    "patch":   ["text-x-patch", "text-x-diff"],
    "pdf":     ["application-pdf"],
    "doc":     ["application-msword", "x-office-document"],
    "sheet":   ["x-office-spreadsheet", "application-vnd.ms-excel"],
    "slides":  ["x-office-presentation", "application-vnd.ms-powerpoint"],
    "img":     ["image-x-generic", "image-png"],
    "vector":  ["image-svg+xml", "image-svg+xml-compressed"],
    "audio":   ["audio-x-generic", "audio-mpeg"],
    "video":   ["video-x-generic", "video-mp4"],
    "zip":     ["application-zip", "application-x-archive"],
    "disk":    ["application-x-cd-image", "media-optical"],
    "package": ["package-x-generic", "application-x-rpm"],
    "app":     ["application-x-executable", "application-x-sharedlib"],
    "font":    ["font-x-generic", "font-ttf", "application-x-font-ttf"],
    "cert":    ["application-certificate", "application-pkcs12"],
    "db":      ["application-x-sqlite3", "application-sql"],
    "book":    ["application-epub+zip", "application-x-mobipocket-ebook"],
    "contact": ["x-office-contact", "text-vcard"],
    "link":    ["application-x-ms-shortcut", "inode-symlink", "emblem-symbolic-link"],
}

# Two layouts are in the wild: Breeze puts the size under the group, the
# freedesktop default puts the group under the size. Try both rather than
# guessing from the theme name.
_GROUPS = ("mimetypes", "places", "apps", "devices")
_SIZES = {
    "small": (("16", "22", "24", "32", "48"),
              ("16x16", "22x22", "24x24", "32x32", "scalable", "symbolic")),
    "large": (("48", "64", "32", "24", "22", "16"),
              ("48x48", "64x64", "scalable", "32x32", "24x24", "16x16", "symbolic")),
}


def _find(root, names, want):
    flat, nested = _SIZES[want]
    for name in names:
        for n in (name, name + "-symbolic"):
            for group in _GROUPS:
                for size in flat:
                    p = os.path.join(root, group, size, n + ".svg")
                    if os.path.exists(p):
                        return p
                for size in nested:
                    p = os.path.join(root, size, group, n + ".svg")
                    if os.path.exists(p):
                        return p
    return None


def _read_svg(path):
    try:
        svg = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    if "<svg" not in svg:
        return None
    svg = svg[svg.index("<svg"):]
    # The theme pins width and height at its own size, which would override the
    # layout. The class carries the size instead, exactly as the drawn set does.
    svg = svg.replace("<svg", '<svg class="art"', 1)
    return svg


def _theme_set(root):
    """Read one icon theme off disk. None when it is not installed.

    Read at build time, never at render time, so a theme that is not there is an
    option we do not offer rather than a page that half renders.
    """
    if not os.path.isdir(root):
        return None
    big, small = aurade()
    big, small = dict(big), dict(small)
    found = 0
    for cat, names in _THEME_NAMES.items():
        for want, table in (("large", big), ("small", small)):
            path = _find(root, names, want)
            if not path:
                continue
            svg = _read_svg(path)
            if svg:
                table[cat] = svg
                found += 1
    return (big, small) if found else None


def _theme(root):
    return lambda: _theme_set(root)


# name -> (title, note, provider). The note is what the settings row prints
# under the name, because a theme drawn for a light background is a real
# tradeoff and the user should not have to discover it by switching.
SETS = {
    "aurade": ("AuraDE", "Drawn for this desktop. Follows light and dark.",
               aurade),
    "breeze": ("Breeze", "KDE's set, coloured for a light background.",
               _theme("/usr/share/icons/breeze")),
    "breeze-dark": ("Breeze Dark", "KDE's set, coloured for a dark background.",
                    _theme("/usr/share/icons/breeze-dark")),
    "adwaita": ("Adwaita", "GNOME's set. Monochrome, and thinner coverage.",
                _theme("/usr/share/icons/Adwaita")),
    "papirus": ("Papirus", "Installed separately. Colourful and very wide.",
                _theme("/usr/share/icons/Papirus")),
}

DEFAULT_SET = "aurade"


def available():
    """The sets this machine can actually offer, in menu order."""
    out = []
    for name, (title, note, provider) in SETS.items():
        try:
            if provider() is not None:
                out.append((name, title, note))
        except Exception:
            continue
    return out


def _stamp(table, small):
    """Write the category onto the glyph itself.

    The page reskins by walking `svg.art[data-art]` and swapping each one for
    the same category out of the newly chosen set. Putting the key on the svg
    rather than on the row means clones carry it for free, and every holder
    (grid thumb, list icon, info pane header, properties dialog) reskins without
    any of them having to know what a category is.
    """
    flag = "1" if small else "0"
    return {k: v.replace("<svg", f'<svg data-art="{k}" data-art-sm="{flag}"', 1)
            for k, v in table.items()}


def load(name):
    """(large, small) for a set, falling back to the drawn one."""
    got = None
    entry = SETS.get(name)
    if entry:
        try:
            got = entry[2]()
        except Exception:
            got = None
    if not got:
        got = aurade()
    return _stamp(got[0], False), _stamp(got[1], True)


def all_sets():
    """{name: (large, small)} for every set this machine can offer."""
    return {name: load(name) for name, _title, _note in available()}


def tints_css():
    return " ".join(f"--{k}:{v};" for k, v in TINTS.items())


_ID_RE = re.compile(r'id="([^"]+)"')


def uniquify(svg, n):
    """Rename every id inside one glyph, and the references to them.

    Two folders on a page both defining id="fg" is a duplicate id, and the
    browser resolves url(#fg) to the first one in the document. When that first
    one happens to sit in a hidden subtree the gradient silently paints nothing,
    so a folder loses its face the moment the file area is hidden. Shipping four
    icon themes in one artlib makes the collisions certain rather than lucky:
    Breeze names its gradients linearGradient1 and its clips a, b, c.
    """
    for i in set(_ID_RE.findall(svg)):
        svg = svg.replace(f'id="{i}"', f'id="{i}__{n}"')
        svg = svg.replace(f"url(#{i})", f"url(#{i}__{n})")
        svg = svg.replace(f'href="#{i}"', f'href="#{i}__{n}"')
    return svg
