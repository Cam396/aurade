# AuraDE installer UI contract

What the front ends are allowed to be, and what they are not allowed to
change. `installer/EXECUTE_PATH_CONTRACT.md` covers what a run must prove;
this covers what the interface owes the person in front of it.

## One engine, one journal, three renderers

`installer/bin/aurade-install` is the deterministic destructive engine. It is
noninteractive, takes arguments, checks everything before it touches a disk,
and writes an append-only journal. Nothing in a front end may change that.

A front end may:

- ask the questions in `installer/lib/aurade-questions.sh`;
- render `installer/lib/aurade-journal.sh` records as progress and failure;
- pass answers to the engine as arguments and mode-0600 files.

A front end may not:

- reimplement a validation rule, a stage, or the confirmation token;
- carry its own question list;
- decide on its own what is reversible or resumable;
- write a secret anywhere except a mode-0600 file it removes on exit.

`installer/bin/aurade-installer-tui` is the text renderer and the guaranteed
one. `installer/bin/aurade-installer-gui` is the graphical renderer. The older
`installer/bin/aurade-installer` remains as a plain prompt-by-prompt flow.
`installer/bin/aurade-installer-start` chooses between the first two using the
probe, and is what the message of the day names.

The graphical renderer owns no contract. It talks to
`installer/bin/aurade-installer-gui-bridge`, which sources the text renderer
with `AURADE_INSTALLER_TUI_LIB=1` and therefore holds the identical
`build_engine_args`, `hash_password`, `write_secret`, `apply_answer`, disk
table, journal readers and stage vocabulary. A graphical installer that built
its own argument list would be a second implementation of the one join where a
mistake reaches a destructive engine, and the two would drift.

The dependency runs one way, and that direction is the point. Nothing in the
bridge or the graphical front end is on the text installer's path, so a broken
or absent graphical renderer cannot affect the fallback. Every way the
graphical path can fail - no toolkit, no compositor, no display, a probe that
says no - ends in the text installer, with the reason printed.

Python is the graphical renderer's language because `python-gobject` is how
GTK 4 is scripted and Python is already on the image. The split inside
`installer/lib/aurade_gui/` follows one line: `bridge.py` and `flow.py` import
no `gi` and are tested headlessly; `app.py` is widgets and is checked against
the toolkit's own introspection data.

## Questions are data

`installer/lib/aurade-questions.sh` holds the question set: label, help, type,
default, validator, error text, advanced flag, engine flag, secret flag. Three
invariants are enforced by `installer/tests/test-questions.sh`:

1. Every default is accepted by its own validator. A default its own rule
   rejects is a prompt the user cannot leave by pressing enter.
2. Every named validator exists. A typo would otherwise be a silently
   accepted answer.
3. Every `flag` is one `aurade-install` parses. This is the join between the
   UI and the engine and the one that rots quietly.

Advanced questions must have working defaults, because skipping the advanced
section has to produce a complete argument list.

A question the engine cannot consume does not belong in the manifest. A prompt
that collects an answer nothing acts on is worse than no prompt.

## Rendering

68 columns, framed. The frame may be Unicode; the interior is strictly ASCII,
because box drawing is reliably one column wide and check marks, arrows and
bullets are not. Width is computed on plain text before colour is applied.

Three tiers: 256 colour, 16 colour, and none. `NO_COLOR`, `TERM=dumb` and
"output is not a terminal" all select the bottom tier, which emits no escape
sequences at all. That tier is the serial console and screen reader path and
has to stay fully operable, not merely legible.

Rendered text is never glob-expanded. Word splitting inside the renderer runs
with pathname expansion disabled, because journal messages, device paths and
failure details can all contain `*` or `?`, and unquoted splitting replaces
them with whatever filenames happen to match.

`--render SCREEN [--journal FILE]` draws any single screen from fixture state
and exits, which is how the layout is tested and how a support case is
reproduced. `--list-screens` prints the set.

## Look

The palette is a Material 3 tonal system whose key colours are measured out of
`assets/aurade-logo.png` by `installer/tools/generate-theme.py`. The mark is a
periwinkle plate carrying a ribbon `A` that runs lilac on the left to aqua on
the right; those two ends are the primary and tertiary accents, and the plate
is the hue the neutrals are tinted with. A palette invented alongside the logo
rather than out of it is how a product ends up with brand artwork that does
not match its own interface.

