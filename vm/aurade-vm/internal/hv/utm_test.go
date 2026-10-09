package hv

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestUTMExplainsWhatIsMissing(t *testing.T) {
	for _, c := range []struct {
		u       *UTM
		want    string
		foreign bool
	}{
		{&UTM{goos: "linux"}, "Mac", true},
		{&UTM{goos: "windows"}, "Mac", true},
		{&UTM{goos: "darwin", goarch: "arm64"}, "Apple Silicon", false},
		{&UTM{goos: "darwin", goarch: "amd64", app: "/nonexistent/UTM.app"}, "not installed", false},
	} {
		d := c.u.Detect(context.Background())
		if d.Available || d.Foreign != c.foreign || !strings.Contains(d.Why, c.want) {
			t.Errorf("%+v: %+v", c.u, d)
		}
	}
}

func TestUTMScriptableFrom42(t *testing.T) {
	for v, want := range map[string]bool{"4.2": true, "4.2.1": true, "4.6.4": true, "5.0": true, "4.1.6": false, "3.2.4": false, "4": false, "": false, "x": false, "4.10": true} {
		if got := utmScriptable(v); got != want {
			t.Errorf("%q: got %v want %v", v, got, want)
		}
	}
}

// The script gets every value as an argument; none of them is spliced into
// the script text, so a name with quotes in it is only a name.
func TestUTMCreateAndFinish(t *testing.T) {
	dir := t.TempDir()
	var calls [][]string
	var sources []string
	u := &UTM{goos: "darwin", goarch: "amd64", app: "/nonexistent/UTM.app",
		script: func(_ context.Context, src string, args ...string) (string, error) {
			sources = append(sources, src)
			calls = append(calls, args)
			return "ok", nil
		}}
	s := Spec{Name: `my "vm"`, Dir: dir, ISO: "/isos/aurade.iso", AnswersISO: filepath.Join(dir, AnswersFile), MemoryMB: 6144, CPUs: 4, DiskGB: 40}
	if err := u.Create(context.Background(), s, nil); err != nil {
		t.Fatal(err)
	}
	want := []string{`my "vm"`, "6144", "4", "40960", "/isos/aurade.iso", filepath.Join(dir, AnswersFile)}
	if strings.Join(calls[0], "|") != strings.Join(want, "|") {
		t.Fatalf("create args %q", calls[0])
	}
	if strings.Contains(sources[0], "my ") || !strings.Contains(sources[0], `architecture:"x86_64"`) || !strings.Contains(sources[0], "uefi:true") {
		t.Fatalf("create script:\n%s", sources[0])
	}
	// No answers disk: the script is told so with an empty argument.
	s.AnswersISO = ""
	if u.CreateArgs(s)[5] != "" {
		t.Fatal("an answers drive with no answers")
	}
	// Finish does nothing without the file, and detaches and deletes it
	// when it is there.
	if err := u.Finish(context.Background(), s); err != nil || len(calls) != 1 {
		t.Fatalf("finish without answers: %v, %d calls", err, len(calls))
	}
	os.WriteFile(filepath.Join(dir, AnswersFile), []byte("x"), 0o600)
	if err := u.Finish(context.Background(), s); err != nil {
		t.Fatal(err)
	}
	if len(calls) != 2 || calls[1][0] != s.Name || calls[1][1] != AnswersFile || fileExists(filepath.Join(dir, AnswersFile)) {
		t.Fatalf("finish: %q", calls)
	}
}
