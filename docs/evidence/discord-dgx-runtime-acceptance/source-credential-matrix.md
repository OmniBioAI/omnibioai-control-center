# Seven-source credential and runtime matrix

The runbook defines these canonical identities and key references. This
workstream had no approved secret-manager interface or runtime administration;
no credentials were generated, read, stored, or injected. No production source
runtime is qualified (0/7). The runbook further identifies several source
contracts as code-only/unwired; credentials alone must not be interpreted as
runtime evidence.

| Source ID | Required secret reference | Key/runtime status |
|---|---|---|
| `github` | `DISCORD_EVENT_GITHUB_SECRET` | Not configured / not runtime-qualified |
| `rag` | `DISCORD_EVENT_RAG_SECRET` | Not configured / not runtime-qualified |
| `workbench` | `DISCORD_EVENT_WORKBENCH_SECRET` | Not configured / not runtime-qualified |
| `documentation` | `DISCORD_EVENT_DOCUMENTATION_SECRET` | Not configured / not runtime-qualified |
| `video` | `DISCORD_EVENT_VIDEO_SECRET` | Not configured / not runtime-qualified |
| `infrastructure` | `DISCORD_EVENT_INFRASTRUCTURE_SECRET` | Not configured / not runtime-qualified |
| `support` | `DISCORD_EVENT_SUPPORT_SECRET` | Not configured / not runtime-qualified |

Provision distinct cryptographically secure values using the organization's
approved secret manager, one producer identity per key. Map only the producer's
key to its runtime `DISCORD_EVENT_SOURCE_SECRET`; configure matching verifier
source identity and replay window. Verify valid signature, invalid signature,
cross-source rejection, replay rejection, rotation with previous-key overlap,
and removal of the old key. Never put values in evidence or shell history.
