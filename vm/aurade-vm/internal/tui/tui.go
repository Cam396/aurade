// Package tui is aurade-vm's interactive front end.
package tui

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/charmbracelet/bubbles/progress"
	"github.com/charmbracelet/bubbles/spinner"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/Cam396/aurade/vm/aurade-vm/internal/answers"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/host"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/hv"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/plan"
)

type screen int

const (
	sWelcome screen = iota
	sHypervisor
	sMode
	sQuestions
	sMachine
	sReview
	sRun
	sDone
)

// Options are what the command line already decided.
type Options struct {
	BaseDir  string
	Tag      string
	LocalISO string
	Version  string // this tool's version
}

type detected struct {
	backend hv.Backend
	det     hv.Detection
}

type detectMsg []detected
type eventMsg plan.Event
type finishedMsg struct{ err error }

// Model is the whole TUI.
type Model struct {
	opt      Options
	host     host.Info
	screen   screen
	width    int
	height   int
	existing []hv.Record // VMs already in BaseDir

	welcomeIdx int // 0 = make a new VM, 1.. = start an existing one

	backends   []detected
	detecting  bool
	backendIdx int

	modeIdx int

	questions        form
	questionsExpress bool
	machine          form

	plan     *plan.Plan
	events   chan tea.Msg
	cancel   context.CancelFunc
	steps    []string
	logs     []string
	done     int64
	total    int64
	verified string
	err      error
	spin     spinner.Model
	bar      progress.Model
}

var modes = []struct {
	id    plan.Mode
	title string
	desc  string
	ready bool
}{
	{plan.Guided, "Guided", "Answer the installer's questions here. The installer opens with them filled in, and you confirm the install.", true},
	{plan.Express, "Express", "Answer once here, including your password, and AuraDE installs itself and restarts at the sign-in screen. Nothing is asked in the VM.", true},
	{plan.Plain, "Just the VM", "Make the VM and start the installer. It asks everything itself.", true},
}

// New builds the model.
func New(opt Options) Model {
	h := host.Detect()
	sp := spinner.New()
	sp.Spinner = spinner.Dot
	sp.Style = lipgloss.NewStyle().Foreground(accent)
	m := Model{
		opt:       opt,
		host:      h,
		spin:      sp,
		bar:       progress.New(progress.WithGradient("#A78BFA", "#5EEAD4")),
		detecting: true,
		existing:  hv.Existing(opt.BaseDir),
	}
	m.questions = questionForm(h, false)
	m.machine = machineForm(h, uniqueName(opt.BaseDir))
	return m
}

func uniqueName(base string) string {
	name := "aurade"
	for i := 2; ; i++ {
		if _, err := os.Stat(filepath.Join(base, name)); os.IsNotExist(err) {
			return name
		}
		name = fmt.Sprintf("aurade-%d", i)
	}
}

func questionForm(h host.Info, express bool) form {
	user := h.User
	if answers.ValidUsername(user) != nil {
		user = ""
	}
	f := form{fields: []*field{
		newText("locale", "Language and region", "How dates and numbers look, and the language. From this computer.", h.Locale,
			func(s string) error { return answers.Answers{Locale: s}.Validate() }),
		newText("keymap", "Keyboard layout", "The layout printed on your keyboard, for example us, uk, de or fr.", answers.KeymapForLocale(h.Locale),
			func(s string) error { return answers.Answers{Keymap: s}.Validate() }),
		newText("timezone", "Time zone", "From this computer. For example America/Chicago or Europe/Berlin.", h.Timezone,
			func(s string) error { return answers.Answers{Timezone: s}.Validate() }),
		newText("hostname", "Computer name", "What the VM calls itself on the network.", "aurade-vm", answers.ValidHostname),
		newText("username", "Username", "Your account in AuraDE. The installer asks for its password.", user, answers.ValidUsername),
		newChoice("filesystem", "Filesystem",
			"Btrfs can take snapshots to roll back to. ext4 and xfs cannot.",
			[]string{"btrfs", "ext4", "xfs"}, []string{"Btrfs, with snapshots", "ext4", "xfs"}, "btrfs"),
	}}
	if express {
		// Express needs the password now, since nothing is asked in the
		// VM. Encryption is not offered: its passphrase would have to be
		// typed there.
		pw := newText("password", "Password", "For signing in to AuraDE. Only a scrambled form of it (a hash) goes to the VM.", "", func(v string) error {
			if v == "" {
				return fmt.Errorf("Choose a password")
			}
			return nil
		})
		pw.secret()
		again := newText("password2", "Password again", "The same password, to be sure it was typed as meant.", "", func(v string) error {
			if v != pw.value() {
				return fmt.Errorf("The two passwords are not the same")
			}
			return nil
		})
		again.secret()
		f.fields = append(f.fields[:5], append([]*field{pw, again}, f.fields[5:]...)...)
	} else {
		f.fields = append(f.fields, newChoice("encrypt", "Encrypt the virtual disk",
			"Encryption asks for a passphrase at every start. Most people trying AuraDE in a VM leave it off.",
			[]string{"no", "yes"}, []string{"No", "Yes, ask for a passphrase at startup"}, "no"))
	}
	f.setFocus(0)
	return f
}

