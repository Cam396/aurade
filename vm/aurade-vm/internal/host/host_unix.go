//go:build !windows

package host

import (
	"bufio"
	"os"
	"os/exec"
	"strconv"
	"strings"
)

func detectLocale() string {
	for _, k := range []string{"LC_ALL", "LC_MESSAGES", "LANG"} {
		if l := NormalizeLocale(os.Getenv(k)); l != "" {
			return l
		}
	}
	// macOS apps started from Finder have no LANG; the system default is in
	// the preferences.
	if out, err := exec.Command("defaults", "read", "-g", "AppleLocale").Output(); err == nil {
		return NormalizeLocale(string(out))
	}
	return ""
}

func detectZone() string {
	if z := os.Getenv("TZ"); z != "" && !strings.HasPrefix(z, ":") && strings.Contains(z, "/") {
		return z
	}
	if b, err := os.ReadFile("/etc/timezone"); err == nil {
		if z := strings.TrimSpace(string(b)); z != "" {
			return z
		}
	}
	return zoneFromLocaltime("/etc/localtime")
}

func memoryMB() int {
	if f, err := os.Open("/proc/meminfo"); err == nil {
		defer f.Close()
		s := bufio.NewScanner(f)
		for s.Scan() {
			fields := strings.Fields(s.Text())
			if len(fields) >= 2 && fields[0] == "MemTotal:" {
				kb, _ := strconv.Atoi(fields[1])
				return kb / 1024
			}
		}
	}
	if out, err := exec.Command("sysctl", "-n", "hw.memsize").Output(); err == nil {
		b, _ := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
		return int(b / (1 << 20))
	}
	return 0
}
