package hv

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

// Libvirt makes the VM through virt-install on the user's own libvirt
// connection (qemu:///session), which is where GNOME Boxes keeps its VMs
// too, so the VM shows up in Boxes and in virt-manager alike.
type Libvirt struct {
	goos   string
	lookup func(string) string
	uri    string
}

// NewLibvirt returns the backend for this computer.
func NewLibvirt() *Libvirt {
	uri := os.Getenv("LIBVIRT_DEFAULT_URI")
	if uri == "" {
		uri = "qemu:///session"
	}
	return &Libvirt{goos: runtime.GOOS, uri: uri,
		lookup: func(n string) string { p, _ := exec.LookPath(n); return p }}
}

func (l *Libvirt) ID() string { return "libvirt" }

func (l *Libvirt) Name() string {
	if l.lookup != nil && l.lookup("gnome-boxes") != "" && l.lookup("virt-manager") == "" {
		return "GNOME Boxes (libvirt)"
	}
	return "libvirt (virt-manager, GNOME Boxes)"
}

func (l *Libvirt) GuestDisk() string { return "/dev/vda" }

func (l *Libvirt) Detect(ctx context.Context) Detection {
	if l.goos != "linux" {
		return Detection{Foreign: true, Why: "libvirt and GNOME Boxes run on Linux."}
	}
	if l.lookup("virsh") == "" || l.lookup("virt-install") == "" {
		return Detection{Why: "libvirt is not installed. virt-install and virsh are needed: on Arch, sudo pacman -S libvirt virt-install; on Debian or Ubuntu, sudo apt install libvirt-clients virtinst; on Fedora, sudo dnf install libvirt-client virt-install."}
	}
	out, err := run(ctx, l.lookup("virsh"), "-c", l.uri, "version", "--daemon")
	if err != nil {
		return Detection{Why: "libvirt is installed but " + l.uri + " does not answer: " + firstLine(out)}
	}
	v := ""
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, "against daemon") {
			v = strings.TrimSpace(line[strings.LastIndex(line, " ")+1:])
		}
	}
	return Detection{Available: true, Version: "libvirt " + v}
}

func (l *Libvirt) virsh(ctx context.Context, args ...string) (string, error) {
	return run(ctx, l.lookup("virsh"), append([]string{"-c", l.uri}, args...)...)
}

func (l *Libvirt) disk(s Spec) string { return filepath.Join(s.Dir, s.Name+".qcow2") }

func (l *Libvirt) Exists(s Spec) bool {
	_, err := l.virsh(context.Background(), "dominfo", s.Name)
	return err == nil
}

func (l *Libvirt) Running(ctx context.Context, s Spec) bool {
	out, err := l.virsh(ctx, "domstate", s.Name)
	return err == nil && strings.TrimSpace(out) == "running"
}

// InstallArgs is virt-install's command line. --import with a boot order
// puts the empty disk first; the firmware falls through to the installer
// until the disk holds a system.
func (l *Libvirt) InstallArgs(s Spec) []string {
	args := []string{
		"--connect", l.uri, "--name", s.Name,
		"--memory", strconv.Itoa(s.MemoryMB), "--vcpus", strconv.Itoa(s.CPUs),
		"--cpu", "host-passthrough", "--osinfo", "archlinux",
		// Secure Boot off, as on every other hypervisor here. Asking for it
		// also keeps libvirt away from enrolled-keys firmware, which some
		// hosts describe with files they do not have.
		"--boot", "uefi,firmware.feature0.name=secure-boot,firmware.feature0.enabled=no,firmware.feature1.name=enrolled-keys,firmware.feature1.enabled=no",
		"--disk", fmt.Sprintf("path=%s,size=%d,format=qcow2,bus=virtio,boot.order=1", l.disk(s), s.DiskGB),
		"--disk", "path=" + s.ISO + ",device=cdrom,bus=sata,readonly=on,boot.order=2",
	}
	if s.AnswersISO != "" {
		args = append(args, "--disk", "path="+s.AnswersISO+",device=cdrom,bus=sata,readonly=on")
	}
	video, graphics := "vga", "spice"
	if s.Accel3D {
		video, graphics = "virtio,accel3d=yes", "spice,gl.enable=yes,listen=none"
	}
	args = append(args, "--network", "user,model=virtio", "--video", video, "--graphics", graphics,
		"--input", "tablet,bus=usb", "--sound", "none",
		// The guest agent's channel, named rather than left to virt-install's
		// guess for this OS, so the agent the installer adds always starts.
		"--channel", "unix,target.type=virtio,name=org.qemu.guest_agent.0",
		"--import", "--noautoconsole", "--noreboot")
	return args
}

func (l *Libvirt) Create(ctx context.Context, s Spec, log func(string)) error {
	if log == nil {
		log = func(string) {}
	}
	if l.Exists(s) {
		return fmt.Errorf("libvirt already has a VM called %s", s.Name)
	}
	if err := os.MkdirAll(s.Dir, 0o755); err != nil {
		return err
	}
	log(fmt.Sprintf("Defining %s on %s with a %d GB disk", s.Name, l.uri, s.DiskGB))
	_, err := run(ctx, l.lookup("virt-install"), l.InstallArgs(s)...)
	return err
}

func (l *Libvirt) Start(ctx context.Context, s Spec) error {
	if !l.Running(ctx, s) {
		if _, err := l.virsh(ctx, "start", s.Name); err != nil {
			return err
		}
	}
	// A window onto it, from whichever viewer this computer has.
	switch {
	case l.lookup("virt-manager") != "":
		return spawn(s.Dir, "viewer.log", l.lookup("virt-manager"), "--connect", l.uri, "--show-domain-console", s.Name)
	case l.lookup("virt-viewer") != "":
		return spawn(s.Dir, "viewer.log", l.lookup("virt-viewer"), "--connect", l.uri, "--wait", s.Name)
	case l.lookup("gnome-boxes") != "":
		return spawn(s.Dir, "viewer.log", l.lookup("gnome-boxes"))
	}
	return nil
}

// Finish detaches the answers drive from the saved definition and deletes
// the file.
func (l *Libvirt) Finish(ctx context.Context, s Spec) error {
	answers := filepath.Join(s.Dir, AnswersFile)
	out, err := l.virsh(ctx, "domblklist", s.Name, "--details")
	if err != nil {
		return err
	}
	if target := blkTarget(out, answers); target != "" {
		if _, err := l.virsh(ctx, "detach-disk", s.Name, target, "--config"); err != nil {
			return err
		}
	}
	if err := os.Remove(answers); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// blkTarget finds the target (sdb, ...) of the drive holding path in
// `virsh domblklist --details` output.
func blkTarget(list, path string) string {
	for _, line := range strings.Split(list, "\n") {
		f := strings.Fields(line)
		if len(f) >= 4 && f[len(f)-1] == path {
			return f[2]
		}
	}
	return ""
}

func firstLine(s string) string { return strings.SplitN(strings.TrimSpace(s), "\n", 2)[0] }
