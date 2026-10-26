# Security review status — Master V1

## Previous review boundary

V11.6 independently passed the disposable harness safety review for source
tree digest `80d620eb86bcb426a504e3c5087be583dd2c2af3af76bd6e58950ddbf8bedc1e`.
After that review, the Master V1 source changed in
`backend/src/control_center/notifications/discord.py` and
`backend/tests/test_discord.py`. The current source tree digest is
`b7bf95c9f9bd1af4da8a2d90a7e325261a304f001781a453334e9fa8c27ec725`.
Therefore the V11.6 PASS remains valid only for the old exact snapshot and is
not a fresh independent review of the integrated master candidate.

## Change under review

`notify()` now requires `DISCORD_LEGACY_WEBHOOK_FALLBACK=enabled` for direct
legacy delivery, and validates opted-in targets as Discord HTTPS webhook URLs.
Any partial central-router configuration fails closed, and central submission
failures never fall back. The focused and full backend tests passed after this
change. No deployed configuration was edited.

Fresh independent review of the current source snapshot: `PASS` for the
fail-closed `notify()` behavior. The reviewer reproduced source digest
`b7bf95c9f9bd1af4da8a2d90a7e325261a304f001781a453334e9fa8c27ec725`, verified
the Master manifests (17/17 checksums, 262/262 source inventory entries,
245/245 Git blob entries), reran the focused routing tests (20 plus two
subtests), and confirmed transport-error webhook token redaction.

Scope caveat: explicit legacy opt-in still permits posting caller-provided
content to a syntactically valid Discord webhook; its actual guild/channel
identity is not established here. Keep that opt-in disabled until destination
and payload are reviewed. Legacy callers may stop delivering when central
routing is unavailable, and the integration-status endpoint may still infer
configuration from variable presence. This is source-level review only, not
runtime qualification. Docker remains blocked by normal-shell daemon
permission denial.

No Docker execution, production access, Discord send, staging, or commit was
performed for this change.
