#!/usr/bin/env bash
# Focused regression test for the Go-template field-casing defect that
# blocked v0.7.4's verify-backend/verify-frontend jobs: scripts/ci/
# verify_release_image.sh read OCI labels via `.Image.config.Labels`
# (lowercase `config`), but buildx's own v1.Image Go struct exposes this
# field as `Config` (capitalized) -- Go template field access uses the
# literal Go identifier, not the `config` json tag, so the lowercase form
# fails with "can't evaluate field config in type *v1.Image" against any
# genuine single-platform manifest digest (confirmed against the real
# v0.7.4 staging artifacts; this test uses a stable public fixture
# instead, so it does not depend on this repo's own release history
# remaining available).
#
# Two checks:
#   1. Static: the real verifier script must use the correct casing
#      (.Image.Config.Labels) and must never regress to the lowercase form.
#   2. Live/behavioral: against a real single-platform manifest digest
#      (alpine:3.20's own linux/amd64 manifest -- small, stable, public,
#      unrelated to any OmniBioAI release artifact), the correct casing
#      must succeed and the incorrect casing must fail with exactly the
#      error this defect produced in production.
#
# Requires: docker buildx, python3. Network access to Docker Hub (for the
# live check only -- manifest/config JSON fetch, no image pull).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERIFIER="${REPO_ROOT}/scripts/ci/verify_release_image.sh"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

echo "== Static check: verifier uses correct Go field casing =="
grep -q '{{json \.Image\.config\.Labels}}' "$VERIFIER" \
  && fail "verify_release_image.sh still contains the invalid lowercase '.Image.config.Labels' -- this is the exact defect that blocked v0.7.4"
grep -q '{{json \.Image\.Config\.Labels}}' "$VERIFIER" \
  || fail "verify_release_image.sh does not contain the correct '.Image.Config.Labels' -- expected exactly one occurrence"
echo "PASS: verify_release_image.sh uses .Image.Config.Labels, not .Image.config.Labels"

echo "== Live check: resolving a stable public single-platform digest fixture =="
FIXTURE_DIGEST="$(docker buildx imagetools inspect alpine:3.20 --raw | python3 -c '
import json, sys
d = json.load(sys.stdin)
for m in d["manifests"]:
    p = m.get("platform", {})
    if p.get("architecture") == "amd64" and p.get("os") == "linux":
        print(m["digest"])
        break
')"
[ -n "$FIXTURE_DIGEST" ] || fail "could not resolve a linux/amd64 manifest digest from alpine:3.20"
echo "Fixture digest (alpine:3.20 linux/amd64): ${FIXTURE_DIGEST}"

echo "== Correct casing must succeed against a real single-platform digest =="
docker buildx imagetools inspect "alpine@${FIXTURE_DIGEST}" --format '{{json .Image.Config.Labels}}' >/dev/null 2>&1 \
  || fail "the corrected template '.Image.Config.Labels' failed against a real manifest digest -- regression"
echo "PASS: .Image.Config.Labels resolves successfully"

echo "== Incorrect casing must fail with the exact production error =="
BUGGY_OUTPUT="$(docker buildx imagetools inspect "alpine@${FIXTURE_DIGEST}" --format '{{json .Image.config.Labels}}' 2>&1)" && \
  fail "the buggy template '.Image.config.Labels' unexpectedly succeeded -- fixture no longer distinguishes the defect"
echo "$BUGGY_OUTPUT" | grep -q "can't evaluate field config in type \*v1.Image" \
  || fail "buggy template failed, but not with the expected error message: ${BUGGY_OUTPUT}"
echo "PASS: .Image.config.Labels reproduces the exact v0.7.4 production error"

echo "PASS: verify_release_image.sh's OCI-label template defect is fixed and the fixture correctly distinguishes buggy from correct behavior"
