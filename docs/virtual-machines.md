# Virtual machines

AuraDE installs into a virtual machine the same way it installs onto a PC.
The scripts in `vm/` set one up for you; the rest of this page is for doing it
by hand or in another hypervisor.

## The one command

Linux or an Intel Mac:

```sh
curl -fsSL https://raw.githubusercontent.com/Cam396/aurade/main/vm/aurade-vm.sh | bash
```

Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/Cam396/aurade/main/vm/aurade-vm.ps1 | iex
```

The first run:

1. finds the latest release and downloads its ISO into `~/AuraDE`;
2. checks the ISO against its published SHA-256, and against the release
   key's signature when gpg is installed (the key's fingerprint is
   `BC390DCF360B2184DBBF008B8B2AB2EFE667CB69`);
3. makes a 40 GB virtual disk and boots the installer.

Choose the virtual disk in the installer. When the install finishes, the VM
restarts into AuraDE. Every later run starts the installed system without
downloading anything. To start over, delete the VM (and on Linux, the
`aurade.qcow2` file in `~/AuraDE`).

Nothing outside that folder is changed, apart from the VM being registered
with libvirt, VirtualBox or Hyper-V when you use one of those.

### Settings

Set these before running the command. On Linux and macOS, put them in front
of `bash`, for example `curl -fsSL ... | AURADE_VM_MEMORY=8192 bash`. In
PowerShell, set `$env:AURADE_VM_MEMORY = 8192` first.

| Setting | Default | |
| --- | --- | --- |
| `AURADE_VM_BACKEND` | `qemu` on Linux and macOS; `hyperv` on Windows in an administrator shell, otherwise `virtualbox` | `qemu`, `libvirt` or `virtualbox` on Linux and macOS; `hyperv` or `virtualbox` on Windows |
| `AURADE_VM_DIR` | `~/AuraDE` | where the ISO and the disk live |
| `AURADE_VM_NAME` | `aurade` | the VM's name |
| `AURADE_VM_MEMORY` | `6144` | MiB; 4096 at least |
| `AURADE_VM_CPUS` | `4` | |
| `AURADE_VM_DISK_GB` | `40` | 30 at least |
| `AURADE_VM_WIDTH`, `AURADE_VM_HEIGHT` | `1920`, `1080` | QEMU only |
| `AURADE_VM_DISPLAY` | `gtk,zoom-to-fit=on` (`cocoa` on a Mac) | QEMU only |
| `AURADE_VM_GL` | `0` | `1` gives the VM 3D through the host's OpenGL; Linux QEMU only |
| `AURADE_VM_VERSION` | the latest release | a tag such as `v1.1.1` |

### What each platform needs

- **Linux, QEMU:** QEMU and UEFI firmware (OVMF). Arch:
  `sudo pacman -S qemu-desktop edk2-ovmf`. Debian and Ubuntu:
  `sudo apt install qemu-system-x86 ovmf`. Fedora:
  `sudo dnf install qemu-kvm edk2-ovmf`. Your user needs access to
  `/dev/kvm` (usually the `kvm` group).
- **Linux, libvirt:** `virt-install`, `virsh`, and `virt-viewer` or
  virt-manager to see the screen. The VM is made in the session connection
  (`qemu:///session`) unless `LIBVIRT_DEFAULT_URI` says otherwise.
- **Intel Mac:** `brew install qemu`. QEMU uses Hypervisor.framework.
- **Windows, Hyper-V:** Windows Pro, Enterprise or Education with Hyper-V
  turned on, and an administrator PowerShell. The VM is Generation 2 with
  Secure Boot off, on the Default Switch.
- **VirtualBox, any system:** VirtualBox 7. The VM uses EFI, the VMSVGA
  adapter and a USB tablet for the mouse.
- **Apple Silicon Macs** are not supported. AuraDE is built for x86_64, and
  emulating a PC on ARM is far too slow to use.

The QEMU path on Linux is the one tested most. If another one gives you
trouble, a [hardware report](https://github.com/Cam396/aurade/issues/new?template=hardware-report.yml)
with the hypervisor's name and version helps.

## Setting one up by hand

Any hypervisor works with these settings:

- **Firmware:** UEFI. AuraDE does not boot with legacy BIOS.
- **Secure Boot:** off, unless you enroll a key for AuraDE.
- **Memory:** 4 GB at least, 6 GB or more is better.
- **Disk:** 30 GB at least.
- **Network:** NAT is fine. The installer downloads packages, so it needs a
  connection.
- **Mouse:** a USB tablet (absolute pointer) if the hypervisor offers one, so
  the pointer follows yours without being captured.

In GNOME Boxes, pick the ISO, give it the memory and disk above, and make
sure the firmware is UEFI. In VMware Workstation or Fusion, choose "Other Linux 6.x
kernel 64-bit", set the firmware to UEFI, and turn on "Accelerate 3D
graphics".

## Graphics in a virtual machine

AuraDE's desktop is drawn on the GPU when it can be and by the processor
when it cannot. Most virtual machines have no 3D acceleration by default, so
the desktop there is drawn by the processor. It works, and it is slower,
especially at high resolutions.

To get 3D with the QEMU backend on Linux, set `AURADE_VM_GL=1`. The VM then
gets a virtio GPU whose drawing is done by the host's OpenGL (virgl). In
virt-manager, the same is "Virtio" video with 3D acceleration on, and an
OpenGL SPICE display.

**On AuraDE 1.1.1 only:** the graphical installer refuses to start in a VM
with no 3D acceleration (Hyper-V, and VirtualBox or QEMU without a 3D
device). Pick **text installer** in the ISO's boot menu instead. It installs
exactly the same system, and the installed desktop works. 1.1.2 lets the
graphical installer run there.
