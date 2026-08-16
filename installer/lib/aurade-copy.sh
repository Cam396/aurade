#!/usr/bin/env bash
# The words. One copy of them, for everything that speaks.
#
# Four programs describe the same install to the same person: the text front
# end, the graphical front end through its bridge, the failure helper, and the
# launcher. Until this file existed they each carried their own vocabulary, and
# the drift was not theoretical. The failure helper's remediation table and the
# text installer's explanation table were keyed on two different sets of cause
# codes, and only one of them matched what the engine actually emits, so a real
# failure printed the literal token `keyring_error` on the screen of somebody
# whose install had just stopped.
#
# So: the engine owns the codes, this file owns the sentences, and nothing else
# is allowed a second opinion. A new cause code is one entry here and no edits
# anywhere else.
#
# The voice is written down in UI_CONTRACT.md. The short version is that these
# sentences get read by someone who is worried, so they say what happened and
# what to do about it, in that order, and they never explain how the program
# knows.

# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------

# Journal stage names are engineering terms. These are what the user sees; the
# journal keeps the real name so a support case and a screenshot still line up.
stage_label() {
  case $1 in
    preflight)      printf 'Checking this computer' ;;
    network)        printf 'Connecting' ;;
    acquire)        printf 'Downloading packages' ;;
    verify)         printf 'Checking the downloads' ;;
    confirm)        printf 'Confirming the disk' ;;
    partition)      printf 'Partitioning the disk' ;;
    format)         printf 'Formatting' ;;
    mount)          printf 'Mounting' ;;
    pacstrap)       printf 'Installing the base system' ;;
    configure)      printf 'Setting things up' ;;
    bootloader)     printf 'Making it bootable' ;;
    snapshot)       printf 'Saving a snapshot to roll back to' ;;
    verify-install) printf 'Checking everything landed' ;;
    done)           printf 'Finishing up' ;;
    *)              printf '%s' "$1" ;;
  esac
}

# Roughly how long a stage takes on a machine that is behaving. A bare
# duration, because the caller wraps it ("Usually five to ten minutes.").
# Deliberately
# vague and deliberately not a countdown: a progress screen that promises four
# minutes and takes eleven has told a lie the user will remember longer than
# the install. A range nobody can be disappointed by is worth more than a
# number nobody can trust.
#
# These are the same words for every machine. The honest per-machine estimate
# needs the engine to report package-level progress out of pacstrap, and until
# it does, an estimate derived from this session would be a guess wearing a
# clock's clothes.
stage_pacing() {
  case $1 in
    preflight)      printf 'a few seconds' ;;
    network)        printf 'a few seconds' ;;
    acquire)        printf 'a few minutes' ;;
    verify)         printf 'under a minute' ;;
    confirm)        printf 'a moment' ;;
    partition)      printf 'a few seconds' ;;
    format)         printf 'under a minute' ;;
    mount)          printf 'a few seconds' ;;
    pacstrap)       printf 'five to ten minutes' ;;
    configure)      printf 'a minute or two' ;;
    bootloader)     printf 'under a minute' ;;
    snapshot)       printf 'under a minute' ;;
    verify-install) printf 'a few seconds' ;;
    *)              printf '' ;;
  esac
}

