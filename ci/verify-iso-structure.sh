#!/usr/bin/env bash
# Inspect an already-built ArchISO without booting or modifying a target disk.
set -Eeuo pipefail

usage() {
  printf '%s\n' 'Usage: ci/verify-iso-structure.sh ISO [--full] [--require-gui]' >&2
}
ISO=${1:-}
FULL=0
REQUIRE_GUI=0
if [[ $# -gt 1 ]]; then
  for option in "${@:2}"; do
    case $option in
      --full) FULL=1 ;;
      --require-gui) REQUIRE_GUI=1; FULL=1 ;;
      *) usage; exit 2 ;;
    esac
  done
fi
[[ -n $ISO ]] || { usage; exit 2; }
[[ $ISO == /* ]] || ISO=$(readlink -f -- "$ISO")
[[ -f $ISO ]] || { echo "verify-iso-structure: ISO does not exist: $ISO" >&2; exit 1; }
command -v bsdtar >/dev/null 2>&1 || {
  echo 'verify-iso-structure: bsdtar is required' >&2
  exit 1
}

TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
listing="$TMP/iso.list"
bsdtar -tf "$ISO" | sed 's#^\./##' >"$listing"
grep -Eiq '^EFI/BOOT/BOOTX64\.EFI$' "$listing" || {
  echo 'verify-iso-structure: UEFI x86_64 fallback loader is missing' >&2
  exit 1
}
grep -Fxq 'loader/loader.conf' "$listing" || {
  echo 'verify-iso-structure: systemd-boot loader.conf is missing' >&2
  exit 1
}
grep -Eq '^loader/entries/[^/]+\.conf$' "$listing" || {
  echo 'verify-iso-structure: no systemd-boot entry was found' >&2
  exit 1
}
loader_conf=$(bsdtar -xOf "$ISO" loader/loader.conf)
grep -Fxq 'editor no' <<<"$loader_conf" || {
  echo 'verify-iso-structure: ISO boot editor is not disabled' >&2
  exit 1
}
entry=$(grep -E '^loader/entries/[^/]+\.conf$' "$listing" | head -1)
entry_text=$(bsdtar -xOf "$ISO" "$entry")
grep -Fq 'cow_spacesize=' <<<"$entry_text" || {
  echo 'verify-iso-structure: live entry has no bounded COW space option' >&2
  exit 1
}

if (( FULL )); then
  command -v unsquashfs >/dev/null 2>&1 || {
    echo 'verify-iso-structure: unsquashfs is required for --full' >&2
    exit 1
  }
  squashfs=$(grep -E '^arch/[^/]+/airootfs\.sfs$' "$listing" | head -1)
  [[ -n $squashfs ]] || {
    echo 'verify-iso-structure: airootfs squashfs is missing' >&2
    exit 1
  }
  image="$TMP/airootfs.sfs"
  bsdtar -xOf "$ISO" "$squashfs" >"$image"
  contents="$TMP/airootfs.list"
  unsquashfs -l "$image" >"$contents"
  required_payload=(
    usr/local/sbin/aurade-installer \
    usr/local/sbin/aurade-install \
    usr/local/sbin/aurade-recovery \
    usr/local/sbin/aurade-installer-start \
    usr/local/lib/aurade/aurade-journal.sh \
    opt/aurade/repo/packages.lock \
    etc/aurade-installer/snapshot
  )
  if grep -Fqx 'squashfs-root/etc/aurade-installer/gui-enabled' "$contents"; then
    gui_enabled=1
    required_payload+=(
      usr/local/sbin/aurade-installer-gui
      usr/local/sbin/aurade-installer-gui-bridge
      usr/local/lib/aurade/aurade_gui/__init__.py
      usr/local/lib/aurade/aurade_gui/app.py
      usr/local/lib/aurade/aurade_gui/bridge.py
      usr/local/lib/aurade/aurade_gui/flow.py
      etc/aurade-installer/gui-release-manifest.json
    )
  else
    gui_enabled=0
  fi
  if (( REQUIRE_GUI && !gui_enabled )); then
    echo 'verify-iso-structure: requested GUI release but the ISO has no GUI marker' >&2
    exit 1
  fi
  for required in "${required_payload[@]}"; do
    grep -Fq "squashfs-root/$required" "$contents" || {
      echo "verify-iso-structure: missing live payload: $required" >&2
      exit 1
    }
  done

  # The lock file is part of the release provenance, so verify it against the
  # package archives inside the final squashfs rather than trusting the
  # pre-mkarchiso staging directory. Extracting individual files with
  # unsquashfs keeps this gate bounded without materialising the whole live
  # filesystem a second time.
  lock_file="$TMP/packages.lock"
  unsquashfs -cat "$image" opt/aurade/repo/packages.lock >"$lock_file" 2>"$TMP/lock.err" || {
    echo 'verify-iso-structure: cannot extract embedded packages.lock' >&2
    exit 1
  }
  lock_entries="$TMP/lock.entries"
  if ! awk '
    BEGIN { valid = 1; count = 0 }
    !/^#/ && NF {
      if (NF < 2 || $1 !~ /^[[:xdigit:]]{64}$/ || $2 !~ /^[^/]+[.]pkg[.]tar[.][^/]+$/) {
        valid = 0
        next
      }
      print $1 "\t" $2
      count++
    }
    END { exit !(valid && count > 0) }
  ' "$lock_file" >"$lock_entries"; then
    echo 'verify-iso-structure: embedded packages.lock is malformed' >&2
    exit 1
  fi
  if [[ $(cut -f2 "$lock_entries" | sort | uniq -d | head -1) ]]; then
    echo 'verify-iso-structure: embedded packages.lock contains duplicate archives' >&2
    exit 1
  fi

  mapfile -t embedded_packages < <(
    awk '$1 ~ /^squashfs-root\/opt\/aurade\/repo\/[^/]+[.]pkg[.]tar[.][^/]+$/ {
      sub(/^squashfs-root\/opt\/aurade\/repo\//, "", $1)
      print $1
    }' "$contents"
  )
  package_index=0
  while IFS=$'\t' read -r expected filename; do
    package_index=$((package_index + 1))
    matches=0
    for embedded in "${embedded_packages[@]}"; do
      [[ $embedded == "$filename" ]] && matches=$((matches + 1))
    done
    if (( matches != 1 )); then
      echo "verify-iso-structure: lock archive is not embedded exactly once: $filename" >&2
      exit 1
    fi
    package_file="$TMP/package-${package_index}.pkg"
    unsquashfs -cat "$image" "opt/aurade/repo/$filename" >"$package_file" 2>"$TMP/package.err" || {
      echo "verify-iso-structure: cannot extract locked archive: $filename" >&2
      exit 1
    }
    actual=$(sha256sum "$package_file" | awk '{print $1}')
    [[ $actual == "$expected" ]] || {
      echo "verify-iso-structure: package checksum mismatch: $filename" >&2
      exit 1
    }
  done <"$lock_entries"
  for embedded in "${embedded_packages[@]}"; do
    grep -Fqx -- "$embedded" <(cut -f2 "$lock_entries") || {
      echo "verify-iso-structure: unlisted package archive in ISO: $embedded" >&2
      exit 1
    }
  done

  if (( REQUIRE_GUI )); then
    build_info="$ISO.build-info"
    [[ -r $build_info ]] || {
      echo 'verify-iso-structure: requested GUI release but build-info is missing' >&2
      exit 1
    }
    gui_release=$(awk -F= '$1 == "gui_release" {print $2}' "$build_info")
    [[ $gui_release == 1 ]] || {
      echo 'verify-iso-structure: requested GUI release but build-info is not GUI-enabled' >&2
      exit 1
    }
    expected_manifest_digest=$(awk -F= '$1 == "gui_manifest_sha256" {print $2}' "$build_info")
    [[ $expected_manifest_digest =~ ^[[:xdigit:]]{64}$ ]] || {
      echo 'verify-iso-structure: GUI build-info lacks a manifest digest' >&2
      exit 1
    }
    manifest_file="$TMP/gui-release-manifest.json"
    unsquashfs -cat "$image" etc/aurade-installer/gui-release-manifest.json >"$manifest_file" 2>"$TMP/gui-manifest.err" || {
      echo 'verify-iso-structure: requested GUI release but its manifest is missing' >&2
      exit 1
    }
    actual_manifest_digest=$(sha256sum "$manifest_file" | awk '{print $1}')
    [[ $actual_manifest_digest == "$expected_manifest_digest" ]] || {
      echo 'verify-iso-structure: embedded GUI manifest digest does not match build-info' >&2
      exit 1
    }
    python3 - "$manifest_file" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(manifest, dict):
    raise SystemExit("verify-iso-structure: embedded GUI manifest is not an object")
if manifest.get("schema") != 1 or manifest.get("release") != "0.2.0":
    raise SystemExit("verify-iso-structure: embedded GUI manifest is not a 0.2.0 candidate")
if manifest.get("status") != "candidate":
    raise SystemExit("verify-iso-structure: embedded GUI manifest is not marked candidate")
if "x86_64" not in manifest.get("architectures", []):
    raise SystemExit("verify-iso-structure: embedded GUI manifest omits x86_64")
expected_payload = {
    "installer/bin/aurade-installer-gui",
    "installer/bin/aurade-installer-gui-bridge",
    "installer/bin/aurade-installer-start",
    "installer/lib/aurade-probe.sh",
    "installer/lib/aurade-questions.sh",
    "installer/lib/aurade-validate.sh",
    "installer/lib/aurade-journal.sh",
    "installer/lib/aurade-tui.sh",
    "installer/lib/aurade_gui/__init__.py",
    "installer/lib/aurade_gui/app.py",
    "installer/lib/aurade_gui/bridge.py",
    "installer/lib/aurade_gui/flow.py",
}
payload = manifest.get("payload")
if not isinstance(payload, list):
    raise SystemExit("verify-iso-structure: embedded GUI manifest payload is not a list")
payload_paths = {entry.get("path") for entry in payload if isinstance(entry, dict)}
if not expected_payload.issubset(payload_paths):
    raise SystemExit("verify-iso-structure: embedded GUI manifest omits required source payload")
if sorted(manifest.get("runtime_packages", [])) != [
    "cage", "gtk4", "libadwaita", "python-gobject"
]:
    raise SystemExit("verify-iso-structure: embedded GUI runtime closure is incomplete")
policy = manifest.get("public_release_policy")
if not isinstance(policy, dict) or policy.get("gui_in_0_1_0") is not False:
    raise SystemExit("verify-iso-structure: embedded GUI manifest does not exclude GUI from 0.1.0")
for key in (
    "artifact_signature_required",
    "full_profile_build_required",
    "physical_accelerated_runtime_required",
):
    if policy.get(key) is not True:
        raise SystemExit(f"verify-iso-structure: embedded GUI policy is not fail-closed for {key}")
PY
  fi
fi

if (( FULL )); then
  if (( REQUIRE_GUI )); then
    printf 'ISO structure verification: PASS (UEFI, boot policy, squashfs payload, GUI 0.2.0 marker)\n'
  else
    printf 'ISO structure verification: PASS (UEFI, boot policy, squashfs payload)\n'
  fi
else
  printf 'ISO structure verification: PASS (UEFI and boot policy; use --full for squashfs payload)\n'
fi
