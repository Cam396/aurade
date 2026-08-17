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
one. `installer/bin/aurade-installer-gui` is the graphical renderer.
`installer/bin/aurade-installer-start` chooses between them using the probe,
and is what the message of the day names.

**Two front ends, and there is no third.** There was one, `aurade-installer`,
a prompt-by-prompt flow that predated both of these. It was packaged onto the
image and reachable from nothing: not in the boot menu, not from the launcher,
not from the message of the day. Copy was written for it that nobody could
read, and roughly thirty assertions in `test-install-dry-run.sh` grepped its
source for behaviour that actually belongs to the engine.

That is the worst shape a test can have. It passed while the front end was
unreachable, and it would have gone on passing if the engine changed
underneath it, because it was asserting on a file rather than on a system.
Those assertions now point at the two front ends that ship and at the engine.

A third way in is not free. It is a third place for a validation rule to
drift, a third set of sentences to keep true, and a third thing to remember
when the shared manifest changes.

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

## The boot menu is part of the interface

Four entries, one per way in, in `installer/archiso/efiboot/loader/entries/`.
Each names a front end on the kernel command line as `aurade.installer=`, and
`aurade-installer-autostart` reads that on tty1 and starts it. An entry that
names a front end nothing acts on is a boot menu that lies, so the staging test
checks both halves against each other.

The titles below are quoted exactly as the entries carry them. Paraphrasing
one here reads as drift the next time somebody audits the copy, and the last
audit duly reported it.

| entry | command line | what starts |
| --- | --- | --- |
| `Install AuraDE` | `aurade.installer=gui` | `aurade-installer-start --graphical` |
| `Install AuraDE with speech` | `aurade.installer=speech` | espeakup, then `--text` in plain mode |
| `Install AuraDE (text only)` | `aurade.installer=text` | `aurade-installer-start --text` |
| `Install AuraDE (safe graphics)` | `aurade.installer=safe` | the same, with every accelerated path skipped |
| `Recovery console` | `aurade.installer=none` | nothing, just a root shell |

**The speech entry is second, and its position is part of the feature.**
Nobody who needs it can read the menu to find it, so it has to be reachable by
counting rather than by looking: boot the image, press Down once, press Enter.
First place is the default and belongs to the common case. Second is the
closest place to it that can be described in six words over a phone.

It starts the text installer rather than the graphical one, and that is not a
downgrade. espeakup reads the console directly, before any toolkit loads, so
the text installer speaks in situations where the graphical one cannot start
at all. For somebody using speech it is the better front end, not the fallback.

The autostart runs the installer rather than replacing the login shell with it,
and marks a stamp on tmpfs so it happens once per boot. The console is an
autologin getty: without both of those, quitting the installer ends the login,
agetty starts another, and the installer comes back - an installer with no way
out of it.

## Icons are pinned to the image, not to the build host

Every icon name the front end asks for is checked by `test-gui-icons.sh`
against `installer/tests/fixtures/image-symbolic-icons.txt`, which is the set
the image's icon theme actually installs. An unresolvable icon name is not an
error in GTK: the widget draws nothing, sizes itself as though nothing were
there, and the page looks like it was designed without an icon. It cannot be
seen in a headless render either, because the build host's icon theme is a
different version with different names in it - which is exactly how five state
ticks and a verdict badge shipped invisible.

## The voice

Apple, with a touch of Hilton at the two ends. Calm and short in the middle,
warm on arrival and departure. Six rules, and `test-voice.sh` enforces the two
that a machine can see.

1. **One idea per sentence.** If a sentence needs a comma to carry a second
   clause, it usually wants to be two sentences. Vary the length. Short ones
   are allowed to be very short. **No semicolons**, which in this codebase
   were never semicolons: they were a way to bolt a reassurance onto the back
   of a diagnosis, as in "could not acquire the package set; the target disk
   was not modified", where the half the reader needs is on the wrong side of
   the mark. `test-voice.sh` fails on one.
2. **State the outcome, not the mechanism.** "15.2 GB free" and not "15.2 GB
   free, which is enough". The justification is the tell: nobody says it out
   loud, and reading it makes the reader feel audited.
3. **Show less.** The strongest fix for copy that reads like a status report
   is deleting the report. The readiness page kept five green ticks and five
   explanations of why each one was fine; the version that reads like a
   product says one sentence and puts the rest behind Details.
