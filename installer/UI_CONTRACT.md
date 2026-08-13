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

`--render SCREEN [--journal FILE]` draws any single screen from fixture state
and exits, which is how the layout is tested and how a support case is
reproduced. `--list-screens` prints the set.

## Progress is a view, not an account

The progress screen is a function of the journal. It does not keep its own
record of what happened, and it does not display stages the engine never
emits: `network` and `verify` are folded into `preflight` and `acquire`, and a
row that stays grey while the rows below it complete reads as a hung step.

## Cancellation

Asymmetric, because the disk is.

| Region | Stages | Behaviour |
| --- | --- | --- |
| Reversible | `preflight` … `confirm` | Cancel freely. The UI states that nothing was written. |
| The gate | typing `ERASE:<target>` | Last free exit. |
| Irreversible | `partition` … `done` | No cancel is offered. |

The boundary comes from `aurade_stage_reversible`, not from a second opinion
held in the renderer.

## Failure

Every stop names the stage, explains what it means for the disk, and offers
export, log, shell and restart.

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

Low memory on the live image is reported differently from a missing GPU. The
installed system has more memory available than the live image does, so low
memory does not predict a black screen and must not be described as if it
does.

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
