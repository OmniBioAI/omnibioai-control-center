# Storage Dashboard release qualification V3

## Candidate and validation

This candidate adds host mount-table access through read-only binds at
`/run/host-storage/mountinfo` and `/run/host-storage/fstab`. The collector
does not fall back to `/proc/self/mountinfo` or the container's `/etc/fstab`.
Capacity remains unknown because container `statvfs` values cannot be treated
as host capacity. Storage source status remains `PARTIAL` until host capacity
and provenance are independently validated.

The report CLI permits public report generation without an access token. The
protected license section skips its request when the token is absent, and
operator session access checks remain required before protected work.

`scripts/verify_python_sources.py` compiles all backend source, test, and script
Python files. Its only exclusion is the tracked concatenation artifact
`backend/src/control_center/combined_control_center.py`, and it verifies the
artifact marker before excluding it.

## Restic status

The candidate supports bounded, read-only Restic snapshot listing only when an
operator configures an approved repository bind and password-file bind. The
host repository could not be read by the qualification account, and no
configured password-file path was found. Snapshot visibility is therefore
unverified; do not deploy with Restic enabled until access is approved and
validated. Never put a password in Compose, shell arguments, or this document.

## Candidate Compose overlay

`ops/storage-dashboard-v3.compose.yml` pins only `control-center` and
`control-center-web` to candidate image tags and adds the two read-only host
mount-table binds. Keep the existing release pin in the Compose file list
before this overlay. The overlay belongs to this release candidate and does
not modify the active production pin file.

## Deployment procedure (requires separate approval)

Run from `omnibioai-studio` after the approval gate. First verify the exact
candidate tags and rollback image IDs recorded in the release qualification
report. Validate the merged Compose configuration with `docker compose config`
and inspect only the two target services. Then deploy the backend first and
the web image second, without dependencies, pulls, or builds:

```sh
docker compose -f docker-compose.yml \
  -f docker-compose.override.yml \
  -f ../release-candidates/compose.release-pin.yml \
  -f ../.worktrees/storage-dashboard-auth-v2/ops/storage-dashboard-v3.compose.yml \
  up -d --no-deps --no-build --pull never control-center
docker compose -f docker-compose.yml \
  -f docker-compose.override.yml \
  -f ../release-candidates/compose.release-pin.yml \
  -f ../.worktrees/storage-dashboard-auth-v2/ops/storage-dashboard-v3.compose.yml \
  up -d --no-deps --no-build --pull never control-center-web
```

Compose resolves relative files from its project directory. Preserve the
existing project name and `.env` inputs when running those commands. After each
service becomes healthy, verify the corresponding immutable image ID and
healthcheck before continuing. If the backend fails, roll it back before
touching the web service.

## Rollback procedure (requires separate approval if deployed)

Use the preserved rollback image IDs and candidate override ordering. Create a
temporary rollback Compose overlay that sets `control-center` and
`control-center-web` to local tags whose inspected image IDs match the recorded
pre-deployment IDs, with `pull_policy: never` and `build: !reset null`. Then
run the same two commands with that overlay after the candidate overlay,
deploying `control-center` first and `control-center-web` second. Verify both
running containers report the original IDs. Do not write either image into
the production release pin as part of rollback.

## Post-deployment acceptance

1. Both services are healthy and use the approved image IDs.
2. Admin login, MFA enrollment/challenge/recovery, session refresh/revocation,
   invitations, licensing checks, and reverse-proxy routes pass smoke checks.
3. Storage navigation is visible only to an account with
   `platform.manage_infra`; API requests without that permission return the
   expected denial.
4. Host storage roles match host `/proc/1/mountinfo` and `/etc/fstab`; capacity
   is not reported until measured from a verified host namespace.
5. Restic snapshots appear only after approved read-only repository and
   password-file access is configured; otherwise the source remains
   unavailable without exposing credentials.
6. Existing Control Center Admin and Control routes still render and their
   proxy requests reach the expected backend routes.
