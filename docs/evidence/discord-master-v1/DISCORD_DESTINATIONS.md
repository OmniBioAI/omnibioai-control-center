# Discord destination contracts and live identities — Master V1

Static source contracts define six automated destinations and twelve event
mappings: announcements, bug-reports, feature-requests, support, tutorials,
and omnibioai-alerts. The static route map is source evidence only.

| Destination | Live guild/channel identity | Deployed router binding | Status |
|---|---|---|---|
| announcements | No authorized readback | No readback | NOT_VERIFIED |
| bug-reports | No authorized readback | No readback | NOT_VERIFIED |
| feature-requests | No authorized readback | No readback | NOT_VERIFIED |
| support | No authorized readback | No readback | NOT_VERIFIED |
| tutorials | No authorized readback | No readback | NOT_VERIFIED |
| omnibioai-alerts (`infrastructure.alert`, `security.alert`, `github.workflow.failed`) | No authorized readback | No readback | NOT_VERIFIED |

Current result: `LIVE_CHANNELS=0/6`. No webhook URL or secret was inspected.
Required human evidence is a sanitized readback associating each distinct
webhook identity with its Discord guild/channel ID and the deployed router
binding, including observation time. Static configuration presence is not
identity verification.

The three community-only exclusions (general, research-chat, show-and-tell)
are absent from automated routes and rejected by local configuration tests.
This is a static/local PASS only; production routing and legacy direct-webhook
destinations remain unverified (`COMMUNITY_EXCLUSIONS=0/3` live).

Evidence: `docs/evidence/discord-v12/readback-closure.md`,
`docs/evidence/track-e/discord-production-integration-v10-c.md`,
`docs/evidence/discord-docker-qualification-v1/channel-provisioning-matrix.md`.
