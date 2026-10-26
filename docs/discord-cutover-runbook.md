# Discord multichannel cutover runbook

This runbook stops at the human-approval boundary. Never paste webhook URLs,
HMAC values, or message content into evidence, terminals, issues, or logs.

## Destination provisioning and G3 readback

Provision exactly one distinct, least-privilege webhook for each automated
channel: `announcements`, `bug-reports`, `feature-requests`, `support`,
`tutorials`, and `omnibioai-alerts`. Do not create or configure automation
webhooks for `general`, `research-chat`, or `show-and-tell`.

For G3, an authorized Discord administrator must capture a sanitized readback
for each automated destination containing only guild ID, channel ID, and UTC
observation timestamp. The evidence must contain no webhook URL, token, or
secret. Verify all six channel IDs are distinct before continuing.

## Source credentials and publishers

Each source gets its own independently rotated HMAC secret. Never share a
secret between rows.

| Source | Secret name | Publisher |
|---|---|---|
| GitHub | `DISCORD_EVENT_GITHUB_SECRET` | `scripts/publish_discord_event.py`, `scripts/publish_github_community_event.py`, and `scripts/publish_github_workflow_failure.py` via repository workflows |
| RAG | `DISCORD_EVENT_RAG_SECRET` | `omnibioai-rag/ragbio/notifications/discord_events.py` |
| Workbench | `DISCORD_EVENT_WORKBENCH_SECRET` | `omnibioai-workbench/notifications/discord_events.py` and `scripts/publish_workbench_discord_event.py` |
| Documentation | `DISCORD_EVENT_DOCUMENTATION_SECRET` | `omnibioai-docs/scripts/deploy-docs.sh` using the central publisher |
| Video | `DISCORD_EVENT_VIDEO_SECRET` | `omnibioai-videos/scripts/publish_discord_video_event.py` |
| Infrastructure | `DISCORD_EVENT_INFRASTRUCTURE_SECRET` | Control Center health/known-issue publishers through `notifications/discord.py` |
| Support | `DISCORD_EVENT_SUPPORT_SECRET` | `scripts/publish_support_discord_event.py` |

For G4, capture only source name, secret reference name, runtime/workload
identity, effective router endpoint identity, authentication result, and UTC
timestamp. Do not capture secret values.

## GitHub-native webhook inventory and retirement

Before cutover, inspect webhook settings for every OmniBioAI repository and
the GitHub organization. Record repository/organization, hook type, subscribed
events, active state, sanitized destination owner, and timestamp. Do not copy
URLs or secrets. Identify the existing GitHub-native Discord webhook but leave
it enabled.

Remove the native webhook only after the `omnibioai-alerts` canary below has
passed, its destination readback is verified, duplicate suppression is
confirmed, and the release owner separately approves retirement. Apply this
check to every repository and then the organization; do not infer organization
coverage from a repository setting.

## Six-canary approval plan

Every item below is **REQUIRES EXPLICIT RELEASE-OWNER APPROVAL (G10)**. Use one
fixed synthetic template only: title `OmniBioAI routing canary`; message
`Synthetic routing verification. No customer, user, research, or operational
data.`; fields `Channel=<expected>` and `Canary ID=<approved-id>`.

- Announcements canary to `announcements` — **REQUIRES EXPLICIT RELEASE-OWNER APPROVAL (G10)**.
- Confirmed-bug canary to `bug-reports` — **REQUIRES EXPLICIT RELEASE-OWNER APPROVAL (G10)**.
- Accepted-feature canary to `feature-requests` — **REQUIRES EXPLICIT RELEASE-OWNER APPROVAL (G10)**.
- Support canary to `support` — **REQUIRES EXPLICIT RELEASE-OWNER APPROVAL (G10)**.
- Documentation canary to `tutorials` — **REQUIRES EXPLICIT RELEASE-OWNER APPROVAL (G10)**.
- Workflow-failure canary to `omnibioai-alerts` — **REQUIRES EXPLICIT RELEASE-OWNER APPROVAL (G10)**.
- After all six, verify zero automated messages in `general`, `research-chat`,
  and `show-and-tell` — **REQUIRES EXPLICIT RELEASE-OWNER APPROVAL (G10)**.

For every approved canary, record the event ID, expected and observed channel
ID, sanitized receipt, UTC timestamp, and duplicate count. Stop on the first
wrong destination, duplicate, missing receipt, or community-channel message.

## Rollback

If the alerts canary or cutover validation fails, stop new router submissions,
disable the router fallback in source configuration, and re-enable the prior
GitHub-native webhook. Preserve the event ledger and all ambiguous delivery
records for reconciliation; do not replay them blindly. Confirm the native
hook is active with a sanitized readback, restore monitoring, and keep the
multichannel router disabled until a corrected candidate repeats approval and
canary gates. Rollback does not authorize a live test message.
