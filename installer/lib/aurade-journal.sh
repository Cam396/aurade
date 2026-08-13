# shellcheck shell=bash
# Structured install journal for the AuraDE installer.
#
# The engine is a linear script; the front ends need to render progress,
# explain failures, and decide whether resuming is safe. All three are views
# over this one append-only stream, so the stream is the contract and the
# renderers own no state of their own.
#
# Two rules shape everything here:
#
#   Raw command output never enters the stream. Records carry a bounded cause
#   code and a written message; unstructured output goes to the raw log, which
#   the UI can display and the diagnostic bundle can collect. A JSONL stream
#   that can contain arbitrary subprocess output cannot be parsed safely and
#   cannot be shown to a user without review.
#
#   Redaction is structural, not filtered. Stages that handle passwords or
#   passphrases emit status only and are never passed the secret, so there is
#   no scrubbing pass that can be got wrong.

AURADE_JOURNAL_VERSION=1
AURADE_JOURNAL_PATH=${AURADE_JOURNAL_PATH:-/run/aurade-install/journal.jsonl}
AURADE_JOURNAL_RAW=${AURADE_JOURNAL_RAW:-/run/aurade-install/install.log}
AURADE_FAILURE_JOURNAL_DIR=${AURADE_FAILURE_JOURNAL_DIR:-}

# Stage order. Everything up to and including `confirm` leaves the disk
# untouched; `partition` is the first stage that cannot be undone.
AURADE_STAGES=(
  preflight network acquire verify confirm
  partition format mount pacstrap configure
  bootloader snapshot verify-install 'done'
)

_J_ID=
_J_SEQ=0
_J_ATTEMPT=1
_J_STAGE_START=0
_J_ACTIVE_STAGE=
_J_TARGET_PATH=
_J_TARGET_SERIAL=
_J_TARGET_WWN=
_J_TARGET_SIZE=

# `start` is a meta-record emitted before any stage runs, so it is reversible
# by definition: nothing has happened yet.
aurade_stage_reversible() {
  case $1 in
    start|preflight|network|acquire|verify|confirm) return 0 ;;
    *) return 1 ;;
  esac
}

# Whether re-running the stage on a resumed install is safe. `snapshot` is not:
# it creates .snapshots/0 and a second run collides with the first.
aurade_stage_idempotent() {
  case $1 in
    snapshot) return 1 ;;
    confirm|done) return 1 ;;
    *) return 0 ;;
  esac
}

# Always succeeds. The engine runs under `set -e`, so a helper that returns
# non-zero for an ordinary lookup miss would abort the install.
aurade_stage_index() {
  local want=$1 stage i=0
  for stage in "${AURADE_STAGES[@]}"; do
    i=$((i + 1))
    if [[ $stage == "$want" ]]; then
      printf '%s' "$i"
      return 0
    fi
  done
  printf '0'
  return 0
}