# What a failure at this stage means for the disk. The engine reports one cause
# code, so the explanation is anchored on the stage, which is always present,
# and refined by cause where a specific one is known.
#
# Every one of these leads with the state of the disk, because that is the only
# question the reader actually has.
stage_explanation() {
  case $1 in
    preflight)  printf 'Nothing has been changed. This computer did not meet one of the requirements.' ;;
    network)    printf 'Nothing has been changed. The package archive could not be reached.' ;;
    acquire)    printf 'Nothing has been changed and no disk was touched. A package could not be downloaded.' ;;
    verify)     printf 'Nothing has been changed. A download did not match its signature, so it was not installed.' ;;
    confirm)    printf 'Nothing has been changed. The confirmation did not match the disk.' ;;
    partition)  printf 'What was on this disk is already gone. It could not be partitioned.' ;;
    format)     printf 'The disk is partitioned and has no filesystem on it yet. Formatting did not finish.' ;;
    mount)      printf 'The disk is partitioned and formatted. The new filesystems could not be mounted.' ;;
    pacstrap)   printf 'The disk is partitioned and formatted. The base system did not finish installing. Every package is already downloaded and verified, so starting again will not need the network.' ;;
    configure)  printf 'Every file is in place. Setting the system up did not finish.' ;;
    bootloader) printf 'The system is installed but cannot start yet. The bootloader was not written.' ;;
    snapshot)   printf 'The system is installed and will start. There is no snapshot to roll back to.' ;;
    verify-install) printf 'The installation finished but did not pass its own final check.' ;;
    *)          printf 'The installation stopped. The journal below records exactly where.' ;;
  esac
}

# --------------------------------------------------------------------------
# Causes
# --------------------------------------------------------------------------

# Every code `aurade-install` can put in the journal, in words.
#
# The list is closed on purpose and the fallback is silence. An unrecognised
# code used to fall through to printing itself, which put `keyring_error` on
# the screen in the place where a sentence belonged. A cause with no sentence
# yet is better represented by the stage explanation, which is always true,
# than by a token that means nothing to the person reading it. The raw code
# stays in the journal, where the person who needs it will look.
cause_explanation() {
  case $1 in
    # The engine traps INT and TERM and records this itself. Both front ends
    # can therefore be stopped while the disk is still untouched, and the
    # resulting screen should say that rather than read as a crash.
    cancelled)          printf 'You stopped the installation.' ;;
    unexpected_exit)    printf 'A step ended without saying why.' ;;
    keyring_error)      printf 'A package did not match its signature, so it was not installed.' ;;
    capacity_error)     printf 'There was not enough room to hold the downloaded packages.' ;;
    network_error)      printf 'The package archive could not be reached.' ;;
    secure_boot_error)  printf 'Secure Boot is on, and this computer does not yet trust a key that can start AuraDE.' ;;
    target_error)       printf 'The disk could not be prepared.' ;;
    storage_error)      printf 'A filesystem could not be created or mounted.' ;;
    # The engine's catch-all. It means the classifier did not recognise the
    # message, not that anything specific happened, so the stage explanation
    # carries the screen alone.
    installer_error)    printf '' ;;
    *)                  printf '' ;;
  esac
}

# One thing to do. Not a list.
#
# A failure screen that offers five things to check is a failure screen that
# has handed the diagnosis back to the person who came here to be told. Where
# several things could be wrong, this names the one that is wrong most often:
# for a signature failure that is the clock, every time, because an image with
# a broken keyring does not get built and a computer with a wrong date is
# ordinary.
cause_next_step() {
  case $1 in
    cancelled)          printf 'Start the installer again whenever you are ready.' ;;
    keyring_error)      printf "Check that this computer's date and time are right, then start again." ;;
    capacity_error)     printf 'Free up space on the disk holding the download, then start again.' ;;
    network_error)      printf 'Check the network connection, then start again.' ;;
    secure_boot_error)  printf "Put Secure Boot into setup mode in this computer's firmware, then start again." ;;
    target_error)       printf 'Choose a different disk, or check that this one is not in use, then start again.' ;;
    storage_error)      printf 'Check the disk for faults, then start again.' ;;
    unexpected_exit)    printf 'Save a report, then start again.' ;;
    *)                  printf 'Save a report, then start again.' ;;
  esac
}

# What starting over actually costs, decided by the reversibility boundary the
# journal library defines rather than by a second opinion held here.
restart_advice() {
  local stage=${1:-}
  if [[ -z $stage ]] || aurade_stage_reversible "$stage"; then
    printf '%s' 'Nothing was written to the disk. You can start the installer again, or save a report first if you want to send it on.'
  else
    printf '%s' 'This installer cannot yet continue from where it stopped, and the disk has already been changed. Starting again erases it and begins from the beginning. Save a report first if you want a record of what happened.'
  fi
}
