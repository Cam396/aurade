// Package host reads what the computer running aurade-vm already knows about
// its owner, so the questions start with sensible answers: the language, the
// time zone, how much memory and how many processors there are to share.
package host

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// Info is a best guess. Every field has a usable fallback.
type Info struct {
	Locale   string // en_US.UTF-8
	Timezone string // America/Chicago, or UTC when unknown
	MemoryMB int    // total memory, 0 when unknown
	CPUs     int
	OS       string // windows, linux, darwin
	Arch     string // amd64, arm64
	User     string // the login name, lowercased, as a username suggestion
	Hostname string
}

// Detect fills Info in.
func Detect() Info {
	h, _ := os.Hostname()
	i := Info{
		Locale:   "en_US.UTF-8",
		Timezone: "UTC",
		CPUs:     runtime.NumCPU(),
		OS:       runtime.GOOS,
		Arch:     runtime.GOARCH,
		User:     strings.ToLower(currentUser()),
		Hostname: h,
	}
	if l := detectLocale(); l != "" {
		i.Locale = l
	}
	if z := detectZone(); z != "" {
		i.Timezone = z
	}
	i.MemoryMB = memoryMB()
	return i
}

func currentUser() string {
	for _, k := range []string{"USER", "USERNAME", "LOGNAME"} {
		if v := os.Getenv(k); v != "" {
			return v
		}
	}
	return ""
}

// NormalizeLocale turns en-US, en_US, en_US.utf8 and en_US.UTF-8 into
// en_US.UTF-8, which is how the installer names locales.
func NormalizeLocale(s string) string {
	s = strings.TrimSpace(s)
	if s == "" || s == "C" || s == "POSIX" || strings.HasPrefix(s, "C.") {
		return ""
	}
	s = strings.SplitN(s, ".", 2)[0]
	s = strings.SplitN(s, "@", 2)[0]
	s = strings.ReplaceAll(s, "-", "_")
	parts := strings.SplitN(s, "_", 2)
	if len(parts[0]) < 2 || len(parts[0]) > 3 {
		return ""
	}
	out := strings.ToLower(parts[0])
	if len(parts) == 2 {
		region := strings.SplitN(parts[1], "_", 2)[0]
		if len(region) != 2 {
			return ""
		}
		out += "_" + strings.ToUpper(region)
	}
	return out + ".UTF-8"
}

// zoneFromLocaltime reads the IANA name out of a /etc/localtime symlink, which
// is how Linux and macOS both record it.
func zoneFromLocaltime(path string) string {
	target, err := os.Readlink(path)
	if err != nil {
		return ""
	}
	target = filepath.ToSlash(target)
	if i := strings.Index(target, "zoneinfo/"); i >= 0 {
		return target[i+len("zoneinfo/"):]
	}
	return ""
}
