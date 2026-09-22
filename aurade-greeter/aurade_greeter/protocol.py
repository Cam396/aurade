"""The greetd conversation, with no toolkit in it.

A login screen is the one place in AuraDE where getting the state machine
wrong locks somebody out of their own computer, so this file holds the whole
conversation and nothing else. It imports no ``gi``, opens no window, and can
be driven to completion by a test against a socket pair. Every rule about
what may follow what lives here, once.

greetd speaks length prefixed JSON over ``$GREETD_SOCK``. The greeter asks to
create a session for a username, greetd replies with a series of
authentication messages (usually one secret prompt, sometimes an informational
line from PAM), the greeter answers each one, and greetd finally replies
success. Only then may the greeter ask for the session to start.

Two failures must never be confused, because the sentence a person reads is
different and so is what they should do next:

* an authentication error means the password was wrong. The account is fine,
  the machine is fine, try again.
* a transport error means greetd is not answering. Trying again will not help
  and telling somebody to check their password would be a lie.

``AuthFailed`` and ``GreeterError`` are that distinction, and they are the
reason this module refuses to collapse both into one exception type.
"""

from __future__ import annotations

import json
import os
import socket
import struct
from typing import Any, Callable

#: Native byte order, standard sizes. greetd frames each message with a
#: four byte unsigned length in the host's own order.
LENGTH = struct.Struct("=I")

#: A single message may not be larger than this. greetd never sends anything
#: close to it; the cap exists so a corrupt or hostile length prefix cannot
#: make the greeter allocate until the machine stops.
MAX_MESSAGE = 1 << 20

#: Authentication message kinds, straight from the protocol.
VISIBLE = "visible"
SECRET = "secret"
INFO = "info"
ERROR = "error"

PROMPTS = (VISIBLE, SECRET)
NOTICES = (INFO, ERROR)


class GreeterError(RuntimeError):
    """greetd could not be reached, or said something unreadable.

    Retrying the password will not fix any of these.
    """


class AuthFailed(RuntimeError):
    """The credentials were refused. The account and the machine are fine."""


class Prompt:
    """One question greetd wants answered.

    ``secret`` decides whether the field hides what is typed. It is not a
    style choice: PAM says which of its messages are passwords, and echoing
    one to a screen in a room with other people in it is the failure this
    flag exists to prevent.
    """

    __slots__ = ("kind", "text")

    def __init__(self, kind: str, text: str) -> None:
        self.kind = kind
        self.text = text

    @property
    def secret(self) -> bool:
        return self.kind == SECRET

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"Prompt({self.kind!r}, {self.text!r})"

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, Prompt) and other.kind == self.kind
                and other.text == self.text)


class Notice:
    """Something greetd wants shown but does not want answered."""

    __slots__ = ("kind", "text")

    def __init__(self, kind: str, text: str) -> None:
        self.kind = kind
        self.text = text

    @property
    def bad(self) -> bool:
        return self.kind == ERROR

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, Notice) and other.kind == self.kind
                and other.text == self.text)


def frame(payload: dict[str, Any]) -> bytes:
    """One request, ready for the wire."""
    body = json.dumps(payload).encode("utf-8")
    if len(body) > MAX_MESSAGE:
        raise GreeterError("the request is too large to send")
    return LENGTH.pack(len(body)) + body


