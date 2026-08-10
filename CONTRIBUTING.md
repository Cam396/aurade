# Contributing to AuraDE

AuraDE is a fast-moving pre-alpha project. Small, reviewable changes are much
easier to land than a large desktop rewrite.

## Before opening a change

1. Read the README and the relevant package/CI documentation.
2. Keep Chromium changes in an ordered patch under `patches/` and add it to
   `patches/SERIES` exactly once.
3. Keep each changed source file owned by one patch; do not create overlapping
   patch layers.
4. Do not commit Chromium checkouts, build output, VM evidence, credentials,
   or hardware reports containing personal data.

## Required checks

For patch changes:

```bash
git apply --check --whitespace=error-all patches/<name>.patch
ci/verify-patch-series.sh --expect-tree-match
```

For package changes, regenerate `.SRCINFO` from the package's `PKGBUILD` and
run the relevant package smoke tests. Shell scripts must pass `bash -n`; Python
must pass the package's focused tests and compile checks. Run `git diff --check`
before opening a pull request.

The linked Chromium build and hardware tests are expensive and are release
gates, not a requirement for every documentation-only change. State exactly
which checks were run and which were not.

## Source conventions

Use `// AuraDE compatibility:` for clean, intentional generic-Linux behavior.
Use `// HACK(AuraDE):` only for a brittle workaround that has a removal plan.
Do not hide missing platform support behind invented success values; report an
unavailable capability and add a focused regression test when practical.

## Pull requests and issues

Explain the user-visible behavior, affected packages/patches, test commands,
and rollback implications. Include exact versions and hashes for binary issues.
Security reports must use the private advisory flow described in
[SECURITY.md](SECURITY.md), not a public issue.
