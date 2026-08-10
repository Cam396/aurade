#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/aurade-materialize-test.XXXXXX")"
trap 'rm -rf "${tmp}"' EXIT

assert_eq() {
  [[ "$1" == "$2" ]] || {
    echo "assertion failed: expected '$2', got '$1'" >&2
    exit 1
  }
}

upstream="${tmp}/upstream"
developer="${tmp}/developer"
patches="${tmp}/patches"
checkout="${tmp}/candidate"
depot_tools="${tmp}/depot_tools"
gclient_log="${tmp}/gclient.log"
mkdir -p "${patches}" "${depot_tools}"

git init -q "${upstream}"
git -C "${upstream}" config user.name "AuraDE CI Test"
git -C "${upstream}" config user.email ci-test@aurade.invalid
printf 'out/\nbuildtools/\nthird_party/\n' > "${upstream}/.gitignore"
printf 'deps-v1\n' > "${upstream}/DEPS"
printf 'base feature\n' > "${upstream}/feature.txt"
printf 'base second\n' > "${upstream}/second.txt"
printf 'base unrelated\n' > "${upstream}/unrelated.txt"
git -C "${upstream}" add .
git -C "${upstream}" commit -qm base
base_sha="$(git -C "${upstream}" rev-parse HEAD)"
git clone -q "${upstream}" "${developer}"
printf 'developer dirt\n' >> "${developer}/unrelated.txt"
developer_head="$(git -C "${developer}" rev-parse HEAD)"
developer_status="$(git -C "${developer}" status --porcelain=v1)"

printf 'aurade feature\n' > "${upstream}/feature.txt"
printf 'patch-owned addition\n' > "${upstream}/added.txt"
git -C "${upstream}" add --intent-to-add added.txt
git -C "${upstream}" diff --binary --full-index > "${patches}/0001-feature.patch"
git -C "${upstream}" restore feature.txt
git -C "${upstream}" restore --staged added.txt
rm -f "${upstream}/added.txt"
printf '0001-feature.patch\n' > "${patches}/SERIES"

cat > "${depot_tools}/gclient" <<'EOF'
#!/bin/bash
set -euo pipefail
printf '%s\n' "$1" >> "${MOCK_GCLIENT_LOG}"
case "$1" in
  sync)
    if [[ ! -d src/.git ]]; then
      git clone -q "${MOCK_UPSTREAM}" src
    fi
    git -C src fetch -q "${MOCK_UPSTREAM}"
    git -C src checkout -q --detach "${AURADE_CANDIDATE_SHA}"
    ;;
  runhooks)
    mkdir -p src/buildtools/linux64 src/third_party/ninja
    printf '#!/bin/sh\nexit 0\n' > src/buildtools/linux64/gn
    printf '#!/bin/sh\nexit 0\n' > src/third_party/ninja/ninja
    chmod 755 src/buildtools/linux64/gn src/third_party/ninja/ninja
    ;;
  *)
    echo "unexpected mocked gclient command: $1" >&2
    exit 2
    ;;
esac
EOF
chmod 755 "${depot_tools}/gclient"

base_env=(
  AURADE_CANDIDATE_CHECKOUT_ROOT="${checkout}"
  AURADE_CHROMIUM_REMOTE="${upstream}"
  AURADE_CHROMIUM_REFERENCE="${developer}"
  AURADE_DEPOT_TOOLS="${depot_tools}"
  AURADE_GCLIENT_JOBS=2
  PATCH_DIR="${patches}"
  SERIES_FILE="${patches}/SERIES"
  MOCK_UPSTREAM="${upstream}"
  MOCK_GCLIENT_LOG="${gclient_log}"
)

env "${base_env[@]}" AURADE_CANDIDATE_SHA="${base_sha}" \
  "${SCRIPT_DIR}/materialize-chromium-candidate.sh" > "${tmp}/first.log"
assert_eq "$(<"${checkout}/src/feature.txt")" "aurade feature"
assert_eq "$(<"${checkout}/src/added.txt")" "patch-owned addition"
assert_eq "$(git -C "${checkout}/src" rev-parse HEAD)" "${base_sha}"
assert_eq "$(grep -c '^runhooks$' "${gclient_log}")" 1
printf 'keep this output\n' > "${checkout}/src/out/Ash/sentinel"

