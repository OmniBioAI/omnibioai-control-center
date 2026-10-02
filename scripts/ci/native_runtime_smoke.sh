#!/usr/bin/env bash
# Native, post-publication runtime smoke for one architecture of one
# Control Center release image. Resolves the exact architecture digest
# from the REAL published OCI index (never a cached build-job digest),
# pulls and runs exactly that immutable artifact, asserts the container
# is actually running on the architecture it claims, and exercises the
# smallest meaningful, safe, no-credential checks proven during the
# original audit. No production credentials, no production database,
# no production Redis, no production platform dependency of any kind.
#
# Usage:
#   native_runtime_smoke.sh <backend|frontend> <image-repo> <version> <expect-uname>
#
# Requires: docker buildx, jq, curl.

set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: $0 <backend|frontend> <image-repo> <version> <expect-uname>" >&2
  exit 2
fi

KIND="$1"
IMAGE="$2"
VERSION="$3"
EXPECT_UNAME="$4"
REF="${IMAGE}:${VERSION}"

case "$EXPECT_UNAME" in
  x86_64) ARCH=amd64 ;;
  aarch64) ARCH=arm64 ;;
  *) echo "FAIL: unknown expect-uname '$EXPECT_UNAME' (expected x86_64 or aarch64)" >&2; exit 1 ;;
esac

case "$KIND" in
  backend) PORT=7070 ;;
  frontend) PORT=5174 ;;
  *) echo "FAIL: unknown kind '$KIND' (expected backend or frontend)" >&2; exit 1 ;;
esac

CONTAINER="cc-release-smoke-${KIND}-${ARCH}-$$"
HOST_PORT=$((20000 + RANDOM % 10000))

cleanup() {
  docker logs "$CONTAINER" 2>&1 | tail -100 || true
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

echo "== Resolving native linux/${ARCH} runtime digest from ${REF} =="
RAW_INDEX="$(docker buildx imagetools inspect "$REF" --raw)" || fail "could not inspect ${REF}"
DIGEST="$(jq -r --arg arch "$ARCH" '
  .manifests[]
  | select(.platform.architecture == $arch and .platform.os == "linux")
  | select((.annotations["vnd.docker.reference.type"] // "") != "attestation-manifest")
  | .digest
' <<<"$RAW_INDEX" | head -1)"
[ -n "$DIGEST" ] || fail "no linux/${ARCH} runtime manifest found in ${REF}"
echo "Resolved digest: ${DIGEST}"

PULL_REF="${IMAGE}@${DIGEST}"
echo "== Pulling exact immutable artifact ${PULL_REF} =="
docker pull "$PULL_REF" || fail "pull failed for ${PULL_REF}"

echo "== Starting disposable container (no production config/secrets) =="
docker run -d --name "$CONTAINER" -p "${HOST_PORT}:${PORT}" "$PULL_REF" >/dev/null \
  || fail "docker run failed for ${PULL_REF}"

echo "== Asserting native architecture inside the running container =="
ACTUAL_UNAME="$(docker exec "$CONTAINER" uname -m)" || fail "could not exec uname -m in ${CONTAINER}"
[ "$ACTUAL_UNAME" = "$EXPECT_UNAME" ] \
  || fail "container reports '${ACTUAL_UNAME}', expected native '${EXPECT_UNAME}' -- possible emulation"
echo "Native architecture confirmed inside container: ${ACTUAL_UNAME}"

wait_for_http() {
  local url="$1" tries=30
  while [ "$tries" -gt 0 ]; do
    if curl -sf -o /dev/null "$url"; then
      return 0
    fi
    if ! docker ps --filter "name=${CONTAINER}" --filter status=running -q | grep -q .; then
      fail "${CONTAINER} exited before becoming ready (see captured logs above)"
    fi
    tries=$((tries - 1))
    sleep 1
  done
  return 1
}

if [ "$KIND" = backend ]; then
  echo "== Waiting for GET /health =="
  wait_for_http "http://127.0.0.1:${HOST_PORT}/health" || fail "backend /health never became ready"

  HEALTH_BODY="$(curl -sf "http://127.0.0.1:${HOST_PORT}/health")"
  echo "$HEALTH_BODY" | jq -e '.status == "ok"' >/dev/null \
    || fail "GET /health returned unexpected body: ${HEALTH_BODY}"
  echo "GET /health -> 200 {\"status\":\"ok\"} OK"

  ROOT_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${HOST_PORT}/")"
  [ "$ROOT_STATUS" = "401" ] || fail "GET / returned ${ROOT_STATUS}, expected 401 (permission gate must be enforced)"
  echo "GET / -> 401 (permission gate enforced) OK"

  METRICS_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${HOST_PORT}/metrics")"
  [ "$METRICS_STATUS" = "200" ] || fail "GET /metrics returned ${METRICS_STATUS}, expected 200"
  echo "GET /metrics -> 200 OK"

elif [ "$KIND" = frontend ]; then
  echo "== Waiting for GET / =="
  wait_for_http "http://127.0.0.1:${HOST_PORT}/" || fail "frontend / never became ready"

  ROOT_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${HOST_PORT}/")"
  [ "$ROOT_STATUS" = "200" ] || fail "GET / returned ${ROOT_STATUS}, expected 200"

  ROOT_BODY="$(curl -sf "http://127.0.0.1:${HOST_PORT}/")"
  grep -qi '<html' <<<"$ROOT_BODY" \
    || fail "GET / returned 200 but body does not look like the built SPA (no <html> found)"
  echo "GET / -> 200, SPA index.html served OK"

  if ! docker ps --filter "name=${CONTAINER}" --filter status=running -q | grep -q .; then
    fail "nginx container is not running after serving the root request"
  fi
  echo "nginx process still running after request OK"
fi

echo "PASS: native linux/${ARCH} ${KIND} runtime smoke succeeded for ${PULL_REF}"