4. **No dashes.** No em dash, no en dash, anywhere the user can see. A dash is
   the joint a sentence uses when it has two ideas and has not decided which
   one it is about.
5. **Nothing from the memo.** "in order to", "utilise", "prior to", "please
   note", and any line that announces its own severity with `WARNING:` or
   `NOTICE:` in front of it. A line that has to label itself a warning is a
   line that did not manage to sound like one. Read it aloud. If it sounds
   like a department, rewrite it.
6. **Lead with the disk.** Wherever a disk is involved, its state is the first
   thing on the screen. "Nothing has been changed" comes before any account of
   what went wrong, because it is the only question the reader actually has.
7. **The destructive path is exempt.** The gate, the token, the refusals and
   every claim about what has and has not been written stay literal and
   exact. The contrast is deliberate: everything is calm and human, and then
   at the erase gate it is suddenly plain, which is the signal.

`test-voice.sh` reads every file listed in its `SOURCES`, which is every
program that speaks: both front ends, the shared copy library and question
manifest, the engine's launcher, the failure helper, the boot menu titles, the
tips and the message of the day. Adding a program that says something to a
person means adding it there.

### One vocabulary, one file

`lib/aurade-copy.sh` holds every sentence about a stage or a cause:
`stage_label`, `stage_pacing`, `stage_explanation`, `cause_explanation`,
`cause_next_step`, `restart_advice`. The text installer sources it, the
graphical bridge inherits it by sourcing the text installer, and the failure
helper sources it directly.

It exists because the drift was not theoretical. The failure helper carried
its own remediation table keyed on one set of cause codes and the text
installer carried another, and only one of the two matched what the engine
actually emits, so seven of the engine's nine real codes reached the screen as
the literal token `keyring_error` with the whole suite green. The fixtures had
been written against invented codes.

Two rules follow. **The engine owns the codes and this file owns the
sentences.** And **an unrecognised code is silence**, never itself: the stage
explanation is always true and a token means nothing to the person reading it,
so the fallback shows the stage and leaves the code in the journal.

The engine picks a code by pattern-matching its own `die` message, which makes
the words in a `die` call load bearing. `tests/test-die-cause.sh` pins every
reachable message to the code it must produce, so rewording one into a
different bucket fails there instead of in front of a user.

### The words that have to match

Both front ends describe the same events, and where they used different words
for one of them they were describing two different products. These are the
ones that had already drifted, so they are written down rather than remembered:

| the thing | the words | not |
| --- | --- | --- |
| the account | **username and password** | name and password |
| leaving with the media | **take out** ... **restart** | remove, reboot |
| an untouched disk | **nothing has been written to any disk** | to the disk, nothing has been written |
| what a disk escaped | **partitioned, formatted or written to** | or erased |
| the loader | **bootloader** | boot loader |
| the first screen after a restart | **sign-in screen** | sign in screen |
| firmware keys | **enroll**, **enrollment** | enrol, enrolment |
| the last screen | **You are all set** | Finished |

Spelling is British otherwise, because that is what the prose in this tree
already is: `colour`, `recognise`, `behaviour`. `enroll` is the one deliberate
exception, and it is deliberate because it is the word firmware documentation
uses for the thing the firmware does.

Anything read aloud in one front end and not the other is a bug in whichever
one is quieter. `tests/voice_test.py` reads every string in both, plus the
engine, the launcher, the boot menu and the network check, and it reads both
single and double quoted shell strings: reading only the single quoted ones
hid every message with a value interpolated into it, which is most of the
messages worth reading.

### Nothing says anything in colour alone, and nothing flashes

Every state carries a mark or a word as well as its colour. The stage list
does this already: `+` finished, `>` running, `!` stopped. It is easy to agree
with and easy to break, because breaking it does not look like breaking
anything. A red row reads perfectly on the screen of the person who added it,
and is invisible to the roughly one man in twelve with red-green colour
blindness, on a monochrome console, and through a projector.

`tests/test-greyscale.sh` renders with the colour removed and asserts the marks
and the words survive. It is deliberately not a pixel comparison: the states
are carried by characters, so checking the characters is both cheaper and
stricter than sampling an image.

Whitespace is not a mark. The plain rendering strips indentation, so a state
whose mark is three spaces becomes no mark at all: that is how "waiting" came
to look identical to "finished" for anybody reading with braille or speech,
and it is why the four states say themselves in words there.

