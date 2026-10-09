// aurade-vm makes a virtual machine, downloads and checks AuraDE, and starts
// its installer, with the questions already answered if you like.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"

	"github.com/Cam396/aurade/vm/aurade-vm/internal/answers"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/host"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/hv"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/plan"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/tui"
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
		dir        = flag.String("dir", defaultDir(), "folder for the ISO and the VMs")
		tag        = flag.String("release", os.Getenv("AURADE_VM_VERSION"), "a release tag such as v1.1.2 (default: the latest)")
		iso        = flag.String("iso", "", "use this AuraDE ISO instead of downloading one (it is not checked)")
		yes        = flag.Bool("yes", false, "do not ask; make and start the VM from the flags and defaults")
		hypervisor = flag.String("hypervisor", "vmware", "with --yes: which hypervisor: vmware, qemu, libvirt, virtualbox, hyperv or parallels")
		mode       = flag.String("mode", "guided", "with --yes: guided (answers filled in) or plain")
		name       = flag.String("name", "aurade", "with --yes: the VM's name")
		memory     = flag.Int("memory", 6144, "with --yes: MiB of memory, 4096 at least")
		cpus       = flag.Int("cpus", 4, "with --yes: virtual processors")
		disk       = flag.Int("disk", 40, "with --yes: disk size in GB, 30 at least")
		accel      = flag.Bool("3d", true, "with --yes: 3D graphics")
		hostname   = flag.String("hostname", "aurade-vm", "with --yes, guided: the computer name")
		username   = flag.String("username", "", "with --yes, guided: your username")
		locale     = flag.String("locale", h.Locale, "with --yes, guided: language and region")
		keymap     = flag.String("keymap", answers.KeymapForLocale(h.Locale), "with --yes, guided: keyboard layout")
		timezone   = flag.String("timezone", h.Timezone, "with --yes, guided: time zone")
		encrypt    = flag.String("encrypt", "no", "with --yes, guided: encrypt the disk (yes or no)")
		filesystem = flag.String("filesystem", "btrfs", "with --yes, guided: btrfs, ext4 or xfs")
		showVer    = flag.Bool("version", false, "print the version and exit")
		listHV     = flag.Bool("hypervisors", false, "list the hypervisors on this computer and exit")
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

	if !*yes {
		return tui.Run(tui.Options{BaseDir: baseDir, Tag: *tag, LocalISO: *iso, Version: version})
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
	case plan.Plain:
	default:
		return fmt.Errorf("--mode is guided or plain, not %q", *mode)
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
