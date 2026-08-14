"""The graphical installer's model process, driven over its real protocol.

This is the test that matters. The graphical front end reaches the destructive
engine through exactly one path - the bridge - so every safety property of the
graphical installer is a statement about what this protocol will and will not
do, and each one is checked by running it rather than by reading it.

It also runs the shipped Python client against the shipped shell model, so a
buffering or quoting bug between them fails here rather than on a machine with
a disk in it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager

TESTS = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.normpath(os.path.join(TESTS, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "installer", "lib"))

from aurade_gui import flow as F  # noqa: E402
from aurade_gui.bridge import Bridge, BridgeError  # noqa: E402

TMP = sys.argv[1]
BRIDGE = os.path.join(ROOT, "installer", "bin", "aurade-installer-gui-bridge")

PASSWORD = "correct horse battery staple"
PASSPHRASE = "a passphrase with  spaces"

FAILURES: list[str] = []
SEEN: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def equal(got: object, want: object, message: str) -> None:
    if got != want:
        FAILURES.append(f"{message}: expected {want!r}, got {got!r}")


class Recording(Bridge):
    """A bridge that keeps every reply, so a leak test can look at all of them."""

    def call(self, command, argument=None, value=None):
        reply = super().call(command, argument, value)
        SEEN.append(json.dumps(reply))
        return reply


#: The same bridge, run from a tree laid out like the image and carrying no
#: diagnostic helpers, so the "this image does not have that" branches are
#: reachable. Pointing an override at an absent path would not do it: the front
#: ends fall back to a helper beside themselves, which in the source tree is
#: present.
BARE_BRIDGE = os.path.join(TMP, "image", "sbin", "aurade-installer-gui-bridge")


@contextmanager
def session(plan_only: bool = False, program: str = BRIDGE, **overrides):
    env = dict(os.environ)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    model = Recording(
        program=program,
        journal=os.path.join(TMP, "run", "journal.jsonl"),
        raw_log=os.path.join(TMP, "run", "install.log"),
        plan_only=plan_only,
        env=env,
    )
    model.start()
    try:
        yield model
    finally:
        model.close()


def shell(script: str) -> str:
    """Ask the question manifest directly, without going through the bridge."""
    return subprocess.run(
        ["bash", "-c", f'. "{ROOT}/installer/lib/aurade-questions.sh"\n{script}'],
        capture_output=True,
        text=True,
        check=True,
        env=dict(os.environ),
    ).stdout


def answer_everything(model: Bridge) -> None:
    for question, value in (
        ("locale", "en_US.UTF-8"),
        ("keymap", "us"),
        ("timezone", "UTC"),
        ("target", "/dev/sda"),
        ("hostname", "aurade-laptop"),
        ("username", "alex"),
        ("encrypt", "yes"),
    ):
        ok, error = model.set(question, value)
        check(ok, f"answering {question} was refused: {error}")
    for question, value in (("password", PASSWORD), ("luks_passphrase", PASSPHRASE)):
        ok, error = model.secret(question, value)
        check(ok, f"answering {question} was refused: {error}")


def calls() -> list[str]:
    path = os.path.join(TMP, "calls")
    if not os.path.exists(path):
        return []
    with open(path) as handle:
        return [line.rstrip("\n") for line in handle]


def reset_calls() -> None:
    for name in ("calls", "passphrase.seen", "hash.seen"):
        path = os.path.join(TMP, name)
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# The manifest is the shared manifest
# ---------------------------------------------------------------------------

with session() as model:
    check(model.ping(), "the model did not answer a ping")
    manifest = model.manifest()

    shell_ids = shell('printf "%s\\n" "${AURADE_QUESTION_IDS[@]}"').split()
    equal(
        sorted(manifest["questions"]),
        sorted(shell_ids),
        "the bridge and the question manifest disagree about which questions exist",
    )
    for question in shell_ids:
        for field in ("label", "short", "help", "type", "error"):
            equal(
                manifest["questions"][question][field],
                shell(f'aurade_question_field {question} {field}'),
                f"{question}.{field} does not match the manifest",
            )
        equal(
            manifest["questions"][question]["default"],
            shell(f"aurade_question_default {question}"),
            f"{question} default does not match the manifest",
        )

    # The advanced question with no literal default is exactly why this is
    # resolved rather than read: the engine requires --arch-snapshot, so a
    # blank default would mean anyone who skipped advanced options answered
    # every question and then failed at argument parsing.
    equal(
        manifest["questions"]["snapshot"]["default"],
        "2026/07/12",
        "the snapshot default was not resolved from the image",
    )

    # Every question the manifest carries is on exactly one graphical page.
    # A question added to the manifest and forgotten here is a question the
    # graphical installer would never ask while the engine still required it.
    pages = {}
    for question in shell_ids:
        page = F.page_for_question(question)
        check(page is not None, f"the manifest question {question} is on no page")
        if page is not None:
            pages.setdefault(question, page.name)
    for question in F.grouped_questions():
        check(
            question in shell_ids,
            f"the graphical flow asks {question}, which the manifest does not carry",
        )

    equal(
        sorted(manifest["advanced"]),
        sorted(shell(
            'for id in "${AURADE_QUESTION_IDS[@]}"; do '
            'aurade_question_is_advanced "$id" && printf "%s\\n" "$id"; done; true'
        ).split()),
        "the bridge and the manifest disagree about which questions are advanced",
    )

# ---------------------------------------------------------------------------
# Validation is delegated, never restated
# ---------------------------------------------------------------------------

with session() as model:
    ok, error = model.set("hostname", "-illegal-")
    check(not ok, "an invalid hostname was accepted")
    equal(
        error,
        shell("aurade_question_field hostname error"),
        "the rejection did not carry the manifest's own error text",
    )
    equal(model.get("hostname"), "", "a rejected answer was recorded anyway")

    ok, _ = model.set("hostname", "aurade-laptop")
    check(ok, "a valid hostname was rejected")
    equal(model.get("hostname"), "aurade-laptop", "an accepted answer was not recorded")

    # A partition is not a whole disk. Installing to one silently skips the
    # partition table the bootloader needs.
    ok, _ = model.set("target", "/dev/sda1")
    check(not ok, "a partition was accepted as an installation target")
    ok, _ = model.set("target", "/dev/nonexistent")
    check(not ok, "a device that does not exist was accepted as a target")
    ok, _ = model.set("target", "/dev/sda")
    check(ok, "a whole disk was rejected as a target")

    ok, _ = model.set("username", "root")
    check(not ok, "a reserved system name was accepted as a username")

    ok, error = model.set("nonexistent", "value")
    check(not ok, "an unknown question was accepted")
    check("unknown question" in error, f"an unknown question gave a poor error: {error}")

# ---------------------------------------------------------------------------
# Disk enumeration and target identity
# ---------------------------------------------------------------------------

with session() as model:
    disks = model.disks()
    check(len(disks) >= 2, f"expected at least 2 disks from fixture, got {len(disks)}")
    for d in disks:
        for field in ("path", "size", "model", "transport", "serial", "wwn"):
            check(field in d, f"disk object missing {field} field: {d}")
    equal(disks[0]["path"], "/dev/sda", "first disk path does not match")
    equal(disks[0]["model"], "WDC WD10EZEX", "first disk model does not match")
    equal(disks[0]["serial"], "WD-WCC6Y4KP1234", "first disk serial does not match")
    equal(disks[0]["transport"], "sata", "first disk transport does not match")
    equal(disks[0]["size"], "931.5G", "first disk size does not match")

    # Target info before selection
    target_unselected = model.target()
    check(not target_unselected.get("ok"), "target succeeded before disk chosen")

    # Target info after selection
    ok, _ = model.set("target", "/dev/sda")
    check(ok, "setting target to /dev/sda failed")
    target_info = model.target()
    check(target_info.get("ok"), f"target failed for /dev/sda: {target_info}")
    equal(target_info.get("path"), "/dev/sda", "target path mismatch")
    equal(target_info.get("model"), "WDC WD10EZEX", "target model mismatch")
    equal(target_info.get("serial"), "WD-WCC6Y4KP1234", "target serial mismatch")
    check("wwn" in target_info, f"wwn field missing from target info: {target_info}")
    equal(target_info.get("size"), "931.5G", "target size mismatch")
    equal(target_info.get("transport"), "sata", "target transport mismatch")
    equal(target_info.get("token"), "ERASE:/dev/sda", "target token mismatch")


# ---------------------------------------------------------------------------
# Answers that take effect immediately
# ---------------------------------------------------------------------------

with session(PATH=f"{TMP}/stub:{os.environ['PATH']}") as model:
    ok, _ = model.set("keymap", "fr")
    check(ok, "a loadable keymap was rejected")
    with open(os.path.join(TMP, "loadkeys.log")) as handle:
        check("fr" in handle.read().split(), "loadkeys was not called for the keymap")

with session(
    PATH=f"{TMP}/stub:{os.environ['PATH']}", AURADE_TEST_LOADKEYS_REJECT="de"
) as model:
    ok, error = model.set("keymap", "de")
    check(not ok, "a keymap the console refused to load was accepted")
    check(
        "could not be loaded" in error,
        f"the console rejection gave a poor error: {error}",
    )
    equal(model.get("keymap"), "", "a keymap that would not load was recorded anyway")

# A missing loadkeys is not a failure. The image ships kbd, but a test host or
# a serial console may not, and refusing would make the question unanswerable.
with session(PATH=os.path.join(TMP, "nokeys")) as model:
    ok, error = model.set("keymap", "us")
    check(ok, f"a missing loadkeys was treated as a failure: {error}")
    equal(model.get("keymap"), "us", "a keymap was not recorded without loadkeys")

# ---------------------------------------------------------------------------
# Which questions apply
# ---------------------------------------------------------------------------

with session() as model:
    model.set("encrypt", "no")
    check(
        "luks_passphrase" not in model.visible(),
        "the passphrase is asked for when encryption is off",
    )
    equal(
        F.encryption_questions_visible("no"),
        False,
        "the flow's stated expectation disagrees with the model",
    )
    model.set("encrypt", "yes")
    check(
        "luks_passphrase" in model.visible(),
        "the passphrase is not asked for when encryption is on",
    )

# ---------------------------------------------------------------------------
# Secrets go in and do not come back
# ---------------------------------------------------------------------------

reset_calls()
with session() as model:
    answer_everything(model)
    equal(model.get("password"), "set", "the password was readable through the model")
    equal(
        model.get("luks_passphrase"),
        "set",
        "the passphrase was readable through the model",
    )
    review = model.answers()
    equal(review["password"]["value"], "set", "the review screen shows the password")
    equal(
        review["luks_passphrase"]["value"],
        "set",
        "the review screen shows the passphrase",
    )

    result = model.plan()
    check(result.get("ok"), f"a valid plan was refused: {result}")

    recorded = calls()
    equal(len(recorded), 1, "the plan step did not invoke the engine exactly once")
    argv = recorded[0]
    check("--dry-run" in argv.split(), "the plan step did not run the engine's dry run")
    check("--execute" not in argv.split(), "the plan step reached the execute path")
    for expected in (
        "--target /dev/sda",
        "--hostname aurade-laptop",
        "--username alex",
        "--encrypt",
        "--arch-snapshot 2026/07/12",
        "--password-hash-file",
        "--luks-passphrase-file",
        "--bundle-dir",
    ):
        check(expected in argv, f"the engine was not given {expected}: {argv}")

    # The passphrase the engine was handed is the passphrase that was typed,
    # spaces and all. A widget that dropped the space key has already shipped
    # here once, and it was only found when a disk would not unlock.
    with open(os.path.join(TMP, "passphrase.seen")) as handle:
        equal(handle.read(), PASSPHRASE, "the passphrase reached the engine altered")
    with open(os.path.join(TMP, "hash.seen")) as handle:
        digest = handle.read().strip()
    check(digest.startswith("$6$"), f"the engine was not given a crypt hash: {digest}")
    check(PASSWORD not in digest, "the password reached the engine in readable form")

for haystack, where in (
    ("\n".join(SEEN), "a protocol response"),
    ("\n".join(calls()), "an engine argument list"),
    (open(os.path.join(TMP, "run", "install.log")).read(), "the raw installer log"),
    (open(os.path.join(TMP, "run", "journal.jsonl")).read()
     if os.path.exists(os.path.join(TMP, "run", "journal.jsonl")) else "", "the journal"),
):
    check(PASSWORD not in haystack, f"the password appeared in {where}")
    check(PASSPHRASE not in haystack, f"the passphrase appeared in {where}")

# ---------------------------------------------------------------------------
# A plan the engine rejects is a plan that failed
# ---------------------------------------------------------------------------

reset_calls()
with session(AURADE_STUB_DRYRUN_STATUS="3") as model:
    answer_everything(model)
    result = model.plan()
    check(not result.get("ok"), f"a rejected dry run reported success: {result}")
    equal(result.get("status"), 3, "the engine's own status was not carried through")

    # And a rejected plan is not a checked plan, so nothing may execute on it.
    check(
        not model.execute("ERASE:/dev/sda").get("ok"),
        "an erase started on a plan the engine rejected",
    )
    check(
        not any("--execute" in call for call in calls()),
        "the execute path was reached after a rejected dry run",
    )

reset_calls()
with session() as model:
    # No disk chosen: the plan step refuses before it hashes anything.
    check(not model.plan().get("ok"), "a plan was built without a disk")
    equal(calls(), [], "the engine ran without a disk chosen")
    ok, error = model.secret("password", "")
    check(not ok, "an empty password was accepted")
    check(bool(error), "an empty password was refused without saying why")
    ok, _ = model.secret("hostname", "value")
    check(not ok, "a question that is not a secret accepted one")


# ---------------------------------------------------------------------------
# Nothing reaches --execute without a checked plan and the exact token
# ---------------------------------------------------------------------------

reset_calls()
with session() as model:
    answer_everything(model)
    result = model.execute("ERASE:/dev/sda")
    check(not result.get("ok"), "an erase started without a checked plan")
    check(
        "plan" in result.get("error", ""),
        f"refusing an unplanned erase gave a poor error: {result}",
    )
    equal(calls(), [], "the engine was invoked without a checked plan")

    check(model.plan().get("ok"), "a valid plan was refused")

    result = model.execute("ERASE:/dev/sdb")
    check(not result.get("ok"), "an erase started with a token for another disk")
    result = model.execute("erase:/dev/sda")
    check(not result.get("ok"), "an erase started with a token of the wrong case")
    result = model.execute("ERASE:/dev/sda ")
    check(not result.get("ok"), "an erase started with a token with trailing space")
    check(
        not any("--execute" in call for call in calls()),
        "a rejected confirmation still reached the execute path",
    )

    result = model.execute("ERASE:/dev/sda")
    check(result.get("ok"), f"the correct confirmation was refused: {result}")
    finished = model.wait()
    equal(finished.get("status"), 0, "the stub install did not finish cleanly")

    executed = [call for call in calls() if "--execute" in call]
    equal(len(executed), 1, "the engine ran the execute path other than once")
    check(
        "--confirm ERASE:/dev/sda" in executed[0],
        f"the engine was not given the confirmation token: {executed[0]}",
    )

    # Progress is a view of the journal, and shows only stages the engine emits.
    progress = model.progress()
    check(not progress["running"], "the engine was reported running after it exited")
    drawn = [row["stage"] for row in progress["stages"]]
    for hidden in ("network", "verify", "done"):
        check(
            hidden not in drawn,
            f"the progress view lists {hidden}, which the engine never emits",
        )
    equal(
        [row["stage"] for row in model.stages()],
        drawn,
        "the stage list and the progress view disagree",
    )
    for row in progress["stages"]:
        equal(row["status"], "ok", f"the {row['stage']} stage did not complete")

# ---------------------------------------------------------------------------
# --plan-only: execute is not refused, it does not exist
# ---------------------------------------------------------------------------

reset_calls()
with session(plan_only=True) as model:
    answer_everything(model)
    result = model.plan()
    check(result.get("ok"), f"a plan-only session could not check a plan: {result}")
    equal(result.get("plan_only"), True, "a plan-only session did not say so")

    result = model.execute("ERASE:/dev/sda")
    check(not result.get("ok"), "a plan-only session started an erase")
    check(
        "unknown command" in result.get("error", ""),
        f"execute was refused rather than absent in plan-only mode: {result}",
    )
    result = model.call("wait")
    check(
        "unknown command" in result.get("error", ""),
        "wait exists in a plan-only session, which implies something to wait for",
    )
    check(
        not any("--execute" in call for call in calls()),
        "a plan-only session reached the execute path",
    )

# ---------------------------------------------------------------------------
# Failure is explained from the journal
# ---------------------------------------------------------------------------

reset_calls()
with session(AURADE_STUB_FAIL_AT="pacstrap") as model:
    answer_everything(model)
    check(model.plan().get("ok"), "a valid plan was refused")
    check(model.execute("ERASE:/dev/sda").get("ok"), "the install did not start")
    finished = model.wait()
    check(finished.get("status") != 0, "a failing install reported success")
    status = int(finished["status"])

    report = model.failure()
    equal(report["stage"], "pacstrap", "the failure was attributed to the wrong stage")
    equal(
        report["label"],
        "Install the base system",
        "the failure screen used the journal's engineering name",
    )
    check(bool(report["explanation"]), "the failure screen explained nothing")
    check(
        not report["reversible"],
        "a failure after the erase gate was described as reversible",
    )
    check(
        "erases it and begins from the beginning" in report["restart_advice"],
        f"restarting after an irreversible failure was undersold: {report}",
    )
    equal(report["position"], "stage 7 of 11", "the failure screen miscounted stages")

    progress = model.progress()
    failed = [row for row in progress["stages"] if row["status"] == "failed"]
    equal([row["stage"] for row in failed], ["pacstrap"], "the progress view disagrees")

    # Saving a report says whether it worked, and a failed export never says
    # "Saved". The helper's exit status cannot answer that question, because it
    # exits with the install's own status on success and 2 on failure.
    result = model.export(status)
    check(result.get("ok"), f"a working export reported failure: {result}")
    check("Saved to" in result.get("notice", ""), f"a working export said: {result}")

with session(AURADE_FAILURE_HELPER=os.path.join(TMP, "stub", "broken-helper")) as model:
    result = model.export(2)
    check(not result.get("ok"), "a failed export reported success")
    check(
        "Saved" not in result.get("notice", ""),
        f"a failed export claimed the report was saved: {result}",
    )
    check(
        "Could not save a report" in result.get("notice", ""),
        f"a failed export gave no actionable message: {result}",
    )

with session(program=BARE_BRIDGE, AURADE_FAILURE_HELPER=None) as model:
    result = model.export(1)
    check(not result.get("ok"), "a missing export helper reported success")
    check(
        "missing from this image" in result.get("notice", ""),
        f"a missing export helper gave a poor message: {result}",
    )

# Two saves in the same second. The second one has nowhere new to write, and
# must not inherit the first one's success.
with session() as model:
    first = model.export(1)
    check(first.get("ok"), f"the first export failed: {first}")
    second = model.export(1)
    check(second.get("ok"), f"an immediate second export failed: {second}")
    check(
        first.get("notice") != second.get("notice"),
        f"two exports reported the same destination: {first}",
    )

# ---------------------------------------------------------------------------
# The network page reports the existing read-only check
# ---------------------------------------------------------------------------

with session(AURADE_NETWORK_HELPER=os.path.join(TMP, "stub", "net-ok")) as model:
    report = model.network()
    check(report["ok"], f"a healthy network was reported as a problem: {report}")
    check(report["available"], "a present network check was reported missing")
    check(bool(report["notes"]), "a healthy network check reported nothing")
    equal(report["issues"], [], "a healthy network check reported an issue")

with session(AURADE_NETWORK_HELPER=os.path.join(TMP, "stub", "net-bad")) as model:
    report = model.network()
    check(not report["ok"], "a broken network was reported as healthy")
    check(
        any("clock" in issue for issue in report["issues"]),
        f"the network check did not carry its own message: {report}",
    )

with session(program=BARE_BRIDGE, AURADE_NETWORK_HELPER=None) as model:
    report = model.network()
    check(not report["available"], "a missing network check was reported as present")
    check(bool(report["issues"]), "a missing network check said nothing at all")
    check(
        not report["ok"],
        "a network check that could not run was reported as having passed",
    )

# ---------------------------------------------------------------------------
# The graphics probe, as the page reads it
# ---------------------------------------------------------------------------

with session(AURADE_PROBE_DRI_DIR=os.path.join(TMP, "empty-dri")) as model:
    probe = model.probe()
    equal(probe["renderer"], "tui", "a machine with no render node offered a GUI")
    equal(probe["reason"], "no-render-node", "the probe gave the wrong reason")
    check(
        probe["predicts_black_screen"],
        "a machine with no render node was not warned about a black desktop",
    )
    check("3D acceleration" in probe["advice"], f"the advice was not actionable: {probe}")

# A render node with a named kernel driver behind it. This is what an ordinary
# machine looks like, and it is the wording most users will read.
with session(
    PATH=os.path.join(TMP, "nokeys"),
    AURADE_PROBE_DRM_DIR=os.path.join(TMP, "drm"),
) as model:
    probe = model.probe()
    equal(probe["reason"], "ok", f"the healthy fixture did not pass the probe: {probe}")
    equal(probe["driver"], "i915", "the probe did not read the driver from sysfs")
    # A device file proves a driver published a node. It does not prove working
    # 3D acceleration, and the wording must not claim it does.
    check(
        "only proven once the desktop starts" in probe["advice"],
        f"the probe overclaimed what a render node proves: {probe['advice']}",
    )
    # "Hardware rendering is available" is reserved for the branch where a GL
    # probe actually answered. Sysfs alone may not borrow it.
    for overclaim in ("Hardware rendering is available", "acceleration is working"):
        check(
            overclaim not in probe["advice"],
            f"the graphics page claims working acceleration: {probe['advice']}",
        )
    check(not probe["predicts_black_screen"], "a working node predicted a black screen")

# The same node with nothing in sysfs behind it. Still not a black screen, and
# still no claim beyond what was established.
with session(
    PATH=os.path.join(TMP, "nokeys"),
    AURADE_PROBE_DRM_DIR=os.path.join(TMP, "drm-unknown"),
) as model:
    probe = model.probe()
    equal(probe["reason"], "ok", f"an unidentified driver failed the probe: {probe}")
    equal(probe["driver"], "", "a driver was reported with no sysfs entry to read")
    check(
        "could not be identified" in probe["advice"],
        f"an unidentified driver was described as known: {probe['advice']}",
    )
    check(
        "only proven once the desktop starts" in probe["advice"],
        f"the probe overclaimed what a render node proves: {probe['advice']}",
    )

# A render node that is a kernel test device, not a GPU. This is the one that
# predicts a black desktop on a virtual machine with 3D acceleration off.
with session(
    PATH=os.path.join(TMP, "nokeys"),
    AURADE_PROBE_DRM_DIR=os.path.join(TMP, "drm-virtual"),
) as model:
    probe = model.probe()
    equal(probe["reason"], "virtual-gpu-only", f"a vgem node passed the probe: {probe}")
    check(
        probe["predicts_black_screen"],
        "a virtual-only graphics device was not warned about",
    )
    check(
        "3D acceleration" in probe["advice"],
        f"the virtual-device advice was not actionable: {probe['advice']}",
    )

# ---------------------------------------------------------------------------
# Candidate lists for enum questions
# ---------------------------------------------------------------------------

with session() as model:
    for question in ("keymap", "locale", "timezone"):
        candidates = model.enum(question)
        check(
            isinstance(candidates, list) and len(candidates) > 0,
            f"model.enum({question!r}) did not return a non-empty candidate list: {candidates}",
        )

# ---------------------------------------------------------------------------
# Protocol safety: newline injection is rejected with BridgeError
# ---------------------------------------------------------------------------

with session() as model:
    try:
        model.call("ping\n")
    except BridgeError:
        pass
    else:
        FAILURES.append("model.call() with newline in command did not raise BridgeError")

    try:
        model.call("get", "hostname\n")
    except BridgeError:
        pass
    else:
        FAILURES.append("model.call() with newline in argument did not raise BridgeError")

    try:
        model.call("set", "hostname", "bad\nhostname")
    except BridgeError:
        pass
    else:
        FAILURES.append("model.call() with newline in value did not raise BridgeError")


if FAILURES:
    for failure in FAILURES:
        print(f"test-gui-bridge: {failure}", file=sys.stderr)
    sys.exit(1)
print("installer GUI bridge test: PASS")
