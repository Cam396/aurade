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
