# shellcheck shell=bash
# shellcheck disable=SC2034  # the HW_* results are read by the installer that sources this file
# What this machine needs beyond the stock Arch packages, worked out from the
# firmware's description of it (DMI) and the PCI devices on it.
#
# Most machines need nothing: the firmware packages on every install cover
# Intel, Qualcomm Atheros, Realtek, MediaTek and Marvell Wi-Fi, which is every
# Surface (the Laptop 1 and 2, Pro 4 to 6 and Book 1 and 2 are Marvell; the
# Go is Qualcomm Atheros; later ones are Intel) and every x86 Chromebook. The
# keyboards that need help at the disk unlock prompt, Surface laptops and
# 2015 to 2017 Macs, are handled by the aurade-hardware package on every
# install. What is left is decided here:
#
#   Broadcom Wi-Fi   A handful of Broadcom chips, the Wi-Fi in most Intel Macs
#                    among them, only work with Broadcom's own driver. Arch
#                    ships it as source, broadcom-wl-dkms, built against the
#                    installed kernel's headers. Installed only when one of
#                    those chips is present: it switches the open drivers off
#                    for every other Broadcom chip.
#   T2 Macs          2018 to 2020 Macs keep the keyboard, trackpad and Wi-Fi
#                    behind Apple's T2 chip, which needs a kernel Arch does not
#                    ship. Said, rather than installed silently broken.
#   Surface touch    The touchscreen and pen need the linux-surface kernel,
#                    which AuraDE does not install. Said, so nobody thinks the
#                    install broke it.
#   Chromebook sound Speakers and microphones need per-model sound settings
#                    that Arch does not carry, and on some models the wrong
#                    ones can damage the speakers. Said, with where the fix
#                    for each model is, rather than guessed at.
#
# Everything reads under AURADE_HW_ROOT (default /), so tests can describe a
# machine with a directory of files.

AURADE_HW_ROOT=${AURADE_HW_ROOT:-/}

# Broadcom devices (vendor 14e4) that only broadcom-wl drives: BCM4331,
# BCM43227, BCM43228, BCM43142, BCM4360 and BCM4352.
AURADE_HW_WL_DEVICES=(4331 4358 4359 4365 43a0 43b1)

# Filled by aurade_hw_detect.
HW_PACKAGES=()
HW_NOTES=()
HW_SUMMARY=generic

_aurade_hw_dmi() {
  local field=$1 value=
  [[ -r ${AURADE_HW_ROOT%/}/sys/class/dmi/id/$field ]] &&
    IFS= read -r value <"${AURADE_HW_ROOT%/}/sys/class/dmi/id/$field" || true
  printf '%s' "$value"
}

# aurade_hw_pci_has VENDOR DEVICE... : true when a PCI device with this
# vendor and any of these device ids is present. Ids are hex, no 0x.
aurade_hw_pci_has() {
  local vendor=$1 device_path id want dev ven
  shift
  for device_path in "${AURADE_HW_ROOT%/}"/sys/bus/pci/devices/*; do
    [[ -r $device_path/vendor && -r $device_path/device ]] || continue
    IFS= read -r ven <"$device_path/vendor" || continue
    [[ ${ven,,} == "0x${vendor,,}" ]] || continue
    IFS= read -r dev <"$device_path/device" || continue
    id=${dev,,}
    for want in "$@"; do
      [[ $id == "0x${want,,}" ]] && return 0
    done
  done
  return 1
}

aurade_hw_is_surface() {
  [[ $(_aurade_hw_dmi sys_vendor) == "Microsoft Corporation" &&
     $(_aurade_hw_dmi product_name) == Surface* ]]
}

aurade_hw_is_mac() {
  [[ $(_aurade_hw_dmi sys_vendor) == "Apple Inc." ]]
}

# The T2 chip shows up as Apple PCI bridges 1801 and 1802.
aurade_hw_is_t2_mac() {
  aurade_hw_pci_has 106b 1801 1802
}

aurade_hw_is_chromebook() {
  [[ $(_aurade_hw_dmi sys_vendor) == "Google" ]]
}

aurade_hw_detect() {
  HW_PACKAGES=()
  HW_NOTES=()
  HW_SUMMARY=generic

  if aurade_hw_is_surface; then
    HW_SUMMARY="Microsoft $(_aurade_hw_dmi product_name)"
    HW_NOTES+=("this is a Surface: Wi-Fi, keyboard, touchpad and battery work with the standard kernel; the touchscreen and pen need the linux-surface kernel, which AuraDE does not install")
  elif aurade_hw_is_chromebook; then
    HW_SUMMARY="Chromebook ($(_aurade_hw_dmi product_name))"
    HW_NOTES+=("this is a Chromebook: Wi-Fi works, and its speakers and microphone may not yet; the fix is per model, at docs.chrultrabook.com, and on some models a wrong one can damage the speakers, so follow its steps for this model only")
  elif aurade_hw_is_mac; then
    HW_SUMMARY="Mac ($(_aurade_hw_dmi product_name))"
  fi

  if aurade_hw_pci_has 14e4 "${AURADE_HW_WL_DEVICES[@]}"; then
    HW_PACKAGES+=(broadcom-wl-dkms linux-headers)
    HW_NOTES+=("this Broadcom Wi-Fi only works with Broadcom's own driver: installing broadcom-wl-dkms, built for this kernel")
  fi

  if aurade_hw_is_t2_mac; then
    HW_NOTES+=("this Mac has Apple's T2 chip: its built-in keyboard, trackpad and Wi-Fi need the t2linux kernel, which AuraDE does not install yet; use a USB keyboard, mouse and network")
  fi
}
