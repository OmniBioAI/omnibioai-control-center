# Regression execution

Date: 2026-10-24. Environment: `spark-c275`, `aarch64`. Docker read-only
access is available through the permitted execution mechanism. Python 3.12.3
environment: `/tmp/omnibioai-control-center-system-312`; no packages or
lockfiles changed.

| Command / suite | Result | Notes |
|---|---|---|
| Focused eight-file Discord/IAM/process pytest command | **134 passed**, 1 warning, 3.21s | Fresh route, IAM, signing, publisher, and seven subprocess tests |
| V8 `isolated-tests` backend run with the Python 3.12 environment | 2,221 passed, 13 failed, 72 subtests; **97.95%** | All 13 failures are sandbox-denied TCP/HTTP loopback tests; runner FAIL |
| V8 `disposable-mock-flow` | PASS: 6/6 routes, 3/3 exclusions | In-process mock only; not Docker E2E |
| V8 `inspect` | Host/image inventory PASS; overall NOT_VERIFIED | Docker 29.6.2/aarch64; source provenance absent, so exit 1 by design |

The prior approved-context backend result of 2,234 passed and 98.00% is
historical and is not substituted for this run. Cross-repository full suites
were not rerun; their dependency/collection/Playwright blockers remain. G8 is
BLOCKED. No test was skipped or weakened to obtain a pass.
