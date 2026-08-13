"""Client for the shell model process.

Everything the graphical installer knows about questions, validation, disks,
graphics, the journal and the engine arrives through here. The renderer holds
no manifest and makes no decision this file cannot get an answer for, because
the alternative is two implementations of the join between a typed answer and
a destructive command line.

The protocol is one command per line, one line of JSON per response. Commands
that carry a value send it as the next line, byte for byte, so a passphrase
with spaces or a device path with a ``*`` in it survives the trip. A value
containing a newline is refused here rather than silently truncated: a
password that arrives cut in half would install an account nobody can sign
into, and it would look like it worked.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any


class BridgeError(RuntimeError):
    """The model process could not answer, or is gone."""


class Bridge:
    """A running ``aurade-installer-gui-bridge``.

    One process for the whole session. That is what lets a password be sent
    once, hashed inside the model, and never exist anywhere the renderer can
    read it back; a fresh process per command would have to be handed the
    secret again for every step that needed it.
    """

    def __init__(
        self,
        program: str,
        journal: str,
        raw_log: str,
        plan_only: bool = False,
        env: dict[str, str] | None = None,
    ) -> None:
        self.program = program
        self.journal = journal
        self.raw_log = raw_log
        self.plan_only = plan_only
        self._env = dict(os.environ if env is None else env)
        self._proc: subprocess.Popen[str] | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "Bridge":
        argv = [self.program, "--journal", self.journal, "--raw-log", self.raw_log]
        if self.plan_only:
            argv.append("--plan-only")
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                bufsize=1,
                env=self._env,
            )
        except OSError as exc:
            raise BridgeError(f"cannot start the installer model: {exc}") from exc
        return self

    def close(self) -> int:
        proc = self._proc
        if proc is None:
            return 0
        self._proc = None
        try:
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
                proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass
        try:
            return proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            return proc.wait()

    def __enter__(self) -> "Bridge":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- protocol ----------------------------------------------------------

    def call(
        self, command: str, argument: str | None = None, value: str | None = None
    ) -> Any:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise BridgeError("the installer model is not running")
        if proc.poll() is not None:
            raise BridgeError("the installer model exited unexpectedly")
        line = command if argument is None else f"{command} {argument}"
        if "\n" in line:
            raise BridgeError("a command may not contain a newline")
        if value is not None and "\n" in value:
            raise BridgeError("an answer may not contain a line break")
        try:
            proc.stdin.write(line + "\n")
            if value is not None:
                proc.stdin.write(value + "\n")
            proc.stdin.flush()
            reply = proc.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise BridgeError(f"the installer model stopped responding: {exc}") from exc
        if not reply:
            raise BridgeError("the installer model stopped responding")
        try:
            return json.loads(reply)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"unreadable reply from the installer model: {exc}") from exc

    # -- typed accessors ---------------------------------------------------
    #
    # Thin on purpose. Each one is the shell function it names; adding
    # cleverness here would be the start of a second model.

    def ping(self) -> bool:
        return bool(self.call("ping").get("ok"))

    def manifest(self) -> dict[str, Any]:
        return self.call("manifest")

    def visible(self) -> list[str]:
        return self.call("visible")

    def disks(self) -> list[dict[str, str]]:
        return self.call("disks")

    def probe(self) -> dict[str, Any]:
        return self.call("probe")

    def network(self) -> dict[str, Any]:
        return self.call("network")

    def stages(self) -> list[dict[str, Any]]:
        return self.call("stages")

    def enum(self, question: str) -> list[str]:
        return self.call("enum", question)

    def answers(self) -> dict[str, dict[str, Any]]:
        return self.call("answers")

    def target(self) -> dict[str, Any]:
        return self.call("target")

    def progress(self) -> dict[str, Any]:
        return self.call("progress")

    def failure(self) -> dict[str, Any]:
        return self.call("failure")

    def get(self, question: str) -> str:
        return str(self.call("get", question).get("value", ""))

    def set(self, question: str, value: str) -> tuple[bool, str]:
        reply = self.call("set", question, value)
        return bool(reply.get("ok")), str(reply.get("error", ""))

    def secret(self, question: str, value: str) -> tuple[bool, str]:
        """Send a secret; the model hashes or stores it immediately."""
        reply = self.call("secret", question, value)
        return bool(reply.get("ok")), str(reply.get("error", ""))

    def plan(self) -> dict[str, Any]:
        return self.call("plan")

    def execute(self, token: str) -> dict[str, Any]:
        """Start the destructive run. Absent entirely in plan-only mode."""
        return self.call("execute", token)

    def wait(self) -> dict[str, Any]:
        return self.call("wait")

    def export(self, status: int) -> dict[str, Any]:
        return self.call("export", str(int(status)))


def find_bridge(self_dir: str) -> str | None:
    """Where the model process lives, image first, source tree second."""
    override = os.environ.get("AURADE_GUI_BRIDGE")
    if override:
        return override if os.access(override, os.X_OK) else None
    candidates = [
        "/usr/local/sbin/aurade-installer-gui-bridge",
        os.path.join(self_dir, "aurade-installer-gui-bridge"),
    ]
    for candidate in candidates:
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("aurade-installer-gui-bridge")
