#!/usr/bin/env bash
# Focused regression test for the third v0.7.4 causal defect: the final
# subject-binding lookup loop in scripts/ci/verify_release_image.sh used
# to pack architecture and digest into one colon-delimited string
# (`pair="amd64:${AMD64_DIGEST}"`, where AMD64_DIGEST is itself
# "sha256:<hex>") and then split with `${pair##*:}` -- which strips to
# the LAST colon, removing the "sha256:" prefix along with "amd64:" and
# leaving a bare hex digest that could never match the
# "sha256:"-prefixed keys HAS_SBOM/HAS_PROVENANCE were actually
# populated with. The real attestations were always correctly present
# and subject-bound; only this final lookup was broken.
#
# The repair eliminates the packing/splitting entirely: an explicit
# verify_subject_binding() helper is called once per architecture with
# the already-complete "$AMD64_DIGEST" / "$ARM64_DIGEST" variables passed
# straight through, exactly as verify_runtime_labels() already does for
# the OCI-label checks.
#
# This test proves:
#   1. Static: the old packing/splitting pattern is gone from the real
#      script, and the new explicit per-architecture calls are present.
#   2. Synthetic/negative (network-free, deterministic): a bare digest
#      (post-${pair##*:}-style stripping) can NEVER accidentally satisfy
#      a lookup against "sha256:"-prefixed keys -- proving the OLD
#      behavior was a guaranteed miss, not a flaky one -- while passing
#      the complete "sha256:"-prefixed digest straight through (the NEW
#      behavior) correctly matches.
#
# Requires: bash 4+ (associative arrays). No network access needed for
# this file; live end-to-end proof against real v0.7.4 artifacts is done
# separately (see release-closure report).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERIFIER="${REPO_ROOT}/scripts/ci/verify_release_image.sh"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

echo "== Static check: old colon-packing/splitting pattern is gone, explicit per-arch calls are present =="
# shellcheck disable=SC2016 # intentional literal match -- these are grep
# patterns for literal source text, not shell expressions to expand.
grep -q '${pair##*:}' "$VERIFIER" \
  && fail "verify_release_image.sh still contains the buggy \${pair##*:} digest-stripping pattern"
# shellcheck disable=SC2016
grep -q '"amd64:${AMD64_DIGEST}"' "$VERIFIER" \
  && fail "verify_release_image.sh still packs architecture and digest into one colon-delimited string"
# shellcheck disable=SC2016
grep -q 'verify_subject_binding amd64 "$AMD64_DIGEST"' "$VERIFIER" \
  || fail "verify_release_image.sh does not call verify_subject_binding with the complete \$AMD64_DIGEST variable"
# shellcheck disable=SC2016
grep -q 'verify_subject_binding arm64 "$ARM64_DIGEST"' "$VERIFIER" \
  || fail "verify_release_image.sh does not call verify_subject_binding with the complete \$ARM64_DIGEST variable"
echo "PASS: digest/architecture packing eliminated; explicit calls pass the complete digest variables directly"

echo "== Synthetic negative control: a bare digest (old-behavior artifact) must NEVER satisfy a sha256:-prefixed lookup =="
declare -A SYNTHETIC_HAS_SBOM=(["sha256:deadbeefcafe"]=1)

# Reproduce the OLD buggy extraction exactly, against a synthetic pair,
# to prove it is a GUARANTEED miss (not an occasional one).
OLD_STYLE_PAIR="amd64:sha256:deadbeefcafe"
OLD_STYLE_DIGEST="${OLD_STYLE_PAIR##*:}"
[ "$OLD_STYLE_DIGEST" = "deadbeefcafe" ] \
  || fail "test harness assumption broken: expected the old-style split to produce a bare digest, got '${OLD_STYLE_DIGEST}'"
[ "${SYNTHETIC_HAS_SBOM[$OLD_STYLE_DIGEST]:-0}" = "1" ] \
  && fail "a bare digest without the sha256: prefix incorrectly satisfied the attestation lookup -- this would silently mask the original defect"
echo "PASS: bare digest '${OLD_STYLE_DIGEST}' correctly fails to match (proves the old behavior was a guaranteed, not flaky, miss)"

# The NEW behavior: the complete, already-correct digest variable passed
# straight through, with no splitting at all.
NEW_STYLE_DIGEST="sha256:deadbeefcafe"
[ "${SYNTHETIC_HAS_SBOM[$NEW_STYLE_DIGEST]:-0}" = "1" ] \
  || fail "the complete sha256:-prefixed digest failed to match its own correctly-populated key -- regression in the fix itself"
echo "PASS: complete digest '${NEW_STYLE_DIGEST}' correctly matches"

echo "PASS: digest-preservation fix is present and the bare-digest failure mode is proven closed"
