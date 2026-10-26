# Discord master release baseline — V1

Observed: 2026-10-25, from `/home/manish/Desktop/omnibioai-ecosystem/omnibioai-control-center`.

## Environment and source identity

- Host: `spark-c275`; Linux `aarch64`; kernel `7.0.11-nvidia`; shell user `1000:1000`.
- Control Center HEAD: `f37ce8c952f917f607e9923cbb47dda8b0406a7a` (`main`).
- Parent ecosystem HEAD: `24f92ed8547e063b91aecefc84ad962b95c28a16`.
- Control Center worktree is dirty: router and related backend/test edits plus
  untracked Discord source, tests, scripts, workflows, and evidence. These are
  preserved as existing user work; no reset, staging, commit, or deployment
  was performed.
- At initial reconciliation, before the Master V1 fail-closed source change,
  the Docker qualification source tree reproduced the independently reviewed
  V11.6 digest:
  `80d620eb86bcb426a504e3c5087be583dd2c2af3af76bd6e58950ddbf8bedc1e`.
- Current V11 source inventory file SHA-256 is
  `bbf9a16297c9376fe197e791722b36a8bb165fd0ec4b349aae22a891ee92dec1`;
  this differs from the historical `5636320f...` reference because the V11.6
  closure/review records were finalized afterward. The current inventory,
  primary harness manifest, and V4 completion manifest verify successfully.
- V11.6 independent review: PASS for static harness safety; this is not Docker
  runtime evidence. See `docs/evidence/discord-v11/independent-review.md`.

## Docker qualification access

The current shell is not in the socket's owning Docker group: user groups are
`1000,65534`, while `/var/run/docker.sock` is mode `0660`, owner `65534:65534`.
`DOCKER_HOST` is unset. The prior V4 Docker access report records a denied API
call in this shell and requires an already-authorized operator shell; no
privilege escalation, socket permission change, or daemon query was attempted
for this baseline. Therefore no DGX Docker preflight passed and no Docker
qualification was run.

## Evidence discovered

Present historical/current evidence includes:

- `docs/evidence/discord-v7/` through `discord-v12/` (V12 readback closure is
  static/local evidence, not production identity verification).
- `docs/evidence/discord-docker-qualification-v1/` and
  `docs/evidence/discord-docker-qualification-v1/v4-completion/`.
- `docs/evidence/track-a/` through `docs/evidence/track-f/`.
- No `docs/evidence/discord-master-v1/` artifacts existed before this baseline.

Historical acceptance currently reports 4/12 gates, revising earlier 3/12
reports by adding G8 (full backend regression at or above 98% coverage). The
track-D report records 2,239/2,239 backend tests and 98.01%, 138 focused
Discord/IAM/recovery tests, 41/41 harness tests, 18/18 crash scenarios
reviewed, 14/14 applicable Docker-free scenarios, 0/14 Docker-backed recovery,
0/6 Docker E2E, and no production readbacks/canaries. Fresh Agent E verification
later passed at 2,242/2,242 and 98.01%; see `BACKEND_REGRESSION.md`.

## Current release-critical state

- Live destinations: 0/6 verified; live source runtimes: 0/7 qualified.
- ARM64 host architecture is observed, but candidate source-to-image provenance
  is FAIL and no compatible rollback image/rehearsal is established.
- Live canaries: 0/6; explicit deployment approval: absent.
- Production remains unchanged. No Discord messages were sent.

This baseline separates historical reports, current static checks, current
Docker-free tests, Docker runtime evidence, production readbacks, and canary
evidence. Subsequent artifacts in this directory must identify their source
revision and evidence type explicitly.
