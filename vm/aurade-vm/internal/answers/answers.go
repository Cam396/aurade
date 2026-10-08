// Package answers writes the answer file the AuraDE text installer reads with
// --answers, and the small disk that carries it into a virtual machine.
//
// The installer checks every line again as though it had been typed, drops
// anything that does not pass, and never accepts a password from the file. The
// checks here exist so the person filling the questions in hears about a bad
// answer before the machine boots, not to replace the installer's.
package answers

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// Answers is what the person chose. Empty fields are left out of the file, and
// the installer asks those questions as usual.
type Answers struct {
	Locale     string // en_US.UTF-8
	Keymap     string // us
	Timezone   string // America/Chicago
	Target     string // /dev/nvme0n1, the virtual disk as the guest sees it
	Hostname   string
	Username   string
	Encrypt    string // yes or no
	Filesystem string // btrfs, ext4 or xfs
	Swap       string // none, file or zram
}

var (
	hostnameRe = regexp.MustCompile(`^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$`)
	usernameRe = regexp.MustCompile(`^[a-z_][a-z0-9_-]{0,31}$`)
	localeRe   = regexp.MustCompile(`^[A-Za-z]{2,3}(_[A-Z]{2})?(\.UTF-8)?(@[a-z]+)?$|^C\.UTF-8$`)
	keymapRe   = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,40}$`)
	zoneRe     = regexp.MustCompile(`^(UTC|[A-Z][A-Za-z_+-]*(/[A-Za-z0-9_+-]+){1,2})$`)
)

// ValidHostname follows the installer's rule: RFC 1123 label, not localhost.
func ValidHostname(s string) error {
	if s == "" || len(s) > 63 || !hostnameRe.MatchString(s) {
		return fmt.Errorf("Use 1-63 letters, digits or inner hyphens, for example aurade-vm")
	}
	if strings.EqualFold(s, "localhost") {
		return fmt.Errorf("A computer cannot call itself localhost; that name always means this computer")
	}
	return nil
}

// ValidUsername follows the installer's rule, including the names the base
// system already owns.
func ValidUsername(s string) error {
	if !usernameRe.MatchString(s) {
		return fmt.Errorf("Start with a lowercase letter, then lowercase letters, digits, _ or -")
	}
	switch {
	case s == "root", s == "bin", s == "daemon", s == "mail", s == "ftp", s == "http",
		s == "nobody", s == "dbus", s == "polkitd", s == "greeter", strings.HasPrefix(s, "systemd-"):
		return fmt.Errorf("The system already uses %s", s)
	}
	return nil
}

// Validate checks every filled-in field. Only the shape is checked for locale,
// keymap and time zone; whether the live image has them is the installer's
// call, and it drops one it does not have.
func (a Answers) Validate() error {
	if a.Hostname != "" {
		if err := ValidHostname(a.Hostname); err != nil {
			return fmt.Errorf("computer name: %w", err)
		}
	}
	if a.Username != "" {
		if err := ValidUsername(a.Username); err != nil {
			return fmt.Errorf("username: %w", err)
		}
	}
	if a.Locale != "" && !localeRe.MatchString(a.Locale) {
		return fmt.Errorf("language: %q is not a locale such as en_US.UTF-8", a.Locale)
	}
	if a.Keymap != "" && !keymapRe.MatchString(a.Keymap) {
		return fmt.Errorf("keyboard: %q is not a keymap name such as us", a.Keymap)
	}
	if a.Timezone != "" && !zoneRe.MatchString(a.Timezone) {
		return fmt.Errorf("time zone: %q is not a zone such as America/Chicago", a.Timezone)
	}
	if a.Target != "" && !strings.HasPrefix(a.Target, "/dev/") {
		return fmt.Errorf("disk: %q is not a device path", a.Target)
	}
	for name, v := range map[string][]string{
		"encryption": {a.Encrypt, "", "yes", "no"},
		"filesystem": {a.Filesystem, "", "btrfs", "ext4", "xfs"},
		"swap":       {a.Swap, "", "none", "file", "zram"},
	} {
		ok := false
		for _, allowed := range v[1:] {
			ok = ok || v[0] == allowed
		}
		if !ok {
			return fmt.Errorf("%s: %q is not one of %s", name, v[0], strings.Join(v[2:], ", "))
		}
	}
	return nil
}

// File renders the answer file, one question=answer to a line, in the same
// shape the installer's --save-answers writes. It never holds a secret.
func (a Answers) File() []byte {
	fields := map[string]string{
		"locale": a.Locale, "keymap": a.Keymap, "timezone": a.Timezone,
		"target": a.Target, "hostname": a.Hostname, "username": a.Username,
		"encrypt": a.Encrypt, "filesystem": a.Filesystem, "swap": a.Swap,
	}
	keys := make([]string, 0, len(fields))
	for k, v := range fields {
		if v != "" {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	var b strings.Builder
	b.WriteString("# AuraDE answers, prepared by aurade-vm\n")
	b.WriteString("# Passwords and passphrases are deliberately not here.\n")
	for _, k := range keys {
		fmt.Fprintf(&b, "%s=%s\n", k, fields[k])
	}
	return []byte(b.String())
}

// KeymapForLocale is the installer's guess of a console keymap from a locale's
// territory, kept to the territories where the guess is unambiguous.
func KeymapForLocale(locale string) string {
	t := strings.SplitN(locale, ".", 2)[0]
	if i := strings.Index(t, "_"); i >= 0 {
		t = t[i+1:]
	} else {
		return "us"
	}
	m := map[string]string{
		"GB": "uk", "FR": "fr", "DE": "de", "AT": "de", "ES": "es", "IT": "it",
		"PT": "pt-latin1", "BR": "br-abnt2", "RU": "ru", "JP": "jp106", "SE": "sv-latin1",
		"NO": "no", "DK": "dk", "FI": "fi", "NL": "nl", "PL": "pl", "CZ": "cz",
		"HU": "hu", "TR": "trq", "GR": "gr", "UA": "ua", "BE": "be-latin1", "CH": "sg",
	}
	if k, ok := m[t]; ok {
		return k
	}
	return "us"
}
