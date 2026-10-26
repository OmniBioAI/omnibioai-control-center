# Six-channel verification matrix

No authorized Discord administrative session or webhook-management interface
was available. Values below are intentionally `NOT_VERIFIED`; do not infer
identity from a webhook setting name or mocked route.

| Automated channel | Guild ID | Channel ID | Webhook ID | Association/permission | Secret-manager ref | Config/routing result |
|---|---|---|---|---|---|---|
| announcements | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | Config missing; mock route PASS |
| bug-reports | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | Config missing; mock route PASS |
| feature-requests | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | Config missing; mock route PASS |
| support | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | Config missing; mock route PASS |
| tutorials | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | Config missing; mock route PASS |
| omnibioai-alerts | NOT_VERIFIED | NOT_VERIFIED | NOT_VERIFIED | Legacy destination unknown | NOT_VERIFIED | Legacy variable name only; mock route PASS |

Totals: `CHANNELS_CONFIGURED=1/6` presence-only; `VERIFIED_CHANNEL_MAPPINGS=0/6`.
The `DISCORD_ALERT_WEBHOOK_URL` value was never read, displayed, or copied to
evidence. `DISCORD_CHANNEL_WEBHOOKS` is absent from the inspected active Studio
configuration. Code-level duplicate webhook-ID, malformed URL/port, and
legacy-alias validation does not prove remote webhook ownership.

Excluded from automated publishing: `general`, `research-chat`,
`show-and-tell`. Their non-routing status must remain enforced in any eventual
configuration.
