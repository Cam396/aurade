#!/usr/bin/env python3
"""The sign in conversation, driven to every one of its ends.

A greeter is the one screen where a state machine bug locks somebody out of
their own computer, so this file drives the real protocol module over a real
socket pair with a scripted greetd on the other side. No toolkit, no display,
no greetd binary, no account.

The properties that matter are not "it can sign in". They are the ones that
decide what a person reads and what they do next:

* a wrong password and a dead login service must raise different exceptions,
  because one of them means try again and the other means that will not help.
* an informational line from PAM is not a question and must not become a
  password field with a blank prompt above it.
* anything unrecognised is refused rather than treated as success, because
  treating an unknown reply as success is how a greeter starts a session for
  somebody who did not authenticate.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
sys.path.insert(0, ROOT)

from aurade_greeter import protocol as P  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def pack(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return struct.pack("=I", len(body)) + body


class Fake:
    """A greetd that says exactly what the test told it to say."""

    def __init__(self, replies: list[dict] | None = None) -> None:
        self.theirs, self.ours = socket.socketpair()
        for reply in replies or ():
            self.theirs.sendall(pack(reply))
        self.transport = P.Transport(self.ours)

    def close(self) -> None:
        self.theirs.close()
        self.ours.close()

    def hang_up(self) -> None:
        self.theirs.close()

    def sent(self) -> list[dict]:
        """Every request the greeter wrote, decoded."""
        self.theirs.setblocking(False)
        chunks = []
        while True:
            try:
                chunk = self.theirs.recv(65536)
            except (BlockingIOError, OSError):
                break
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        out = []
        while len(data) >= 4:
            (size,) = struct.unpack("=I", data[:4])
            out.append(json.loads(data[4:4 + size].decode("utf-8")))
            data = data[4 + size:]
        return out


SECRET_PROMPT = {"type": "auth_message", "auth_message_type": "secret",
                 "auth_message": "Password:"}
SUCCESS = {"type": "success"}
REFUSED = {"type": "error", "error_type": "auth_error",
           "description": "Login incorrect"}
# What greetd 0.10 answers when a refused attempt is cancelled: an error,
# because the PAM conversation behind it has already gone. The attempt is
# cleared all the same.
REFUSED_CANCELLED = {"type": "error", "error_type": "error",
                     "description": "unable to send message: Connection "
                                    "refused (os error 111)"}


# --- the framing ----------------------------------------------------------

def test_framing() -> None:
    body = P.frame({"type": "cancel_session"})
    (size,) = struct.unpack("=I", body[:4])
    check(size == len(body) - 4,
          "the length prefix does not match the message it introduces")
    check(json.loads(body[4:].decode("utf-8")) == {"type": "cancel_session"},
          "a framed request does not decode back to itself")


def test_short_read_is_not_a_message() -> None:
    fake = Fake()
    fake.theirs.sendall(struct.pack("=I", 40) + b'{"type":"suc')
    fake.hang_up()
    try:
        fake.transport.receive()
        FAILURES.append("a truncated reply was accepted as a whole message")
    except P.GreeterError:
        pass
    fake.close()


def test_a_truncated_message_that_parses_is_still_truncated() -> None:
    """The dangerous short read is the one that happens to be valid JSON.

    A length prefix that promises more than arrives, followed by a hang up,
    must not be accepted just because the bytes that did arrive decode. That
    is the shape a success reply takes when somebody can write to the socket
    and greetd cannot.
    """
    fake = Fake()
    body = b'{"type": "success"}'
    fake.theirs.sendall(struct.pack("=I", len(body) + 50) + body)
    fake.hang_up()
    try:
        reply = fake.transport.receive()
        FAILURES.append(
            f"a message shorter than its own length prefix was accepted: {reply}")
    except P.GreeterError:
        pass
    fake.close()


def test_impossible_length_is_refused() -> None:
    fake = Fake()
    fake.theirs.sendall(struct.pack("=I", 1 << 30))
    try:
        fake.transport.receive()
        FAILURES.append("an impossible length prefix was accepted")
    except P.GreeterError:
        pass
    fake.close()


def test_unreadable_body_is_refused() -> None:
    fake = Fake()
    body = b"not json at all"
    fake.theirs.sendall(struct.pack("=I", len(body)) + body)
    try:
        fake.transport.receive()
        FAILURES.append("a reply that is not JSON was accepted")
    except P.GreeterError:
        pass
    fake.close()


def test_reply_must_be_a_message() -> None:
    fake = Fake()
    body = b'["success"]'
    fake.theirs.sendall(struct.pack("=I", len(body)) + body)
    try:
        fake.transport.receive()
        FAILURES.append("a JSON array was accepted as a greetd message")
    except P.GreeterError:
        pass
    fake.close()


# --- the happy path -------------------------------------------------------

def test_sign_in() -> None:
    fake = Fake([SECRET_PROMPT, SUCCESS, SUCCESS])
    session = P.Session(fake.transport)
    prompt = session.begin("ada")
    check(prompt == P.Prompt("secret", "Password:"),
          "the first prompt is not the secret one greetd sent")
    check(prompt.secret, "a secret prompt did not report itself as secret")
    check(session.state == P.Session.ASKING,
          "the session is not waiting for an answer after a prompt")
    following = session.answer("correct horse")
    check(following is None, "an answered prompt produced another prompt")
    check(session.state == P.Session.READY,
          "the session is not ready after greetd reported success")
    session.start(["/usr/bin/aurade-session-supervisor", "/usr/bin/ash"], ["A=b"])
    check(session.state == P.Session.CLOSED,
          "a started session did not close the attempt")
    requests = fake.sent()
    check([request["type"] for request in requests] ==
          ["create_session", "post_auth_message_response", "start_session"],
          f"the conversation was not the three expected requests: {requests}")
    check(requests[0]["username"] == "ada",
          "the username did not reach greetd unchanged")
    check(requests[1]["response"] == "correct horse",
          "the answer did not reach greetd unchanged")
    check(requests[2]["cmd"] == ["/usr/bin/aurade-session-supervisor",
                                 "/usr/bin/ash"],
          "the session command did not reach greetd unchanged")
    check(requests[2]["env"] == ["A=b"],
          "the session environment did not reach greetd unchanged")
    fake.close()


def test_account_with_no_question() -> None:
    """An account greetd needs nothing for goes straight to ready."""
    fake = Fake([SUCCESS])
    session = P.Session(fake.transport)
    check(session.begin("ada") is None,
          "an account that needs no answer produced a prompt")
    check(session.state == P.Session.READY,
          "an account that needs no answer did not become ready")
    fake.close()


# --- the two failures that must not be one --------------------------------

def test_wrong_password_is_its_own_failure() -> None:
    fake = Fake([SECRET_PROMPT, REFUSED, REFUSED_CANCELLED])
    session = P.Session(fake.transport)
    session.begin("ada")
    try:
        session.answer("wrong")
        FAILURES.append("a refused password did not raise")
    except P.AuthFailed as exc:
        check("Login incorrect" in str(exc),
              "the refusal did not carry what greetd said about it")
    except P.GreeterError:
        FAILURES.append(
            "a wrong password raised the same exception as a dead service")
    fake.close()


def test_a_refusal_is_cancelled_so_the_next_try_can_start() -> None:
    """greetd keeps a refused attempt until it is cancelled, and answers the
    next create_session with "a session is already being configured" until
    then. The greeter read that as a service that had died: one mistyped
    password, and the screen told the person to restart the computer and
    meant it, because nothing else would let anybody in. The replies are the
    ones greetd 0.10 gave on a real machine."""
    fake = Fake([SECRET_PROMPT, REFUSED, REFUSED_CANCELLED, SECRET_PROMPT])
    first = P.Session(fake.transport)
    first.begin("ada")
    try:
        first.answer("wrong")
    except P.AuthFailed:
        pass
    retry = P.Session(fake.transport)
    prompt = None
    try:
        prompt = retry.begin("ada")
    except P.GreeterError as exc:
        FAILURES.append(f"the try after a refused password failed: {exc}")
    check(prompt is not None and prompt.secret,
          "the try after a refused password was not asked for one")
    check([r["type"] for r in fake.sent()] ==
          ["create_session", "post_auth_message_response",
           "cancel_session", "create_session"],
          "a refused attempt was not cancelled before the next one began")
    fake.close()


def test_service_failure_is_not_a_wrong_password() -> None:
    fake = Fake([SECRET_PROMPT,
                 {"type": "error", "error_type": "error",
                  "description": "pam_open_session failed"}])
    session = P.Session(fake.transport)
    session.begin("ada")
    try:
        session.answer("anything")
        FAILURES.append("a service failure did not raise")
    except P.AuthFailed:
        FAILURES.append(
            "a service failure was reported as a wrong password")
    except P.GreeterError:
        pass
    fake.close()


def test_hang_up_is_a_service_failure() -> None:
    fake = Fake()
    session = P.Session(fake.transport)
    fake.hang_up()
    try:
        session.begin("ada")
        FAILURES.append("a closed socket did not raise")
    except P.AuthFailed:
        FAILURES.append("a closed socket was reported as a wrong password")
    except P.GreeterError:
        pass
    fake.close()


# --- messages that are not questions --------------------------------------

def test_info_is_collected_not_asked() -> None:
    fake = Fake([{"type": "auth_message", "auth_message_type": "info",
                  "auth_message": "Your password expires in 3 days"},
                 SECRET_PROMPT, SUCCESS])
    session = P.Session(fake.transport)
    prompt = session.begin("ada")
    check(prompt == P.Prompt("secret", "Password:"),
          "an informational line was handed back as a question")
    check(session.notices == [P.Notice("info", "Your password expires in 3 days")],
          f"the informational line was not kept: {session.notices}")
    session.answer("x")
    check(len(fake.sent()) == 2,
          "an informational line was answered as though it were a question")
    fake.close()


def test_error_notice_is_kept_and_marked() -> None:
    fake = Fake([{"type": "auth_message", "auth_message_type": "error",
                  "auth_message": "Account locked briefly"},
                 SECRET_PROMPT, SUCCESS])
    session = P.Session(fake.transport)
    session.begin("ada")
    check(len(session.notices) == 1 and session.notices[0].bad,
          "an error notice was not kept and marked as bad")
    fake.close()


def test_visible_prompt_is_not_secret() -> None:
    fake = Fake([{"type": "auth_message", "auth_message_type": "visible",
                  "auth_message": "One time code:"}])
    session = P.Session(fake.transport)
    prompt = session.begin("ada")
    check(prompt is not None and not prompt.secret,
          "a visible prompt would have been hidden as though it were a password")
    fake.close()


def test_unknown_message_kind_is_refused() -> None:
    fake = Fake([{"type": "auth_message", "auth_message_type": "biometric",
                  "auth_message": "Touch the sensor"}])
    session = P.Session(fake.transport)
    try:
        session.begin("ada")
        FAILURES.append("an unrecognised prompt kind was accepted")
    except P.GreeterError:
        pass
    fake.close()


def test_unknown_reply_type_is_refused() -> None:
    fake = Fake([{"type": "welcome"}])
    session = P.Session(fake.transport)
    try:
        session.begin("ada")
        FAILURES.append("an unrecognised reply type was accepted")
    except P.GreeterError:
        pass
    fake.close()


# --- the order things may happen in ---------------------------------------

def test_start_before_authentication_is_refused() -> None:
    fake = Fake([SECRET_PROMPT])
    session = P.Session(fake.transport)
    session.begin("ada")
    try:
        session.start(["/usr/bin/ash"])
        FAILURES.append("a session started while a password was still outstanding")
    except P.GreeterError:
        pass
    check("start_session" not in [r["type"] for r in fake.sent()],
          "a start_session request went out before authentication finished")
    fake.close()


def test_answer_without_a_question_is_refused() -> None:
    fake = Fake([SUCCESS])
    session = P.Session(fake.transport)
    session.begin("ada")
    try:
        session.answer("unasked")
        FAILURES.append("an answer was sent when nothing had been asked")
    except P.GreeterError:
        pass
    fake.close()


def test_begin_twice_is_refused() -> None:
    fake = Fake([SECRET_PROMPT])
    session = P.Session(fake.transport)
    session.begin("ada")
    try:
        session.begin("grace")
        FAILURES.append("a second sign in attempt reused a live session")
    except P.GreeterError:
        pass
    fake.close()


def test_start_needs_a_command() -> None:
    fake = Fake([SUCCESS])
    session = P.Session(fake.transport)
    session.begin("ada")
    try:
        session.start([])
        FAILURES.append("an empty session command was sent to greetd")
    except P.GreeterError:
        pass
    fake.close()


def test_cancel_tells_greetd() -> None:
    fake = Fake([SECRET_PROMPT, SUCCESS])
    session = P.Session(fake.transport)
    session.begin("ada")
    session.cancel()
    check([r["type"] for r in fake.sent()] ==
          ["create_session", "cancel_session"],
          "backing out of a sign in did not cancel the session with greetd")
    check(session.state == P.Session.CLOSED,
          "a cancelled session did not close")
    fake.close()


def test_cancel_after_the_service_is_gone_is_quiet() -> None:
    fake = Fake([SECRET_PROMPT])
    session = P.Session(fake.transport)
    session.begin("ada")
    fake.hang_up()
    try:
        session.cancel()
    except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
        FAILURES.append(f"cancelling after greetd went away raised {exc!r}")
    fake.close()


# --- what the object is allowed to remember -------------------------------

def test_the_password_is_not_kept() -> None:
    fake = Fake([SECRET_PROMPT, SUCCESS])
    session = P.Session(fake.transport)
    session.begin("ada")
    session.answer("hunter2 is the password")
    held = [value for value in vars(session).values()
            if isinstance(value, str)]
    held.extend(str(getattr(session, name, "")) for name in P.Session.__dict__
                if not name.startswith("_"))
    check(not any("hunter2" in value for value in held),
          "the session object still holds the password after sending it")
    check(session.prompt is None,
          "the answered prompt is still hanging off the session")
    fake.close()


def test_unsendable_values_are_refused() -> None:
    fake = Fake([SECRET_PROMPT])
    session = P.Session(fake.transport)
    for bad in ("", "ada\nroot", "ada\x00root"):
        try:
            P.Session(fake.transport).begin(bad)
            FAILURES.append(f"the username {bad!r} was sent to greetd")
        except P.GreeterError:
            pass
    session.begin("ada")
    try:
        session.answer("pass\x00word")
        FAILURES.append("an answer containing a null byte was sent")
    except P.GreeterError:
        pass
    fake.close()


def test_started_outside_greetd_says_so() -> None:
    saved = os.environ.pop("GREETD_SOCK", None)
    try:
        P.Transport.connect()
        FAILURES.append("connecting with no socket in the environment succeeded")
    except P.GreeterError as exc:
        check("greetd" in str(exc),
              "the message for running outside greetd does not mention greetd")
    finally:
        if saved is not None:
            os.environ["GREETD_SOCK"] = saved


def main() -> int:
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
    if FAILURES:
        print("greeter protocol test: FAIL")
        for failure in FAILURES:
            print(f"  {failure}")
        return 1
    print("greeter protocol test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
