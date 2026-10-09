package update

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/ProtonMail/go-crypto/openpgp"
	"github.com/ProtonMail/go-crypto/openpgp/armor"
)

const shPins = `# >>> pins (written by build.sh; do not edit by hand)
VERSION=0.3.1
PIN_linux_amd64=1111111111111111111111111111111111111111111111111111111111111111
PIN_linux_arm64=
PIN_darwin_amd64=2222222222222222222222222222222222222222222222222222222222222222
PIN_darwin_arm64=
# <<< pins
`

const psPins = `# >>> pins (written by build.sh; do not edit by hand)
$Version = '0.3.1'
$Pins = @{
  'windows-amd64' = '3333333333333333333333333333333333333333333333333333333333333333'
  'windows-arm64' = ''
}
# <<< pins
`

func TestParsePins(t *testing.T) {
	for _, c := range []struct {
		script, goos, goarch, sha string
	}{
		{shPins, "linux", "amd64", strings.Repeat("1", 64)},
		{shPins, "linux", "arm64", ""},
		{shPins, "darwin", "amd64", strings.Repeat("2", 64)},
		{psPins, "windows", "amd64", strings.Repeat("3", 64)},
		{psPins, "windows", "arm64", ""},
	} {
		p, err := ParsePins([]byte(c.script), c.goos, c.goarch)
		if err != nil || p.Version != "0.3.1" || p.SHA256 != c.sha {
			t.Errorf("%s/%s: %+v %v", c.goos, c.goarch, p, err)
		}
	}
	if _, err := ParsePins([]byte("nothing here"), "linux", "amd64"); err == nil {
		t.Error("a script with no pins was read")
	}
	if _, err := ParsePins([]byte("VERSION=1.0.0\nPIN_linux_amd64=xyz\n"), "linux", "amd64"); err != nil {
		// xyz does not match the pattern, so it reads as no pin at all.
		t.Error(err)
	}
}

func TestNewer(t *testing.T) {
	for _, c := range []struct {
		a, b string
		want bool
	}{
		{"0.3.1", "0.3.0", true}, {"0.10.0", "0.9.9", true}, {"1.0.0", "0.99.99", true},
		{"0.3.0", "0.3.0", false}, {"0.2.9", "0.3.0", false},
		{"0.3.1", "dev", false}, {"dev", "0.3.0", false}, {"0.3", "0.2.0", false},
	} {
		if got := Newer(c.a, c.b); got != c.want {
			t.Errorf("Newer(%q, %q) = %v", c.a, c.b, got)
		}
	}
}

// A whole update against a fake release: a matching build replaces the
// program and the old one is kept aside; a tampered one is refused and the
// program is left as it was.
func TestApply(t *testing.T) {
	good := []byte("the new aurade-vm")
	sum := sha256.Sum256(good)
	pin := Pin{Version: "0.3.1", SHA256: hex.EncodeToString(sum[:])}
	name := BuildName("0.3.1", runtime.GOOS, runtime.GOARCH)
	serve := good
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/releases/aurade-vm-v0.3.1/"+name {
			w.Write(serve)
			return
		}
		http.NotFound(w, r)
	}))
	defer srv.Close()
	s := Sources{Scripts: srv.URL + "/scripts", Releases: srv.URL + "/releases", Key: srv.URL + "/key", HTTP: srv.Client()}

	dir := t.TempDir()
	exe := filepath.Join(dir, "aurade-vm")
	os.WriteFile(exe, []byte("the old aurade-vm"), 0o755)

	serve = []byte("something else")
	if _, err := s.Apply(context.Background(), "0.3.0", pin, exe); err == nil || !strings.Contains(err.Error(), "does not match") {
		t.Fatalf("a tampered build was accepted: %v", err)
	}
	if b, _ := os.ReadFile(exe); string(b) != "the old aurade-vm" {
		t.Fatal("a refused update changed the program")
	}

	serve = good
	r, err := s.Apply(context.Background(), "0.3.0", pin, exe)
	if err != nil {
		t.Fatal(err)
	}
	if r.Signed || r.To != "0.3.1" {
		t.Fatalf("%+v", r)
	}
	if b, _ := os.ReadFile(exe); string(b) != string(good) {
		t.Fatal("the program was not replaced")
	}
	if b, _ := os.ReadFile(exe + ".old"); string(b) != "the old aurade-vm" {
		t.Fatal("the old program was not kept aside")
	}
	if fi, _ := os.Stat(exe); fi.Mode().Perm()&0o100 == 0 {
		t.Fatal("the new program cannot be run")
	}
	Cleanup(exe)
	if _, err := os.Stat(exe + ".old"); !os.IsNotExist(err) {
		t.Fatal("cleanup left the old program")
	}

	if _, err := s.Apply(context.Background(), "0.3.0", Pin{Version: "0.3.1"}, exe); err == nil {
		t.Fatal("an update with no published build for this computer went ahead")
	}
}

// Checksums signed by some other key are refused, even when the build matches
// its pin: a release that claims a signature has to carry the real one.
func TestApplyRefusesAForeignSignature(t *testing.T) {
	good := []byte("the new aurade-vm")
	sum := sha256.Sum256(good)
	sha := hex.EncodeToString(sum[:])
	name := BuildName("0.3.1", runtime.GOOS, runtime.GOARCH)
	sums := []byte(sha + "  " + name + "\n")
	ent, err := openpgp.NewEntity("someone else", "", "x@example.invalid", nil)
	if err != nil {
		t.Fatal(err)
	}
	var sig, key bytes.Buffer
	if err := openpgp.DetachSign(&sig, ent, bytes.NewReader(sums), nil); err != nil {
		t.Fatal(err)
	}
	w, _ := armor.Encode(&key, openpgp.PublicKeyType, nil)
	ent.Serialize(w)
	w.Close()
	files := map[string][]byte{
		"/releases/aurade-vm-v0.3.1/" + name:        good,
		"/releases/aurade-vm-v0.3.1/SHA256SUMS":     sums,
		"/releases/aurade-vm-v0.3.1/SHA256SUMS.sig": sig.Bytes(),
		"/key": key.Bytes(),
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if b, ok := files[r.URL.Path]; ok {
			w.Write(b)
			return
		}
		http.NotFound(w, r)
	}))
	defer srv.Close()
	s := Sources{Scripts: srv.URL, Releases: srv.URL + "/releases", Key: srv.URL + "/key", HTTP: srv.Client()}
	exe := filepath.Join(t.TempDir(), "aurade-vm")
	os.WriteFile(exe, []byte("old"), 0o755)
	_, err = s.Apply(context.Background(), "0.3.0", Pin{Version: "0.3.1", SHA256: sha}, exe)
	if err == nil || !strings.Contains(err.Error(), "not signed by the AuraDE release key") {
		t.Fatalf("a foreign signature was accepted: %v", err)
	}
	if b, _ := os.ReadFile(exe); string(b) != "old" {
		t.Fatal("a refused update changed the program")
	}
}
