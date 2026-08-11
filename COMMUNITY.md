# AuraDE Community server

Recommended server name: **AuraDE Community**

Recommended description:

> Community hub for AuraDE — a ChromiumOS Ash-based desktop environment for
> Arch Linux. Builds, hardware testing, development, support, and release
> updates.

Current Discord invite: <https://discord.gg/vkZ7CSMG5>

Keep the server community-focused rather than calling it “official” while the
project is hosted under a personal GitHub account. Change the wording after a
formal project organization and maintainer group exist.

## Categories and channels

### START HERE

- `#welcome` — read-only onboarding and links.
- `#rules` — read-only conduct and safety rules.
- `#announcements` — maintainer-only release and outage notices.
- `#changelog` — automated GitHub release/commit summaries.

### COMMUNITY

- `#general` — project conversation.
- `#showcase` — screenshots, themes, and desk setups.
- `#off-topic` — non-project conversation.
- `Lounge` — optional voice room.

### SUPPORT

- `#install-help` — Arch/package/install troubleshooting.
- `#hardware-testing` — laptop and USB test reports.
- `#bug-reports` — link to GitHub Issues; do not post security reports here.
- `#feature-ideas` — proposals that are not yet GitHub issues.

### DEVELOPMENT

- `#dev-chat` — implementation discussion.
- `#chromium-patches` — patch-series and upstream-rebase work.
- `#packaging-aur` — Arch packaging and future AUR work.
- `#ci-builds` — CI results, hashes, and release evidence.
- `#release-planning` — release checklists, launch coordination, and milestones.
- `Pairing / Debug` — temporary voice room for live debugging.

### CONTRIBUTORS

- `#introductions` — say hello and share your setup or interests.
- `#good-first-issues` — small, well-scoped tasks for first-time contributors.
- `#help-wanted` — open tasks that need a second pair of hands.
- `#docs-and-design` — documentation, UX, themes, and visual design.
- `Contributor Hangout` — voice room for pairing and contributor calls.

### STAFF

- `#staff-chat` — private maintainer coordination.
- `#mod-log` — private moderation and audit notes.
- `#staff-announcements` — private notices for moderators and staff.

## Roles

The live hierarchy is ordered below the setup bot and is intentionally scoped:

- `Cam396 • Project Owner` — owner-only identity role for the project owner.
- `Maintainer` — project administration, moderation, and release control.
- `Founder` — project-leadership marker with maintainer-scoped capabilities.
- `Community Moderator` — day-to-day moderation without server administration.
- `Developer` — implementation and development-room access.
- `Package Builder` — packaging and release-build work.
- `Hardware Tester` — laptop and hardware qualification.
- `Documentation` — docs and changelog collaboration.
- `Theme Designer` — visual/theme collaboration.
- `Contributor` — general contribution path.
- `Early Adopter` — pre-alpha feedback and testing.
- `Community` — general community identity.

`#welcome`, `#rules`, and `#changelog` are read-only for ordinary members.
`#announcements` is intended for maintainers, and the `STAFF` category is
private. Discord join/leave system notices should be routed to `#welcome`.
Keep `Administrator` limited to the project owner and review every bot's role
and channel access after installation.

## Bot checklist

1. Enable Discord AutoMod and slow mode before installing extra bots.
2. Add one GitHub notification bot for releases/issues/CI, scoped to
   `#changelog` and `#ci-builds`.
3. Add a moderation bot only if AutoMod is insufficient; do not install several
   overlapping bots.
4. Never give a bot Administrator permission or access to private security
   discussions.
5. Review every bot's data policy and remove it if the project no longer needs
   it.

## Welcome message

```text
Welcome to AuraDE Community.

AuraDE is a pre-alpha ChromiumOS Ash-based desktop environment for Arch Linux.
Start with #rules and #welcome, use #install-help for setup questions, and
file reproducible bugs at https://github.com/Cam396/aurade/issues.

Do not post passwords, API keys, private logs, or security vulnerabilities in
Discord. Use the private GitHub security-advisory flow for security reports.
```

## Setup note

This page is a public community blueprint. Keep live moderation notes, bot
bootstrap state, permission audits, and staff coordination in private
maintainer records rather than publishing them here.
