"""Turn locale, keymap and timezone codes into names a person recognises.

`en_US.UTF-8` is a correct answer to "which locale" and a useless answer to
"which language". Someone who cannot read English cannot find their own
language in a list written in English either, so the picker shows the language
in its own words first.

Nothing here decides what is valid. The model still supplies the candidate
list and still validates the answer; this only decides how a candidate is
labelled, which is the renderer's job and no one else's.

The data comes from `iso-codes`, which is already on the image because GTK 4
depends on it. Its message catalogues translate a language's English name into
that language, so `gettext` gives real endonyms without shipping a hand-typed
table that would be wrong for half the world and stale for the rest.
"""

from __future__ import annotations

import gettext
import json
import os

ISO_CODES_DIR = os.environ.get("AURADE_ISO_CODES_DIR", "/usr/share/iso-codes/json")
LOCALE_DIR = os.environ.get("AURADE_ISO_LOCALE_DIR", "/usr/share/locale")


def _load(name: str) -> list[dict]:
    path = os.path.join(ISO_CODES_DIR, f"{name}.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    for key in (name, name.replace("-", "_")):
        if key in data:
            return data[key]
    return next((v for v in data.values() if isinstance(v, list)), [])


class Names:
    """Language and country names, looked up once per session."""

    def __init__(self) -> None:
        self._languages: dict[str, str] = {}
        self._countries: dict[str, str] = {}
        self._endonyms: dict[str, str] = {}
        for entry in _load("iso_639-3"):
            english = entry.get("name", "")
            if not english:
                continue
            for key in ("alpha_2", "alpha_3"):
                code = entry.get(key)
                if code:
                    self._languages.setdefault(code, english)
        for entry in _load("iso_3166-1"):
            code = entry.get("alpha_2")
            if code:
                self._countries[code] = entry.get("name", code)

    # -- lookups -----------------------------------------------------------

    def language(self, code: str) -> str:
        return self._languages.get(code, "")

    def country(self, code: str) -> str:
        return self._countries.get(code, "")

    def endonym(self, code: str) -> str:
        """The language's name in that language, if the catalogues have it."""
        if code in self._endonyms:
            return self._endonyms[code]
        english = self.language(code)
        result = ""
        if english:
            try:
                catalogue = gettext.translation(
                    "iso_639-3", localedir=LOCALE_DIR, languages=[code]
                )
            except (OSError, FileNotFoundError):
                result = ""
            else:
                translated = catalogue.gettext(english)
                result = "" if translated == english else translated
        self._endonyms[code] = result
        return result

    # -- the label a picker shows -----------------------------------------

    def describe_locale(self, locale: str) -> tuple[str, str]:
        """`(title, detail)` for one locale from the model's candidate list.

        The title is what the language calls itself where that is known, so a
        Spanish speaker looks for "Espanol" and not for "Spanish". The detail
        carries the English name and the region, so someone helping over the
        phone and the person in front of the screen are looking at the same
        row.
        """
        code = locale.split(".")[0]
        if code in ("C", "POSIX"):
            return ("English (no regional formats)", locale)
        language, _, territory = code.partition("_")
        territory = territory.split("@")[0]
        english = self.language(language)
        own = self.endonym(language)
        country = self.country(territory) if territory else ""

        title = own or english or language
        if country:
            title = f"{title} ({country})"
        detail_bits = []
        if own and english and own != english:
            detail_bits.append(english)
        detail_bits.append(locale)
        return (title, "  ".join(detail_bits))


#: Keyboard layouts whose console name gives no clue what they are. Only the
#: ones the layout list actually contains and a person would plausibly hunt
#: for; an exhaustive table would be a maintenance burden and mostly wrong.
KEYMAP_NOTES = {
    "us": "US English",
    "us-acentos": "US English, international with dead keys",
    "uk": "United Kingdom",
    "gb": "United Kingdom",
    "de": "German",
    "de-latin1": "German",
    "fr": "French, AZERTY",
    "fr-latin1": "French, AZERTY",
    "es": "Spanish",
    "it": "Italian",
    "pt-latin1": "Portuguese",
    "br-abnt2": "Portuguese, Brazil",
    "dvorak": "Dvorak",
    "colemak": "Colemak",
    "sv-latin1": "Swedish",
    "no": "Norwegian",
    "dk": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cz": "Czech",
    "hu": "Hungarian",
    "tr": "Turkish",
    "ru": "Russian",
    "ua": "Ukrainian",
    "gr": "Greek",
    "jp106": "Japanese",
    "ko": "Korean",
    "cf": "Canadian French",
    "ca": "Canadian",
    "ch-de": "Swiss German",
    "ch-fr": "Swiss French",
    "be-latin1": "Belgian",
    "nl": "Dutch",
}


def describe_keymap(keymap: str) -> tuple[str, str]:
    note = KEYMAP_NOTES.get(keymap, "")
    return (note or keymap, keymap if note else "")


def describe_timezone(zone: str) -> tuple[str, str]:
    """`Europe/Lisbon` reads better as `Lisbon` with `Europe` alongside."""
    region, _, city = zone.rpartition("/")
    if not region:
        return (zone, "")
    return (city.replace("_", " "), region.replace("_", " "))


#: The storage answers, in the words a person would use, with the consequence
#: as the second line. The engine's vocabulary (`wipe`, `btrfs`, `zram`) is
#: correct and stays the value that travels; it is not what a chooser reads.
#:
#: Every second line here is a fact the engine enforces, not a caution. "No
#: rollback" is what ext4 actually gets, and it is the single thing worth
#: knowing before choosing it.
STORAGE_NAMES: dict[str, dict[str, tuple[str, str]]] = {
    "layout": {
        "wipe": ("Erase the whole disk", "Everything on it is destroyed"),
        "alongside": ("Alongside what is there",
                      "Free space only. Nothing existing is moved"),
    },
    "filesystem": {
        "btrfs": ("Btrfs", "Snapshots, and a rollback entry in the boot menu"),
        "ext4": ("ext4", "Long established. No snapshots, no rollback"),
        "xfs": ("XFS", "Fast with large files. No snapshots, no rollback"),
    },
    "swap": {
        "none": ("None", "Memory only"),
        "file": ("Swap file", "Inside the root filesystem, so encrypted with it"),
        "zram": ("Compressed in memory", "Nothing is written to the disk"),
    },
    "swap_size": {
        "auto": ("Automatic", "Matches memory, up to 8 GB"),
        "hibernate": ("Enough to hibernate", "As large as memory, plus headroom"),
    },
}


def describe_storage(question: str, value: str) -> tuple[str, str]:
    known = STORAGE_NAMES.get(question, {})
    if value in known:
        return known[value]
    if question == "swap_size":
        return (value.replace("G", " GB").replace("M", " MB"), "")
    return (value, "")


def timezone_regions(zones: list[str]) -> list[str]:
    seen: list[str] = []
    for zone in zones:
        region = zone.partition("/")[0] if "/" in zone else "Other"
        if region not in seen:
            seen.append(region)
    return seen