func machineForm(h host.Info, name string) form {
	memChoices, memLabels := []string{}, []string{}
	recommended := "6144"
	for _, gb := range []int{4, 6, 8, 12, 16} {
		mb := gb * 1024
		// Leave the host at least 4 GB, or half of what it has.
		if h.MemoryMB > 0 && mb > h.MemoryMB-4096 && gb > 4 {
			continue
		}
		memChoices = append(memChoices, strconv.Itoa(mb))
		memLabels = append(memLabels, fmt.Sprintf("%d GB", gb))
		if h.MemoryMB >= 24*1024 && gb == 8 {
			recommended = strconv.Itoa(mb)
		}
	}
	if len(memChoices) == 1 {
		recommended = memChoices[0]
	}
	cpuChoices := []string{}
	cpuRec := "2"
	for _, c := range []int{2, 4, 6, 8} {
		if c > h.CPUs && c > 2 {
			continue
		}
		cpuChoices = append(cpuChoices, strconv.Itoa(c))
		if c <= h.CPUs/2 {
			cpuRec = strconv.Itoa(c)
		}
	}
	f := form{fields: []*field{
		newText("name", "VM name", "Shown in the hypervisor, and the name of its folder.", name, func(s string) error {
			if s == "" || strings.ContainsAny(s, `/\:*?"<>|`) {
				return fmt.Errorf("Use letters, digits, spaces, - or _")
			}
			return nil
		}),
		newChoice("memory", "Memory", fmt.Sprintf("This computer has %s. AuraDE needs 4 GB at least.", gbString(h.MemoryMB)), memChoices, memLabels, recommended),
		newChoice("cpus", "Processors", fmt.Sprintf("This computer has %d.", h.CPUs), cpuChoices, nil, cpuRec),
		newChoice("disk", "Disk size", "The disk grows as it fills, so this is a limit, not space taken now.",
			[]string{"40", "64", "100", "30"}, []string{"40 GB", "64 GB", "100 GB", "30 GB"}, "40"),
		newChoice("accel", "3D graphics", "Makes the desktop much smoother. Turn it off only if the VM's screen stays black.",
			[]string{"yes", "no"}, []string{"On", "Off"}, "yes"),
	}}
	f.setFocus(0)
	return f
}

func gbString(mb int) string {
	if mb <= 0 {
		return "an unknown amount of memory"
	}
	return fmt.Sprintf("%.0f GB", float64(mb)/1024)
}

// Init starts hypervisor detection in the background.
func (m Model) Init() tea.Cmd {
	return tea.Batch(m.spin.Tick, func() tea.Msg {
		var out []detected
		for _, b := range hv.All() {
			out = append(out, detected{b, b.Detect(context.Background())})
		}
		return detectMsg(out)
	})
}

func (m Model) available() []int {
	var idx []int
	for i, d := range m.backends {
		if d.det.Available {
			idx = append(idx, i)
		}
	}
	return idx
}

