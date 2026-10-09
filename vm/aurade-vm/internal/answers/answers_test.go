package answers

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestValidateMatchesInstallerRules(t *testing.T) {
	good := Answers{Locale: "en_US.UTF-8", Keymap: "us", Timezone: "America/Chicago",
		Target: "/dev/nvme0n1", Hostname: "aurade-vm", Username: "cam", Encrypt: "no",
		Filesystem: "btrfs", Swap: "zram"}
	if err := good.Validate(); err != nil {
		t.Fatalf("good answers refused: %v", err)
	}
	bad := []Answers{
		{Hostname: "localhost"}, {Hostname: "LocalHost"}, {Hostname: "-x"}, {Hostname: "a_b"},
		{Hostname: strings.Repeat("a", 64)},
		{Username: "Cam"}, {Username: "root"}, {Username: "systemd-foo"}, {Username: "9lives"},
		{Encrypt: "maybe"}, {Filesystem: "zfs"}, {Swap: "big"},
		{Timezone: "Chicago"}, {Locale: "english"}, {Target: "nvme0n1"},
	}
	for _, a := range bad {
		if a.Validate() == nil {
			t.Errorf("accepted %+v", a)
		}
	}
}

func TestFileHasNoEmptyLinesOrSecrets(t *testing.T) {
	f := string(Answers{Hostname: "box", Username: "me"}.File())
	if !strings.Contains(f, "hostname=box\n") || !strings.Contains(f, "username=me\n") {
		t.Fatalf("missing answers:\n%s", f)
	}
	if strings.Contains(f, "=\n") || strings.Contains(f, "password") {
		t.Fatalf("empty or secret line:\n%s", f)
	}
}

func TestKeymapForLocale(t *testing.T) {
	for in, want := range map[string]string{"de_DE.UTF-8": "de", "en_US.UTF-8": "us", "fr_CA.UTF-8": "us", "C.UTF-8": "us"} {
		if got := KeymapForLocale(in); got != want {
			t.Errorf("%s: got %s want %s", in, got, want)
		}
	}
}

// The image is read back with the same tool that makes ISOs for the release,
// when it is installed, so the layout is checked by something that is not
// this code.
func TestISOReadsBack(t *testing.T) {
	content := Answers{Hostname: "isotest", Username: "me"}.File()
	img := BuildISO(time.Date(2026, 10, 8, 12, 0, 0, 0, time.UTC), File{"answers.txt", content})
	if len(img)%sector != 0 || !bytes.Equal(img[16*sector+1:16*sector+6], []byte("CD001")) {
		t.Fatal("not an ISO 9660 image")
	}
	if !bytes.Contains(img[16*sector:17*sector], []byte(Label)) {
		t.Fatal("label missing")
	}
	xorriso, err := exec.LookPath("xorriso")
	if err != nil {
		t.Skip("xorriso not installed")
	}
	dir := t.TempDir()
	iso := filepath.Join(dir, "a.iso")
	if err := os.WriteFile(iso, img, 0o600); err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "out.txt")
	cmd := exec.Command(xorriso, "-osirrox", "on", "-indev", iso, "-extract", "/ANSWERS.TXT", out)
	if b, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("xorriso: %v\n%s", err, b)
	}
	got, _ := os.ReadFile(out)
	if !bytes.Equal(got, content) {
		t.Fatalf("read back %q, want %q", got, content)
	}
	b, _ := exec.Command(xorriso, "-indev", iso, "-pvd_info").CombinedOutput()
	if !bytes.Contains(b, []byte("Volume Id    : "+Label)) {
		t.Fatalf("volume id not %s:\n%s", Label, b)
	}
}

// Vectors made with `openssl passwd -6 -salt SALT PASSWORD`, which is what
// the installer hashes a typed password with.
func TestSHA512CryptMatchesOpenSSL(t *testing.T) {
	b, err := os.ReadFile("testdata/crypt.txt")
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range strings.Split(strings.TrimSpace(string(b)), "\n") {
		f := strings.SplitN(line, "|", 3)
		if got := sha512Crypt([]byte(f[0]), []byte(f[1])); got != f[2] {
			t.Errorf("%q %q: got %s want %s", f[0], f[1], got, f[2])
		}
	}
	h, err := HashPassword("pw")
	if err != nil || !strings.HasPrefix(h, "$6$") || len(h) != 3+16+1+86 {
		t.Fatalf("%q %v", h, err)
	}
	if h2, _ := HashPassword("pw"); h2 == h {
		t.Fatal("two hashes of one password share a salt")
	}
}
