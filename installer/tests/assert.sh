# Negative assertions that actually fail.
#
# `set -e` ignores a command whose return value is inverted with `!`. It is in
# the manual, one clause into a long sentence, and what it means for a test
# file is that every line reading
#
#     ! grep -Fq 'PRIVATE_RAW_SECRET' "$TMP/report.out"
#
# is a comment. The grep matches, the negation makes the status 1, errexit
# looks away because of the `!`, and the run goes green with the secret in the
# file. The assertion has never once been able to fail.
#
# That is worse than not having written it. A positive assertion that rots
# turns red; a negative one written this way is indistinguishable from a
# working one for as long as anybody cares to look, and every one of them here
# guards something that matters: a secret not reaching a screen, a cause code
# not reaching a user, plain mode not drawing block characters at a braille
# display, the word "unknown" never being said about a disk.
#
# So negative assertions go through `refute` instead, which is an ordinary
# command whose failure errexit is willing to see.
#
# Sourced rather than duplicated per file so there is one place to be right.

# Fail unless the command fails. The mirror of every `! cmd` this replaced.
refute() {
  if "$@"; then
    printf '%s: refute: this succeeded and should not have: %s\n' \
      "${0##*/}" "$*" >&2
    exit 1
  fi
}

# The positive direction, for the cases where the failure is worth a sentence
# rather than a line number. Bare `[[ ... ]]` is still fine and still fails
# correctly; this is for when the message is the point.
expect() {
  if ! "$@"; then
    printf '%s: expect: this failed and should not have: %s\n' \
      "${0##*/}" "$*" >&2
    exit 1
  fi
}
