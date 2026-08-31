#!/usr/bin/env python3
"""Who the greeter thinks lives here.

Both mistakes this file guards against are the kind a person notices in the
first second. Too strict and somebody's account is simply absent from their
own login screen, with no error and nothing to press. Too loose and the
greeter offers to sign you in as a printing daemon.

Every source the policy reads is redirected at a fixture here, so the answer
does not depend on who happens to have an account on the machine running the
test.
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
sys.path.insert(0, ROOT)

from aurade_greeter import accounts as A  # noqa: E402

FAILURES: list[str] = []

PASSWD = """\
root:x:0:0:root:/root:/bin/bash
bin:x:1:1::/:/usr/bin/nologin
http:x:33:33::/srv/http:/usr/bin/nologin
systemd-coredump:x:979:979:systemd Core Dumper:/:/usr/bin/nologin
systemd-oomd:x:981:981::/:/usr/bin/nologin
ada:x:1000:1000:Ada Lovelace,Room 4,555-0100:/home/ada:/bin/bash
grace:x:1001:1001:Grace Hopper:/home/grace:/usr/bin/fish
kiosk:x:1002:1002::/home/kiosk:/bin/bash
greeter:x:1004:1004:Login screen:/var/lib/greetd:/bin/bash
aurade-greeter:x:1005:1005:Login screen:/var/lib/greetd:/bin/bash
retired:x:1003:1003:Retired Account:/home/retired:/usr/bin/nologin
nobody:x:65534:65534:Nobody:/:/usr/bin/nologin
buildbot:x:70000:70000:Out of range:/home/buildbot:/bin/bash
"""

LOGIN_DEFS = "UID_MIN 1000\nUID_MAX 60000\n"


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


class Fixture:
    """A whole small system, on disk, for the length of one test."""

    def __init__(self, passwd: str = PASSWD, defs: str = LOGIN_DEFS) -> None:
        self.dir = tempfile.TemporaryDirectory()
        root = self.dir.name
        self.passwd = os.path.join(root, "passwd")
        self.defs = os.path.join(root, "login.defs")
        self.service = os.path.join(root, "users")
        self.icons = os.path.join(root, "icons")
        self.state = os.path.join(root, "state", "last-user")
        with open(self.passwd, "w", encoding="utf-8") as handle:
            handle.write(passwd)
        with open(self.defs, "w", encoding="utf-8") as handle:
            handle.write(defs)
        os.makedirs(self.service)
        os.makedirs(self.icons)
        self.saved = {}
        for name, value in (("AURADE_GREETER_PASSWD", self.passwd),
                            ("AURADE_GREETER_LOGIN_DEFS", self.defs),
                            ("AURADE_GREETER_SERVICE_DIR", self.service),
                            ("AURADE_GREETER_ICON_DIR", self.icons),
                            ("AURADE_GREETER_STATE", self.state)):
            self.saved[name] = os.environ.get(name)
            os.environ[name] = value

    def service_file(self, name: str, body: str) -> None:
        with open(os.path.join(self.service, name), "w", encoding="utf-8") as handle:
            handle.write(body)

    def icon(self, name: str) -> str:
        path = os.path.join(self.icons, name)
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG")
        return path

    def close(self) -> None:
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.dir.cleanup()


def names(state: str | None = None) -> list[str]:
    return [account.name for account in A.accounts(state)]


# --- who is a person ------------------------------------------------------

def test_people_appear_and_machinery_does_not() -> None:
    fixture = Fixture()
    try:
        found = names()
        check(found == ["ada", "grace", "kiosk"],
              f"the account list is not the three people on this system: {found}")
        check("root" not in found, "root was offered on the login screen")
        check("http" not in found, "a service account was offered as a person")
        check("greeter" not in found, "the greeter offered to sign in as itself")
        check("nobody" not in found, "nobody was offered as somebody")
        check("retired" not in found,
              "an account with no login shell was offered as one that can sign in")
        check("buildbot" not in found,
              "an account outside the interactive range was offered")
        check("systemd-coredump" not in found,
              "a system account inside the range was offered as a person")
        check("aurade-greeter" not in found,
              "the account this greeter itself runs as was offered as a person")
    finally:
        fixture.close()


def test_the_range_is_read_not_assumed() -> None:
    """A system whose administrator moved UID_MIN still shows its people."""
    fixture = Fixture(defs="UID_MIN 500\nUID_MAX 70000\n")
    try:
        check("buildbot" in names(),
              "an account inside this system's own range was still hidden")
    finally:
        fixture.close()


def test_an_unreadable_login_defs_falls_back_rather_than_emptying() -> None:
    fixture = Fixture()
    os.environ["AURADE_GREETER_LOGIN_DEFS"] = os.path.join(
        fixture.dir.name, "not-here")
    try:
        check(names() == ["ada", "grace", "kiosk"],
              "a missing login.defs emptied the login screen")
    finally:
        fixture.close()


def test_accountsservice_can_hide_an_account() -> None:
    fixture = Fixture()
    try:
        fixture.service_file("kiosk", "[User]\nSystemAccount=true\n")
        found = names()
        check("kiosk" not in found,
              "an account the system marks as machinery was still offered")
        check("ada" in found,
              "marking one account as machinery hid the others")
    finally:
        fixture.close()


# --- what the row says ----------------------------------------------------

def test_the_name_on_the_row_is_the_person_s_name() -> None:
    fixture = Fixture()
    try:
        found = {account.name: account for account in A.accounts()}
        check(found["ada"].title == "Ada Lovelace",
              "the row shows the username where a real name exists")
        check(found["ada"].subtitle == "ada",
              "the row does not carry the username somebody would have to type")
        check(found["kiosk"].title == "kiosk",
              "an account with no real name lost its username too")
    finally:
        fixture.close()


def test_the_office_and_phone_number_stay_off_the_screen() -> None:
    """The comment field may hold four values. Only the first is a name."""
    fixture = Fixture()
    try:
        found = {account.name: account for account in A.accounts()}
        check("555-0100" not in found["ada"].title,
              f"a phone number reached the login screen: {found['ada'].title}")
        check("Room 4" not in found["ada"].title,
              "an office number reached the login screen")
    finally:
        fixture.close()


def test_accountsservice_name_wins() -> None:
    fixture = Fixture()
    try:
        fixture.service_file("ada", "[User]\nRealName=Ada, Countess of Lovelace\n")
        found = {account.name: account for account in A.accounts()}
        check(found["ada"].title == "Ada, Countess of Lovelace",
              "the name the rest of the system uses is not the name here")
    finally:
        fixture.close()


def test_an_avatar_is_found_when_there_is_one() -> None:
    fixture = Fixture()
    try:
        path = fixture.icon("grace")
        found = {account.name: account for account in A.accounts()}
        check(found["grace"].avatar == path,
              "a picture the system already has was not used")
        check(found["ada"].avatar is None,
              "a picture was claimed for an account that has none")
        check(found["ada"].initial == "A",
              "the letter drawn in place of a picture is not the person's")
        check(found["kiosk"].initial == "K",
              "an account with no real name has no letter either")
    finally:
        fixture.close()


# --- who leads the list ---------------------------------------------------

def test_the_last_person_to_sign_in_leads() -> None:
    fixture = Fixture()
    try:
        check(names()[0] == "ada",
              "with nobody remembered the list is not in name order")
        A.remember("grace")
        check(names()[0] == "grace",
              "the person who signed in last is not the first row")
        check(sorted(names()) == ["ada", "grace", "kiosk"],
              "remembering somebody lost or duplicated an account")
    finally:
        fixture.close()


def test_remembering_somebody_who_left_changes_nothing() -> None:
    fixture = Fixture()
    try:
        A.remember("someone-else")
        check(names() == ["ada", "grace", "kiosk"],
              "a remembered account that no longer exists disturbed the list")
    finally:
        fixture.close()


def test_a_state_file_is_not_a_way_in() -> None:
    """The remembered name is read before anybody has authenticated."""
    fixture = Fixture()
    try:
        os.makedirs(os.path.dirname(fixture.state), exist_ok=True)
        for bad in ("../../etc/shadow", "a" * 200, "ada\x00root"):
            with open(fixture.state, "w", encoding="utf-8") as handle:
                handle.write(bad + "\n")
            check(A.last_user() == "",
                  f"the greeter accepted {bad!r} out of its state file")
        check(A.remember("../root") is False,
              "the greeter would write a name containing a path separator")
    finally:
        fixture.close()


def test_remembering_survives_a_read_only_disk() -> None:
    """A convenience file is never worth refusing somebody their computer."""
    fixture = Fixture()
    try:
        os.environ["AURADE_GREETER_STATE"] = "/proc/aurade/last-user"
        check(A.remember("ada") is False,
              "an unwritable state path was reported as written")
        check(A.last_user() == "",
              "an unreadable state path produced a name")
    finally:
        fixture.close()


def main() -> int:
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
    if FAILURES:
        print("greeter accounts test: FAIL")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print("greeter accounts test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