**And nothing flashes.** Nothing does today, and the sheen and the aurora are
both slow and continuous rather than blinking. The rule is written down because
it is a rule about what may be added later: anything that alternates faster
than about three times a second can trigger a seizure, and the person it
happens to has no way to have prevented it.

### One next step

A failure screen names exactly one thing to do. Not five. Where several things
could be wrong it names the one that is wrong most often, which for a
signature failure is the clock, every time: an image with a broken keyring
does not get built, and a computer with the wrong date is ordinary.

## The drawn layer

Three rules, each of which was broken somewhere before it was written down.

**The gradient is lilac, plate, aqua.** All three stops, everywhere the ribbon
is drawn: the hairline under the chrome, the progress ribbon, and the swoop.
The swoop was interpolating straight from lilac to aqua and skipping the
middle, so the one place the mark is drawn at full size was the one place it
was not the mark's own gradient.

**The pen is one fixed tone, not a role.** `brand.PEN` is the aqua ramp at
tone 90 and it is the same colour in both schemes and in both drawings. Picked
by role, it came out as two different colours in the same scheme; picked as
the same role in both, the progress ribbon ended up with an aqua pen sitting
on the aqua end of its own gradient, which is invisible. A pen is a highlight,
so it has to be lighter than whatever it rides on.

**Tone 40 is not a mistake.** A review recommended moving the light scheme's
accents to tone 50 or 60 to keep the mark's luminance. Measured, primary at
tone 50 is 4.28:1 against the light surface and tone 60 is 3.02:1, against
tone 40's 6.14:1, so both fail 4.5:1 and `test-gui-theme.sh` would fail with
them. The accent ink on a light surface has to be dark. The brand's luminance
in light mode lives in the tone 90 containers and in the aurora, not in the
ink.

**The aurora is measured, not chosen.** At alpha 0.30 the light aurora blended
to 2.35 L\* against the surface behind it, which is not a backdrop, it is
nothing. It is 0.42 now, about 3.3 L\*, and body text over it still measures
15.5:1.

**A caution is a caution colour.** `warning` has its own amber ramp at hue 78.
It used to alias `secondary`, which is the plate hue at chroma 0.045: a slate
grey. Four live states used it and all four drew caution in ordinary chrome.

**One radius for a card.** 16px, on `.card` and on everything named
`aurade-*-pane` or `aurade-live-step`. There were three: libadwaita's 12px
default, the panes at 16, and two new cards at 20.

## Type

The scale in `generate-theme.py` began as the Material 3 table and is no
longer it. Tracking is zero or negative rather than M3's positive tracking on
body sizes, headings carry weight rather than expressing hierarchy through
size alone, body text is a size larger than the spec, and every role emits a
line height, which the generator previously carried in its table and never
wrote out.

The face is named rather than inherited. GTK's built-in default is Cantarell,
which the image does not install, so anything drawn outside this stylesheet's
reach would render in whatever fontconfig substituted. `Adwaita Sans` is on
the image because the toolkit depends on it. Renders taken on a build host are
not evidence about type unless that host's fonts have been replaced with the
image's, which is the same trap the icons set.

## Getting something onto the screen

Two independent things have to work before anyone sees a window, and they fail
identically. `cage` has to start on this machine's graphics device, and GTK has
to be able to draw into the compositor that started. Neither can be predicted
from anything readable: the only proof a graphics path works is a window on it.

So `aurade-installer-start` tries, in order, and reads the outcome rather than
inferring it. `installer/lib/aurade-renderers.sh` supplies both axes -
compositor candidates best first, displays-attached before display-less cards,
software last; then client drawing paths under whichever compositor came up.
An explicit `WLR_RENDERER` or `GSK_RENDERER` in the environment is tried first
and never overridden.

The launcher cannot read the outcome from an exit status, because `cage` exits
with its client's status: a compositor that never started, a window that
appeared and died, and a user who quit all arrive as the same number. So the
front end records how far it got, through `installer/lib/aurade_gui/stage.py`,
and that file is the contract:

