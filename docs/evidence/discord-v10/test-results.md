# Discord V10 test and validation results

Date: 2026-10-24. Results are from the current dirty multi-repository
worktree; historical V2/V8/V9 results are not included as V10 passes.

## Environment

- Host: `spark-c275`, Linux `aarch64`; hardware model not verified. No
  container marker was present. Docker CLI/context exist, but daemon access
  from this session is denied.
- Python: system Python 3.14.7; system pytest 9.1.1. System environment lacks
  pytest-asyncio, pytest-cov/coverage, FastAPI, Starlette, and python-dotenv.
- Control Center `.venv`: Python 3.14.7; pytest is absent. It contains
  FastAPI 0.143.0, Starlette 1.7.0, cryptography 50.0.2, and
  prometheus-fastapi-instrumentator 8.1.0, which do not match the backend's
  declared FastAPI 0.115.12, Starlette `<1`, cryptography 46.0.3, and
  instrumentator 7.1.0 constraints.
- No Python lockfiles were found for Control Center, RAG, Workbench, or
  Videos. Their dependency declarations are ranges/requirements, not a
  reproducible resolved lock.
- An isolated `/tmp` environment was created. Installing backend dev extras
  from `backend/pyproject.toml` failed before dependency installation because
  this session cannot resolve `pypi.org`. No project or production Python
  environment was modified by the failed install.

## Executed commands

| Command / suite | Result | Notes |
|---|---|---|
| `PYTHONPATH=src python3 -m pytest -o addopts= -q --tb=short tests/test_discord.py tests/test_discord_event_client.py tests/test_discord_events.py tests/test_discord_process_crash.py tests/test_discord_routing.py tests/test_github_discord_event_adapter.py tests/test_support_discord_publisher.py` (Control Center `backend/`) | **119 passed** | Current focused Discord, source contract, event-store, IAM-independent and process tests; no failures |
| `PYTHONPATH=src python3 -m pytest -o addopts= -q --tb=short tests/test_discord_process_crash.py` (Control Center `backend/`) | **7 passed** | Subprocesses terminate against temporary SQLite state; included in the 119 above |
| `python3 -m pytest -o addopts= -q --tb=short tests/test_discord_publication.py` (Videos) | **6 passed** | Mocked signed publication contract, not live delivery |
| `python3 -m pytest -o addopts= -q --tb=short tests/test_discord.py` (RAG) | **2 passed; 8 blocked by runner** | Global pytest lacks async plugin; coroutine tests were not executed. Three unknown-asyncio-mark warnings |
| `python3 -m pytest -o addopts= -q --tb=short discord_tests/test_discord_events.py` (Workbench) | **Blocked before collection** | Django setup cannot import `dotenv`; requirements now names `python-dotenv`, but install is unavailable |
| V8 runner `python3 scripts/qualify_discord_v8.py --mode isolated-tests --timeout 600` | **Backend NOT RUN; in-process mock flow PASS** | Runner's project `.venv` reports `No module named pytest`; mock reports six routes, three community exclusions, signatures, durable approval, mock delivery, and duplicate suppression. Not Docker E2E |
| IAM/API suite included in focused collection attempt | **Not run** | Collection error: system Python has no FastAPI. No current V10 IAM pass |
| `python3 scripts/verify_python_sources.py` | **PASS** | Compiled 272 files; excludes only known tracked `combined_control_center.py` concatenation artifact |
| `bash -n` for ecosystem build, docs deploy, and five Control Center CI scripts | **PASS** | No live script execution |
| `docker compose config --quiet` (Studio) | **PASS** | Static Compose validation; one unrelated unset `NCBI_API_KEY` warning. Does not inspect daemon/container values |
| V8 read-only `--mode inspect --timeout 10` | **BLOCKED** | aarch64/default context; Docker daemon permission denied; no containers or image provenance read |
| `git diff --check` in Control Center and workspace parent | **PASS** | No whitespace errors |
| V8 and V9 `sha256sum -c SHA256SUMS` | **PASS** | Historical evidence preserved and checksums verified |

The full backend regression and coverage were **not run**. The V8 runner
attempted to invoke the Control Center virtualenv, but pytest was absent. The
separate dependency restore could not reach PyPI. Therefore V8's 2,224 tests
and 98.01% coverage remain historical; no V10 coverage percentage is
available. No test result here qualifies production configuration or live
Discord delivery.

## Reliability assertions represented in passing tests

- All 11 central event mappings resolve to their fixed destinations; the six
  automated channels route with mocked Discord 2xx responses.
- Invalid JSON/types, unknown/community channel names, non-HTTPS/unapproved
  hosts, malformed paths/ports, and duplicate webhook IDs are rejected.
- The legacy alerts credential remains an alerts-only fallback; its ID may
  not alias another mapped channel even when an explicit alerts mapping
  overrides it.
- Mocked 401/403 permanent rejection does not retry; 429 honors bounded
  `Retry-After`; 5xx/read timeout becomes ambiguous and is not blindly
  retried; connect failure is bounded; failures remain channel-local.
- Stable event IDs suppress duplicate delivery. DLQ records contain only
  safe metadata/hash, webhook secrets are redacted, event payload mentions
  are suppressed, and store/receipt tests cover approval, reconciliation,
  and explicit local replay.
- Process tests terminate workers before persistence, after claim/before
  HTTP, during mocked submission, and after mocked remote acceptance before
  receipt; cover restart, concurrent claims, retry-worker termination, and
  locked database fail-closed behavior. These use real processes and
  temporary durable SQLite but a mocked remote transport.

IAM-protected replay authorization, live channel permissions, and the full
container/API crash-recovery stack remain unverified because current IAM
dependencies and Docker access are unavailable.
