# Source runtimes and IAM — Master V1

Static code defines seven source identities and source-scoped event allowlists:
github, rag, workbench, documentation, video, infrastructure, and support.
The local implementation includes signed source identity, timestamp/nonce
checks, event-type allowlists, and IAM tests. This does not prove deployed
workload identity or effective authorization.

| Source | Local contract | Live workload identity / auth result |
|---|---|---|
| github | Present | NOT_VERIFIED |
| rag | Present | NOT_VERIFIED |
| workbench | Present | NOT_VERIFIED |
| documentation | Present | NOT_VERIFIED |
| video | Present | NOT_VERIFIED |
| infrastructure | Present | NOT_VERIFIED |
| support | Present | NOT_VERIFIED |

Current result: `LIVE_SOURCES=0/7`; production IAM readback is blocked. No
secret values were read. Required operator input: executing workload identity,
secret reference/version metadata (not values), and sanitized authentication /
IAM decisions showing allowed source/event binding plus signature, replay, and
cross-source rejection. No production probe was run.

Sources: `docs/evidence/discord-v12/readback-closure.md`,
`docs/evidence/track-e/discord-production-integration-v10-c.md`,
`backend/src/control_center/notifications/discord_events.py`, and
`backend/tests/test_discord_iam_api.py`.