_json_escape() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\n'/\\n}
  s=${s//$'\r'/\\r}
  s=${s//$'\t'/\\t}
  # Drop any remaining control characters rather than emit invalid JSON.
  printf '%s' "$s" | tr -d '\000-\037'
}

_j_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

_j_target_json() {
  printf '{"path":"%s","serial":"%s","wwn":"%s","size_bytes":%s}' \
    "$(_json_escape "$_J_TARGET_PATH")" \
    "$(_json_escape "$_J_TARGET_SERIAL")" \
    "$(_json_escape "$_J_TARGET_WWN")" \
    "${_J_TARGET_SIZE:-0}"
}

# Record the identity of the disk, not just its path. /dev/sda can be a
# different disk after a reboot, so a journal that only stores the path cannot
# prove a resumed run is pointed at the same hardware.
aurade_journal_set_target() {
  local device=$1
  _J_TARGET_PATH=$device
  _J_TARGET_SERIAL=$(lsblk -dnro SERIAL "$device" 2>/dev/null | head -1 || true)
  _J_TARGET_WWN=$(lsblk -dnro WWN "$device" 2>/dev/null | head -1 || true)
  _J_TARGET_SIZE=$(blockdev --getsize64 "$device" 2>/dev/null || printf '0')
  [[ $_J_TARGET_SIZE =~ ^[0-9]+$ ]] || _J_TARGET_SIZE=0
}

aurade_journal_init() {
  local mode=$1 target=${2:-} journal_dir raw_dir
  journal_dir=$(dirname -- "$AURADE_JOURNAL_PATH")
  raw_dir=$(dirname -- "$AURADE_JOURNAL_RAW")
  install -d -m 0700 -- "$journal_dir" "$raw_dir" 2>/dev/null || {
    printf 'aurade-journal: cannot create journal directories\n' >&2
    return 1
  }
  _J_ID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || printf 'unknown-%s' "$$")
  _J_SEQ=0
  _J_ATTEMPT=${AURADE_INSTALL_ATTEMPT:-1}
  if [[ -n $target ]]; then
    aurade_journal_set_target "$target"
  fi
  : >"$AURADE_JOURNAL_PATH" 2>/dev/null || {
    printf 'aurade-journal: cannot create structured journal: %s\n' "$AURADE_JOURNAL_PATH" >&2
    return 1
  }
  : >"$AURADE_JOURNAL_RAW" 2>/dev/null || {
    printf 'aurade-journal: cannot create raw log: %s\n' "$AURADE_JOURNAL_RAW" >&2
    return 1
  }
  chmod 0600 "$AURADE_JOURNAL_PATH" "$AURADE_JOURNAL_RAW" 2>/dev/null || {
    printf 'aurade-journal: cannot restrict journal permissions\n' >&2
    return 1
  }
  [[ -w $AURADE_JOURNAL_PATH && -w $AURADE_JOURNAL_RAW ]] || {
    printf 'aurade-journal: journal paths are not writable\n' >&2
    return 1
  }
  aurade_journal_emit start started "mode=${mode}"
}

# One record. Extra JSON fields may be passed as a single pre-formatted string
# in $4; callers build those from bounded values only, never from output.
aurade_journal_emit() {
  local stage=$1 status=$2 message=${3:-} extra=${4:-}
  local reversible=false idempotent=false
  if aurade_stage_reversible "$stage"; then reversible=true; fi
  if aurade_stage_idempotent "$stage"; then idempotent=true; fi
  _J_SEQ=$((_J_SEQ + 1))
  if ! {
    printf '{"v":%s,"install_id":"%s","seq":%s,"attempt":%s,"t":"%s",' \
      "$AURADE_JOURNAL_VERSION" "$(_json_escape "$_J_ID")" \
      "$_J_SEQ" "$_J_ATTEMPT" "$(_j_now)"
    printf '"stage":"%s","status":"%s","reversible":%s,"idempotent":%s' \
      "$(_json_escape "$stage")" "$(_json_escape "$status")" \
      "$reversible" "$idempotent"
    if [[ -n $message ]]; then
      printf ',"message":"%s"' "$(_json_escape "$message")"
    fi
    if [[ -n $extra ]]; then
      printf ',%s' "$extra"
    fi
    printf ',"target":%s}\n' "$(_j_target_json)"
  } >>"$AURADE_JOURNAL_PATH" 2>/dev/null; then
    printf 'aurade-journal: cannot append structured journal: %s\n' "$AURADE_JOURNAL_PATH" >&2
    return 1
  fi
}

aurade_journal_begin() {
  local stage=$1 message=${2:-}
  _J_STAGE_START=$(date +%s)
  _J_ACTIVE_STAGE=$stage
  aurade_journal_emit "$stage" running "$message" \
    "\"index\":$(aurade_stage_index "$stage"),\"of\":${#AURADE_STAGES[@]}"
}

# Progress within a stage. `detail` is a short caller-authored string such as
# "612/1041 packages" - never a line lifted from a subprocess.
aurade_journal_progress() {
  local stage=$1 pct=$2 detail=${3:-}
  [[ $pct =~ ^[0-9]+$ ]] || pct=0
  aurade_journal_emit "$stage" running "$detail" "\"pct\":${pct}"
}

