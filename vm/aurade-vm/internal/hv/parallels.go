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

// Parallels drives Parallels Desktop through prlctl. Its command line comes
// with the Pro and Business editions; the Standard edition has none, which
// Detect says plainly.
type Parallels struct {
	goos, goarch string
	lookup       func(string) string
}

// NewParallels returns the backend for this computer.
func NewParallels() *Parallels {
	return &Parallels{goos: runtime.GOOS, goarch: runtime.GOARCH, lookup: func(n string) string {
		if p, err := exec.LookPath(n); err == nil {
			return p
		}
		if p := "/usr/local/bin/" + n; fileExists(p) {
			return p
		}
		return ""
	}}
}

func (p *Parallels) ID() string        { return "parallels" }
func (p *Parallels) Name() string      { return "Parallels Desktop" }
func (p *Parallels) GuestDisk() string { return "/dev/sda" }

func (p *Parallels) Detect(ctx context.Context) Detection {
	switch {
	case p.goos != "darwin":
		return Detection{Foreign: true, Why: "Parallels Desktop runs on a Mac."}
	case p.goarch == "arm64":
		return Detection{Why: "Parallels on an Apple Silicon Mac can only run Arm systems, and AuraDE is built for x86_64 PCs."}
	}
	prl := p.lookup("prlctl")
	if prl == "" {
		if fileExists("/Applications/Parallels Desktop.app") {
			return Detection{Why: "This edition of Parallels Desktop has no command line (prlctl), which comes with Pro and Business."}
		}
		return Detection{Why: "Parallels Desktop is not installed."}
	}
	out, err := run(ctx, prl, "--version")
	if err != nil {
		return Detection{Why: "prlctl does not run: " + firstLine(out)}
	}
	return Detection{Available: true, Version: strings.TrimPrefix(firstLine(out), "prlctl version ")}
}

func (p *Parallels) prl(ctx context.Context, args ...string) (string, error) {
	return run(ctx, p.lookup("prlctl"), args...)
}

func (p *Parallels) Exists(s Spec) bool {
	if p.lookup("prlctl") == "" {
		return false
	}
	_, err := p.prl(context.Background(), "status", s.Name)
	return err == nil
}

func (p *Parallels) Running(ctx context.Context, s Spec) bool {
	out, err := p.prl(ctx, "status", s.Name)
	return err == nil && strings.HasSuffix(strings.TrimSpace(out), " running")
}

// Steps are the prlctl calls that make the VM. The bundle goes in the
// parent of s.Dir; Parallels names it after the VM.
func (p *Parallels) Steps(s Spec) [][]string {
	steps := [][]string{
		{"create", s.Name, "--ostype", "linux", "--distribution", "linux", "--no-hdd", "--dst", filepath.Dir(s.Dir)},
		{"set", s.Name, "--cpus", strconv.Itoa(s.CPUs), "--memsize", strconv.Itoa(s.MemoryMB), "--efi-boot", "on", "--efi-secure-boot", "off"},
		{"set", s.Name, "--3d-accelerate", map[bool]string{true: "highest", false: "off"}[s.Accel3D]},
		{"set", s.Name, "--device-add", "hdd", "--type", "expand", "--size", strconv.Itoa(s.DiskGB * 1024), "--iface", "sata"},
		{"set", s.Name, "--device-add", "cdrom", "--image", s.ISO, "--iface", "sata", "--connect"},
	}
	if s.AnswersISO != "" {
		steps = append(steps, []string{"set", s.Name, "--device-add", "cdrom", "--image", s.AnswersISO, "--iface", "sata", "--connect"})
	}
	return append(steps, []string{"set", s.Name, "--device-bootorder", "hdd0 cdrom0"})
}

func (p *Parallels) Create(ctx context.Context, s Spec, log func(string)) error {
	if log == nil {
		log = func(string) {}
	}
	if p.Exists(s) {
		return fmt.Errorf("Parallels already has a VM called %s", s.Name)
	}
	log(fmt.Sprintf("Making the VM and a %d GB virtual disk", s.DiskGB))
	for _, step := range p.Steps(s) {
		if _, err := p.prl(ctx, step...); err != nil {
			return err
		}
	}
	return nil
}

func (p *Parallels) Start(ctx context.Context, s Spec) error {
	if !p.Running(ctx, s) {
		if _, err := p.prl(ctx, "start", s.Name); err != nil {
			return err
		}
	}
	_ = exec.Command("open", "-a", "Parallels Desktop").Start()
	return nil
}

// Finish removes the drive holding the answers disk and deletes the file.
func (p *Parallels) Finish(ctx context.Context, s Spec) error {
	answers := filepath.Join(s.Dir, AnswersFile)
	if !fileExists(answers) {
		return nil
	}
	out, err := p.prl(ctx, "list", "-i", s.Name)
	if err != nil {
		return err
	}
	if dev := prlDevice(out, answers); dev != "" {
		if _, err := p.prl(ctx, "set", s.Name, "--device-del", dev); err != nil {
			return err
		}
	}
	if err := os.Remove(answers); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// prlDevice finds the device (cdrom1, ...) whose image is path in
// `prlctl list -i` output, where a drive reads like
//
//	cdrom1 (+) sata:2 image='/path/to/file.iso'
func prlDevice(info, path string) string {
	for _, line := range strings.Split(info, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "cdrom") && strings.Contains(line, "image='"+path+"'") {
			return strings.Fields(line)[0]
		}
	}
	return ""
}
