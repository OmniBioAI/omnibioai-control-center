# Storage Dashboard V1 and Auth recovery compatibility candidate

This isolated branch merges dashboard `cc247f1bbd694f363caf539e573bbe43f41931df`
with Auth recovery `8654080a12114aee362aa3a05a101b081af6b35c`. Their merge base is
`3cd86f69f313a3a53da8d7d721191ad8808cbdd5`. Both histories are parents
of the candidate merge commit.

The sole textual conflict was in `frontend/cc-ui/src/apps/AdminApp.test.tsx`.
Both the Storage Dashboard permission and deep-link tests and the manual
licensing navigation tests were retained. The merged application retains MFA
challenge and resend handling, session probe recovery, organization invitation
flows, manual license proxy and UI, and the Storage Dashboard at `/storage`.
The dashboard API router remains guarded by `platform.manage_infra` in
`backend/src/control_center/main.py`; the matching frontend navigation and
page gates use the same permission.

The Auth recovery branch's workspace path update exposed a repository-owner
inference bug: an absolute path under `omnibioai-ecosystem` was attributed to
the workspace directory instead of its child repository. The parser now skips
that container directory; the existing 53 deployment-health tests pass.
Generated report files introduced by the recovery branch were excluded from
the merge result. They are not source or runtime inputs to the Control Center
images.

## Validation

- Focused backend Auth, proxy, and Storage Dashboard tests: 210 passed,
  45 subtests passed.
- Complete backend suite excluding `test_report_authentication.py`: 1,875
  passed, 72 subtests passed.
- Focused frontend Auth, navigation, and Storage Dashboard tests: 170 passed.
- Complete frontend suite: 802 passed across 73 files.
- TypeScript project check and all four production frontend builds (`build`,
  `build:admin`, `build:control`, `build:control:studio`): passed.
- Python compilation of application code, tests, and scripts: passed when
  excluding the preexisting tracked `combined_control_center.py` concatenation
  artifact, whose `===== FILE` delimiters make it invalid Python.

The unfiltered backend suite is not green. In the isolated Python 3.12 backend
environment, 42 `test_report_authentication.py` cases errored because that
environment lacks the root reporting dependency `pandas`. Running that module
under the system Python with pandas available produced 32 passes and 10
failures. Those 10 tests require an access token, while the dashboard source
already documents and implements an optional token for report generation.
The report CLI behavior and these existing tests are outside this merge's
Auth login and Storage Dashboard changes. Resolve that contract mismatch and
rerun the unfiltered backend suite before treating this candidate as fully
qualified for deployment.

No production deployment, container restart, database operation, credential
reset, or release-pin change was performed.
