# AuraDE Community server

Recommended server name: **AuraDE Community**

Recommended description:

> Community hub for AuraDE — a ChromiumOS Ash-based desktop environment for
> Arch Linux. Builds, hardware testing, development, support, and release
> updates.

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
- `Pairing / Debug` — temporary voice room for live debugging.

## Roles

Start with the smallest useful set: `Maintainer`, `Developer`, `Package
Builder`, `Hardware Tester`, `Contributor`, and `Community`. Keep
`Administrator` limited to the account owner; bots should receive only the
channel permissions they need.

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
