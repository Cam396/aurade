package hv

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

// QEMU runs the VM directly with qemu-system-x86_64: KVM on Linux, the
// Hypervisor framework on an Intel Mac. It keeps nothing outside the VM's
// folder: the disk, a copy of the firmware's variables, and a pid file.
type QEMU struct {
	goos, goarch string
	lookup       func(string) string
	kvmUsable    func() bool
}

// NewQEMU returns the backend for this computer.
func NewQEMU() *QEMU {
	return &QEMU{goos: runtime.GOOS, goarch: runtime.GOARCH,
		lookup: func(n string) string { p, _ := exec.LookPath(n); return p },
		kvmUsable: func() bool {
			f, err := os.OpenFile("/dev/kvm", os.O_RDWR, 0)
			if err != nil {
				return false
			}
			f.Close()
			return true
		}}
}

func (q *QEMU) ID() string        { return "qemu" }
func (q *QEMU) Name() string      { return "QEMU" }
func (q *QEMU) GuestDisk() string { return "/dev/vda" }

// UEFI firmware lives somewhere different on every distribution. Each pair is
// the read-only code and the writable variables template that go with it.
var firmwarePairs = [][2]string{
	{"/usr/share/edk2/x64/OVMF_CODE.4m.fd", "/usr/share/edk2/x64/OVMF_VARS.4m.fd"},
	{"/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"},
	{"/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"},
	{"/usr/share/edk2/ovmf/OVMF_CODE.fd", "/usr/share/edk2/ovmf/OVMF_VARS.fd"},
	{"/usr/share/qemu/ovmf-x86_64-code.bin", "/usr/share/qemu/ovmf-x86_64-vars.bin"},
	{"/usr/share/edk2-ovmf/x64/OVMF_CODE.fd", "/usr/share/edk2-ovmf/x64/OVMF_VARS.fd"},
	{"/opt/homebrew/share/qemu/edk2-x86_64-code.fd", "/opt/homebrew/share/qemu/edk2-i386-vars.fd"},
	{"/usr/local/share/qemu/edk2-x86_64-code.fd", "/usr/local/share/qemu/edk2-i386-vars.fd"},
}

func (q *QEMU) firmware() (code, vars string, ok bool) {
	for _, p := range firmwarePairs {
		if fileExists(p[0]) && fileExists(p[1]) {
			return p[0], p[1], true
		}
	}
	return "", "", false
}

func (q *QEMU) installHint() string {
	if q.goos == "darwin" {
		return "Install it with Homebrew: brew install qemu"
	}
	return "Install it: on Arch, sudo pacman -S qemu-desktop edk2-ovmf; on Debian or Ubuntu, sudo apt install qemu-system-x86 ovmf; on Fedora, sudo dnf install qemu-kvm edk2-ovmf."
}

func (q *QEMU) Detect(ctx context.Context) Detection {
	switch {
	case q.goos == "windows":
		return Detection{Foreign: true, Why: "QEMU on Windows has no fast way to run a PC; use VMware Workstation, Hyper-V or VirtualBox."}
	case q.goos == "darwin" && q.goarch == "arm64":
		return Detection{Why: "On an Apple Silicon Mac QEMU can only emulate a PC, which is far too slow for AuraDE."}
	}
	bin := q.lookup("qemu-system-x86_64")
	if bin == "" {
		return Detection{Why: "QEMU is not installed. " + q.installHint()}
	}
	if q.lookup("qemu-img") == "" {
		return Detection{Why: "qemu-img is missing; it comes with QEMU. " + q.installHint()}
	}
	if _, _, ok := q.firmware(); !ok {
		return Detection{Why: "QEMU is installed without UEFI firmware. Install the ovmf (or edk2-ovmf) package."}
	}
	if q.goos == "linux" && !q.kvmUsable() {
		return Detection{Why: "/dev/kvm cannot be opened, so the VM would crawl. Turn on virtualization in the firmware settings and add yourself to the kvm group: sudo usermod -aG kvm $USER"}
	}
	out, _ := exec.CommandContext(ctx, bin, "--version").Output()
	v := strings.TrimSpace(strings.SplitN(string(out), "\n", 2)[0])
	v = strings.TrimPrefix(v, "QEMU emulator ")
	return Detection{Available: true, Version: v}
}

func (q *QEMU) disk(s Spec) string    { return filepath.Join(s.Dir, s.Name+".qcow2") }
func (q *QEMU) vars(s Spec) string    { return filepath.Join(s.Dir, s.Name+"-efivars.fd") }
func (q *QEMU) pidfile(s Spec) string { return filepath.Join(s.Dir, "qemu.pid") }

