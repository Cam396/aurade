// aurade-vm makes a virtual machine, downloads and checks AuraDE, and starts
// its installer, with the questions already answered if you like.
package main

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strings"

	"github.com/Cam396/aurade/vm/aurade-vm/internal/answers"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/archhost"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/host"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/hv"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/plan"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/tui"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/update"
)

// version is set at build time with -ldflags "-X main.version=...".
var version = "dev"

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "aurade-vm:", err)
		os.Exit(1)
	}
}

func defaultDir() string {
	if d := os.Getenv("AURADE_VM_DIR"); d != "" {
		return d
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "AuraDE"
	}
	return filepath.Join(home, "AuraDE")
}

func run() error {
	h := host.Detect()
	var (
		dir          = flag.String("dir", defaultDir(), "folder for the ISO and the VMs")
		tag          = flag.String("release", os.Getenv("AURADE_VM_VERSION"), "a release tag such as v1.1.2 (default: the latest)")
		iso          = flag.String("iso", "", "use this AuraDE ISO instead of downloading one (it is not checked)")
		yes          = flag.Bool("yes", false, "do not ask; make and start the VM from the flags and defaults")
		hypervisor   = flag.String("hypervisor", "vmware", "with --yes: which hypervisor: vmware, qemu, libvirt, virtualbox, hyperv, parallels or utm")
		mode         = flag.String("mode", "guided", "with --yes: guided (answers filled in), express (installs itself) or plain")
		pwStdin      = flag.Bool("password-stdin", false, "with --yes and express: read the account password from the first line of standard input")
		name         = flag.String("name", "aurade", "with --yes: the VM's name")
		memory       = flag.Int("memory", 6144, "with --yes: MiB of memory, 4096 at least")
		cpus         = flag.Int("cpus", 4, "with --yes: virtual processors")
		disk         = flag.Int("disk", 40, "with --yes: disk size in GB, 30 at least")
		accel        = flag.Bool("3d", true, "with --yes: 3D graphics")
		hostname     = flag.String("hostname", "aurade-vm", "with --yes, guided: the computer name")
		username     = flag.String("username", "", "with --yes, guided: your username")
		locale       = flag.String("locale", h.Locale, "with --yes, guided: language and region")
		keymap       = flag.String("keymap", answers.KeymapForLocale(h.Locale), "with --yes, guided: keyboard layout")
		timezone     = flag.String("timezone", h.Timezone, "with --yes, guided: time zone")
		encrypt      = flag.String("encrypt", "no", "with --yes, guided: encrypt the disk (yes or no)")
		filesystem   = flag.String("filesystem", "btrfs", "with --yes, guided: btrfs, ext4 or xfs")
		scale        = flag.String("display-scale", "auto", "with --yes, guided: display size, auto, 100, 125, 150, 175 or 200")
		profile      = flag.String("features", "auto", "with --yes, guided: auto, standard, plus, advanced_plus or advanced_plus_ai")
		apps         = flag.String("apps", "", "with --yes, guided: extra apps, a comma list of firefox, vscode, flatpak, waydroid and devtools")
		snapshots    = flag.String("update-snapshots", "", "with --yes, guided: a snapshot before every update, yes or no (default yes on btrfs)")
		showVer      = flag.Bool("version", false, "print the version and exit")
		doUpdate     = flag.Bool("update", false, "replace this program with the newest published aurade-vm, checked as the installers check it, and exit")
		listHV       = flag.Bool("hypervisors", false, "list the hypervisors on this computer and exit")
		existingArch = flag.Bool("existing-arch", false, "install AuraDE on this Arch Linux computer, beside its desktop, instead of in a VM")
		dryRun       = flag.Bool("dry-run", false, "with --existing-arch: print the commands and change nothing")
	)
	flag.Usage = func() {
		fmt.Fprintf(flag.CommandLine.Output(), "aurade-vm %s: try AuraDE in a virtual machine.\n\n", version)
		fmt.Fprintf(flag.CommandLine.Output(), "Run it with no options for the interactive setup. Options:\n\n")
		flag.PrintDefaults()
	}
	flag.Parse()
	if *showVer {
		fmt.Println("aurade-vm", version)
		return nil
	}
	exe, exeErr := os.Executable()
	if exeErr == nil {
		if resolved, err := filepath.EvalSymlinks(exe); err == nil {
			exe = resolved
		}
		update.Cleanup(exe)
	}
	if *doUpdate {
		if exeErr != nil {
			return fmt.Errorf("could not find this program's file: %w", exeErr)
		}
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
		defer stop()
		src := update.Default()
		pin, err := src.Latest(ctx)
		if err != nil {
			return err
		}
		if !update.Newer(pin.Version, version) {
			fmt.Printf("aurade-vm %s is the newest (published: %s)\n", version, pin.Version)
			return nil
		}
		r, err := src.Apply(ctx, version, pin, exe)
		if err != nil {
			return err
		}
		how := "its published SHA-256"
		if r.Signed {
			how += " and the release key's signature"
		}
		fmt.Printf("aurade-vm %s -> %s, checked against %s\n", r.From, r.To, how)
		return nil
	}
	if *listHV {
		for _, b := range hv.All() {
			d := b.Detect(context.Background())
			switch {
			case d.Foreign:
			case d.Available:
				fmt.Printf("%-12s ready      %s %s\n", b.ID(), b.Name(), d.Version)
			default:
				fmt.Printf("%-12s not ready  %s: %s\n", b.ID(), b.Name(), d.Why)
			}
		}
		return nil
	}
	if *iso != "" {
		abs, err := filepath.Abs(*iso)
		if err != nil {
			return err
		}
		*iso = abs
	}
	baseDir, err := filepath.Abs(*dir)
	if err != nil {
		return err
	}

	if !*yes && !*existingArch {
		res, err := tui.Run(tui.Options{BaseDir: baseDir, Tag: *tag, LocalISO: *iso, Version: version,
			Arch: archhost.Detect(),
			Newest: func(ctx context.Context) string {
				if pin, err := update.Default().Latest(ctx); err == nil && update.Newer(pin.Version, version) && pin.SHA256 != "" {
					return pin.Version
				}
				return ""
			}})
		if err != nil || !res.ExistingArch {
			return err
		}
		*existingArch = true
	}

	if *existingArch {
		if !archhost.Detect() {
			return fmt.Errorf("--existing-arch is for a computer running Arch Linux itself")
		}
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
		defer stop()
		return archhost.Run(ctx, archhost.Options{DryRun: *dryRun, NoConfirm: *yes})
	}

	if *memory < 4096 {
		return fmt.Errorf("AuraDE needs at least 4096 MiB of memory in the VM")
	}
	if *disk < 30 {
		return fmt.Errorf("AuraDE needs a disk of at least 30 GB")
	}
	// A VM that already exists is started with whatever made it.
	for _, r := range hv.Existing(baseDir) {
		if r.Spec.Name == *name {
			*hypervisor = r.Backend
		}
	}
	b, err := hv.Find(*hypervisor)
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if d := b.Detect(ctx); !d.Available {
		return fmt.Errorf("%s: %s", b.Name(), d.Why)
	}
	p := &plan.Plan{
		Backend:  b,
		Mode:     plan.Mode(*mode),
		BaseDir:  baseDir,
		Tag:      *tag,
		LocalISO: *iso,
		Spec:     hv.Spec{Name: *name, MemoryMB: *memory, CPUs: *cpus, DiskGB: *disk, Accel3D: *accel},
	}
	switch p.Mode {
	case plan.Guided:
		p.Answers = answers.Answers{Locale: *locale, Keymap: *keymap, Timezone: *timezone,
			Hostname: *hostname, Username: *username, Encrypt: *encrypt, Filesystem: *filesystem}
	case plan.Express:
		p.Answers = answers.Answers{Locale: *locale, Keymap: *keymap, Timezone: *timezone,
			Hostname: *hostname, Username: *username, Encrypt: "no", Filesystem: *filesystem}
		if !*pwStdin {
			return fmt.Errorf("an express install needs the password: pass it on standard input with --password-stdin")
		}
		line, err := bufio.NewReader(os.Stdin).ReadString('\n')
		if err != nil && line == "" {
			return fmt.Errorf("no password on standard input")
		}
		line = strings.TrimRight(line, "\r\n")
		if p.PasswordHash, err = answers.HashPassword(line); err != nil {
			return err
		}
	case plan.Plain:
	default:
		return fmt.Errorf("--mode is guided, express or plain, not %q", *mode)
	}
	if p.Mode != plan.Plain {
		p.Answers.DisplayScale, p.Answers.Profile, p.Answers.Apps = *scale, *profile, *apps
		p.Answers.AutoSnapshots = *snapshots
		if p.Answers.AutoSnapshots == "" {
			p.Answers.AutoSnapshots = "no"
			if p.Answers.Filesystem == "btrfs" {
				p.Answers.AutoSnapshots = "yes"
			}
		}
	}
	lastPct := -1
	return p.Run(ctx, func(e plan.Event) {
		switch {
		case e.Step != "":
			fmt.Println("==>", e.Step)
			lastPct = -1
		case e.Log != "":
			fmt.Println("   ", e.Log)
		case e.Total > 0:
			if pct := int(e.Done * 100 / e.Total); pct/5 != lastPct/5 {
				fmt.Printf("    %3d%%  %d / %d MB\n", pct, e.Done/1e6, e.Total/1e6)
				lastPct = pct
			}
		}
	})
}
