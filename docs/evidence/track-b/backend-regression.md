# Track B backend regression evidence

Date: 2026-10-25 (America/Chicago)

Candidate repository commit: `f37ce8c952f917f607e9923cbb47dda8b0406a7a`
(dirty workspace preserved; this result qualifies the source tree as present at
execution time, not the commit by itself).

## Environment

- Interpreter: CPython 3.12.3 at
  `/tmp/omnibioai-control-center-system-312/bin/python`.
- Isolation: Python virtual environment with system site packages disabled.
- Dependency health: `python -m pip check` returned
  `No broken requirements found.`
- Application install: editable `omnibioai-control-center==0.1.0` from
  `backend/`.
- Exact package versions: `backend/requirements-test.lock`.
- Configured test gate: `backend/pyproject.toml`, including
  `--cov-fail-under=98`; the threshold and tests were not weakened.
- Linux test event loop: the existing `backend/tests/conftest.py` selects
  `uvloop` when installed, matching the supported `uvicorn[standard]` runtime.

The test lock is sufficient to reproduce the qualified version set on a
compatible Python 3.12/Linux package index. It intentionally does not claim
artifact-integrity reproducibility; a release build still needs a hash-bearing
lock/wheelhouse attestation.

## Historical 13-failure diagnosis

The restricted environment run reproduced the historical result exactly:

```text
13 failed, 2221 passed, 601 warnings, 72 subtests passed in 25.75s
FAIL Required test coverage of 98% not reached. Total coverage: 97.95%
```

All 13 failures were `PermissionError: [Errno 1] Operation not permitted` at
`socket.socket(AF_INET, ...)`. They comprise six TCP/HTTP check tests, four
runner tests that invoke TCP checks, and three summary-client loopback HTTP
tests. This execution sandbox prohibits socket creation. The failures are an
execution-context restriction, not missing packages or backend regressions.

No tests were skipped, mocked away, or changed to turn these failures green.
The unchanged suite was rerun in an authorized host context permitting local
loopback sockets. Docker was not invoked.

## Fresh full regression

Command, run from `backend/`:

```bash
PYTHONPATH=src /tmp/omnibioai-control-center-system-312/bin/python \
  -m pytest -q --tb=short
```

Result:

```text
2234 passed, 601 warnings, 72 subtests passed in 30.39s
TOTAL 9157 statements, 183 missed, 98%
Required test coverage of 98% reached. Total coverage: 98.00%
```

Exit status: `0`.

Track B status: **PASS** for the Control Center backend regression and existing
98% coverage gate. This is not cross-repository regression evidence and does
not imply Docker or production qualification.