// Update is the state machine.
func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.bar.Width = min(60, max(20, msg.Width-12))
		return m, nil
	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spin, cmd = m.spin.Update(msg)
		return m, cmd
	case detectMsg:
		m.backends = nil
		for _, d := range msg {
			if !d.det.Foreign {
				m.backends = append(m.backends, d)
			}
		}
		m.detecting = false
		if av := m.available(); len(av) > 0 {
			m.backendIdx = av[0]
		}
		return m, nil
	case eventMsg:
		e := plan.Event(msg)
		if e.Step != "" {
			m.steps = append(m.steps, e.Step)
			m.done, m.total = 0, 0
		}
		if e.Log != "" {
			m.logs = append(m.logs, e.Log)
		}
		if e.Total > 0 || e.Done > 0 {
			m.done, m.total = e.Done, e.Total
		}
		if e.Verified != "" {
			m.verified = string(e.Verified)
		}
		return m, m.waitEvent()
	case finishedMsg:
		m.err = msg.err
		m.screen = sDone
		return m, nil
	case tea.KeyMsg:
		if msg.String() == "ctrl+c" {
			if m.cancel != nil {
				m.cancel()
			}
			return m, tea.Quit
		}
		return m.key(msg)
	}
	return m, nil
}

func (m Model) key(k tea.KeyMsg) (tea.Model, tea.Cmd) {
	back := func(s screen) (tea.Model, tea.Cmd) { m.screen = s; return m, nil }
	switch m.screen {
	case sWelcome:
		n := len(m.existing) + 1
		switch k.String() {
		case "up", "k":
			m.welcomeIdx = (m.welcomeIdx - 1 + n) % n
		case "down", "j", "tab":
			m.welcomeIdx = (m.welcomeIdx + 1) % n
		case "q", "esc":
			return m, tea.Quit
		case "enter":
			if m.welcomeIdx > 0 {
				if m.detecting {
					return m, nil
				}
				return m.startExisting(m.existing[m.welcomeIdx-1])
			}
			m.screen = sHypervisor
		}
	case sHypervisor:
		switch k.String() {
		case "esc":
			return back(sWelcome)
		case "up", "k":
			if m.backendIdx > 0 {
				m.backendIdx--
			}
		case "down", "j", "tab":
			if m.backendIdx < len(m.backends)-1 {
				m.backendIdx++
			}
		case "enter":
			if !m.detecting && m.backendIdx < len(m.backends) && m.backends[m.backendIdx].det.Available {
				m.screen = sMode
			}
		}
	case sMode:
		switch k.String() {
		case "esc":
			return back(sHypervisor)
		case "up", "k":
			if m.modeIdx > 0 {
				m.modeIdx--
			}
		case "down", "j", "tab":
			if m.modeIdx < len(modes)-1 {
				m.modeIdx++
			}
		case "enter":
			if !modes[m.modeIdx].ready {
				return m, nil
			}
			switch modes[m.modeIdx].id {
			case plan.Guided, plan.Express:
				express := modes[m.modeIdx].id == plan.Express
				if express != m.questionsExpress {
					m.questions = questionForm(m.host, express)
					m.questionsExpress = express
				}
				m.screen = sQuestions
			default:
				m.screen = sMachine
			}
		}
	case sQuestions:
		if k.String() == "esc" {
			return back(sMode)
		}
		cmd, finished := m.questions.update(k)
		if finished && m.questions.valid() {
			m.screen = sMachine
		}
		return m, cmd
	case sMachine:
		if k.String() == "esc" {
			if id := modes[m.modeIdx].id; id == plan.Guided || id == plan.Express {
				return back(sQuestions)
			}
			return back(sMode)
		}
		cmd, finished := m.machine.update(k)
		if finished && m.machine.valid() {
			m.screen = sReview
		}
		return m, cmd
	case sReview:
		switch k.String() {
		case "esc":
			return back(sMachine)
		case "enter":
			p := m.buildPlan()
			if p.Mode == plan.Express {
				h, err := answers.HashPassword(m.questions.get("password"))
				if err != nil {
					m.err = err
					m.screen = sDone
					return m, nil
				}
				p.PasswordHash = h
			}
			return m.start(p)
		}
	case sDone:
		switch k.String() {
		case "enter", "q", "esc":
			return m, tea.Quit
		}
	}
	return m, nil
}