func (q *QEMU) Exists(s Spec) bool { return fileExists(q.disk(s)) }

func (q *QEMU) Running(ctx context.Context, s Spec) bool {
	b, err := os.ReadFile(q.pidfile(s))
	if err != nil {
		return false
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(b)))
	return err == nil && processAlive(pid)
}

func (q *QEMU) Create(ctx context.Context, s Spec, log func(string)) error {
	if log == nil {
		log = func(string) {}
	}
	if q.Exists(s) {
		return fmt.Errorf("a VM is already at %s", q.disk(s))
	}
	if err := os.MkdirAll(s.Dir, 0o755); err != nil {
		return err
	}
	_, varsTemplate, ok := q.firmware()
	if !ok {
		return errors.New("no UEFI firmware for QEMU was found")
	}
	log(fmt.Sprintf("Making a %d GB virtual disk (it only takes the space AuraDE uses)", s.DiskGB))
	if _, err := run(ctx, q.lookup("qemu-img"), "create", "-q", "-f", "qcow2", q.disk(s), strconv.Itoa(s.DiskGB)+"G"); err != nil {
		return err
	}
	log("Copying the firmware's settings store")
	return copyFile(varsTemplate, q.vars(s))
}

// Args is the command line for the VM. The disk boots first once it holds a
// system; until then the firmware falls through to the installer, which
// stays attached so its recovery tools are there if they are ever needed.
func (q *QEMU) Args(s Spec, code string) []string {
	accel, display := "kvm", "gtk,zoom-to-fit=on"
	gpu := "VGA,edid=on,xres=1920,yres=1080"
	if q.goos == "darwin" {
		accel, display = "hvf", "cocoa"
	} else if s.Accel3D {
		// virgl hands the desktop's drawing to the host's GPU. Without it
		// AuraDE draws on the processor: it works, slowly.
		gpu = "virtio-vga-gl,edid=on,xres=1920,yres=1080"
		display += ",gl=on"
	}
	if d := os.Getenv("AURADE_VM_DISPLAY"); d != "" {
		display = d
	}
	args := []string{
		"-name", s.Name, "-machine", "q35,accel=" + accel, "-cpu", "host",
		"-smp", strconv.Itoa(s.CPUs), "-m", strconv.Itoa(s.MemoryMB),
		"-drive", "if=pflash,format=raw,readonly=on,file=" + code,
		"-drive", "if=pflash,format=raw,file=" + q.vars(s),
		"-drive", "file=" + q.disk(s) + ",if=none,id=hd0,format=qcow2,discard=unmap",
		"-device", "virtio-blk-pci,drive=hd0,bootindex=1",
	}
	if s.ISO != "" {
		args = append(args, "-drive", "file="+s.ISO+",media=cdrom,if=none,id=cd0,readonly=on",
			"-device", "ide-cd,drive=cd0,bus=ide.0,bootindex=2")
	}
	if a := filepath.Join(s.Dir, AnswersFile); fileExists(a) {
		args = append(args, "-drive", "file="+a+",media=cdrom,if=none,id=cd1,readonly=on",
			"-device", "ide-cd,drive=cd1,bus=ide.1")
	}
	args = append(args, "-device", gpu,
		"-device", "qemu-xhci", "-device", "usb-tablet",
		"-nic", "user,model=virtio-net-pci",
		"-audiodev", "none,id=snd0",
		"-display", display,
		"-pidfile", q.pidfile(s))
	return args
}

func (q *QEMU) Start(ctx context.Context, s Spec) error {
	if q.Running(ctx, s) {
		return nil
	}
	code, _, ok := q.firmware()
	if !ok {
		return errors.New("no UEFI firmware for QEMU was found")
	}
	if s.ISO == "" {
		// A later run does not know which ISO the VM was made with; the
		// record does, and when it is gone the newest one in the folder
		// above will do.
		s.ISO = newestISO(filepath.Dir(s.Dir))
	}
	return spawn(s.Dir, "qemu.log", q.lookup("qemu-system-x86_64"), q.Args(s, code)...)
}

// Finish deletes the answers disk; the next start leaves it out.
func (q *QEMU) Finish(ctx context.Context, s Spec) error {
	err := os.Remove(filepath.Join(s.Dir, AnswersFile))
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

func newestISO(dir string) string {
	m, _ := filepath.Glob(filepath.Join(dir, "aurade-v*-x86_64.iso"))
	if len(m) == 0 {
		return ""
	}
	return m[len(m)-1]
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}
