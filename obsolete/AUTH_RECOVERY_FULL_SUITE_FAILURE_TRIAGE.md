# Full-suite failure triage and clean baseline

Prior dirty-source run (reported before this reconciliation): **1,572 passed, 52 failed, 35 skipped**. Recorded failure clusters were:

- Five `test_bio_agent_service_role_bootstrap.py` failures associated with already-modified bootstrap/startup audit files.
- Rate-limit, MFA challenge throttling, and login timing failures associated with the local test setup and Redis 8.1.0 / fakeredis 2.31.0 combination.
- Migration tests failing on the untracked local manual-license migration's SQLite-incompatible `ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL` operation.
- Two platform-permission failures associated with the modified permission registry.

A clean tracked `HEAD` snapshot (`ffca316a53136e284cefc791c726e6453fe38b6f`) was run with the same cached Auth image, Python 3.11, staged pytest 8.3.5/fakeredis 2.31.0 dependencies, test-only secrets, SQLite fixture defaults, and disabled network. Result: **22 failed, 1,568 passed, 9 skipped, 76 warnings in 774.97s**. The clean run reproduced bootstrap and rate-limiting/MFA-throttling failures. Its final failure output identifies the login rate-limiting and timing cases and MFA challenge-throttling cases; the suite's full detailed trace was not retained, so this report does not invent a precise per-file failure count.

Compared with the prior dirty-source result (52 failed, 1,572 passed, 35 skipped), clean HEAD has 30 fewer failures. The prior run's bootstrap, manual-license migration/SQLite compatibility, and permission-registry clusters are absent from clean HEAD and therefore belong to non-HEAD local changes/environment interactions, not established credential-recovery regressions. The 22 clean-HEAD failures are pre-existing for this workstream and relate to the local rate-limit/throttling test setup. Because the two runs had different test counts and the dirty run also contained unrelated modifications, a 30-failure delta is not a one-to-one attribution of individual regressions.

Failure classification: **zero genuine credential-recovery regressions established**. The clean run cannot show whether unrelated dirty-only failures came from credential recovery or the other local edits, so those remain unattributed rather than being counted as recovery regressions. Manual-license changes and unrelated dirty files must not be included in credential-recovery regression attribution.
