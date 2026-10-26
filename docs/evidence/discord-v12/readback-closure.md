# Discord production readback closure — V12

Observation time: 2026-10-25 07:16 UTC
Repository revision observed: `f37ce8c952f917f607e9923cbb47dda8b0406a7a` (`main`), with pre-existing dirty worktree changes
Evidence type: read-only local source inspection and focused tests; no production interfaces were available

## Result

```text
WORKSTREAM=OMNIBIOAI_DISCORD_PRODUCTION_READBACK_CLOSURE_V12
CHANNEL_CONTRACTS=6/6
LIVE_CHANNELS_VERIFIED=0/6
SOURCE_CONTRACTS=7/7
LIVE_SOURCES_QUALIFIED=0/7
LEGACY_FALLBACK_DESTINATION=UNKNOWN
COMMUNITY_EXCLUSIONS=UNVERIFIED
IAM_RUNTIME_VERIFICATION=BLOCKED
TESTS=109/109 focused tests passed (one deprecation warning)
CANARIES_EXECUTED=0
PRODUCTION_UNCHANGED=YES
MISSING_ACCESS=Read-only Discord guild/webhook metadata; deployed router binding metadata; approved source runtime identity/auth metadata; legacy webhook destination metadata
NEXT_ACTION=Have authorized Discord, deployment, and IAM operators provide sanitized read-only metadata readbacks with observation timestamps.
```

No message or webhook delivery endpoint was invoked. No production secret value was read. No credentials, configuration, databases, or services were changed. Local historical reports are not treated as fresh production evidence.

## Destination readback matrix

Local route contract source: `backend/src/control_center/notifications/discord.py` (`EVENT_ROUTES`, six destinations, eleven event mappings). This is source evidence only. No production router binding or authoritative Discord metadata interface was available in this session.

| Destination | Intended route contract | Deployed binding | Discord guild/channel identity | Readback status |
|---|---|---|---|---|
| announcements | `platform.release`, `platform.milestone` | Not available | Not available | UNVERIFIED |
| bug-reports | `github.issue.confirmed`, `github.issue.resolved` | Not available | Not available | UNVERIFIED |
| feature-requests | `feature.request.accepted` | Not available | Not available | UNVERIFIED |
| support | `support.incident`, `support.resolved` | Not available | Not available | UNVERIFIED |
| tutorials | `documentation.published`, `video.published` | Not available | Not available | UNVERIFIED |
| omnibioai-alerts | `infrastructure.alert`, `security.alert` | Not available | Not available | UNVERIFIED |

Required read-only evidence for each: actual guild ID and channel ID from Discord server integration/channel metadata, plus the deployed router's destination binding identity. A webhook variable name or configured presence is not destination proof. Record no webhook URL or token. Current live verification is 0/6.

## Source runtime matrix

Local source contract: `backend/src/control_center/notifications/discord_events.py` (`SOURCE_EVENT_TYPES`) and `scripts/publish_discord_event.py`. The repository defines seven source/event allowlists. No production runtime metadata, effective authentication result, or IAM decision log was available. Static contracts and passing synthetic tests do not qualify live identity.

| Source | Contract present | Expected authorization contract | Runtime identity/authentication | IAM runtime result |
|---|---|---|---|---|
| github | Yes | Only event types in the GitHub source allowlist; signed source identity required | No readback | UNVERIFIED |
| rag | Yes | Only event types in the RAG source allowlist; signed source identity required | No readback | UNVERIFIED |
| workbench | Yes | Only event types in the Workbench source allowlist; signed source identity required | No readback | UNVERIFIED |
| documentation | Yes | Only event types in the Documentation source allowlist; signed source identity required | No readback | UNVERIFIED |
| video | Yes | Only `video.published`; signed source identity required | No readback | UNVERIFIED |
| infrastructure | Yes | Only infrastructure/security alert types; signed source identity required | No readback | UNVERIFIED |
| support | Yes | Only support incident/resolution and accepted feature types; signed source identity required | No readback | UNVERIFIED |

Required access: approved read-only runtime/deployment metadata identifying the executing workload and secret-reference names/versions (never values), plus an approved non-mutating authentication/IAM decision probe or sanitized audit record showing source binding, authorized event types, and rejection for invalid signature, replay, and cross-source use. No production probe was run because no such approved interface was exposed. Configured identity must be reported separately from demonstrated runtime authentication.