func (m Model) buildPlan() *plan.Plan {
	b := m.backends[m.backendIdx].backend
	mem, _ := strconv.Atoi(m.machine.get("memory"))
	cpus, _ := strconv.Atoi(m.machine.get("cpus"))
	disk, _ := strconv.Atoi(m.machine.get("disk"))
	p := &plan.Plan{
		Backend:  b,
		Mode:     modes[m.modeIdx].id,
		BaseDir:  m.opt.BaseDir,
		Tag:      m.opt.Tag,
		LocalISO: m.opt.LocalISO,
		Spec: hv.Spec{
			Name: m.machine.get("name"), MemoryMB: mem, CPUs: cpus, DiskGB: disk,
			Accel3D: m.machine.get("accel") == "yes",
		},
	}
	if p.Mode == plan.Guided || p.Mode == plan.Express {
		p.Answers = answers.Answers{
			Locale: m.questions.get("locale"), Keymap: m.questions.get("keymap"),
			Timezone: m.questions.get("timezone"), Hostname: m.questions.get("hostname"),
			Username: m.questions.get("username"), Encrypt: m.questions.get("encrypt"),
			Filesystem: m.questions.get("filesystem"),
		}
		if p.Mode == plan.Express {
			p.Answers.Encrypt = "no"
		}
	}
	return p
}

func (m Model) startExisting(r hv.Record) (tea.Model, tea.Cmd) {
	for _, d := range m.backends {
		if d.backend.ID() != r.Backend {
			continue
		}
		if !d.det.Available {
			m.err = fmt.Errorf("%s made %s, and it is not ready on this computer: %s", d.backend.Name(), r.Spec.Name, d.det.Why)
			m.screen = sDone
			return m, nil
		}
		return m.start(&plan.Plan{Backend: d.backend, BaseDir: m.opt.BaseDir, Spec: hv.Spec{Name: r.Spec.Name}})
	}
	m.err = fmt.Errorf("%s was made with %s, which this version does not know", r.Spec.Name, r.Backend)
	m.screen = sDone
	return m, nil
}

func (m Model) start(p *plan.Plan) (tea.Model, tea.Cmd) {
	m.plan = p
	m.screen = sRun
	m.events = make(chan tea.Msg, 64)
	ctx, cancel := context.WithCancel(context.Background())
	m.cancel = cancel
	ch := m.events
	go func() {
		err := p.Run(ctx, func(e plan.Event) { ch <- eventMsg(e) })
		ch <- finishedMsg{err}
	}()
	return m, tea.Batch(m.spin.Tick, m.waitEvent())
}

func (m Model) waitEvent() tea.Cmd {
	ch := m.events
	return func() tea.Msg { return <-ch }
}

// View draws the current screen.
func (m Model) View() string {
	var body string
	switch m.screen {
	case sWelcome:
		body = m.viewWelcome()
	case sHypervisor:
		body = m.viewHypervisor()
	case sMode:
		body = m.viewMode()
	case sQuestions:
		body = m.viewForm("About you and this computer",
			"The installer opens with these filled in. It asks for your password itself; nothing secret is written down here.", &m.questions)
	case sMachine:
		body = m.viewForm("The virtual machine", "Recommended sizes for this computer are already picked.", &m.machine)
	case sReview:
		body = m.viewReview()
	case sRun:
		body = m.viewRun()
	case sDone:
		body = m.viewDone()
	}
	return lipgloss.NewStyle().Padding(1, 2).Render(banner() + "\n\n" + body)
}

func backendName(ds []detected, id string) string {
	for _, d := range ds {
		if d.backend.ID() == id {
			return d.backend.Name()
		}
	}
	return id
}

func keys(s string) string { return "\n" + keysStyle.Render(s) }

// wrap fits text to the terminal, indented under the line it explains.
func (m Model) wrap(st lipgloss.Style, indent int, s string) string {
	w := m.width - 4 - indent
	if m.width == 0 || w > 96 {
		w = 96
	}
	if w < 30 {
		w = 30
	}
	return lipgloss.NewStyle().MarginLeft(indent).Render(st.Width(w).Render(s))
}

