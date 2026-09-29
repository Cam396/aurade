# What this directory pins

Three facts about one Chromium, kept apart so that nothing has to parse a
sentence to find them, and compared by `ci/verify-release-identity.sh` so they
cannot drift apart quietly.

- `chromium.sha` is the git revision, forty hex characters and nothing else.
  `build-aurade.sh` and `ci/bootstrap-chromium-src.sh` both read this to decide
  what to fetch, so it is the file that decides what anybody following the
  documented build path actually gets.
- `chromium.version` is the dotted version that revision carries in
  `chrome/VERSION`. The Chromium package's `pkgver` must equal it.

They were allowed to disagree once. The pin held a 152 revision while the
package declared a 154 version and the tree that had actually been built was a
third thing, so anybody following the build instructions would have fetched
152 and packaged it as 154. The artifact was not traceable to a source, which
is the plainest possible definition of not being releasable.

Changing either file means changing both, and running the gate.

`arch.snapshot` is the Arch Linux Archive date that the ISO installs from and
that the CI package job builds against, in the archive's `YYYY/MM/DD` form.

`aurade-release.gpg` is the public half of the release signing key
(fingerprint `BC390DCF360B2184DBBF008B8B2AB2EFE667CB69`), the same file each
release publishes as `aurade-repository.gpg`. It lets CI and anybody else check
the hosted repository without a keyring. The private half never enters this
tree.
