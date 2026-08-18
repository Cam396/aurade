#!/usr/bin/env bash
# The catalogue of log messages, and the program that reads it.
#
# This file exists because of what the catalogue is going to become. Forty odd
# rows can be held in a head. Two thousand cannot, and most of them will have
# been generated rather than typed, which means the failure mode is not a typo
# but a hundred plausible rows that are quietly wrong in the same way.
#
# Two kinds of wrong matter, and they need different checks.
#
# A row can be malformed, and then `aurade-explain` skips it. That is the safe
# failure, and it is still a bug, because a skipped row looks exactly like a
# row that never matched anything.
#
# A row can be *too eager*. A key of `error` would fire on every log ever
# produced, and the tool would answer a person's real disk fault with forty
# paragraphs about nothing. That one cannot be caught by reading a row on its
# own, so it is checked against a log of a machine where nothing is wrong.
set -Eeuo pipefail
trap 'case $- in *e*) printf "%s: line %s gave up: %s\n" "${0##*/}" "$LINENO" "$BASH_COMMAND" >&2 ;; esac' ERR
# shellcheck source=assert.sh
. "$(dirname -- "$0")/assert.sh"

ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
EXPLAIN=$ROOT/installer/bin/aurade-explain
NOTES=$ROOT/installer/data/hardware-notes.tsv

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "test-explain: $*" >&2; exit 1; }

[[ -x $EXPLAIN ]] || fail 'aurade-explain is not executable'
[[ -r $NOTES ]] || fail 'the catalogue is missing'

