//go:build windows

package host

import (
	"os/exec"
	"strings"
	"syscall"
	"unsafe"
)

var (
	kernel32                     = syscall.NewLazyDLL("kernel32.dll")
	procGetUserDefaultLocaleName = kernel32.NewProc("GetUserDefaultLocaleName")
	procGlobalMemoryStatusEx     = kernel32.NewProc("GlobalMemoryStatusEx")
)

func detectLocale() string {
	buf := make([]uint16, 85)
	r, _, _ := procGetUserDefaultLocaleName.Call(uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)))
	if r == 0 {
		return ""
	}
	return NormalizeLocale(syscall.UTF16ToString(buf))
}

func detectZone() string {
	out, err := exec.Command("tzutil", "/g").Output()
	if err != nil {
		return ""
	}
	return WindowsZoneToIANA(strings.TrimSpace(string(out)))
}

type memoryStatusEx struct {
	length               uint32
	memoryLoad           uint32
	totalPhys            uint64
	availPhys            uint64
	totalPageFile        uint64
	availPageFile        uint64
	totalVirtual         uint64
	availVirtual         uint64
	availExtendedVirtual uint64
}

func memoryMB() int {
	var m memoryStatusEx
	m.length = uint32(unsafe.Sizeof(m))
	r, _, _ := procGlobalMemoryStatusEx.Call(uintptr(unsafe.Pointer(&m)))
	if r == 0 {
		return 0
	}
	return int(m.totalPhys / (1 << 20))
}
