# Discord destination verification

No Discord administration interface/session was available. No webhook was
created or inspected; identifiers and permissions below are intentionally
unknown. Existing `DISCORD_ALERT_WEBHOOK_URL` presence is compatibility-path
evidence only; its destination is unverified. No secret value or complete URL
was read or recorded. All six mapping verifications remain pending.

| Automated route | Guild ID | Channel ID | Webhook ID / association | Secret ref | Status |
|---|---|---|---|---|---|
| announcements | Unknown | Unknown | Unknown | `DISCORD_CHANNEL_WEBHOOKS` entry required | BLOCKED |
| bug-reports | Unknown | Unknown | Unknown | `DISCORD_CHANNEL_WEBHOOKS` entry required | BLOCKED |
| feature-requests | Unknown | Unknown | Unknown | `DISCORD_CHANNEL_WEBHOOKS` entry required | BLOCKED |
| support | Unknown | Unknown | Unknown | `DISCORD_CHANNEL_WEBHOOKS` entry required | BLOCKED |
| tutorials | Unknown | Unknown | Unknown | `DISCORD_CHANNEL_WEBHOOKS` entry required | BLOCKED |
| omnibioai-alerts | Unknown | Unknown | Legacy destination not verified | `DISCORD_CHANNEL_WEBHOOKS` entry required | BLOCKED |

Operator checklist: in the authorized guild UI use Server Settings →
Integrations → Webhooks. For each exact route create/verify a least-privilege
channel webhook, record guild/channel/webhook IDs and secret reference only,
and confirm the webhook's selected channel. Verify six unique destinations and
router aliases. Determine the legacy alert webhook's actual channel before
changing fallback behavior. Exclude `general`, `research-chat`, and
`show-and-tell`. Do not send a live message without separate explicit approval.
