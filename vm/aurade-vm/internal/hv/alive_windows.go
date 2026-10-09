//go:build windows

package hv

// processAlive is only asked about QEMU, which this tool does not run on Windows.
func processAlive(pid int) bool { return false }
