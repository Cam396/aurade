//go:build !windows

package hv

import (
	"os/exec"
	"syscall"
)

// detach lets a hypervisor's own window outlive aurade-vm.
func detach(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}