| stage | meaning | what the launcher does |
| --- | --- | --- |
| *(no file)* | nothing was ever drawn | next compositor candidate; no client setting can rescue a compositor that did not start |
| `mapped` | a window reached the screen | a clean exit is a user who quit, and stops; a failure is the client's drawing path, so the next client candidate under the same compositor |
| `engaged` | the user pressed Continue | stop. There are answers on screen that a restart would discard |
| `declined` | the front end refused to draw | stop, and run the text installer. Every other candidate reaches the same answer |

`declined` also inverts the usual fallback. Inside a compositor the launcher
started there is no terminal behind the front end, so a text installer started
there draws where nobody can type; the launcher still owns the real console
and does the handover on it.

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

### Ten minutes is a design problem

Every other screen in this installer is measured in seconds. This one is
measured in ten minutes, and it held a title, a list and a bar: the longest
screen in the product was the least designed one.

**Pacing is a range and never a countdown.** `stage_pacing` gives "usually
five to ten minutes"; the elapsed half is measured from the journal. That is
the right way round, because the number that is real is the one about the
past. An estimate that turns out wrong is remembered longer than the install
it was wrong about, and there is no honest per-machine number until the engine
reports package by package. The tests fail on the words "remaining", "time
left" and "estimated".

**Something to read.** `lib/aurade-tips` is one file both front ends parse:
lane, tab, text. `tip` is something true about the system being written,
`next` is something to have ready after the restart and is interleaved every
fourth turn, `rare` shows up about one turn in forty. The rotation walks in
order rather than picking at random, because random repeats and a repeat on a
screen somebody is staring at reads as a screen that has frozen. Every line
goes through `test-voice.sh` and has to fit two lines of the text frame, which
is 120 characters.

**Something to do.** A snake, on the same card, behind one quiet control. The
rules are in `lib/aurade-wait.sh` and `aurade_gui/wait.py`, as state machines
with no drawing in them, so a test can play a whole game without a terminal or
a window and neither file has any way to reach the engine.

In the text installer this also fixed something that was quietly wrong: for
the whole of a ten minute install, nothing read standard input. Anything typed
in that time sat in the terminal buffer and was delivered to whichever screen
came next, so a few bored presses of return during `pacstrap` could arrive at
the failure menu and choose something. Draining input is the point, and the
game is what the drained input is spent on.

### The screen fits the console it is on

The text frame is a fixed 68 columns, because a frame that changes shape
between screens reads as two programs. The height is not something the
installer gets to choose, so the progress screen costs every layout and takes
the first that fits, giving things up in a deliberate order: the finished
stages fold to a count, then the ribbon goes, then the stages still to come
fold as well, and the tip is last because on the screen somebody stares at for
ten minutes, something to read is worth more than a checklist. Whatever else
comes off, the running stage and its detail stay. A 24 row console lands on
the second step and keeps both the ribbon and the tip.

`AURADE_TUI_HEIGHT` is pinned in the tests. Unpinned, the same screen renders
one way on a build machine with a tall terminal and another way in CI, and
every layout assertion becomes a coin toss.

### Nothing on this screen is bound to the install

The progress screen is the least recoverable moment in the product, and the
right number of ways to interrupt it from the keyboard is none. The footer
offers one key, `g`, which changes which picture is being drawn. The movement
keys steer a snake. That is the whole set, and the graphical page is the same:
its key controller takes the arrows and four letters and refuses everything
else, so Return still belongs to the page.

### Three things are hidden

Deliberately, and none of them touches the install.

The `rare` tip lane, at about one turn in forty. Typing `aurora` on the
welcome page of the graphical installer replays the swoop, which otherwise
plays once per session and is the best thing this front end draws. Typing it
at the text installer's progress screen widens the ribbon for five seconds.
And the snake changes colour past ten.

They are not documented anywhere a user reads, and `--render` turns the rare
lane off so that a rendered screen is the same picture every time.

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
| `test-gui-runtime.sh` | the window built on a headless compositor: containment, storage and scheme controls, and the stage the front end reports after drawing |
| `test-renderer-chain.sh` | the order graphics candidates are tried in, and the launcher's rule for what each outcome means |
| `test-gui-icons.sh` | every icon name the front end asks for, against the set the image carries |
| `test-voice.sh` | no dashes and nothing from the memo, across every user-facing string |

The render and flow tests exist because this project has already shipped a
prompt that hung at its own keyboard validation while `bash -n` and a
source-text grep both passed. Assertions here are about rendered output and
recorded state, not about the source containing the right words.