func (m Model) viewWelcome() string {
	var b strings.Builder
	b.WriteString(titleStyle.Render("Welcome") + "\n")
	b.WriteString("This makes a virtual machine, downloads AuraDE into it, checks the download\n")
	b.WriteString("against the release key, and starts the installer. Everything stays in\n")
	b.WriteString(choiceStyle.Render(m.opt.BaseDir) + ".\n\n")
	if m.host.Arch != "amd64" {
		b.WriteString(warnStyle.Render("AuraDE is built for x86_64 PCs, and this computer is "+m.host.Arch+".") + "\n")
		b.WriteString(warnStyle.Render("Hypervisors here cannot run it at a usable speed.") + "\n\n")
	}
	opts := []string{"Make a new AuraDE VM"}
	for _, r := range m.existing {
		opts = append(opts, "Start "+r.Spec.Name+dimStyle.Render("  ("+backendName(m.backends, r.Backend)+")"))
	}
	for i, o := range opts {
		if i == m.welcomeIdx {
			b.WriteString(focusStyle.Render("› "+o) + "\n")
		} else {
			b.WriteString("  " + o + "\n")
		}
	}
	return b.String() + keys("↑/↓ choose · enter continue · q quit")
}

func (m Model) viewHypervisor() string {
	var b strings.Builder
	b.WriteString(titleStyle.Render("Where should it run?") + "\n")
	b.WriteString(subtitleStyle.Render("The hypervisors found on this computer.") + "\n\n")
	if m.detecting {
		return b.String() + m.spin.View() + " Looking…"
	}
	for i, d := range m.backends {
		cursor := "  "
		name := d.backend.Name()
		if i == m.backendIdx {
			cursor = focusStyle.Render("› ")
			name = focusStyle.Render(name)
		}
		if d.det.Available {
			b.WriteString(cursor + name + "  " + goodStyle.Render("ready") + dimStyle.Render("  "+d.det.Version) + "\n")
		} else {
			b.WriteString(cursor + dimStyle.Render(d.backend.Name()) + "  " + warnStyle.Render("not available") + "\n")
			b.WriteString(m.wrap(helpStyle, 4, d.det.Why) + "\n")
		}
	}
	if len(m.available()) == 0 {
		b.WriteString("\n" + warnStyle.Render("None of the supported hypervisors is ready on this computer yet.") + "\n")
	}
	return b.String() + keys("↑/↓ choose · enter continue · esc back")
}

func (m Model) viewMode() string {
	var b strings.Builder
	b.WriteString(titleStyle.Render("How much should be set up for you?") + "\n\n")
	for i, md := range modes {
		title := md.title
		cursor := "  "
		if i == m.modeIdx {
			cursor = focusStyle.Render("› ")
			title = focusStyle.Render(title)
		}
		if !md.ready {
			title = dimStyle.Render(md.title + " (coming soon)")
		}
		b.WriteString(cursor + title + "\n")
		b.WriteString(m.wrap(helpStyle, 4, md.desc) + "\n\n")
	}
	return b.String() + keys("↑/↓ choose · enter continue · esc back")
}

func (m Model) viewForm(title, sub string, f *form) string {
	var b strings.Builder
	b.WriteString(titleStyle.Render(title) + "\n")
	b.WriteString(m.wrap(subtitleStyle, 0, sub) + "\n\n")
	for i, fl := range f.fields {
		label := labelStyle.Render(fl.label)
		if i == f.focus {
			label = focusStyle.Render("› " + fl.label)
		} else {
			label = "  " + label
		}
		var val string
		if fl.kind == choiceField {
			val = choiceStyle.Render("‹ " + fl.shown() + " ›")
		} else if i == f.focus {
			val = fl.input.View()
		} else {
			val = fl.shown()
		}
		b.WriteString(fmt.Sprintf("%-28s %s\n", label, val))
		if fl.err != "" {
			b.WriteString(m.wrap(errStyle, 4, fl.err) + "\n")
		} else if i == f.focus {
			b.WriteString(m.wrap(helpStyle, 4, fl.help) + "\n")
		}
	}
	return b.String() + keys("↑/↓ move · ←/→ change a choice · enter next · esc back")
}

