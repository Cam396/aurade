package host

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNormalizeLocale(t *testing.T) {
	for in, want := range map[string]string{
		"en-US": "en_US.UTF-8", "en_US.utf8": "en_US.UTF-8", "de_DE.UTF-8@euro": "de_DE.UTF-8",
		"fr": "fr.UTF-8", "C": "", "POSIX": "", "C.UTF-8": "", "": "", "zh-Hans-CN": "",
		"en_GB\n": "en_GB.UTF-8",
	} {
		if got := NormalizeLocale(in); got != want {
			t.Errorf("%q: got %q want %q", in, got, want)
		}
	}
}

func TestZoneFromLocaltime(t *testing.T) {
	dir := t.TempDir()
	link := filepath.Join(dir, "localtime")
	if err := os.Symlink("/usr/share/zoneinfo/America/Chicago", link); err != nil {
		t.Skip(err)
	}
	if got := zoneFromLocaltime(link); got != "America/Chicago" {
		t.Fatalf("got %q", got)
	}
	if zoneFromLocaltime(filepath.Join(dir, "missing")) != "" {
		t.Fatal("a missing file gave a zone")
	}
}

func TestWindowsZones(t *testing.T) {
	if WindowsZoneToIANA("Central Standard Time") != "America/Chicago" || WindowsZoneToIANA("Nowhere") != "" {
		t.Fatal("windows zone mapping")
	}
}
