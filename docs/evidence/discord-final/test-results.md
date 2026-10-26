# Discord final workstream — test results

Date: 2026-10-24. Counts below are from this current dirty candidate, not V2,
V8, or V9 historical evidence.

## Environment

- Host `spark-c275`, Linux aarch64; DGX hardware identity not confirmed.
- System Python 3.14.7; an existing `/tmp/omnibioai-control-center-system-312`
  Python 3.12.3 environment was used for the current complete CC suite. It
  contains pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0, coverage
  7.16.2, FastAPI 0.115.12, Starlette 0.46.2, HTTPX 0.28.1, cryptography
  46.0.3, and prometheus-fastapi-instrumentator 7.1.0. It was already present;
  no dependency installation or production environment change occurred.
- No repository lockfiles were found for Control Center, RAG, Workbench, or
  Videos. The Python 3.12 environment is a compatible existing environment,
  not a committed hash-locked cross-repo environment.
- Docker context `default`; daemon access denied. Discord admin and approved
  secret-manager interfaces unavailable.

## Executed suites

| Repository / command | Result | Qualification note |
|---|---|---|
| Control Center backend: `PYTHONPATH=src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q --tb=short` | **2,234 passed; 0 failed; 72 subtests passed; 98.00%** | Full suite; run with approved non-sandbox execution because the sandbox denies local socket creation in existing TCP/HTTP probe tests. 601 warnings. |
| Control Center Discord IAM: `PYTHONPATH=src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -o addopts= -q --tb=short tests/test_discord_iam_api.py` | **15 passed** | Isolated API/IAM tests; one upstream Starlette deprecation warning. Included in full backend result; do not add counts twice. |
| Control Center focused Discord/source/process suite | **119 passed** | Included in full backend count. Seven subprocess termination tests use temporary SQLite and mocked Discord transport. |
| RAG focused Discord: existing RAG env, `python -m pytest -o addopts= -q --tb=short tests/test_discord.py` | **10 passed** | Focused module only; environment contains versions outside current RAG dependency constraints. |
| RAG full suite: same existing RAG env, `python -m pytest -o addopts= -q --tb=short` | **Blocked at collection: 12 errors** | Missing `iam_client`, `python-dotenv`, `ollama`, and other declared packages. |
| Workbench focused Discord: existing test env with ephemeral `DJANGO_SECRET_KEY`, `python -m pytest -o addopts= -q --tb=short discord_tests/test_discord_events.py` | **12 passed** | SQLite in-memory test settings; test key was process-local and not stored. |
| Workbench full suite: same test env, `python -m pytest -o addopts= -q --tb=short` | **Blocked at collection: 351 errors** | Dependency gaps and duplicate test module basenames prevent full collection. |
| Videos Discord publication: `/tmp/videos-test-venv/bin/python -m pytest -o addopts= -q --tb=short tests/test_discord_publication.py` | **6 passed** | Signed mock publication only. |
| Videos full suite: `/tmp/videos-test-venv/bin/python -m pytest -o addopts= -q --tb=no` in approved non-sandbox test context | **312 passed, 16 skipped, 2 xfailed, 0 failed, 39 errors** | Loopback-dependent tests pass outside the sandbox. Remaining errors require the absent Playwright Chromium executable. Not accepted as full regression. |
| `python3 scripts/verify_python_sources.py` (Control Center) | **PASS** | Compiled 272 Python source files; only the known concatenation artifact excluded. |
| Bash syntax for Docs deploy, Utils build, five CC CI scripts | **PASS** | Syntax only; no deploy scripts executed. |
| Studio `docker compose config --quiet` | **PASS** | Static validation only; unrelated unset `NCBI_API_KEY` warning. |
| Docker read-only inspector | **BLOCKED** | Daemon denied access; no images/containers inspected. |
| Git diff checks | **PASS** | `git diff --check` in workspace and Control Center. |

## Test accounting

Unique passing tests across the reported runs: **2,568** (2,234 CC + 10 RAG
focused + 12 Workbench focused + 312 Videos full suite); the 72 CC subtests
are reported separately. No duplicate targeted CC/IAM or Videos Discord
counts were added. The Videos suite has 39 browser setup errors because the
Playwright Chromium executable is absent. RAG's 12 and Workbench's 351
collection errors also remain blocked, not passed. Cross-repository full
regression is therefore BLOCKED, despite the complete CC backend and
publisher-focused suites passing.

The full CC suite first ran inside the restricted sandbox and reported 13
socket-permission failures at 97.95% coverage. The same unmodified suite was
then run in the approved test execution context; all tests passed and coverage
reached 98.00%. The first restricted run is superseded, not counted as a code
failure.

Historical evidence integrity: V8's preserved SHA256SUMS verifies. V9's
qualification checksum verifies, but its preserved SHA256SUMS also hashes the
shared runbook; that entry no longer matches because the runbook was extended
for V10 and final closure. The original V9 checksum file was not rewritten.
The current runbook is covered by this final evidence set's SHA256SUMS.
