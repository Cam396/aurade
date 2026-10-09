package archhost

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ProtonMail/go-crypto/openpgp"
	"github.com/ProtonMail/go-crypto/openpgp/armor"
)

func TestIsArch(t *testing.T) {
	for s, want := range map[string]bool{
		"NAME=\"Arch Linux\"\nID=arch\n": true,
		"ID=\"arch\"\n":                  true,
		"ID=endeavouros\nID_LIKE=arch\n": false,
		"ID=manjaro\nID_LIKE=arch\n":     false,
		"ID=ubuntu\n":                    false,
		"":                               false,
	} {
		if got := IsArch(s); got != want {
			t.Errorf("%q: got %v", s, got)
		}
	}
}

func TestStepsFollowTheDoc(t *testing.T) {
	join := func(st []Step) string {
		var b strings.Builder
		for _, s := range st {
			b.WriteString(strings.Join(s.Args, " ") + "\n")
		}
		return b.String()
	}
	got := join(Steps("/tmp/k.gpg", "[core]\nInclude = x\n", false, false))
	want := "sudo pacman-key --add /tmp/k.gpg\n" +
		"sudo pacman-key --lsign-key BC390DCF360B2184DBBF008B8B2AB2EFE667CB69\n" +
		"sudo tee -a /etc/pacman.conf\n" +
		"sudo pacman -Syu aurade\n"
	if got != want {
		t.Fatalf("got\n%swant\n%s", got, want)
	}
	// Already there: the repository is not added twice. As root, no sudo.
	got = join(Steps("/tmp/k.gpg", "[core]\n\n  [aurade]  \nServer = x\n", true, true))
	if strings.Contains(got, "tee") || strings.Contains(got, "sudo") || !strings.Contains(got, "pacman -Syu aurade --noconfirm") {
		t.Fatalf("got\n%s", got)
	}
	st := Steps("k", "", false, false)[2]
	if st.Stdin != "\n[aurade]\nServer = https://github.com/Cam396/aurade/releases/download/repo-x86_64\n" {
		t.Fatalf("pacman.conf lines %q", st.Stdin)
	}
}

// A key that is not the release key is refused before pacman sees it, and a
// dry run with the real one changes nothing.
func TestRunChecksTheKey(t *testing.T) {
	ent, _ := openpgp.NewEntity("someone else", "", "x@example.invalid", nil)
	var wrong bytes.Buffer
	w, _ := armor.Encode(&wrong, openpgp.PublicKeyType, nil)
	ent.Serialize(w)
	w.Close()
	real, err := os.ReadFile("../../../../pins/aurade-release.gpg")
	if err != nil {
		t.Skip("the release key is not beside this checkout")
	}
	serve := wrong.Bytes()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write(serve) }))
	defer srv.Close()
	conf := filepath.Join(t.TempDir(), "pacman.conf")
	os.WriteFile(conf, []byte("[core]\n"), 0o644)
	var out bytes.Buffer
	o := Options{DryRun: true, Out: &out, HTTP: srv.Client(), KeyURL: srv.URL, PacmanConf: conf}
	if err := Run(context.Background(), o); err == nil || !strings.Contains(err.Error(), "not the AuraDE release key") {
		t.Fatalf("a foreign key was accepted: %v", err)
	}
	serve = real
	out.Reset()
	if err := Run(context.Background(), o); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"It is the release key", "pacman-key --lsign-key", "tee -a /etc/pacman.conf", "pacman -Syu aurade", "Nothing was changed"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("dry run output lacks %q:\n%s", want, out.String())
		}
	}
	if b, _ := os.ReadFile(conf); string(b) != "[core]\n" {
		t.Fatal("a dry run changed pacman.conf")
	}
}