def _read_exactly(recv: Callable[[int], bytes], count: int) -> bytes:
    """Read exactly ``count`` bytes or say why not.

    A short read is the shape a closed socket takes, and treating it as a
    complete message would hand malformed JSON to the parser and produce an
    error sentence about the reply rather than about greetd being gone.
    """
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = recv(remaining)
        if not chunk:
            raise GreeterError("the login service closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def unframe(recv: Callable[[int], bytes]) -> dict[str, Any]:
    """One reply, off the wire and checked."""
    (size,) = LENGTH.unpack(_read_exactly(recv, LENGTH.size))
    if size > MAX_MESSAGE:
        raise GreeterError("the login service sent an impossible reply")
    body = _read_exactly(recv, size) if size else b""
    try:
        reply = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GreeterError(f"unreadable reply from the login service: {exc}") from exc
    if not isinstance(reply, dict):
        raise GreeterError("the login service sent a reply that is not a message")
    return reply


class Transport:
    """The socket, wrapped thinly enough to fake.

    Tests pass a connected ``socket.socketpair`` half and drive the other end
    themselves, which is why nothing here reaches for ``GREETD_SOCK`` on its
    own.
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    @classmethod
    def connect(cls, path: str | None = None) -> "Transport":
        path = path or os.environ.get("GREETD_SOCK", "")
        if not path:
            raise GreeterError(
                "this greeter was started outside greetd, so there is nothing "
                "to sign in to")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(path)
        except OSError as exc:
            sock.close()
            raise GreeterError(f"the login service is not answering: {exc}") from exc
        return cls(sock)

    def send(self, payload: dict[str, Any]) -> None:
        try:
            self._sock.sendall(frame(payload))
        except OSError as exc:
            raise GreeterError(f"the login service stopped listening: {exc}") from exc

    def receive(self) -> dict[str, Any]:
        def recv(count: int) -> bytes:
            try:
                return self._sock.recv(count)
            except OSError as exc:
                raise GreeterError(
                    f"the login service stopped answering: {exc}") from exc
        return unframe(recv)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class Session:
    """One attempt to sign somebody in.

    The object is deliberately small and deliberately forgetful. It holds a
    username and a position in the conversation. It never holds a password:
    ``answer`` takes the secret, writes it to the socket, and lets it go. An
    object that kept the last password around so it could retry would be an
    object that keeps a password around.
    """

    #: Nothing has been asked yet.
    IDLE = "idle"
    #: greetd asked something and is waiting for the answer.
    ASKING = "asking"
    #: Authentication finished. The session may be started.
    READY = "ready"
    #: The attempt is over, either started or cancelled.
    CLOSED = "closed"

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self.state = self.IDLE
        self.username = ""
        self.prompt: Prompt | None = None
        self.notices: list[Notice] = []

    # -- conversation ------------------------------------------------------

    def begin(self, username: str) -> Prompt | None:
        """Ask greetd to start authenticating ``username``.

        Returns the first prompt, or ``None`` when the account needs no
        answer at all, which is what an empty password account looks like.
        """
        if self.state != self.IDLE:
            raise GreeterError("this sign in attempt has already started")
        if not username or "\n" in username or "\x00" in username:
            raise GreeterError("that is not a username this greeter can send")
        self.username = username
        self.transport.send({"type": "create_session", "username": username})
        return self._advance()

    def answer(self, response: str | None) -> Prompt | None:
        """Answer the outstanding prompt and return the next one, if any.

        ``response`` is not stored. It goes onto the socket inside this call
        and the only reference to it is the caller's, which the caller is
        expected to drop.
        """
        if self.state != self.ASKING:
            raise GreeterError("the login service is not waiting for an answer")
        if response is not None and "\x00" in response:
            raise GreeterError("an answer may not contain a null byte")
        payload: dict[str, Any] = {"type": "post_auth_message_response"}
        if response is not None:
            payload["response"] = response
        self.prompt = None
        self.transport.send(payload)
        return self._advance()

    def start(self, command: list[str], env: list[str] | None = None) -> None:
        """Hand the authenticated session over to greetd and stand down."""
        if self.state != self.READY:
            raise GreeterError("this session has not been authenticated")
        if not command:
            raise GreeterError("there is no session command to start")
        self.transport.send({
            "type": "start_session",
            "cmd": list(command),
            "env": list(env or ()),
        })
        reply = self.transport.receive()
        kind = reply.get("type")
        if kind == "success":
            self.state = self.CLOSED
            return
        if kind == "error":
            self.state = self.CLOSED
            raise GreeterError(_description(
                reply, "the session could not be started"))
        raise GreeterError("the login service answered something unexpected")

    def cancel(self) -> None:
        """Abandon the attempt.

        Called whenever somebody backs out of a half finished sign in. Without
        it greetd keeps the PAM conversation open and the next attempt for the
        same account meets a service that thinks it is mid question.
        """
        if self.state in (self.CLOSED, self.IDLE):
            self.state = self.CLOSED
            return
        self.state = self.CLOSED
        self.prompt = None
        try:
            self.transport.send({"type": "cancel_session"})
            self.transport.receive()
        except GreeterError:
            # The attempt is being abandoned either way. A greetd that has
            # already gone is not a failure worth showing anybody.
            pass

    # -- internals ---------------------------------------------------------

    def _advance(self) -> Prompt | None:
        """Read replies until greetd wants something or is finished.

        Informational and error lines from PAM arrive as their own messages
        and are not questions, so they are collected and the loop keeps
        reading. Anything else ends the loop one way or another.
        """
        while True:
            reply = self.transport.receive()
            kind = reply.get("type")
            if kind == "auth_message":
                message = self._auth_message(reply)
                if message is not None:
                    self.state = self.ASKING
                    self.prompt = message
                    return message
                continue
            if kind == "success":
                self.state = self.READY
                self.prompt = None
                return None
            if kind == "error":
                self.state = self.CLOSED
                self.prompt = None
                if reply.get("error_type") == "auth_error":
                    self._clear_refused()
                    raise AuthFailed(_description(
                        reply, "that did not sign you in"))
                raise GreeterError(_description(
                    reply, "the login service could not sign you in"))
            raise GreeterError("the login service answered something unexpected")

    def _clear_refused(self) -> None:
        """Tell greetd the refused attempt is over.

        greetd keeps an attempt it has refused configured until it is
        cancelled, and answers the next ``create_session`` with "a session is
        already being configured". The greeter read that as a service that had
        died, told the person to restart the computer, and a single mistyped
        password kept everybody out until somebody did. greetd's own answer
        to this cancel is an error as well, because the PAM conversation
        behind the attempt has already gone, and it clears the attempt all
        the same, so it is read and dropped.
        """
        try:
            self.transport.send({"type": "cancel_session"})
            self.transport.receive()
        except GreeterError:
            pass

    def _auth_message(self, reply: dict[str, Any]) -> Prompt | None:
        kind = reply.get("auth_message_type")
        text = reply.get("auth_message")
        if not isinstance(text, str):
            text = ""
        if kind in PROMPTS:
            return Prompt(kind, text)
        if kind in NOTICES:
            self.notices.append(Notice(kind, text))
            return None
        raise GreeterError("the login service asked something unrecognised")


def _description(reply: dict[str, Any], fallback: str) -> str:
    text = reply.get("description")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return fallback