# --- the shape of every row --------------------------------------------------
#
# Checked in awk rather than in bash because this file is going to be long, and
# a bash loop over two thousand rows is a test nobody will wait for.
awk -F'\t' '
  /^#/ || /^[[:space:]]*$/ { next }
  {
    n++
    if (NF != 6) { print "row " NR ": " NF " fields, not 6"; bad++; next }
    key = $1; source = $2; severity = $3; what = $4; todo = $5; evidence = $6

    if (key in seen) { print "row " NR ": duplicate key: " key; bad++ }
    seen[key] = 1

    # Long enough and specific enough not to fire on everything. Twelve is not
    # arbitrary: `BTRFS: error` is twelve and is a real distinctive string, and
    # nothing shorter than that has ever been one.
    if (length(key) < 12) { print "row " NR ": key is too short to be distinctive: " key; bad++ }
    # A single bare word is a word, not a message. `timeout`, `failed` and
    # `error` are in nine thousand messages between them.
    if (key !~ /[ :,.()\/-]/) { print "row " NR ": key is one bare word: " key; bad++ }
    if (key ~ /^[[:space:]]/) { print "row " NR ": key starts with a space: " key; bad++ }
    # A format specifier means the row was copied out of the source without
    # being cut down to the literal part, so it can never match a real log.
    if (key ~ /%[0-9.*#-]*[a-zA-Z]/) { print "row " NR ": key contains a format specifier: " key; bad++ }
    if (key ~ /\\n/) { print "row " NR ": key contains an escape: " key; bad++ }

    if (severity != "fault" && severity != "warn" && severity != "note") {
      print "row " NR ": severity is not fault, warn or note: " severity; bad++
    }
    if (source == "") { print "row " NR ": no source"; bad++ }
    if (evidence == "" || evidence == "-") { print "row " NR ": no evidence"; bad++ }
    if (source == "kernel" && evidence !~ /^[a-zA-Z0-9_\/.+-]+\.[ch]:[0-9]+$/) {
      print "row " NR ": kernel evidence is not path.c:line: " evidence; bad++
    }

    # The voice, as much of it as a machine can see. The rest is read aloud.
    prose = what " " todo
    if (index(prose, ";") > 0)  { print "row " NR ": semicolon in the prose"; bad++ }
    if (prose ~ /\xe2\x80\x94/) { print "row " NR ": em dash in the prose"; bad++ }
    if (prose ~ /\xe2\x80\x93/) { print "row " NR ": en dash in the prose"; bad++ }
    if (what == "")             { print "row " NR ": nothing in the what column"; bad++ }
    if (what !~ /[.?]$/)        { print "row " NR ": what does not end in a full stop: " what; bad++ }
    if (todo != "-" && todo !~ /[.?]$/) { print "row " NR ": do does not end in a full stop: " todo; bad++ }
    if (length(what) > 240)     { print "row " NR ": what is a paragraph, not a sentence"; bad++ }
    if (length(todo) > 260)     { print "row " NR ": do is a paragraph, not a sentence"; bad++ }
    # A line that has to label itself a warning is a line that failed to sound
    # like one, and hexadecimal is never an answer to a person.
    if (prose ~ /(WARNING|NOTICE|CRITICAL|ERROR):/) { print "row " NR ": the prose announces its own severity"; bad++ }
    if (prose ~ /0x[0-9a-fA-F]/) { print "row " NR ": hexadecimal in the prose"; bad++ }
    if (tolower(prose) ~ /(in order to|utilise|utilize|prior to|please note|kindly)/) {
      print "row " NR ": the prose is from a memo"; bad++
    }
    # A `note` says nothing is wrong, so it has nothing to ask for.
    if (severity == "note" && todo != "-") {
      print "row " NR ": a note that is normal should not ask for anything: " todo; bad++
    }
    if (severity != "note" && todo == "-") {
      print "row " NR ": a fault or a warning with nothing to do about it"; bad++
    }
  }
  END {
    if (n < 1) { print "the catalogue has no rows at all"; bad++ }
    if (bad > 0) exit 1
  }
' "$NOTES" || fail 'the catalogue has rows that are wrong, listed above'

rows=$(grep -cv '^#' "$NOTES")
echo "catalogue: $rows rows"

# --- no key may fire on a machine where nothing is wrong ---------------------
#
# This is the check a row cannot fail on its own. A key like `error` or `failed`
# passes every rule above and then matches half of every log on earth, and the
# person with a real disk fault gets it buried under forty paragraphs about
# nothing at all.
#
# So: an ordinary boot of an ordinary machine, and nothing in the catalogue is
# allowed to have an opinion about it.
cat >"$TMP/clean.log" <<'CLEAN'
[    0.000000] Linux version 6.12.4-aurade (builder@aurade) #1 SMP PREEMPT_DYNAMIC
[    0.000000] Command line: BOOT_IMAGE=/vmlinuz-linux root=UUID=1234 rw quiet
[    0.004000] KERNEL supported cpus: Intel GenuineIntel AMD AuthenticAMD
[    0.021000] BIOS-provided physical RAM map:
[    0.115000] Memory: 16269308K/16777216K available
[    0.221000] ACPI: Added _OSI(Module Device)
[    0.310000] pci 0000:00:02.0: [8086:5917] type 00 class 0x030000
[    0.512000] usb 1-1: new high-speed USB device number 2 using xhci_hcd
[    0.688000] ahci 0000:00:17.0: AHCI vers 0001.0301, 1 command slots
[    0.701000] ata1: SATA max UDMA/133 abar m2048@0xdc27f000 port 0xdc27f100
[    0.902000] scsi 0:0:0:0: Direct-Access ATA Samsung SSD 860 1B6Q PQ: 0 ANSI: 5
[    0.903000] sd 0:0:0:0: [sda] 976773168 512-byte logical blocks: (500 GB/466 GiB)
[    0.904000] sd 0:0:0:0: [sda] Write Protect is off
[    0.911000] sd 0:0:0:0: [sda] Attached SCSI disk
[    1.100000] nvme nvme0: pci function 0000:02:00.0
[    1.211000] nvme0n1: p1 p2 p3
[    1.400000] EXT4-fs (sda2): mounted filesystem with ordered data mode
[    1.512000] systemd[1]: Detected architecture x86-64
[    2.001000] iwlwifi 0000:00:14.3: loaded firmware version 77.d21ac105.0
[    2.310000] Bluetooth: Core ver 2.22
[    3.001000] i915 0000:00:02.0: [drm] Finished loading DMC firmware
[    4.100000] systemd[1]: Reached target Graphical Interface.
CLEAN
if ! "$EXPLAIN" --all --quiet "$TMP/clean.log" >"$TMP/clean.out" 2>&1; then
  fail "a clean boot log was reported as a fault: $(cat "$TMP/clean.out")"
fi
grep -Fq 'Nothing in this log is something AuraDE recognises.' "$TMP/clean.out" ||
  fail "the catalogue has an opinion about a machine where nothing is wrong:
$(cat "$TMP/clean.out")"

# --- and it does fire on a machine where something is --------------------------
cat >"$TMP/broken.log" <<'BROKEN'
[    1.004112] APIC error on CPU0: 00(40)
[    1.004115] APIC error on CPU0: 40(40)
[   12.667001] ata1.00: exception Emask 0x0 SAct 0x0 SErr 0x0 action 0x6 frozen
[   17.891233] ata1: hard resetting link
[   90.223311] nvme nvme0: I/O tag 42 (0042) QID 3 timeout, reset controller
BROKEN

status=0
"$EXPLAIN" --quiet "$TMP/broken.log" >"$TMP/broken.out" 2>&1 || status=$?
(( status == 1 )) || fail "a log with a fault in it exited $status, not 1"
grep -Fq 'The drive reported an error' "$TMP/broken.out" ||
  fail 'a SATA error was not explained'
grep -Fq 'Check the SATA cable at both ends' "$TMP/broken.out" ||
  fail 'a SATA error was explained without saying what to do'
# The engine's own vocabulary never reaches the screen. `Emask` is on the line
# the tool quotes back and must be nowhere in a sentence it wrote.
refute grep -Fq 'Emask 0x' "$TMP/broken.out"

# A note is held back until it is asked for, because a person reading this has
# a fault to deal with and four reassurances are four things in the way.
refute grep -Fq 'The processor reported an interrupt problem' "$TMP/broken.out"
grep -Fq 'alarming and' "$TMP/broken.out" ||
  fail 'the normal lines were hidden without the reader being told they exist'
"$EXPLAIN" --all --quiet "$TMP/broken.log" >"$TMP/broken-all.out" 2>&1 || true
grep -Fq 'The processor reported an interrupt problem' "$TMP/broken-all.out" ||
  fail '--all did not reveal the normal lines'

# Repeats are counted, not repeated. The same key on twenty lines is one thing
# that happened twenty times, and printing it twenty times is how a summary
# becomes as long as the log it replaced.
grep -Fq 'Seen 2 times.' "$TMP/broken-all.out" ||
  fail 'a message that appeared twice was not counted'
[[ $(grep -c 'The processor reported an interrupt problem' "$TMP/broken-all.out") -eq 1 ]] ||
  fail 'a message that appeared twice was explained twice'

# --- a log with nothing but normal lines is not a failure --------------------
printf '[    1.004112] APIC error on CPU0: 00(40)\n' >"$TMP/onlynotes.log"
status=0
"$EXPLAIN" --quiet "$TMP/onlynotes.log" >"$TMP/onlynotes.out" 2>&1 || status=$?
(( status == 0 )) || fail "a log with only normal lines exited $status, not 0"
grep -Fq 'Nothing in this log is a fault.' "$TMP/onlynotes.out" ||
  fail 'a log with only normal lines did not say so'

# --- the quoted line ---------------------------------------------------------
#
# The log line is shown by default because somebody comparing this against a
# photograph of their screen needs to see the line it is about. It is stripped
# of control characters on the way, because a log is not guaranteed to be text
# and a terminal that reads an escape out of one repaints the screen.
"$EXPLAIN" "$TMP/broken.log" >"$TMP/quoted.out" 2>&1 || true
grep -Fq 'ata1.00: exception Emask' "$TMP/quoted.out" ||
  fail 'the line the explanation is about was not shown'
"$EXPLAIN" --quiet "$TMP/broken.log" >"$TMP/unquoted.out" 2>&1 || true
refute grep -Fq 'ata1.00: exception Emask' "$TMP/unquoted.out"

printf 'ata1.00: exception Emask \033[2J\033[31m 0x0 frozen\n' >"$TMP/escapes.log"
"$EXPLAIN" "$TMP/escapes.log" >"$TMP/escapes.out" 2>&1 || true
refute grep -qP '\x1b' "$TMP/escapes.out"

# A very long line is cut. A single log line has no length limit and the
# quoted line is inside a paragraph, not a scrolling pane.
{ printf 'ata1.00: exception Emask '; head -c 4000 /dev/zero | tr '\0' 'x'; printf '\n'; } >"$TMP/longline.log"
"$EXPLAIN" "$TMP/longline.log" >"$TMP/longline.out" 2>&1 || true
[[ $(awk '{ if (length($0) > m) m = length($0) } END { print m }' "$TMP/longline.out") -le 200 ]] ||
  fail 'a four thousand character log line was quoted whole'

# --- narrowing ----------------------------------------------------------------
"$EXPLAIN" --source kernel --quiet "$TMP/broken.log" >"$TMP/src.out" 2>&1 || true
grep -Fq 'The drive reported an error' "$TMP/src.out" ||
  fail '--source kernel dropped a kernel row'
if "$EXPLAIN" --source nosuchsource --quiet "$TMP/broken.log" >"$TMP/src2.out" 2>&1; then
  fail 'a source that is in no row was accepted'
fi
grep -Fq 'no catalogue entries for that source' "$TMP/src2.out" ||
  fail 'an unknown source did not say so'

# --- the overlapping key ------------------------------------------------------
#
# Two rows where one key contains the other, which is going to happen a lot
# once this file is generated rather than typed. There are two cases and they
# want opposite answers, so both are pinned.
#
# On one line, the specific one wins and the general one is not also printed.
# `grep -oF` is leftmost longest, so this is already true, and it is asserted
# because a future change to how the scan is done could quietly stop it being
# true and nothing else would notice.
printf '%s\n' \
  'the drive fell over	kernel	fault	The longer one.	Do the longer thing.	x.c:1' \
  'drive fell	kernel	fault	The shorter one.	Do the shorter thing.	x.c:2' \
  >"$TMP/overlap.tsv"
printf 'something: the drive fell over today\n' >"$TMP/overlap.log"
"$EXPLAIN" --catalogue "$TMP/overlap.tsv" --quiet "$TMP/overlap.log" >"$TMP/overlap.out" 2>&1 || true
grep -Fq 'The longer one.' "$TMP/overlap.out" ||
  fail 'the more specific of two overlapping rows was dropped'
refute grep -Fq 'The shorter one.' "$TMP/overlap.out"

# On two lines they are two different things that happened, and printing only
# the longer loses the second one entirely. There was a loop in here that did
# that, added on the assumption that the same-line case above needed handling.
# It did not, and this is the case it broke.
printf '%s\n' 'first: the drive fell over today' 'second: the drive fell only a bit' \
  >"$TMP/overlap2.log"
"$EXPLAIN" --catalogue "$TMP/overlap.tsv" --quiet "$TMP/overlap2.log" >"$TMP/overlap2.out" 2>&1 || true
grep -Fq 'The longer one.' "$TMP/overlap2.out" ||
  fail 'the specific row was dropped when both appeared on their own lines'
grep -Fq 'The shorter one.' "$TMP/overlap2.out" ||
  fail 'a row that matched a line of its own was suppressed by a longer row on another line'

# --- rows that are wrong are skipped, not guessed at --------------------------
printf '%s\n' \
  'this row has four fields	kernel	fault' \
  'bad severity here	kernel	catastrophe	Something.	Do something.	x.c:1' \
  'no evidence at all	kernel	fault	Something.	Do something.	' \
  'the good row survives	kernel	fault	The good one.	Do the good thing.	x.c:9' \
  >"$TMP/ragged.tsv"
printf 'log line with the good row survives in it\n' >"$TMP/ragged.log"
"$EXPLAIN" --catalogue "$TMP/ragged.tsv" --quiet "$TMP/ragged.log" >"$TMP/ragged.out" 2>&1 || true
grep -Fq 'The good one.' "$TMP/ragged.out" ||
  fail 'one malformed row stopped the good rows from being read'

# --- input that is not a log --------------------------------------------------
head -c 20000 /dev/urandom >"$TMP/binary.log"
status=0
"$EXPLAIN" --quiet "$TMP/binary.log" >"$TMP/binary.out" 2>&1 || status=$?
(( status <= 1 )) || fail "twenty kilobytes of random bytes exited $status"

: >"$TMP/empty.log"
"$EXPLAIN" --quiet "$TMP/empty.log" >"$TMP/emptyout" 2>&1 ||
  fail 'an empty log was treated as a failure'
grep -Fq 'Save a report and send it on.' "$TMP/emptyout" ||
  fail 'a log with nothing in it did not invite the report that would grow the list'

printf 'no newline at the end of this one: ata1.00: exception Emask' >"$TMP/nonewline.log"
"$EXPLAIN" --quiet "$TMP/nonewline.log" >"$TMP/nonewline.out" 2>&1 || true
grep -Fq 'The drive reported an error' "$TMP/nonewline.out" ||
  fail 'the last line of a file with no trailing newline was not read'

# It reads standard input, because `dmesg | aurade-explain` is the whole
# interface and every other way of running it is a convenience.
"$EXPLAIN" --quiet <"$TMP/broken.log" >"$TMP/stdin.out" 2>&1 || true
grep -Fq 'The drive reported an error' "$TMP/stdin.out" ||
  fail 'reading from standard input did not work'

# --- being pointed at the wrong thing ----------------------------------------
status=0
"$EXPLAIN" "$TMP/no-such-log" >"$TMP/missing.out" 2>&1 || status=$?
(( status == 2 )) || fail "a missing log exited $status, not 2"
install -d "$TMP/a-directory"
status=0
"$EXPLAIN" "$TMP/a-directory" >"$TMP/dir.out" 2>&1 || status=$?
(( status == 2 )) || fail "a directory as the log exited $status, not 2"
status=0
"$EXPLAIN" --catalogue "$TMP/no-such-catalogue" "$TMP/broken.log" >"$TMP/nocat.out" 2>&1 || status=$?
(( status == 2 )) || fail "a missing catalogue exited $status, not 2"

# --- it says what it knows ----------------------------------------------------
"$EXPLAIN" --list >"$TMP/list.out" 2>&1 || fail '--list failed'
[[ $(wc -l <"$TMP/list.out") -eq $rows ]] ||
  fail "--list printed $(wc -l <"$TMP/list.out") rows, and the catalogue has $rows"
"$EXPLAIN" --help >"$TMP/help.out" 2>&1 || fail '--help failed'
grep -Fq 'dmesg | aurade-explain' "$TMP/help.out" ||
  fail 'the help does not show the way this is actually run'

echo 'log explainer test: PASS'
