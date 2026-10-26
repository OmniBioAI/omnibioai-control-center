# Operator handoff

1. Restore Docker access through the same explicitly permitted execution mechanism used for the authorized harness attempt. Current ordinary-context Docker API access returns socket permission denied. Do not change socket permissions or bypass execution restrictions.
2. Before retry, capture redacted exit status/error diagnostics for the disposable Redis container only. Investigate the local pinned Redis image/runtime contract, correct only the test harness if needed, then obtain an independent review of any safety-relevant change.
3. Re-run from the repository root on `spark-c275`: `python3 scripts/discord-docker-qualification/run_qualification.py`. It rejects collisions and only cleans resources carrying exact run labels and manifest ownership. Preserve the manifest if cleanup is incomplete.
4. Review before/after inventories and ownership-verification. Stop if protected fingerprints change, a protected resource disappears, or final inventory is absent. Never use global prune commands.
5. The V2 Docker-free exceptional-path suite passed 16/16. Do not report crash qualification from those fake-Docker tests. The existing application is synchronous and has no worker/queue; several historical scenarios are inapplicable as worded and remain unexecuted.
6. Identify a legitimate prior Discord candidate and establish source/schema/config compatibility before any rollback qualification.
7. Provision six Discord destinations and seven source credentials through the approved secret manager. Record non-secret references and identity readbacks only. Live canaries require separate approval; none were sent.
8. Run full backend regression in an environment supporting its loopback/socket requirements. Production deployment remains out of scope and prohibited by this workstream.

No production credentials or live Discord destinations are configured by this harness.
