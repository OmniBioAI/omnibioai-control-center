#!/usr/bin/env bash
# Focused regression test for the second v0.7.4 causal defect: scripts/ci/
# verify_release_image.sh used to overload a single $VERSION argument as
# both the registry ref-tag to inspect (correct: staging-index-<sha>) and
# the expected org.opencontainers.image.version label (wrong when
# verifying a pre-publication staging index, whose tag name differs from
# the real semantic version already baked into its runtime labels). This
# caused both verify-backend and verify-frontend to fail against the
# real, correctly-labeled v0.7.4 staging artifacts.
#
# The interface is now REF_TAG / EXPECTED_VERSION as two independent
# arguments. This test proves:
#   D/G. both ci.yml callers pass exactly 5 distinct arguments, with
#        ref-tag referencing staging-index-<sha> and the 5th argument
#        referencing the resolved semantic version output -- never the
#        same expression (no caller remains on the old 4-argument,
#        overloaded contract).
#   E.   (same check) the version argument specifically comes from
#        needs.resolve-version.outputs.version, the one authoritative
#        release-version output.
#   A/B. the real, immutable v0.7.4 backend staging index -- ref-tag
#        "staging-index-<sha>", OCI version label "0.7.4" -- verifies
#        successfully end-to-end when given the CORRECT expected version,
#        proving ref-tag and expected-version are genuinely independent
#        and not silently reconverging.
#   C.   supplying a deliberately WRONG expected version against that
#        same real artifact still fails closed (negative control).
#
# Read-only throughout: only inspects existing GHCR artifacts from the
# already-failed v0.7.4 run (permanent, collision-safe staging tags, per
# the release design -- never rebuilt, never retagged, never mutated).
#
# Requires: docker buildx, python3. Network access to GHCR.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERIFIER="${REPO_ROOT}/scripts/ci/verify_release_image.sh"
CI_YML="${REPO_ROOT}/.github/workflows/ci.yml"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

METADATA_OUTPUT_FILE=""
NEGATIVE_OUTPUT_FILE=""
cleanup() {
  rm -f "$METADATA_OUTPUT_FILE" "$NEGATIVE_OUTPUT_FILE" 2>/dev/null || true
}
trap cleanup EXIT

# Real, immutable v0.7.4 staging fixture (backend). Permanent by design --
# see release-closure report; not cleaned up on a failed release.
BACKEND_IMAGE="ghcr.io/omnibioai/omnibioai-control-center"
STAGING_REF_TAG="staging-index-2568b777e014dd4b40718727f0b53ae02c0a2045"
EXPECTED_SOURCE="https://github.com/OmniBioAI/omnibioai-control-center"
EXPECTED_REVISION="2568b777e014dd4b40718727f0b53ae02c0a2045"
REAL_VERSION="0.7.4"

echo "== D/E/G: ci.yml callers pass 5 distinct arguments; ref-tag and version are never the same expression =="
python3 - "$CI_YML" <<'PYEOF'
import re
import sys

text = open(sys.argv[1]).read()
calls = re.findall(r'scripts/ci/verify_release_image\.sh \\\n((?:\s+"[^"]*"\s*\\?\n)+)', text)
if len(calls) != 2:
    print(f"FAIL: expected exactly 2 callers of verify_release_image.sh in ci.yml, found {len(calls)}", file=sys.stderr)
    sys.exit(1)

for i, block in enumerate(calls):
    args = re.findall(r'"([^"]*)"', block)
    if len(args) != 5:
        print(f"FAIL: caller {i} passes {len(args)} argument(s), expected exactly 5 "
              f"(image, ref-tag, source, revision, version) -- found: {args}", file=sys.stderr)
        sys.exit(1)
    ref_tag, version = args[1], args[4]
    if "staging-index-" not in ref_tag:
        print(f"FAIL: caller {i}'s ref-tag argument does not reference staging-index-<sha>: {ref_tag}", file=sys.stderr)
        sys.exit(1)
    if "outputs.version" not in version:
        print(f"FAIL: caller {i}'s 5th argument does not reference the resolved semantic "
              f"version output (needs.resolve-version.outputs.version): {version}", file=sys.stderr)
        sys.exit(1)
    if ref_tag == version:
        print(f"FAIL: caller {i}'s ref-tag and version arguments are identical -- "
              f"overloaded-contract regression", file=sys.stderr)
        sys.exit(1)

print("PASS: both ci.yml callers pass exactly 5 arguments; ref-tag references "
      "staging-index-<sha>, the 5th argument references the resolved semantic "
      "version output, and the two are never the same expression")
PYEOF

echo "== A/B: real staging ref-tag + CORRECT expected version passes the OCI metadata check for both architectures =="
# Deliberately does not require the whole script to exit 0: a separate,
# independently-tracked defect downstream of this check (subject-digest
# parsing in the SBOM/provenance-binding loop -- see release-closure
# report) can fail the run for an UNRELATED reason. This test's claim is
# narrowly about the metadata check this round's repair targets: that a
# staging ref-tag (not itself a version string) correctly verifies
# against the real OCI version label via the new, independent
# EXPECTED_VERSION argument.
METADATA_OUTPUT_FILE="$(mktemp)"
"$VERIFIER" "$BACKEND_IMAGE" "$STAGING_REF_TAG" "$EXPECTED_SOURCE" "$EXPECTED_REVISION" "$REAL_VERSION" \
  >"$METADATA_OUTPUT_FILE" 2>&1 || true
grep -q "amd64: OCI source/revision/version OK" "$METADATA_OUTPUT_FILE" \
  || { cat "$METADATA_OUTPUT_FILE" >&2; fail "amd64 OCI source/revision/version check did not pass against the real staging ref-tag with the correct expected version -- the ref-tag/version split is not working as intended"; }
grep -q "arm64: OCI source/revision/version OK" "$METADATA_OUTPUT_FILE" \
  || { cat "$METADATA_OUTPUT_FILE" >&2; fail "arm64 OCI source/revision/version check did not pass against the real staging ref-tag with the correct expected version -- the ref-tag/version split is not working as intended"; }
echo "PASS: ref-tag '${STAGING_REF_TAG}' (not a version string) correctly verified against real OCI version '${REAL_VERSION}' for both architectures"

echo "== C: an INCORRECT expected version against the SAME real artifact must still fail closed =="
NEGATIVE_OUTPUT_FILE="$(mktemp)"
if "$VERIFIER" "$BACKEND_IMAGE" "$STAGING_REF_TAG" "$EXPECTED_SOURCE" "$EXPECTED_REVISION" "0.7.999-invalid" >"$NEGATIVE_OUTPUT_FILE" 2>&1; then
  cat "$NEGATIVE_OUTPUT_FILE" >&2
  fail "verifier incorrectly PASSED with a deliberately wrong expected version '0.7.999-invalid' -- the version check is not enforced"
fi
grep -q "expected '0.7.999-invalid'" "$NEGATIVE_OUTPUT_FILE" \
  || { cat "$NEGATIVE_OUTPUT_FILE" >&2; fail "verifier failed, but not with the expected version-mismatch message"; }
echo "PASS: a deliberately wrong expected version is correctly rejected (fail-closed, no registry mutation)"

echo "PASS: REF_TAG and EXPECTED_VERSION are independent and enforced; both ci.yml callers use the new 5-argument contract"