aurade_journal_ok() {
  local stage=$1 message=${2:-} elapsed=0
  if (( _J_STAGE_START )); then
    elapsed=$(( ($(date +%s) - _J_STAGE_START) * 1000 ))
  fi
  aurade_journal_emit "$stage" ok "$message" "\"elapsed_ms\":${elapsed}"
  [[ $_J_ACTIVE_STAGE == "$stage" ]] && _J_ACTIVE_STAGE=
}

# Bounded cause codes. The UI maps these to explanations and remediations, so
# adding a cause means teaching the UI about it - which is the point.
aurade_journal_fail() {
  local stage=$1 exit_code=$2 cause=$3 message=$4
  shift 4
  local remediation='' item resumable=false
  if aurade_stage_idempotent "$stage"; then resumable=true; fi
  for item in "$@"; do
    remediation+="${remediation:+,}\"$(_json_escape "$item")\""
  done
  [[ -n $remediation ]] || remediation='"log","shell","reboot"'
  [[ $exit_code =~ ^[0-9]+$ ]] || exit_code=1
  aurade_journal_emit "$stage" failed "$message" \
    "\"exit\":${exit_code},\"cause\":\"$(_json_escape "$cause")\",\"resumable\":${resumable},\"remediation\":[${remediation}]"
  [[ $_J_ACTIVE_STAGE == "$stage" ]] && _J_ACTIVE_STAGE=
}

# Append unstructured output to the raw log. This is the only sink for
# subprocess output; nothing here reaches the JSONL stream.
aurade_journal_raw() {
  printf '%s\n' "$*" >>"$AURADE_JOURNAL_RAW" 2>/dev/null || true
}

# Preserve only the structured journal when a caller opts into a disk-backed
# failure directory.  The installer work directory contains package caches,
# temporary keyrings, and other private state; copying it wholesale would make
# failure recovery a secret-retention mechanism.  A caller can point this at a
# mounted writable volume when post-reboot evidence is required.  The copy is
# deliberately best-effort so a full or read-only recovery volume never masks
# the original installer failure.
aurade_journal_preserve_failure() {
  local destination
  [[ -n $AURADE_FAILURE_JOURNAL_DIR ]] || return 0
  [[ $AURADE_FAILURE_JOURNAL_DIR == /* && $AURADE_FAILURE_JOURNAL_DIR != / ]] || return 1
  [[ -r $AURADE_JOURNAL_PATH ]] || return 0
  install -d -m 0700 -- "$AURADE_FAILURE_JOURNAL_DIR" || return 1
  destination=$(mktemp -d "$AURADE_FAILURE_JOURNAL_DIR/failure.XXXXXX") || return 1
  if ! install -m 0600 -- "$AURADE_JOURNAL_PATH" "$destination/journal.jsonl"; then
    rm -rf -- "$destination"
    return 1
  fi
  printf '%s\n' "$destination"
}

# A resumed install may continue only when the next stage can safely re-run
# AND the disk currently present is the disk the journal describes. Either
# check failing leaves the user with export, log, shell and reboot.
aurade_journal_target_identity_matches() {
  local serial=$1 wwn=$2 size=$3
  [[ -n $_J_TARGET_SERIAL || -n $_J_TARGET_WWN ]] || return 1
  [[ -n $_J_TARGET_SERIAL ]] && [[ $serial == "$_J_TARGET_SERIAL" ]] || {
    [[ -z $_J_TARGET_SERIAL ]] || return 1
  }
  [[ -n $_J_TARGET_WWN ]] && [[ $wwn == "$_J_TARGET_WWN" ]] || {
    [[ -z $_J_TARGET_WWN ]] || return 1
  }
  [[ $_J_TARGET_SIZE =~ ^[1-9][0-9]*$ && $size == "$_J_TARGET_SIZE" ]]
}

aurade_journal_may_resume() {
  local stage=$1 device=$2 serial wwn size
  aurade_stage_idempotent "$stage" || return 1
  [[ -b $device ]] || return 1
  serial=$(lsblk -dnro SERIAL "$device" 2>/dev/null | head -1 || true)
  wwn=$(lsblk -dnro WWN "$device" 2>/dev/null | head -1 || true)
  size=$(blockdev --getsize64 "$device" 2>/dev/null || printf '0')
  aurade_journal_target_identity_matches "$serial" "$wwn" "$size"
}
