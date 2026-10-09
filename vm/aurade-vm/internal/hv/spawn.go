package hv

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

// spawn starts a program in the background, its output going to a log in
// dir, and returns once it has either kept running for a moment or exited.
// An exit in that moment is a failure, reported with the end of the log.
func spawn(dir, logName, name string, args ...string) error {
	logPath := filepath.Join(dir, logName)
	logf, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	defer logf.Close()
	cmd := exec.Command(name, args...)
	cmd.Stdout, cmd.Stderr, cmd.Stdin = logf, logf, nil
	detach(cmd)
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("could not start %s: %w", baseName(name), err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		b, _ := os.ReadFile(logPath)
		tail := string(b)
		if len(tail) > 600 {
			tail = "..." + tail[len(tail)-600:]
		}
		if err == nil {
			err = fmt.Errorf("exited straight away")
		}
		return fmt.Errorf("%s stopped as it started (%v): %s", baseName(name), err, tail)
	case <-time.After(3 * time.Second):
		_ = cmd.Process.Release()
		return nil
	}
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}
