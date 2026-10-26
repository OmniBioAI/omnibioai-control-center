# Isolated rollback

**NOT_VERIFIED.** Docker inventory is available, but there is no reviewed
disposable Compose project, pinned candidate/prior image pair, schema
compatibility contract, or isolated database/queue fixture. No rollback
command was executed. Existing production and acceptance/Auth/MySQL/Redis/
recovery resources remain untouched, supported by identical before/after
inventory fingerprints.

Rollback acceptance remains: record candidate and prior immutable digests;
seed only disposable pending, approved, and ambiguous events; exercise the
candidate; switch only the disposable project to the prior image; verify
health, schema compatibility, queue and ambiguous-state preservation,
configuration restoration, audit continuity, and no extra mock sends. Abort
unless every target is positively attributable to the disposable project.