# Change patch ownership for the next generation. The old feature path must be
# restored even though it is absent from the new series.
printf 'aurade second\n' > "${upstream}/second.txt"
git -C "${upstream}" diff --binary --full-index > "${patches}/0002-second.patch"
git -C "${upstream}" restore second.txt
printf '0002-second.patch\n' > "${patches}/SERIES"
printf 'candidate two\n' > "${upstream}/unrelated.txt"
git -C "${upstream}" add unrelated.txt
git -C "${upstream}" commit -qm candidate-two
second_sha="$(git -C "${upstream}" rev-parse HEAD)"

env "${base_env[@]}" AURADE_CANDIDATE_SHA="${second_sha}" \
  "${SCRIPT_DIR}/materialize-chromium-candidate.sh" > "${tmp}/second.log"
assert_eq "$(<"${checkout}/src/feature.txt")" "base feature"
[[ ! -e "${checkout}/src/added.txt" ]]
assert_eq "$(<"${checkout}/src/second.txt")" "aurade second"
assert_eq "$(<"${checkout}/src/out/Ash/sentinel")" "keep this output"
assert_eq "$(grep -c '^runhooks$' "${gclient_log}")" 1
assert_eq "$(awk -F '\t' '$1 == "CHROME_SRC" {print $2}' \
  "${checkout}/.aurade-state/materialized.env")" "${checkout}/src"

# Recover from a partially applied series even when the repaired series drops a
# path that was applied before a later patch failed.
printf 'partial attempt\n' > "${upstream}/partial.txt"
git -C "${upstream}" add --intent-to-add partial.txt
git -C "${upstream}" diff --binary --full-index > "${patches}/0003-partial.patch"
git -C "${upstream}" restore --staged partial.txt
rm -f "${upstream}/partial.txt"
cat > "${patches}/9999-fail.patch" <<'EOF'
diff --git a/missing.txt b/missing.txt
index 1111111111..2222222222 100644
--- a/missing.txt
+++ b/missing.txt
@@ -1 +1 @@
-missing base
+never applies
EOF
printf '0003-partial.patch\n9999-fail.patch\n' > "${patches}/SERIES"
if env "${base_env[@]}" AURADE_CANDIDATE_SHA="${second_sha}" \
    "${SCRIPT_DIR}/materialize-chromium-candidate.sh" \
    > "${tmp}/partial-fail.log" 2>&1; then
  echo "partially invalid series unexpectedly materialized" >&2
  exit 1
fi
[[ -e "${checkout}/src/partial.txt" ]]
printf '0002-second.patch\n' > "${patches}/SERIES"
env "${base_env[@]}" AURADE_CANDIDATE_SHA="${second_sha}" \
  "${SCRIPT_DIR}/materialize-chromium-candidate.sh" \
  > "${tmp}/partial-recovery.log"
[[ ! -e "${checkout}/src/partial.txt" ]]
assert_eq "$(<"${checkout}/src/second.txt")" "aurade second"

# Dirt outside the recorded patch-owned set must stop before gclient sync and
# must never be erased by the helper.
printf 'unexpected local dirt\n' >> "${checkout}/src/unrelated.txt"
sync_count="$(grep -c '^sync$' "${gclient_log}")"
if env "${base_env[@]}" AURADE_CANDIDATE_SHA="${second_sha}" \
    "${SCRIPT_DIR}/materialize-chromium-candidate.sh" > "${tmp}/dirty.log" 2>&1; then
  echo "materializer accepted unrelated source dirt" >&2
  exit 1
fi
assert_eq "$(grep -c '^sync$' "${gclient_log}")" "${sync_count}"
grep -Fq 'unexpected local dirt' "${checkout}/src/unrelated.txt"
git -C "${checkout}/src" restore unrelated.txt

# A DEPS change changes the hook fingerprint, while out/ remains warm.
printf 'deps-v2\n' > "${upstream}/DEPS"
git -C "${upstream}" add DEPS
git -C "${upstream}" commit -qm candidate-three
third_sha="$(git -C "${upstream}" rev-parse HEAD)"
env "${base_env[@]}" AURADE_CANDIDATE_SHA="${third_sha}" \
  "${SCRIPT_DIR}/materialize-chromium-candidate.sh" > "${tmp}/third.log"
assert_eq "$(grep -c '^runhooks$' "${gclient_log}")" 2
assert_eq "$(<"${checkout}/src/out/Ash/sentinel")" "keep this output"
assert_eq "$(<"${checkout}/.aurade-state/revision")" "${third_sha}"

# The dirty developer/reference checkout is a read-only ownership hint only.
assert_eq "$(git -C "${developer}" rev-parse HEAD)" "${developer_head}"
assert_eq "$(git -C "${developer}" status --porcelain=v1)" "${developer_status}"

echo "materialize-chromium-candidate tests: PASS"
