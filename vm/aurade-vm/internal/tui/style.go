package tui

import "github.com/charmbracelet/lipgloss"

// Colours that read on both dark and light terminals.
var (
	accent  = lipgloss.AdaptiveColor{Light: "#6D28D9", Dark: "#A78BFA"}
	accent2 = lipgloss.AdaptiveColor{Light: "#0F766E", Dark: "#5EEAD4"}
	muted   = lipgloss.AdaptiveColor{Light: "#6B7280", Dark: "#9CA3AF"}
	warn    = lipgloss.AdaptiveColor{Light: "#B45309", Dark: "#FBBF24"}
	bad     = lipgloss.AdaptiveColor{Light: "#B91C1C", Dark: "#F87171"}
	good    = lipgloss.AdaptiveColor{Light: "#15803D", Dark: "#4ADE80"}

	titleStyle    = lipgloss.NewStyle().Bold(true).Foreground(accent)
	subtitleStyle = lipgloss.NewStyle().Foreground(muted)
	labelStyle    = lipgloss.NewStyle().Bold(true)
	focusStyle    = lipgloss.NewStyle().Foreground(accent).Bold(true)
	helpStyle     = lipgloss.NewStyle().Foreground(muted)
	errStyle      = lipgloss.NewStyle().Foreground(bad)
	warnStyle     = lipgloss.NewStyle().Foreground(warn)
	goodStyle     = lipgloss.NewStyle().Foreground(good)
	dimStyle      = lipgloss.NewStyle().Foreground(muted).Faint(true)
	choiceStyle   = lipgloss.NewStyle().Foreground(accent2).Bold(true)
	keysStyle     = lipgloss.NewStyle().Foreground(muted)
	panelStyle    = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(accent).Padding(1, 2)
)

// banner is the wordmark at the top of every screen.
func banner() string {
	a := lipgloss.NewStyle().Bold(true).Foreground(accent).Render("Aura")
	d := lipgloss.NewStyle().Bold(true).Foreground(accent2).Render("DE")
	return a + d + subtitleStyle.Render("  ·  try it in a virtual machine")
}
