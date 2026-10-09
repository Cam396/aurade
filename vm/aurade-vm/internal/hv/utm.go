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

// UTM drives UTM on a Mac. utmctl can start and stop a VM but not make one,
// so the VM is made, and its answers drive later removed, through UTM's
// AppleScript dictionary, which is the way UTM documents for scripting it.
// Every value reaches the script as an argument, never as script text, so a
// VM name cannot change what the script does.
type UTM struct {
	goos, goarch string
	app          string // the UTM.app bundle
	script       func(ctx context.Context, src string, args ...string) (string, error)
}

// NewUTM returns the backend for this computer.
func NewUTM() *UTM {
	return &UTM{goos: runtime.GOOS, goarch: runtime.GOARCH, app: "/Applications/UTM.app",
		script: func(ctx context.Context, src string, args ...string) (string, error) {
			cmd := exec.CommandContext(ctx, "osascript", append([]string{"-"}, args...)...)
			cmd.Stdin = strings.NewReader(src)
			out, err := cmd.CombinedOutput()
			s := strings.TrimSpace(string(out))
			if err != nil {
				if s == "" {
					s = err.Error()
				}
				return s, fmt.Errorf("UTM: %s", s)
			}
			return s, nil
		}}
}

func (u *UTM) ID() string   { return "utm" }
func (u *UTM) Name() string { return "UTM" }

// GuestDisk is the virtio disk UTM gives a new x86_64 VM.
func (u *UTM) GuestDisk() string { return "/dev/vda" }

func (u *UTM) utmctl() string { return filepath.Join(u.app, "Contents/MacOS/utmctl") }

func (u *UTM) Detect(ctx context.Context) Detection {
	switch {
	case u.goos != "darwin":
		return Detection{Foreign: true, Why: "UTM runs on a Mac."}
	case u.goarch == "arm64":
		return Detection{Why: "UTM on an Apple Silicon Mac can only emulate an x86_64 PC, far too slowly for a desktop, and AuraDE is built for x86_64 PCs."}
	case !fileExists(u.app):
		return Detection{Why: "UTM is not installed. It is free from mac.getutm.app."}
	}
	out, err := run(ctx, "defaults", "read", filepath.Join(u.app, "Contents/Info"), "CFBundleShortVersionString")
	if err != nil {
		return Detection{Why: "UTM's version could not be read: " + firstLine(out)}
	}
	v := firstLine(out)
	if !utmScriptable(v) {
		return Detection{Version: v, Why: "UTM " + v + " cannot be scripted; UTM 4.2 or later can."}
	}
	return Detection{Available: true, Version: v}
}

// utmScriptable reports whether this UTM version has the scripting dictionary,
// which arrived in 4.2.
func utmScriptable(v string) bool {
	parts := strings.SplitN(v, ".", 3)
	major, err := strconv.Atoi(parts[0])
	if err != nil {
		return false
	}
	minor := 0
	if len(parts) > 1 {
		minor, _ = strconv.Atoi(strings.TrimFunc(parts[1], func(r rune) bool { return r < '0' || r > '9' }))
	}
	return major > 4 || major == 4 && minor >= 2
}

func (u *UTM) Exists(s Spec) bool {
	if !fileExists(u.utmctl()) {
		return false
	}
	_, err := run(context.Background(), u.utmctl(), "status", s.Name)
	return err == nil
}

func (u *UTM) Running(ctx context.Context, s Spec) bool {
	out, err := run(ctx, u.utmctl(), "status", s.Name)
	return err == nil && strings.Contains(out, "started")
}

// utmCreate makes the VM: UEFI, the hypervisor framework rather than
// emulation, the installer and the answers as removable drives, and an empty
// virtio disk sized in MiB. Arguments: name, memory MiB, cores, disk MiB,
// installer ISO, answers ISO or "".
const utmCreate = `on run argv
	set vmName to item 1 of argv
	set mem to (item 2 of argv) as integer
	set cores to (item 3 of argv) as integer
	set diskSize to (item 4 of argv) as integer
	set iso to POSIX file (item 5 of argv)
	set theDrives to {{removable:true, source:iso}}
	if (item 6 of argv) is not "" then
		set end of theDrives to {removable:true, source:(POSIX file (item 6 of argv))}
	end if
	set end of theDrives to {guest size:diskSize}
	tell application "UTM"
		set vm to make new virtual machine with properties {backend:qemu, configuration:{name:vmName, architecture:"x86_64", memory:mem, cpu cores:cores, hypervisor:true, uefi:true, drives:theDrives}}
	end tell
	return "made"
end run
`

// utmDetach removes every removable drive whose file is the answers disk.
// Arguments: name, the answers disk's file name.
const utmDetach = `on run argv
	set vmName to item 1 of argv
	set answersName to item 2 of argv
	tell application "UTM"
		set vm to virtual machine named vmName
		set config to configuration of vm
		set kept to {}
		repeat with d in drives of config
			set drop to false
			if removable of d then
				try
					if (POSIX path of (source of d)) ends with answersName then set drop to true
				end try
			end if
			if not drop then set end of kept to (contents of d)
		end repeat
		set drives of config to kept
		update configuration of vm with config
	end tell
	return "detached"
end run
`

// CreateArgs are the arguments utmCreate is run with.
func (u *UTM) CreateArgs(s Spec) []string {
	return []string{s.Name, strconv.Itoa(s.MemoryMB), strconv.Itoa(s.CPUs), strconv.Itoa(s.DiskGB * 1024), s.ISO, s.AnswersISO}
}

func (u *UTM) Create(ctx context.Context, s Spec, log func(string)) error {
	if log == nil {
		log = func(string) {}
	}
	if u.Exists(s) {
		return fmt.Errorf("UTM already has a VM called %s", s.Name)
	}
	log(fmt.Sprintf("Making the VM and a %d GB virtual disk in UTM", s.DiskGB))
	if !s.Accel3D {
		log("UTM's own display is used; 3D graphics are UTM's setting, under Display")
	}
	_, err := u.script(ctx, utmCreate, u.CreateArgs(s)...)
	return err
}

func (u *UTM) Start(ctx context.Context, s Spec) error {
	if !u.Running(ctx, s) {
		if _, err := run(ctx, u.utmctl(), "start", s.Name); err != nil {
			return err
		}
	}
	_ = exec.Command("open", "-a", u.app).Start()
	return nil
}

// Finish takes the answers drive out of the VM's settings and deletes the
// file. UTM only accepts a changed configuration while the VM is stopped,
// which it is on the first start after the install.
func (u *UTM) Finish(ctx context.Context, s Spec) error {
	answers := filepath.Join(s.Dir, AnswersFile)
	if !fileExists(answers) {
		return nil
	}
	if _, err := u.script(ctx, utmDetach, s.Name, AnswersFile); err != nil {
		return err
	}
	if err := os.Remove(answers); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}