## Legacy publisher and fallback audit

Repository source inspection found these direct/compatibility paths:

| Path | Local source observation | Production destination status |
|---|---|---|
| Control Center known-issue alert | `backend/src/control_center/checks/known_issues.py` uses `DISCORD_ALERT_WEBHOOK_URL`; `notifications/discord.py` central-routes when available and retains legacy webhook fallback otherwise | Unknown; no webhook metadata readback |
| Control Center checks/runner compatibility | `DISCORD_WEBHOOK_URL` is read by disk, GPU, and runner paths; existing docs describe these as legacy direct publishers | Unknown; no deployed configuration readback |
| RAG / Workbench / Documentation / ecosystem build paths | Existing integration documentation reports central signed routing with retired notices or compatibility fallback depending on path/configuration | Current deployed state and destination not independently read back |
| GitHub community workflow | `.github/workflows/discord-github-community-events.yml` submits through the signed central client; it is a source adapter, not destination proof | Runtime credentials and deployment state unverified |

`DISCORD_ALERT_WEBHOOK_URL` presence was documented by a prior local audit, but that is historical, non-authoritative for the current deployment, and does not identify a guild/channel. Consequently `LEGACY_FALLBACK_DESTINATION=UNKNOWN` and production `COMMUNITY_EXCLUSIONS=UNVERIFIED`.

Fail-closed migration proposal (not applied):

1. Inventory deployed publisher references by workload and environment using read-only deployment metadata; do not inspect secret values.
2. For any direct fallback whose destination is not verified, disable that fallback through a reviewed deployment change or make the publisher fail closed with a sanitized alert/metric. Do not silently redirect it to another channel.
3. Replace retained paths with the signed central router only after the source has its own secret reference, workload identity binding, and tested event allowlist.
4. Before retiring the legacy alert path, independently verify its actual destination and establish an approved equivalent for `omnibioai-alerts`; preserve service alert visibility during the approved change window.
5. Enforce the three community exclusions centrally and at channel configuration; reject `general`, `research-chat`, and `show-and-tell` regardless of source or fallback. Verify the deployed binding metadata before claiming PASS.
6. Require code review, change approval, rollback plan, and post-change read-only checks. No step in this proposal is authorization to deploy.

## Synthetic canary acceptance (prepared only)

No canary was executed. After separate explicit publication approval and verified destination identities, use six unique synthetic event IDs, one for each destination, and verify both approval and readback:

| Canary | Destination | Acceptance evidence |
|---|---|---|
| C-ANN | announcements | Approved synthetic event; router receipt bound to verified channel ID; read back exactly one synthetic message |
| C-BUG | bug-reports | Same checks; no user or issue data in payload |
| C-FEATURE | feature-requests | Same checks; no user-submitted private content |
| C-SUPPORT | support | Same checks; synthetic-only incident payload |
| C-TUTORIAL | tutorials | Same checks; synthetic publication payload |
| C-ALERT | omnibioai-alerts | Same checks; synthetic alert; legacy fallback remains controlled until equivalence is proven |

For each, record only event ID, timestamp, verified guild/channel IDs, sanitized router status, and message ID if policy permits. Confirm there is no message in any excluded community destination. Do not retry ambiguous acceptance automatically; reconcile through read-only message lookup before deciding next steps.

## Test evidence

Command (Python 3.12 isolated test environment):

```text
/tmp/omnibioai-control-center-system-312/bin/python -m pytest -q --no-cov backend/tests/test_discord_routing.py backend/tests/test_discord_events.py backend/tests/test_discord_iam_api.py backend/tests/test_github_discord_event_adapter.py backend/tests/test_support_discord_publisher.py
```

Result: **109 passed, 1 warning in 2.57s**. `git diff --check` passed. A run without `--no-cov` also executed all 109 tests but exited nonzero because the repository's 98% coverage threshold was applied to this intentionally focused subset (85.43%); this is not a full regression or coverage result. Plain `python3` initially failed collection because `control_center` was not on its import path; the isolated Python 3.12 environment succeeded.

Source revision and local files are not a substitute for live readbacks. The production channels, seven runtimes, IAM decisions, and fallback destinations remain unverified.
