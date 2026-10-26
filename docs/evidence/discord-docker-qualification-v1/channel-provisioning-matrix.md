# Discord channel provisioning matrix

| Channel | Expected event types | Guild/channel identity | Webhook identity | Unique secret reference | Routing config | Live verification |
|---|---|---|---|---|---|---|
| announcements | platform.release | NOT_VERIFIED | NOT_VERIFIED | MISSING | Synthetic only | NOT_RUN |
| bug-reports | github.issue.confirmed | NOT_VERIFIED | NOT_VERIFIED | MISSING | Synthetic only | NOT_RUN |
| feature-requests | feature.request.accepted | NOT_VERIFIED | NOT_VERIFIED | MISSING | Synthetic only | NOT_RUN |
| support | support.incident | NOT_VERIFIED | NOT_VERIFIED | MISSING | Synthetic only | NOT_RUN |
| tutorials | documentation.published | NOT_VERIFIED | NOT_VERIFIED | MISSING | Synthetic only | NOT_RUN |
| omnibioai-alerts | infrastructure.alert | NOT_VERIFIED | NOT_VERIFIED | MISSING | Synthetic only | NOT_RUN |

No webhook identity or secret reference is invented here. Production credentials were neither generated nor read; no live Discord messages were sent.
