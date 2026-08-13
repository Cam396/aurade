# AuraDE installer UI contract

What the front ends are allowed to be, and what they are not allowed to
change. `installer/EXECUTE_PATH_CONTRACT.md` covers what a run must prove;
this covers what the interface owes the person in front of it.

## One engine, one journal, two renderers

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

`installer/bin/aurade-installer-tui` is the current renderer. The older
`installer/bin/aurade-installer` remains as a plain prompt-by-prompt flow.

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

Returning to a question shows the answer already given, not the default.
A "back" that silently rewrites an answer to its default is the same class of
untruth as a wrong footer.

Returning to review re-runs the dry run, so the plan approved at the gate is
always the plan for the answers currently held.

Cancellation is asymmetric, because the disk is.

| Region | Stages | Behaviour |
| --- | --- | --- |
| Reversible | `preflight` … `confirm` | Cancel freely. The UI states that nothing was written. |
| The gate | typing `ERASE:<target>` | Last free exit. |
| Irreversible | `partition` … `done` | No cancel is offered, and none is advertised. |

The boundary comes from `aurade_stage_reversible`, not from a second opinion
held in the renderer.

`--plan-only` reaches a terminal `planned` state that has no transition to
`execute`. It is not a flag checked before a destructive call; it is a state
from which the destructive call is unreachable.

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

There is deliberately no "try that step again". The journal records which
stages could safely re-run, but the engine is a linear script with no entry
point that starts at one, so invoking it again runs `wipefs` again. Offering a
retry would erase the disk a second time.

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

The render and flow tests exist because this project has already shipped a
prompt that hung at its own keyboard validation while `bash -n` and a
source-text grep both passed. Assertions here are about rendered output and
recorded state, not about the source containing the right words.
