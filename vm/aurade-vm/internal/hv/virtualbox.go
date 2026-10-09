package hv

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
)

// VirtualBox drives VBoxManage, on Windows, Linux and Intel Macs.
type VirtualBox struct {
	goos, goarch string
	lookup       func(string) string
}

// NewVirtualBox returns the backend for this computer.
func NewVirtualBox() *VirtualBox {
	v := &VirtualBox{goos: runtime.GOOS, goarch: runtime.GOARCH}
	v.lookup = v.find
	return v
}

func (v *VirtualBox) ID() string        { return "virtualbox" }
func (v *VirtualBox) Name() string      { return "VirtualBox" }
func (v *VirtualBox) GuestDisk() string { return "/dev/sda" }

func (v *VirtualBox) find(name string) string {
	if name != "VBoxManage" {
		return ""
	}
	var cands []string
	switch v.goos {
	case "windows":
		for _, env := range []string{"VBOX_MSI_INSTALL_PATH", "VBOX_INSTALL_PATH"} {
			if p := os.Getenv(env); p != "" {
				cands = append(cands, filepath.Join(p, "VBoxManage.exe"))
			}
		}
		if p := os.Getenv("ProgramFiles"); p != "" {
			cands = append(cands, filepath.Join(p, "Oracle", "VirtualBox", "VBoxManage.exe"))
		}
	case "darwin":
		cands = append(cands, "/Applications/VirtualBox.app/Contents/MacOS/VBoxManage")
	}
	for _, c := range cands {
		if fileExists(c) {
			return c
		}
	}
	if p, err := exec.LookPath("VBoxManage"); err == nil {
		return p
	}
	return ""
}

var vboxVersionRe = regexp.MustCompile(`^(\d+)\.(\d+)`)

func (v *VirtualBox) Detect(ctx context.Context) Detection {
	if v.goos == "darwin" && v.goarch == "arm64" {
		return Detection{Why: "VirtualBox on an Apple Silicon Mac cannot run x86_64 systems at a usable speed."}
	}
	vb := v.lookup("VBoxManage")
	if vb == "" {
		return Detection{Why: "VirtualBox is not installed. It is free from virtualbox.org."}
	}
	out, err := run(ctx, vb, "--version")
	if err != nil {
		return Detection{Why: "VirtualBox is installed but VBoxManage does not run: " + firstLine(out)}
	}
	m := vboxVersionRe.FindStringSubmatch(out)
	if m != nil {
		major, _ := strconv.Atoi(m[1])
		minor, _ := strconv.Atoi(m[2])
		if major < 6 || major == 6 && minor < 1 {
			return Detection{Version: out, Why: "VirtualBox " + m[1] + "." + m[2] + " is too old; AuraDE needs 6.1 or newer."}
		}
	}
	return Detection{Available: true, Version: firstLine(out)}
}

func (v *VirtualBox) vbox(ctx context.Context, args ...string) (string, error) {
	return run(ctx, v.lookup("VBoxManage"), args...)
}

func (v *VirtualBox) disk(s Spec) string { return filepath.Join(s.Dir, s.Name+".vdi") }

func (v *VirtualBox) Exists(s Spec) bool {
	if v.lookup("VBoxManage") == "" {
		return false
	}
	_, err := v.vbox(context.Background(), "showvminfo", s.Name, "--machinereadable")
	return err == nil
}

func (v *VirtualBox) Running(ctx context.Context, s Spec) bool {
	out, err := v.vbox(ctx, "list", "runningvms")
	return err == nil && strings.Contains(out, `"`+s.Name+`"`)
}

// Steps are the VBoxManage calls that make the VM, in order. The VM's files
// go in the parent of s.Dir with --basefolder, which makes s.Dir itself.
func (v *VirtualBox) Steps(s Spec) [][]string {
	graphics, accel := "vmsvga", "off"
	if s.Accel3D {
		accel = "on"
	}
	steps := [][]string{
		{"createvm", "--name", s.Name, "--ostype", "ArchLinux_64", "--register", "--basefolder", filepath.Dir(s.Dir)},
		{"modifyvm", s.Name, "--memory", strconv.Itoa(s.MemoryMB), "--cpus", strconv.Itoa(s.CPUs),
			"--firmware", "efi", "--graphicscontroller", graphics, "--vram", "128", "--accelerate3d", accel,
			"--nic1", "nat", "--mouse", "usbtablet", "--usbxhci", "on", "--audio-enabled", "off",
			"--boot1", "disk", "--boot2", "dvd", "--boot3", "none", "--boot4", "none"},
		{"createmedium", "disk", "--filename", v.disk(s), "--size", strconv.Itoa(s.DiskGB * 1024), "--format", "VDI"},
		{"storagectl", s.Name, "--name", "SATA", "--add", "sata", "--controller", "IntelAhci", "--portcount", "3"},
		{"storageattach", s.Name, "--storagectl", "SATA", "--port", "0", "--device", "0", "--type", "hdd", "--medium", v.disk(s)},
		{"storageattach", s.Name, "--storagectl", "SATA", "--port", "1", "--device", "0", "--type", "dvddrive", "--medium", s.ISO},
	}
	if s.AnswersISO != "" {
		steps = append(steps, []string{"storageattach", s.Name, "--storagectl", "SATA", "--port", "2", "--device", "0", "--type", "dvddrive", "--medium", s.AnswersISO})
	}
	return steps
}

func (v *VirtualBox) Create(ctx context.Context, s Spec, log func(string)) error {
	if log == nil {
		log = func(string) {}
	}
	if v.Exists(s) {
		return fmt.Errorf("VirtualBox already has a VM called %s", s.Name)
	}
	log(fmt.Sprintf("Making the VM and a %d GB virtual disk", s.DiskGB))
	for _, step := range v.Steps(s) {
		if _, err := v.vbox(ctx, step...); err != nil {
			return err
		}
	}
	return nil
}

func (v *VirtualBox) Start(ctx context.Context, s Spec) error {
	if v.Running(ctx, s) {
		return nil
	}
	_, err := v.vbox(ctx, "startvm", s.Name, "--type", "gui")
	return err
}

// Finish empties the answers drive and deletes the file. VirtualBox also
// keeps the image in its media registry, so it is closed there as well.
func (v *VirtualBox) Finish(ctx context.Context, s Spec) error {
	answers := filepath.Join(s.Dir, AnswersFile)
	if !fileExists(answers) {
		return nil
	}
	if _, err := v.vbox(ctx, "storageattach", s.Name, "--storagectl", "SATA", "--port", "2", "--device", "0", "--type", "dvddrive", "--medium", "none"); err != nil {
		return err
	}
	_, _ = v.vbox(ctx, "closemedium", "dvd", answers)
	if err := os.Remove(answers); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}
