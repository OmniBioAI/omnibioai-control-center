# Disposable Discord qualification architecture

The harness builds a run-labeled ARM64 image by overlaying the current workspace's `backend/src/` onto the locally inspected Control Center base image. The actual FastAPI process is launched as `control_center.main:app`; `DiscordPublisher` and its SQLite delivery ledger are real application code. A synthetic HTTPS receiver replaces only Discord's external webhook service. An isolated Redis is included because the IAM implementation can use Redis, but current E2E does not exercise jti revocation.

Compose defines a unique project, an internal-only network, one disposable named volume, five bounded services, no published host ports, and no Docker socket. Test credentials and a private test CA are generated in a mode-0700 run directory under `/tmp`; they are not production credentials. The test runner submits signed HTTP events, requests IAM-protected approvals, and verifies receiver payloads and SQLite state.

The architecture is synchronous: event ingest, durable event record, approval, and outbound webhook call run through the actual API/publisher. There is no queue/worker in the current source architecture. Therefore queue interruption, worker-crash, and queue-reconciliation cases from broad candidate lists cannot be asserted as behavior of this service. No candidate behavior has been replaced by an in-process mock.

Static validation performed: `python3 -m py_compile scripts/discord-docker-qualification/*.py`; `docker compose -f scripts/discord-docker-qualification/compose.yaml config --no-interpolate --quiet`; `git diff --check -- scripts/discord-docker-qualification`. These passed. Docker qualification has not run because the independent safety review has not yet passed.
