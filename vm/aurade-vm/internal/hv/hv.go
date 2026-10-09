// Package hv is the hypervisor layer: what is installed on this computer, and
// how each one makes, starts and finishes an AuraDE virtual machine.
package hv

import (
	"context"
	"fmt"
	"os/exec"
	"runtime"
	"strings"
)

// Spec is the machine to make.
type Spec struct {
	Name       string // shown in the hypervisor, and the folder name
	Dir        string // the folder holding the VM's files
	ISO        string // the AuraDE installer image
	AnswersISO string // the answers disk, or "" for none
	MemoryMB   int
	CPUs       int
	DiskGB     int
	Accel3D    bool
}

// Detection is what a backend found on this computer.
type Detection struct {
	Available bool
	Version   string // as the hypervisor reports it
	Why       string // when not available: what to install or change, in a sentence
	// Foreign is set when this hypervisor does not exist for this kind of
	// computer at all, so it is not worth listing.
	Foreign bool
}

// AnswersFile is the answers disk's name inside a VM's folder.
const AnswersFile = "aurade-answers.iso"

// Backend is one hypervisor.
type Backend interface {
	ID() string   // vmware, qemu, ...
	Name() string // VMware Workstation, ...
	Detect(ctx context.Context) Detection
	// GuestDisk is the device name the AuraDE installer sees for the virtual
	// disk this backend attaches, so the answers can name it.
	GuestDisk() string
	// Exists reports whether a VM made from spec is already there.
	Exists(spec Spec) bool
	// Running reports whether that VM is powered on.
	Running(ctx context.Context, spec Spec) bool
	// Create makes the VM and its disk. It refuses to overwrite one.
	Create(ctx context.Context, spec Spec, log func(string)) error
	// Start powers the VM on, with its window shown.
	Start(ctx context.Context, spec Spec) error
	// Finish runs on the first start after install: it detaches the answers
	// disk and deletes it, since the installed system has no use for it.
	Finish(ctx context.Context, spec Spec) error
}

// All lists every backend this build knows, best first for this kind of
// computer: the first one that is ready is the one offered.
func All() []Backend {
	switch runtime.GOOS {
	case "windows":
		return []Backend{NewVMware(), NewHyperV(), NewVirtualBox(), NewQEMU(), NewLibvirt(), NewParallels(), NewUTM()}
	case "darwin":
		return []Backend{NewVMware(), NewParallels(), NewUTM(), NewQEMU(), NewVirtualBox(), NewLibvirt(), NewHyperV()}
	}
	return []Backend{NewLibvirt(), NewQEMU(), NewVMware(), NewVirtualBox(), NewHyperV(), NewParallels(), NewUTM()}
}

// Find returns the backend with this id.
func Find(id string) (Backend, error) {
	for _, b := range All() {
		if b.ID() == id {
			return b, nil
		}
	}
	return nil, fmt.Errorf("unknown hypervisor %q", id)
}

func run(ctx context.Context, name string, args ...string) (string, error) {
	out, err := exec.CommandContext(ctx, name, args...).CombinedOutput()
	s := strings.TrimSpace(string(out))
	if err != nil {
		if s == "" {
			s = err.Error()
		}
		return s, fmt.Errorf("%s %s: %s", baseName(name), strings.Join(args, " "), s)
	}
	return s, nil
}

func baseName(p string) string {
	if i := strings.LastIndexAny(p, `/\`); i >= 0 {
		return p[i+1:]
	}
	return p
}
