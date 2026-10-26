# Backend regression — V4

No full backend regression was completed in V4. Historical result retained as historical only: 2,221 passed, 13 environment-related loopback/socket failures, coverage 97.95%; target is at least 98.00%.

V4 attempts:

1. System Python `python3 -m pytest ...` could not load the repository test configuration because pytest-cov options (`--cov=...`) are unsupported in that environment.
2. System Python with `PYTHONPATH=src` and a temporary pytest `addopts` override then failed collection because `fastapi` is missing. No source tests were changed or skipped to conceal the failure.
3. The repository `.venv` Python does not have pytest installed.
4. The independent harness unit suite did run: `python3 -m unittest discover -s scripts/discord-docker-qualification -p 'test_*.py' -v` — **16 passed, 0 failed**. These fake-Docker tests are not backend regression or Docker qualification.

V4 backend totals: passed `NOT_ESTABLISHED`; failed `NOT_ESTABLISHED` (collection/environment failure, no assertion failures reported); coverage `NOT_MEASURED`. Install/use the repository's pinned test environment through an approved reproducible dependency workflow, then rerun the full suite without changing tests or coverage thresholds.
