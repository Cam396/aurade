package release

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// testdata holds a real release's SHA256SUMS and its signature by the release
// key, standing in for an ISO: same key, same signature format, small file.
func fakeGitHub(t *testing.T, iso, sig []byte) *httptest.Server {
	t.Helper()
	key, err := os.ReadFile("testdata/aurade-repository.asc")
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(iso)
	files := map[string][]byte{
		"aurade-v9.9.9-x86_64.iso":        iso,
		"aurade-v9.9.9-x86_64.iso.sha256": []byte(hex.EncodeToString(sum[:]) + "  aurade-v9.9.9-x86_64.iso\n"),
		"aurade-v9.9.9-x86_64.iso.sig":    sig,
		"aurade-repository.asc":           key,
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/"+Repo+"/releases/latest", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/"+Repo+"/releases/tag/v9.9.9", http.StatusFound)
	})
	mux.HandleFunc("/"+Repo+"/releases/tag/v9.9.9", func(w http.ResponseWriter, r *http.Request) {})
	mux.HandleFunc("/"+Repo+"/releases/download/v9.9.9/", func(w http.ResponseWriter, r *http.Request) {
		b, ok := files[filepath.Base(r.URL.Path)]
		if !ok {
			http.NotFound(w, r)
			return
		}
		http.ServeContent(w, r, "", fixedTime, strings.NewReader(string(b)))
	})
	return httptest.NewServer(mux)
}

func readTestdata(t *testing.T, name string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestLatestAndFetchVerifies(t *testing.T) {
	srv := fakeGitHub(t, readTestdata(t, "SHA256SUMS"), readTestdata(t, "SHA256SUMS.sig"))
	defer srv.Close()
	c := &Client{HTTP: srv.Client(), Base: srv.URL}
	tag, err := c.Latest(context.Background())
	if err != nil || tag != "v9.9.9" {
		t.Fatalf("latest: %q %v", tag, err)
	}
	dir := t.TempDir()
	var calls int
	iso, v, err := c.Fetch(context.Background(), tag, dir, func(done, total int64) { calls++ })
	if err != nil {
		t.Fatalf("fetch: %v", err)
	}
	if v != VerifiedSignature || calls == 0 {
		t.Fatalf("verified=%s progress calls=%d", v, calls)
	}
	if _, err := os.Stat(iso + ".checked"); err != nil {
		t.Fatal("no stamp after a checked download")
	}
	// A second run trusts the stamp and does not download again.
	srv.Close()
	if _, v2, err := c.Fetch(context.Background(), tag, dir, nil); err != nil || v2 != VerifiedSignature {
		t.Fatalf("second fetch: %v %s", err, v2)
	}
}

func TestTamperedISOIsRefused(t *testing.T) {
	iso := readTestdata(t, "SHA256SUMS")
	iso[0] ^= 1 // the published SHA-256 is of this changed file, the signature is not
	srv := fakeGitHub(t, iso, readTestdata(t, "SHA256SUMS.sig"))
	defer srv.Close()
	c := &Client{HTTP: srv.Client(), Base: srv.URL}
	dir := t.TempDir()
	if _, _, err := c.Fetch(context.Background(), "v9.9.9", dir, nil); err == nil ||
		!strings.Contains(err.Error(), "not signed by the AuraDE release key") {
		t.Fatalf("tampered ISO accepted: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dir, ISOName("v9.9.9"))); err == nil {
		t.Fatal("the refused ISO was left behind")
	}
}

func TestOtherKeyIsRefused(t *testing.T) {
	f := filepath.Join(t.TempDir(), "x")
	os.WriteFile(f, readTestdata(t, "SHA256SUMS"), 0o600)
	err := VerifySignature(f, readTestdata(t, "SHA256SUMS.sig"), []byte("-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n-----END PGP PUBLIC KEY BLOCK-----\n"))
	if err == nil {
		t.Fatal("verified with no usable key")
	}
}

var fixedTime = mustTime()
