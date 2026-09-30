#!/usr/bin/env bash
# Try AuraDE in a virtual machine on Linux or an Intel Mac.
#
#   curl -fsSL https://raw.githubusercontent.com/Cam396/aurade/main/vm/aurade-vm.sh | bash
#
# The first run downloads the latest release ISO, checks it (its SHA-256, and
# its signature when gpg is installed), makes a virtual disk and boots the
# installer. Install onto the virtual disk; every run after that boots the
# installed system. Nothing outside the VM folder is touched.
#
# Settings, all optional, as environment variables in front of `bash`:
#   AURADE_VM_BACKEND   qemu (default), libvirt, or virtualbox
#   AURADE_VM_DIR       where the ISO and disk live (default ~/AuraDE)
#   AURADE_VM_NAME      the VM's name (default aurade)
#   AURADE_VM_MEMORY    MiB of memory (default 6144, 4096 at least)
#   AURADE_VM_CPUS      virtual CPUs (default 4)
#   AURADE_VM_DISK_GB   disk size (default 40, 30 at least)
#   AURADE_VM_WIDTH / AURADE_VM_HEIGHT   screen size for QEMU (default 1920x1080)
#   AURADE_VM_DISPLAY   QEMU's window: gtk, sdl, cocoa, or none (default gtk, cocoa on a Mac)
#   AURADE_VM_GL        1 gives a Linux QEMU VM a virtio GPU with 3D through the host's
#                       OpenGL, which makes the desktop much faster (default 0)
#   AURADE_VM_VERSION   a release tag such as v1.1.1 instead of the latest
set -euo pipefail

REPO=Cam396/aurade
FINGERPRINT=BC390DCF360B2184DBBF008B8B2AB2EFE667CB69
BACKEND=${AURADE_VM_BACKEND:-qemu}
DIR=${AURADE_VM_DIR:-$HOME/AuraDE}
NAME=${AURADE_VM_NAME:-aurade}
MEMORY=${AURADE_VM_MEMORY:-6144}
CPUS=${AURADE_VM_CPUS:-4}
DISK_GB=${AURADE_VM_DISK_GB:-40}
WIDTH=${AURADE_VM_WIDTH:-1920}
HEIGHT=${AURADE_VM_HEIGHT:-1080}

