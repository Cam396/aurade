"""Which people this computer belongs to.

The greeter shows a list of accounts, so the rules for what counts as a person
have to live somewhere provable. Getting them wrong in either direction is
bad in a way a user notices immediately: too strict and somebody's account is
missing from the screen with no way to reach it, too loose and the login
screen offers to sign you in as a printing daemon.

Nothing here imports a toolkit. Every source it reads can be pointed
somewhere else through the environment, so the whole policy can be tested
against a fixture directory rather than against whoever happens to have an
account on the build machine.
"""

from __future__ import annotations

import os
import pwd
from typing import Iterable

#: Names that are never people, whatever their user id says.
NEVER = frozenset({"nobody", "greeter", "aurade-greeter"})

#: Shells that mean the account cannot be signed in to interactively.
NOT_A_LOGIN = frozenset({"nologin", "false", "sync", "shutdown", "halt"})

#: What Arch ships when /etc/login.defs is missing or unreadable.
DEFAULT_UID_MIN = 1000
DEFAULT_UID_MAX = 60000


class Account:
    """One person the greeter can offer to sign in."""

    __slots__ = ("name", "real_name", "uid", "home", "shell", "avatar")

    def __init__(self, name: str, real_name: str, uid: int, home: str,
                 shell: str, avatar: str | None = None) -> None:
        self.name = name
        self.real_name = real_name
        self.uid = uid
        self.home = home
        self.shell = shell
        self.avatar = avatar

    @property
    def title(self) -> str:
        """What to put on the row. The real name if there is one."""
        return self.real_name or self.name

    @property
    def subtitle(self) -> str:
        """The username, when the row is already showing something else.

        Shown even when it duplicates the title on some systems, because the
        username is what the person types if the list ever fails them, and a
        greeter that hides it has hidden the one fact needed to recover.
        """
        return self.name

    @property
    def initial(self) -> str:
        """One letter for the avatar circle when there is no picture."""
        for source in (self.real_name, self.name):
            for character in source:
                if character.isalpha():
                    return character.upper()
        return "?"

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"Account({self.name!r}, uid={self.uid})"


def _path(variable: str, fallback: str) -> str:
    return os.environ.get(variable) or fallback


def login_defs(path: str | None = None) -> tuple[int, int]:
    """The interactive user id range this system was configured with.

    Read rather than assumed, because a system whose administrator moved
    UID_MIN would otherwise have every account hidden from its own login
    screen with no error anywhere.
    """
    path = path or _path("AURADE_GREETER_LOGIN_DEFS", "/etc/login.defs")
    low, high = DEFAULT_UID_MIN, DEFAULT_UID_MAX
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 2:
                    continue
                if fields[0] == "UID_MIN" and fields[1].isdigit():
                    low = int(fields[1])
                elif fields[0] == "UID_MAX" and fields[1].isdigit():
                    high = int(fields[1])
    except OSError:
        return DEFAULT_UID_MIN, DEFAULT_UID_MAX
    if low > high:
        return DEFAULT_UID_MIN, DEFAULT_UID_MAX
    return low, high


def _passwd_entries() -> Iterable[tuple[str, int, str, str]]:
    """Every account on the system, as name, uid, gecos, shell, home.

    Reads a fixture file when one is named, so the account policy can be
    tested without needing accounts on the machine running the test.
    """
    fixture = os.environ.get("AURADE_GREETER_PASSWD")
    if not fixture:
        for entry in pwd.getpwall():
            yield entry.pw_name, entry.pw_uid, entry.pw_gecos, entry.pw_shell, entry.pw_dir
        return
    try:
        with open(fixture, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                fields = line.rstrip("\n").split(":")
                if len(fields) < 7 or not fields[2].isdigit():
                    continue
                yield fields[0], int(fields[2]), fields[4], fields[6], fields[5]
    except OSError:
        return


def _service_flags(name: str, directory: str | None = None) -> tuple[bool, str]:
    """What AccountsService says about an account: system, and real name.

    Desktops write this file, so honouring it is what keeps the greeter's
    idea of a person the same as the rest of the system's. Absent file means
    no opinion, not a system account.
    """
    directory = directory or _path(
        "AURADE_GREETER_SERVICE_DIR", "/var/lib/AccountsService/users")
    system = False
    real_name = ""
    try:
        with open(os.path.join(directory, name), "r",
                  encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key == "SystemAccount":
                    system = value.lower() == "true"
                elif key == "RealName" and value:
                    real_name = value
    except OSError:
        return False, ""
    return system, real_name


def _avatar(name: str, directory: str | None = None) -> str | None:
    directory = directory or _path(
        "AURADE_GREETER_ICON_DIR", "/var/lib/AccountsService/icons")
    candidate = os.path.join(directory, name)
    return candidate if os.path.isfile(candidate) else None


def _gecos_name(gecos: str) -> str:
    """The person's name out of the comment field, without the office and
    phone numbers the format allows after it."""
    return gecos.split(",", 1)[0].strip()


def is_person(name: str, uid: int, shell: str, low: int, high: int) -> bool:
    """The whole rule, in one place, so a test can hold it."""
    if name in NEVER:
        return False
    if not low <= uid <= high:
        return False
    if os.path.basename(shell) in NOT_A_LOGIN:
        return False
    return True


def accounts(state_path: str | None = None) -> list[Account]:
    """Everybody this greeter should offer, best first.

    The remembered account leads, because on a machine with one person that
    is the only row that will ever be pressed, and on a machine with several
    it is still the likeliest. Everyone else follows in name order so the
    list does not reshuffle itself between boots.
    """
    low, high = login_defs()
    found: list[Account] = []
    for name, uid, gecos, shell, home in _passwd_entries():
        if not is_person(name, uid, shell, low, high):
            continue
        system, service_name = _service_flags(name)
        if system:
            continue
        real_name = service_name or _gecos_name(gecos)
        found.append(Account(name, real_name, uid, home, shell, _avatar(name)))
    found.sort(key=lambda account: (account.title.lower(), account.uid))
    remembered = last_user(state_path)
    if remembered:
        for index, account in enumerate(found):
            if account.name == remembered:
                found.insert(0, found.pop(index))
                break
    return found


def _state_file(state_path: str | None = None) -> str:
    return state_path or _path(
        "AURADE_GREETER_STATE", "/var/lib/aurade-greeter/last-user")


def last_user(state_path: str | None = None) -> str:
    """Who signed in here last, if anybody has."""
    try:
        with open(_state_file(state_path), "r", encoding="utf-8") as handle:
            name = handle.readline().strip()
    except OSError:
        return ""
    if not name or len(name) > 64 or "/" in name or "\x00" in name:
        return ""
    return name


def remember(name: str, state_path: str | None = None) -> bool:
    """Record who just signed in, for the next boot.

    Best effort on purpose. A greeter that refused to start a session because
    it could not write a convenience file would be trading somebody's login
    for a preference.
    """
    if not name or "/" in name or "\x00" in name:
        return False
    path = _state_file(state_path)
    try:
        os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
        temporary = f"{path}.new"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(name + "\n")
        os.replace(temporary, path)
    except OSError:
        return False
    return True
