# AuraDE CI and Chromium build strategy

This document records the release-build decision for AuraDE. It was checked
against the current GitHub Actions and Chromium requirements on 2026-08-12.

## Decision

GitHub Actions can orchestrate a full AuraDE Chromium build, but the free
standard `ubuntu-latest` runner cannot perform it. The release path should use
GitHub-hosted runners for cheap source/package checks and a protected,
warm, self-hosted Linux runner for the expensive Chromium/package/ISO job.

A paid GitHub-hosted larger runner is a viable one-off experiment, not the
default release plan: every job starts on a fresh VM, the cold checkout and
hooks consume significant time, and GitHub-hosted jobs have a six-hour
execution limit.

## Why the standard runner is not enough

Public repositories get a 4-vCPU, 16-GB RAM, 14-GB SSD `ubuntu-latest` VM. The
Chromium build instructions require at least 100 GB of free disk and recommend
more than 16 GB of RAM. AuraDE additionally needs the ChromeOS dependency
sync, hooks, an `out/Ash` build directory, an Arch validation root, package
caches, and ISO/repository staging. The 14-GB runner will run out of disk
before a meaningful build starts.

The relevant build stages are visible in:

- `ci/bootstrap-chromium-src.sh` / `ci/materialize-chromium-candidate.sh`
  (pinned source sync and hooks),
- `chromiumos-ash/PKGBUILD` (GN generation and Ninja `chrome`/
  `chrome_sandbox` build),
- `ci/build-release-candidate.sh` (Arch package repository), and
- `installer/build-iso.sh` (release ISO).

## Runner choices

| Runner | Practical result | Cost/risk |
| --- | --- | --- |
| Public `ubuntu-latest` | Source checks only; no full build | Free, but 14-GB disk is a hard blocker |
| GitHub larger 8-core | Potentially fits (32 GB RAM/300 GB SSD) if the job is warm enough and finishes under six hours | $0.022/minute; paid on public repos; requires an organization on Team or Enterprise Cloud |
| GitHub larger 16-core | Better chance of finishing (64 GB RAM/600 GB SSD) | $0.042/minute; still cold/ephemeral and capped at six hours |
| Self-hosted warm runner | Recommended; keeps the checkout, hooks, and `out/Ash` between releases | No GitHub runner-minute charge; owner pays for the machine/VPS |

The larger-runner sizes and rates are documented by GitHub in the [larger
runner reference](https://docs.github.com/en/actions/reference/runners/larger-runners)
and [Actions runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing).
GitHub's [Chromium Linux build requirements](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/build_instructions.md)
are the lower bound, not a complete AuraDE sizing recommendation.

For AuraDE, budget at least 8 vCPUs, 32 GB RAM, and 300 GB of fast SSD for a
reusable runner. A 16-vCPU, 64-GB, 600-GB NVMe host is the comfortable target;
32 vCPUs/128 GB/1.2 TB is useful only when release turnaround justifies it.
This sizing is an engineering buffer around Chromium's published minimums and
AuraDE's extra package/root/ISO state, not a claim that every machine will
finish in a fixed time.

## Recommended workflow split

1. **Every push and pull request:** keep `.github/workflows/source-checks.yml`
   on a standard public runner. It runs shell/Python syntax checks, patch
   manifest checks, package metadata checks, the public leak gate, and
   installer tests. It must never require Chromium or a self-hosted runner.
2. **Maintainer-only release build:** add a manual/tag-triggered workflow that
   targets a runner labelled `self-hosted`, `linux`, `x64`, and
   `aurade-chromium`. It should use an approval-protected environment and one
   concurrency slot. It should checkout the selected main/tag commit, reuse a
   work directory outside the checkout, run the pinned candidate/materializer,
   run `ci/build-release-candidate.sh`, build the ISO once from that repository,
   run the release gates, and upload only checksummed release assets.
3. **No pull-request execution on the build runner:** GitHub warns that forks
   of a public repository can change workflow code and execute it on a
   self-hosted machine. Keep expensive builds manual or protected and never
   expose the warm runner to untrusted `pull_request` jobs. See GitHub's
   [self-hosted runner security warning](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).
4. **Optional ephemeral VPS:** if a persistent machine is unavailable, start a
   donation-funded VPS with a persistent data volume, register a one-job
   ephemeral runner, run the release workflow, upload the artifacts, wipe the
   runner, and stop the VPS. Preserve the Chromium checkout/cache volume only
   if its contents are treated as disposable build inputs.

## How to reduce paid/build time

- Keep the pinned checkout and `out/Ash` on the runner. Do not delete the work
  directory between package-only changes.
- Re-run `gclient sync` and hooks only when the Chromium pin or hook inputs
  change. `ci/materialize-chromium-candidate.sh` already fingerprints hook
  inputs and reuses them when possible.
- Run the full job only for an explicit release dispatch or release tag. Let
  the standard workflow reject obvious source, metadata, and secret mistakes
  before consuming build capacity.
- Keep only one release build in flight; cancel stale manual requests before
  they compete for the same checkout.
- Do not depend on GitHub's ordinary Actions cache for a 100+ GB Chromium
  checkout. A local persistent disk is faster, cheaper, and less failure-prone.

## Release acceptance

A successful build job is not itself a release. Before publishing, retain the
source manifest, patch-series digest, package-repository checksums, ISO
checksums/build-info, and the results of the release/leak gates. Runtime VM and
hardware checks remain separate from CI and must not be implied by a green
build.
