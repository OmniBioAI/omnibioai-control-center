# Backend regression — Master V1

Environment: `/tmp/omnibioai-control-center-system-312`, Python 3.12.3,
pytest 9.1.1; configured backend coverage threshold 98%.

## Current integrated results

Focused post-change Discord/router/IAM/recovery/integration command:

```text
PYTHONPATH=backend/src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q --no-cov -o addopts='' backend/tests/test_discord.py backend/tests/test_discord_routing.py backend/tests/test_discord_events.py backend/tests/test_discord_event_client.py backend/tests/test_discord_iam_api.py backend/tests/test_discord_process_crash.py backend/tests/test_github_discord_event_adapter.py backend/tests/test_support_discord_publisher.py backend/tests/test_routes_integrations.py
152 passed, 5 warnings, 2 subtests passed
```

Full suite from `backend/` after the fail-closed change:

```text
PYTHONPATH=src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q --tb=short
2,242 passed, 601 warnings, 74 subtests passed
9,174 statements; 183 missed; 98.01% coverage
```

The backend's configured 98% threshold passed exactly. The earlier ordinary
sandbox attempt had 13 socket-fixture `PermissionError` failures and 97.95%
coverage because local test servers could not bind/connect; the same full suite
was rerun with loopback access enabled and passed. This was a local test
execution boundary, not an application/test assertion failure.

Baseline comparison: V10-D reported 2,239 passed at 98.01%; this integration
adds three explicit fail-closed tests, improves two recovery boundary tests,
and changes one source branch, resulting in 2,242 passed at 98.01%. Current
source is still an uncommitted overlay on HEAD
`f37ce8c952f917f607e9923cbb47dda8b0406a7a`. Tests were not weakened. Full
output is not retained as a repository artifact; these exact commands and
summaries are recorded here. `git diff --check` passed for the integrated
source files.