func (m Model) viewReview() string {
	p := m.buildPlan()
	var b strings.Builder
	b.WriteString(titleStyle.Render("Ready") + "\n\n")
	row := func(k, v string) { b.WriteString(fmt.Sprintf("  %-18s %s\n", dimStyle.Render(k), v)) }
	row("Hypervisor", p.Backend.Name())
	row("VM", fmt.Sprintf("%s · %s memory · %d processors · %d GB disk", p.Spec.Name, gbString(p.Spec.MemoryMB), p.Spec.CPUs, p.Spec.DiskGB))
	row("Folder", plan.VMDir(p.BaseDir, p.Spec.Name))
	switch {
	case m.opt.LocalISO != "":
		row("AuraDE", m.opt.LocalISO+warnStyle.Render("  (your own ISO, not checked)"))
	case m.opt.Tag != "":
		row("AuraDE", m.opt.Tag)
	default:
		row("AuraDE", "the latest release")
	}
	row("Setup", modes[m.modeIdx].title)
	if p.Mode == plan.Guided || p.Mode == plan.Express {
		a := p.Answers
		row("Account", a.Username+" on "+a.Hostname)
		row("Region", a.Locale+" · "+a.Keymap+" keyboard · "+a.Timezone)
		enc := "not encrypted"
		if a.Encrypt == "yes" {
			enc = "encrypted"
		}
		row("Disk", a.Filesystem+", "+enc)
	}
	b.WriteString("\n" + helpStyle.Render("Nothing is erased on this computer. The installer only ever sees the VM's own empty disk.") + "\n")
	return b.String() + keys("enter start · esc back")
}

func (m Model) viewRun() string {
	var b strings.Builder
	b.WriteString(titleStyle.Render("Setting up") + "\n\n")
	for i, s := range m.steps {
		if i == len(m.steps)-1 {
			b.WriteString(m.spin.View() + " " + s + "\n")
		} else {
			b.WriteString(goodStyle.Render("✓") + " " + dimStyle.Render(s) + "\n")
		}
	}
	if m.total > 0 {
		frac := float64(m.done) / float64(m.total)
		b.WriteString("\n  " + m.bar.ViewAs(frac) + "  " + fmt.Sprintf("%.0f / %.0f MB", float64(m.done)/1e6, float64(m.total)/1e6) + "\n")
	}
	if n := len(m.logs); n > 0 {
		b.WriteString("\n")
		for _, l := range m.logs[max(0, n-3):] {
			b.WriteString("  " + helpStyle.Render(l) + "\n")
		}
	}
	return b.String() + keys("ctrl+c stop (a download picks up where it stopped)")
}

func (m Model) viewDone() string {
	var b strings.Builder
	if m.err != nil {
		b.WriteString(errStyle.Bold(true).Render("That did not work") + "\n\n")
		b.WriteString(m.err.Error() + "\n")
		return b.String() + keys("enter quit")
	}
	b.WriteString(goodStyle.Bold(true).Render("Your AuraDE VM is starting") + "\n\n")
	for _, s := range m.steps {
		b.WriteString(goodStyle.Render("✓") + " " + dimStyle.Render(s) + "\n")
	}
	b.WriteString("\n")
	p := m.plan
	if p != nil && p.Spec.ISO != "" {
		switch p.Mode {
		case plan.Express:
			b.WriteString(panelStyle.Render(
				"AuraDE is installing itself in the VM's window. It needs\n" +
					"the internet for about ten minutes, then restarts at the\n" +
					"sign-in screen. Sign in as " + p.Answers.Username + " with the password you chose.\n" +
					"Next time, run aurade-vm and choose Start " + p.Spec.Name + "."))
		case plan.Guided:
			b.WriteString(panelStyle.Render(
				"The installer opens with your answers filled in.\n" +
					"It asks for your password, and checks the disk with you\n" +
					"before anything is written. When it finishes, run aurade-vm\n" +
					"again and choose Start " + p.Spec.Name + "."))
		default:
			b.WriteString(panelStyle.Render(
				"Follow the installer in the VM's window. When it finishes,\n" +
					"run aurade-vm again and choose Start " + p.Spec.Name + "."))
		}
	}
	return b.String() + "\n" + keys("enter quit")
}

// Run starts the TUI.
func Run(opt Options) error {
	_, err := tea.NewProgram(New(opt), tea.WithAltScreen()).Run()
	return err
}