Tones are solved in OKLCh against a CIELAB lightness target. That
approximates Material 3's HCT rather than reproducing it, and the comment in
the generator says so; the role mapping, shape scale, state-layer opacities
and type scale are the published specification. libadwaita's own named
colours are redefined from the same roles, so stock widgets wear the palette
instead of being fought with per-widget overrides.

`installer/tests/test-gui-theme.sh` regenerates and compares, so a colour hand
edited into the stylesheet does not survive. It also measures every
foreground/background pair in both schemes, requires AAA for body text rather
than AA, and compares the accent hues back to the artwork, so a redrawn logo
that nobody propagated fails there instead of shipping.

Two registers of type. Prose is the system sans. Anything the user has to
match against hardware or type back exactly - a device path, a disk serial,
the erase token, a stage timing - is mono, because a face that separates `0`
from `O` is the difference between confirming the right disk and confirming a
different one. That is why the image carries a mono face at all.

Motion is only ever a state change, a piece of feedback, or the aurora. The
aurora runs on the pages that are about the product and stops on the pages
that are about a decision, and all of it stops when GTK reports that
animations are switched off.

## Progress is a view, not an account

The progress screen is a function of the journal. It does not keep its own
record of what happened, and it does not display stages the engine never
emits: `network` and `verify` are folded into `preflight` and `acquire`, and a
row that stays grey while the rows below it complete reads as a hung step.

## Navigation and cancellation

Every footer states what the key actually does. This is a hard rule, not a
style note: a footer offering `esc back` on a screen that exits is worse than
no footer, because it is read at the moment the user is least sure.

`main_flow` is a state machine rather than a straight line, because "back" has
to be able to go back:

| Screen | `esc` |
| --- | --- |
| Graphics check, welcome | quits |
| First question | quits, after confirming |
| Later questions | previous question |
| Review | reopens the last question |
| Erase gate | returns to review |
| Progress | nothing — no key is offered, because none is read |

The graphical renderer states the same thing with a button rather than a
footer, and the label comes from the same call that decides the action:
`Flow.back_action` returns `quit`, `back` or nothing, and `Flow.back_label`
is derived from it, so a button reading "Back" on a screen that quits is not
expressible. `Escape` is bound to whatever that button does, and no control at
all is drawn once the erase gate is behind the user.

Returning to a question shows the answer already given, not the default.
A "back" that silently rewrites an answer to its default is the same class of
untruth as a wrong footer.

Returning to review re-runs the dry run, so the plan approved at the gate is
always the plan for the answers currently held.

The graphical review screen goes further: every row opens the page that set
it. Walking back through four screens to fix one typo is how people talk
themselves into accepting a wrong answer.

Cancellation is asymmetric, because the disk is.

| Region | Stages | Behaviour |
| --- | --- | --- |
| Reversible | `preflight` … `confirm` | Cancel freely. The UI states that nothing was written. |
| The gate | typing `ERASE:<target>` | Last free exit. |
| Irreversible | `partition` … `done` | No cancel is offered, and none is advertised. |

The boundary comes from `aurade_stage_reversible`, not from a second opinion
held in the renderer.

Inside the reversible region the graphical installer offers Stop, and that is
not a new capability: `aurade-install` already traps `TERM`, already records a
`cancelled` stage failure, and already unmounts, closes any LUKS mapping and
removes its work directory on the way out. The renderer only surfaces it, and
only while the shared boundary says nothing has been written. At the boundary
the control is removed rather than disabled, because a greyed-out Stop invites
the user to keep pressing it at the exact moment the answer has become no. A
run ended this way reaches a `stopped` screen and not the failure screen: a
run the user ended on purpose is not a run that broke.

`--plan-only` reaches a terminal `planned` state that has no transition to
`execute`. It is not a flag checked before a destructive call; it is a state
from which the destructive call is unreachable.

Both renderers say this the same way. The bridge chooses one of two dispatch
tables once at startup, and the plan-only table has no `execute` command to
refuse — it reports `unknown command`. The graphical flow's transition graph
is walked in its test, and `gate`, `progress` and `done` must all be absent
from the set reachable from the welcome screen.

Nothing reaches `--execute` without both a dry run the engine accepted and a
confirmation token equal, whole, to `ERASE:<target>`. Those are two separate
gates in the bridge and both are tested by trying to get past them.

## Setting up a network is not a question

The engine has no flag for Wi-Fi, and the manifest carries nothing the engine
cannot consume, so joining a network sits beside `apply_answer` rather than in
the question set: something done now so the rest of the flow can proceed,
exactly like loading a keymap.

