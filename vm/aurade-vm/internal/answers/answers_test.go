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

func TestDesktopAnswers(t *testing.T) {
	good := Answers{Filesystem: "btrfs", Profile: "plus", DisplayScale: "125",
		Apps: "firefox,flatpak", AutoSnapshots: "yes"}
	if err := good.Validate(); err != nil {
		t.Fatalf("good answers refused: %v", err)
	}
	f := string(good.File())
	for _, line := range []string{"profile=plus\n", "display_scale=125\n", "apps=firefox,flatpak\n", "auto_snapshots=yes\n"} {
		if !strings.Contains(f, line) {
			t.Errorf("missing %q in:\n%s", line, f)
		}
	}
	bad := []Answers{
		{Profile: "everything"}, {DisplayScale: "130"}, {Apps: "steam"}, {Apps: "firefox,"},
		{Apps: ",firefox"}, {Apps: "firefox,,vscode"}, {AutoSnapshots: "maybe"},
		{Filesystem: "ext4", AutoSnapshots: "yes"},
	}
	for _, a := range bad {
		if a.Validate() == nil {
			t.Errorf("accepted %+v", a)
		}
	}
}

// The installer checks the answers again, and anything it refuses is asked in
// the VM as if it had never been answered. So the two sets of rules have to
// agree, and the installer's are run here to make sure they do.
func TestDesktopRulesAgreeWithTheInstaller(t *testing.T) {
	lib, err := filepath.Abs("../../../../installer/lib/aurade-validate.sh")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(lib); err != nil {
		t.Skip("the installer is not beside this checkout")
	}
	if _, err := exec.LookPath("bash"); err != nil {
		t.Skip("no bash")
	}
	installer := func(fn, v string) bool {
		return exec.Command("bash", "-c", `. "$1"; "$2" "$3"`, "_", lib, fn, v).Run() == nil
	}
	for _, v := range []string{"none", "firefox", "firefox,vscode,flatpak,waydroid,devtools", "steam", "firefox,", ",firefox", "a,,b", "firefox,firefox"} {
		mine := ValidApps(v) == nil
		if theirs := installer("aurade_valid_apps", v); mine != theirs {
			t.Errorf("apps %q: aurade-vm says %v, the installer says %v", v, mine, theirs)
		}
	}
	for _, v := range []string{"auto", "standard", "plus", "advanced_plus", "advanced_plus_ai", "max"} {
		mine := Answers{Profile: v}.Validate() == nil
		if theirs := installer("aurade_valid_feature_profile", v); mine != theirs {
			t.Errorf("profile %q: aurade-vm says %v, the installer says %v", v, mine, theirs)
		}
	}
	for _, v := range []string{"auto", "100", "125", "150", "175", "200", "300", "1.5"} {
		mine := Answers{DisplayScale: v}.Validate() == nil
		if theirs := installer("aurade_valid_display_scale", v); mine != theirs {
			t.Errorf("display size %q: aurade-vm says %v, the installer says %v", v, mine, theirs)
		}
	}
	for _, n := range AppNames {
		if !installer("aurade_valid_apps", n.ID) {
			t.Errorf("the installer does not know the app %s", n.ID)
		}
	}
}

// The wallpapers offered are the installer's list, which test-questions.sh
// holds to the package, and their titles are the manifest's.
func TestWallpapersAgreeWithTheInstaller(t *testing.T) {
	lib, _ := filepath.Abs("../../../../installer/lib/aurade-validate.sh")
	manifest, err := os.ReadFile("../../../../aurade-wallpapers/manifest.tsv")
	if _, serr := os.Stat(lib); serr != nil || err != nil {
		t.Skip("the installer is not beside this checkout")
	}
	out, err := exec.Command("bash", "-c", `. "$1"; printf '%s\n' "${AURADE_DESKTOP_WALLPAPERS[@]}"`, "_", lib).Output()
	if err != nil {
		t.Fatal(err)
	}
	var mine []string
	for _, w := range Wallpapers {
		mine = append(mine, w.ID)
		if !strings.Contains(string(manifest), w.ID+".png\t"+w.Title+"\t") {
			t.Errorf("%s is not titled %q in the manifest", w.ID, w.Title)
		}
	}
	if got := strings.Fields(string(out)); strings.Join(got, " ") != strings.Join(mine, " ") {
		t.Errorf("installer offers %v\naurade-vm offers %v", got, mine)
	}
	if (Answers{Wallpaper: "quiet-rainleaves"}).Validate() != nil || (Answers{Wallpaper: "../x"}).Validate() == nil {
		t.Error("wallpaper validation")
	}
	if !strings.Contains(string(Answers{Wallpaper: "wild-lava"}.File()), "wallpaper=wild-lava\n") {
		t.Error("the wallpaper is not in the answers file")
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
