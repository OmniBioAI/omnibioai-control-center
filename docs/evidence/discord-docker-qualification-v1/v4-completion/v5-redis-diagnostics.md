# V5 Redis diagnostic capture implementation

Workstream: `OMNIBIOAI_DISCORD_REDIS_DIAGNOSTICS_V5`

## Change

Updated the existing `scripts/discord-docker-qualification/run_qualification.py`; no replacement harness was created. In the existing run `finally` path, Redis diagnostics are attempted before `finalize_run`. Resource discovery is filtered by this run ID, then checked against the ownership manifest's project, exact Compose Redis name/service, workstream/run/disposable labels, and full immutable container ID. The ID is re-inspected and ownership revalidated before state/log reads. A verified ID is recorded in the existing ownership manifest.

The capture records only container state, exit code, health, OOM status, bounded stdout/stderr from the ID-scoped Docker `json-file` log, and redacted error/status metadata. It never inspects or records container environment variables. The log tail is limited to 64 KiB before parsing; each persisted stream is capped at 16 KiB. Known synthetic values from this run's mode-0600 Compose env are loaded only in memory for redaction; Discord webhook URL patterns and credential-shaped fields are also redacted. Outer run-error and ownership/cleanup diagnostic evidence applies the same redaction.

The diagnostics artifact is written at `docs/evidence/discord-docker-qualification-v1/redis-diagnostics.json`, including `NOT_FOUND` and partial collection states. Collection errors are passed separately to `ownership-verification.json`. The existing finalizer still independently attempts ownership-limited cleanup and after-inventory/protected-resource comparison even if diagnostics fail.

## Tests and checks

- Syntax: `python3 -m py_compile scripts/discord-docker-qualification/run_qualification.py scripts/discord-docker-qualification/test_ownership.py` — PASS.
- Docker-free tests: `python3 -m unittest discover -s scripts/discord-docker-qualification -p 'test_*.py' -v` — **24 passed, 0 failed**.
- The suite includes successful redacted/bounded capture, missing and ambiguous Redis, discovery and immutable-ID ownership mismatch, log retrieval failure, cleanup/after-inventory after diagnostic failure, and exception-evidence redaction.
- `git diff --check` — PASS.

## Scope boundary

No Docker command/container was run for V5. Redis startup is not claimed fixed and Docker E2E remains unverified. No production services, Discord destinations, credentials, or Docker permissions were touched.

## Fresh independent safety review

Reviewer: separate `/root/v5_safety_review` agent; review performed after final code/test changes. No Docker invoked.

| Finding | Result | Basis |
|---|---|---|
| Exact ownership validation | PASS | Run-label discovery; project/service/name/workstream/run/disposable validation; full immutable-ID reinspection; ambiguous or mismatched targets rejected before state/log access |
| Secret redaction | PASS | No Config.Env access; run secrets are memory-only redaction inputs; webhook/credential-shaped values redacted; run-error and cleanup evidence also sanitized |
| Diagnostic bounds | PASS (V5 implementation superseded by V6) | V5 briefly used a Docker-managed log file path; V6 removes that access and retrieves output through `docker logs` by the verified full ID |
| Exceptional paths | PASS | Capture attempted in existing `finally` before cleanup for startup failure, router non-readiness, runner result, and exceptions |
| Cleanup/after-inventory | PASS | Diagnostic failures remain separate; finalizer independently attempts ownership cleanup and after-inventory/protected comparison |
| Docker-free tests | PASS | All 24 existing and new harness tests pass, including requested failure cases |
| Independent safety review | PASS | Fresh final review approved current diff |

Review outcome: **PASS — ready for execution by an already authorized DGX Docker operator**. This is not a Redis runtime fix or E2E pass. The operator command is `python3 scripts/discord-docker-qualification/run_qualification.py`, from repository root and only in the authorized terminal; no Docker run was performed in V5.