The passphrase never appears in a command line. `nmcli ... password <psk>`
would put it in argv where every process on the machine can read it, so the
profile is written the way NetworkManager stores one itself, as a mode-0600
keyfile in its own profile directory. A profile whose association failed is
deleted rather than left behind, because an installed system should not
inherit a saved network it was never able to join.

## Answers that take effect immediately

Some answers are applied as soon as they are accepted, so the rest of the flow
is operated with the setting just chosen. `apply_answer` owns this.

The keyboard is the case that matters: the layout is chosen before any
password, and a layout that passes validation but will not load on this
console has to be rejected there rather than discovered at a masked prompt.
A missing `loadkeys` is not a failure — the image ships `kbd`, but a test host
or serial console may not, and refusing to continue would make the question
unanswerable.

## Failure

Every stop names the stage, explains what it means for the disk, and offers
export, log, shell and restart.

Saving a diagnostic report reports whether it worked. The helper's exit status
cannot be used for this — it exits with the install's own status on success and
2 on failure, and the install status may itself be 2 — so the artifact is
checked directly. A failed export shows what went wrong and leaves the menu
usable; it never shows "Saved".

The destination has to be one the current call created. Two saves in the same
second are ordinary — the second is usually a retry — and a directory that
already held a previous export would answer "did this write anything" with
someone else's files.

There is deliberately no "try that step again". The journal records which
stages could safely re-run, but the engine is a linear script with no entry
point that starts at one, so invoking it again runs `wipefs` again. Offering a
retry would erase the disk a second time.

The graphical failure screen also has no "open a shell", which the text one
offers. The image carries no terminal emulator, and a button that does nothing
on the screen where the user is already stuck is worse than its absence. It
shows the raw log in a window instead, and names the log's path so it can be
reached from a console.

When the engine grows a resume entry point, the option belongs on this screen
gated on `aurade_journal_may_resume`, which requires both that the stage is
idempotent and that the disk present is still the disk the journal describes.

## Secrets

Structural, not filtered. A password is hashed as soon as it is entered and
the plaintext is removed; the engine only ever receives a crypt(3) hash in a
mode-0600 file. Secret-typed questions render as masking and appear on the
review screen as `set`. No secret is passed as a command-line argument, and
none reaches the journal, the raw log, the screen or a diagnostic export.

## Graphics

`installer/lib/aurade-probe.sh` runs before anything else and decides whether
a graphical installer could run. Its second job matters more: when the machine
has no working render node, it says so before the erase gate, because a
successful install followed by a permanently black first boot on an
already-erased disk is the worst failure available here.

The probe claims only what it has established. A `renderD*` device file proves
that a driver published a node; it does not prove working 3D acceleration, and
the wording says so. Three distinctions are kept apart because they call for
different advice:

| Finding | Predicts a black desktop |
| --- | --- |
| No render node, or only `vgem`/`vkms` | yes |
| Software rendering (`llvmpipe` and friends) | no — it will start, and be slow |
| Low memory on the live image | no — the installed system has more |

The kernel driver behind the node is read from sysfs, which is always present.
An optional, time-bounded `eglinfo` probe refines the result when mesa-utils is
on the image; when it is absent, slow or broken, the result stands on the sysfs
evidence alone and the wording claims no more than that.

## Tests

| File | Covers |
| --- | --- |
| `test-questions.sh` | manifest invariants against fixture lookup roots |
| `test-tui-render.sh` | alignment in every tier, ASCII interior, determinism, screen content |
| `test-tui-flow.sh` | state transitions, validation failures, back/cancel, gate token, argument construction |
| `test-probe.sh` | renderer decisions and fallback advice |
| `test-tui-engine.sh` | the whole flow against a recording stub engine |
| `test-gui-flow.sh` | page grouping, back/forward labels, plan-only unreachability |
| `test-gui-bridge.sh` | the whole protocol against a recording stub engine, including secrets, refusals, progress and export |
| `test-gui-launch.sh` | which renderer starts, and the fallback when the graphical one cannot |
| `test-gui-widgets.sh` | every toolkit name against GTK's introspection data; skips when the toolkit is absent |

The render and flow tests exist because this project has already shipped a
prompt that hung at its own keyboard validation while `bash -n` and a
source-text grep both passed. Assertions here are about rendered output and
recorded state, not about the source containing the right words.
