# Contributing to AuraDE

Thanks for taking a look. Small, well-tested changes are welcome, especially
when they improve hardware support, accessibility, documentation, or recovery.

## Before opening a change

1. Read the relevant public design document.
2. Keep the change focused and explain the user-visible reason.
3. Do not include credentials, private logs, machine identifiers, or generated
   build output.
4. Update tests and user documentation when behavior changes.

## Required checks

~~~bash
git diff --check
ci/source-integrity-gate.sh
ci/public-release-leak-gate.sh
bash installer/tests/run.sh
~~~

Run the narrowest relevant test while developing, then run the complete suite
before opening a pull request. A skipped runtime dependency should be called
out rather than described as a pass.

## Source conventions

Use // AuraDE compatibility: for intentional compatibility code and
// HACK(AuraDE): for temporary workarounds. Keep public copy direct and human.
Avoid session notes, private paths, and references to tools or people that are
not part of the product.

## Pull requests and issues

Describe what changed, why it changed, how it was tested, and what remains
unproven. Use SECURITY.md for vulnerabilities instead of a public issue.
