# Discord operator acceptance — test and evidence results

Date: 2026-10-24. No historical result is being promoted to a current pass.

## Checks performed in this operator run

| Check | Result |
|---|---|
| Prior `discord-final/SHA256SUMS` | PASS for all five listed files |
| Prior candidate JSON syntax | PASS |
| Prior source worktree fingerprints | PASS in the final-closure workstream; current source repos unchanged since that manifest |
| Exact V8 read-only inspect command | BLOCKED: Docker daemon permission denied; no containers/images read |
| Host identity | `spark-c275`, Linux aarch64; DGX hardware identity not verified |
| Docker context | `default`; daemon unavailable in this session |
| Active Studio Discord config names | legacy `DISCORD_ALERT_WEBHOOK_URL` present; channel map absent; values not read |
| Discord admin / secret manager | no authorized integration or supported CLI available |
| Production changes / live messages | none |

The full current candidate test record remains: Control Center 2,234 passed,
0 failed, 72 subtests, 98.00% coverage; focused Discord IAM 15 passed; RAG
focused Discord 10 passed; Workbench focused Discord 12 passed; Videos Discord
publication 6 passed. Cross-repository full regression remains blocked: RAG
full collection had 12 errors, Workbench full collection 351 errors, and
Videos full suite had 312 passed, 16 skipped, 2 xfailed, 0 failed, 39 browser
setup errors because Chromium is absent. Docs Vitest was not run because
`node_modules` is absent. The exact earlier commands and caveats are in
`../discord-final/test-results.md`.

`PYTHONPATH=backend/src python3 scripts/discord_disposable_e2e.py` still
produces an in-process mock result of 6/6 routes and 3/3 community exclusions.
It does not start containers and is not counted as Docker E2E.

Previous V8 evidence checksum verifies. The preserved V9 qualification
checksum verifies; the V9 checksum entry for the shared runbook does not match
because that runbook was intentionally updated. The original V9 checksum file
was not changed. The current runbook is covered by `discord-final/SHA256SUMS`.