say() { printf '\033[1maurade-vm:\033[0m %s\n' "$*"; }
die() { printf '\033[1maurade-vm:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

(( MEMORY >= 4096 )) || die 'AuraDE needs at least 4096 MiB of memory in the VM'
(( DISK_GB >= 30 )) || die 'AuraDE needs a disk of at least 30 GB'
have curl || die 'curl is needed to download the ISO'

OS=$(uname -s)
ARCH=$(uname -m)
if [[ $ARCH != x86_64 ]]; then
  die "AuraDE is built for x86_64 PCs. This machine is ${ARCH}, and emulating a PC
           here is too slow to use (an Apple Silicon Mac is one of these)."
fi

mkdir -p "$DIR"
cd "$DIR"

# --- the ISO -----------------------------------------------------------------

sha256_of() {
  if have sha256sum; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

fetch_iso() {
  local tag=${AURADE_VM_VERSION:-} base iso want got
  if [[ -z $tag ]]; then
    # The latest release page redirects to its tag, which names the files.
    tag=$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/${REPO}/releases/latest")
    tag=${tag##*/}
  fi
  [[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not work out the latest release (got '${tag}')"
  base="https://github.com/${REPO}/releases/download/${tag}"
  iso="aurade-${tag}-x86_64.iso"
  ISO="$DIR/$iso"
  if [[ -f $ISO.checked ]]; then
    say "using ${iso}, already downloaded and checked"
    return
  fi
  say "downloading AuraDE ${tag} (about 1.7 GB) into ${DIR}"
  curl -fL -# --retry 3 -C - -o "$ISO.part" "$base/$iso"
  curl -fsSL -o "$ISO.sha256" "$base/$iso.sha256"
  want=$(cut -d' ' -f1 <"$ISO.sha256")
  got=$(sha256_of "$ISO.part")
  if [[ $got != "$want" ]]; then
    rm -f "$ISO.part"
    die "the download does not match its published SHA-256; run this again to retry"
  fi
  mv -f "$ISO.part" "$ISO"
  if have gpg; then
    local keyring status
    keyring=$(mktemp -d)
    curl -fsSL -o "$keyring/key.asc" "$base/aurade-repository.asc"
    curl -fsSL -o "$ISO.sig" "$base/$iso.sig"
    GNUPGHOME=$keyring gpg --batch --quiet --import "$keyring/key.asc" 2>/dev/null
    status=$(GNUPGHOME=$keyring gpg --batch --status-fd 1 --verify "$ISO.sig" "$ISO" 2>/dev/null || true)
    rm -rf "$keyring"
    grep -q "VALIDSIG ${FINGERPRINT} " <<<"$status" ||
      die "the ISO is not signed by the AuraDE release key ${FINGERPRINT}"
    say "checked: SHA-256 and the release key's signature"
  else
    say "checked: SHA-256 (install gpg to check the signature as well)"
  fi
  touch "$ISO.checked"
}

# --- QEMU ----------------------------------------------------------------------

# UEFI firmware lives in a different place on every distribution. Each entry
# is the read-only code and the writable variables template that go with it.
find_firmware() {
  local pairs=(
    "/usr/share/edk2/x64/OVMF_CODE.4m.fd:/usr/share/edk2/x64/OVMF_VARS.4m.fd"
    "/usr/share/OVMF/OVMF_CODE_4M.fd:/usr/share/OVMF/OVMF_VARS_4M.fd"
    "/usr/share/OVMF/OVMF_CODE.fd:/usr/share/OVMF/OVMF_VARS.fd"
    "/usr/share/edk2/ovmf/OVMF_CODE.fd:/usr/share/edk2/ovmf/OVMF_VARS.fd"
    "/usr/share/qemu/ovmf-x86_64-code.bin:/usr/share/qemu/ovmf-x86_64-vars.bin"
    "/usr/share/edk2-ovmf/x64/OVMF_CODE.fd:/usr/share/edk2-ovmf/x64/OVMF_VARS.fd"
  )
  if have brew; then
    local prefix; prefix=$(brew --prefix qemu 2>/dev/null || true)
    pairs+=("$prefix/share/qemu/edk2-x86_64-code.fd:$prefix/share/qemu/edk2-i386-vars.fd")
  fi
  local pair
  for pair in "${pairs[@]}"; do
    if [[ -r ${pair%%:*} && -r ${pair##*:} ]]; then
      FIRMWARE_CODE=${pair%%:*}
      FIRMWARE_VARS=${pair##*:}
      return
    fi
  done
  die 'no UEFI firmware for QEMU was found; install the ovmf (or edk2-ovmf) package'
}

run_qemu() {
  have qemu-system-x86_64 || die "QEMU is not installed. Install it first:
           Arch: sudo pacman -S qemu-desktop edk2-ovmf
           Debian, Ubuntu: sudo apt install qemu-system-x86 ovmf
           Fedora: sudo dnf install qemu-kvm edk2-ovmf
           Intel Mac: brew install qemu"
  have qemu-img || die 'qemu-img is missing; it comes with QEMU'
  find_firmware
  local accel display disk="$DIR/$NAME.qcow2" vars="$DIR/$NAME-efivars.fd"
  # Extra QEMU arguments, split on spaces. Empty arrays are expanded with the
  # ${a[@]+...} form below because macOS still ships bash 3.2, where "${a[@]}"
  # of an empty array is an unbound variable under set -u.
  local -a extra=()
  read -r -a extra <<<"${AURADE_VM_QEMU_EXTRA:-}" || true
  local -a cdrom=() gpu=(-device "VGA,edid=on,xres=${WIDTH},yres=${HEIGHT}")
  case $OS in
    Linux)
      if [[ -w /dev/kvm ]]; then
        accel=kvm
      else
        die "/dev/kvm is not usable, so the VM would crawl. Turn on virtualization in the
           firmware settings, and add yourself to the kvm group: sudo usermod -aG kvm \$USER"
      fi
      display=${AURADE_VM_DISPLAY:-gtk,zoom-to-fit=on}
      if [[ ${AURADE_VM_GL:-0} == 1 ]]; then
        # Without this the VM has no 3D, and AuraDE draws its desktop on the
        # processor: it works, slowly. virgl hands the drawing to the host.
        gpu=(-device "virtio-vga-gl,edid=on,xres=${WIDTH},yres=${HEIGHT}")
        display="${display},gl=on"
      fi
      ;;
    Darwin) accel=hvf; display=${AURADE_VM_DISPLAY:-cocoa} ;;
    *) die "this script runs on Linux and Intel Macs; on Windows use vm/aurade-vm.ps1" ;;
  esac
  if [[ ! -f $disk ]]; then
    fetch_iso
    qemu-img create -q -f qcow2 "$disk" "${DISK_GB}G"
    cp -f "$FIRMWARE_VARS" "$vars"
    say "made a ${DISK_GB} GB virtual disk; the installer starts now"
    say "choose the virtual disk in the installer; after it finishes, the VM boots AuraDE"
  fi
  # The disk boots first once it holds a system; until then the firmware
  # falls through to the installer. The installer stays attached so the
  # recovery tools are there if they are ever needed.
  if [[ -z ${ISO:-} ]]; then
    ISO=$(printf '%s\n' "$DIR"/aurade-v*-x86_64.iso | sort -V | tail -1)
  fi
  if [[ -n ${ISO:-} && -f $ISO ]]; then
    cdrom=(-drive "file=$ISO,media=cdrom,if=none,id=cd0,readonly=on"
           -device "ide-cd,drive=cd0,bootindex=2")
  fi
  say "starting ${NAME} (${CPUS} CPUs, ${MEMORY} MiB, ${WIDTH}x${HEIGHT})"
  exec qemu-system-x86_64 \
    -name "$NAME" -machine q35,accel="$accel" -cpu host \
    -smp "$CPUS" -m "$MEMORY" \
    -drive "if=pflash,format=raw,readonly=on,file=$FIRMWARE_CODE" \
    -drive "if=pflash,format=raw,file=$vars" \
    -drive "file=$disk,if=none,id=hd0,format=qcow2,discard=unmap" \
    -device "virtio-blk-pci,drive=hd0,bootindex=1" \
    ${cdrom[@]+"${cdrom[@]}"} \
    "${gpu[@]}" \
    -device qemu-xhci -device usb-tablet \
    -nic user,model=virtio-net-pci \
    -display "$display" \
    ${extra[@]+"${extra[@]}"}
}

# --- libvirt (virt-manager) ------------------------------------------------------

run_libvirt() {
  if ! have virt-install || ! have virsh; then
    die 'libvirt is not installed (virt-install and virsh are needed)'
  fi
  local uri=${LIBVIRT_DEFAULT_URI:-qemu:///session}
  if virsh -c "$uri" dominfo "$NAME" >/dev/null 2>&1; then
    say "starting the existing libvirt VM ${NAME}"
    virsh -c "$uri" start "$NAME" 2>/dev/null || true
    have virt-viewer && exec virt-viewer -c "$uri" "$NAME"
    say 'open it in virt-manager to see it'
    return
  fi
  fetch_iso
  say "creating the libvirt VM ${NAME} (${uri})"
  exec virt-install --connect "$uri" --name "$NAME" \
    --memory "$MEMORY" --vcpus "$CPUS" --cpu host-passthrough \
    --disk "size=${DISK_GB},bus=virtio,format=qcow2" \
    --cdrom "$ISO" --boot uefi --osinfo archlinux \
    --network user,model=virtio --video vga --graphics spice \
    --input tablet,bus=usb
}

# --- VirtualBox -------------------------------------------------------------------

run_virtualbox() {
  have VBoxManage || die 'VirtualBox is not installed (VBoxManage is needed)'
  if VBoxManage showvminfo "$NAME" >/dev/null 2>&1; then
    say "starting the existing VirtualBox VM ${NAME}"
    exec VBoxManage startvm "$NAME"
  fi
  fetch_iso
  local disk="$DIR/$NAME.vdi"
  say "creating the VirtualBox VM ${NAME}"
  VBoxManage createvm --name "$NAME" --ostype ArchLinux_64 --register --basefolder "$DIR" >/dev/null
  VBoxManage modifyvm "$NAME" --memory "$MEMORY" --cpus "$CPUS" --firmware efi \
    --graphicscontroller vmsvga --vram 128 --nic1 nat --mouse usbtablet \
    --usbxhci on --audio-enabled off --boot1 disk --boot2 dvd
  VBoxManage createmedium disk --filename "$disk" --size $((DISK_GB * 1024)) >/dev/null
  VBoxManage storagectl "$NAME" --name SATA --add sata --portcount 2
  VBoxManage storageattach "$NAME" --storagectl SATA --port 0 --type hdd --medium "$disk"
  VBoxManage storageattach "$NAME" --storagectl SATA --port 1 --type dvddrive --medium "$ISO"
  exec VBoxManage startvm "$NAME"
}

case $BACKEND in
  qemu) run_qemu ;;
  libvirt) run_libvirt ;;
  virtualbox) run_virtualbox ;;
  *) die "AURADE_VM_BACKEND must be qemu, libvirt or virtualbox, not ${BACKEND}" ;;
esac
