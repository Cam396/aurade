package hv

import (
	"context"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
	"time"
)

// vmrun starting VMware's window leaves that window running with vmrun's
// output. This is the same shape: a command that returns at once and leaves a
// child holding its output. It must not wait for the child.
func TestRunLoggedDoesNotWaitForWhatTheCommandLeaves(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("uses sh")
	}
	if _, err := exec.LookPath("sh"); err != nil {
		t.Skip("no sh")
	}
	start := time.Now()
	out, err := runLogged(context.Background(), filepath.Join(t.TempDir(), "x.log"), "sh", "-c", "sleep 5 & echo started")
	if err != nil || out != "started" {
		t.Fatalf("%q %v", out, err)
	}
	if d := time.Since(start); d > 3*time.Second {
		t.Fatalf("waited %v for a child the command left behind", d)
	}
	if _, err := runLogged(context.Background(), filepath.Join(t.TempDir(), "y.log"), "sh", "-c", "echo nope >&2; exit 3"); err == nil || err.Error() != "sh -c echo nope >&2; exit 3: nope" {
		t.Fatalf("error %v", err)
	}
}
