# Discord production integration V10_C — Track E qualification

Workstream: `OMNIBIOAI_DISCORD_PRODUCTION_INTEGRATION_V10_C`  
Date: 2026-10-25  
Scope: source inspection, credential-name presence checks, and isolated tests.
No Discord message, production request, credential creation/rotation, deployment,
or production-state mutation was performed.

## Decision

The software contracts are complete: `CHANNEL_CONTRACTS=6/6` and
`SOURCE_CONTRACTS=7/7`. Live qualification remains zero because there is no
authorized Discord metadata readback or production runtime evidence:
`VERIFIED_LIVE_CHANNELS=0/6` and `QUALIFIED_LIVE_SOURCES=0/7`.

The router is synchronous. An ingestion or operator request persists the event
record and performs delivery in that request when approval permits. Database
states named `queued` describe a durable recoverable status; they do not imply
that a queue service, background worker, or asynchronous delivery architecture
exists.

## Destination contracts and production checklist

The fixed event table has 11 event types and exactly six automated
destinations. Configuration accepts only Discord HTTPS webhook endpoints,
rejects credentials in URLs, nonstandard ports, query/fragment components,
unknown/community destinations, duplicate webhook IDs, and legacy-alert
aliasing to another route. These checks validate configuration shape and route
isolation; they cannot establish guild/channel identity.

| Destination | Authorized event contracts | Source-level | Production acceptance checklist | Live |
|---|---|---:|---|---:|
| `announcements` | `platform.release`, `platform.milestone` | PASS | distinct webhook ID; approved guild; channel name/ID readback; one authorized canary; durable receipt; duplicate produces no second post | 0/1 |
| `bug-reports` | `github.issue.confirmed`, `github.issue.resolved` | PASS | same identity, canary, receipt, and deduplication checks | 0/1 |
| `feature-requests` | `feature.request.accepted` | PASS | same identity, canary, receipt, and deduplication checks | 0/1 |
| `support` | `support.incident`, `support.resolved` | PASS | same identity, canary, receipt, and deduplication checks | 0/1 |
| `tutorials` | `documentation.published`, `video.published` | PASS | same identity, canary, receipt, and deduplication checks | 0/1 |
| `omnibioai-alerts` | `infrastructure.alert`, `security.alert` | PASS | same checks plus prove equivalence to the preserved legacy alert target before retiring it | 0/1 |

Presence-only inspection did not read values. The current process has none of
the channel/source variables. The Studio environment file contains the legacy
alert variable name, but not `DISCORD_CHANNEL_WEBHOOKS` or any of the seven
canonical source-key names. A variable name is not channel-identity evidence.

## Authoritative source inventory and production checklist

The authoritative inventory is
`control_center.notifications.discord_events.SOURCE_EVENT_TYPES`. The seven
identities are `github`, `rag`, `workbench`, `documentation`, `video`,
`infrastructure`, and `support`; no additional identity was inferred. A new
test requires the standalone publisher's full source/event matrix and route
table to equal the authoritative router constants exactly.

| Source | Allowed event scope | Runtime checklist | Live |
|---|---|---|---:|
| `github` | releases, milestones, confirmed/resolved issues, accepted features | own key reference only; signed synthetic ingestion; bad signature, nonce replay, and cross-scope rejection; audit record | 0/1 |
| `rag` | support incident/resolution, documentation publication | same checks; prove no query, prompt, study, tenant, user, or PHI fields leave the runtime | 0/1 |
| `workbench` | support incident/resolution, platform release | same checks; prove retired user/pipeline task names remain no-op and caller text/approval is ignored | 0/1 |
| `documentation` | documentation publication, infrastructure alert | same checks; stable revision identity; central attempt never falls through to a duplicate legacy post | 0/1 |
| `video` | video publication | same checks; require reviewed public manifest digest and commit identity | 0/1 |
| `infrastructure` | infrastructure/security alert | same checks; stable incident identity and sanitized fixed template | 0/1 |
| `support` | support incident/resolution, accepted feature | same checks; operator-reviewed fixed template; no invented ticket-system connection | 0/1 |

Production acceptance is 7/7 only after each real runtime proves its own key
binding, signature validation, timestamp/nonce replay defense, event-scope
isolation, durable deduplication, audit records, and rejection behavior. Source
code or a Compose variable reference is not runtime evidence.

## IAM, authorization, reliability, and audit result

Source-level security is **PASS**:

- HMAC-SHA256 covers timestamp, nonce, and exact request bytes. Signatures have
  a five-minute window, nonces are durable and source-bound, and current plus
  one previous key is the maximum rotation set.
- The authenticated source must match the envelope source and its allowlisted
  event type. The destination is derived from the fixed route and must match.
- Source authentication does not grant editorial approval. Only explicitly
  configured source/event pairs may assert prior approval; otherwise
  `platform.manage_content` is required. Read/recover/replay/reconciliation use
  the narrower documented `platform.manage_content` or
  `platform.manage_infra` scopes and verified, revocation-aware access tokens.
- Event IDs and payload hashes provide durable deduplication. Ambiguous sends
  are never retried automatically; an infrastructure-authorized operator must
  reconcile them. Retry counts and `Retry-After` are bounded.
- Public records omit payload and secret material. Dead-letter records contain
  metadata and a payload hash, webhook URLs are redacted, and Discord mentions
  are suppressed.

This PASS is a code/test result, not production IAM qualification. Production
source keys are absent and live source qualification remains 0/7.

## Legacy publisher audit

Status: **PARTIAL** (`4/5` migrated or safely retired under the conservative
operational classification).

| Historical path | Disposition |
|---|---|
| RAG | Signed central client for fixed sanitized service incidents; successful-query/community content removed |
| Workbench | Private per-user/pipeline publishers retired as compatible no-ops; fixed-template central publisher retained |
| Documentation deploy | Central-first signed client; direct webhook retained only when central configuration is absent; no fallback after any central attempt |
| Ecosystem build | Central-first infrastructure event; direct alert compatibility path retained only when central configuration is absent |
| Control Center health/known issues | Central-first infrastructure event; direct alert webhook retained until live destination equivalence is proven |

No fallback was removed because its replacement destination has not been
verified. That is why the result is PARTIAL rather than PASS.

## Community-only exclusions

The central router result is **PASS**: `general`, `research-chat`, and
`show-and-tell` have no event routes, are rejected as webhook-map keys, and the
isolated six-route flow proves none can be selected. End-to-end production
status is **UNVERIFIED**, because the preserved legacy alert webhook's actual
channel identity has not been read back. Production acceptance must prove that
all current and replacement webhook IDs avoid those three channel IDs.

## Secure provisioning procedure (prepared, not executed)

1. A Discord administrator creates or inspects one channel-scoped incoming
   webhook for each named automated destination. Record only guild ID, channel
   ID, webhook ID, and the approved secret-manager reference in evidence.
2. The administrator independently reads back all six guild/channel bindings,
   proves webhook IDs are distinct, and proves none target a community-only
   channel.
3. Store the six complete URLs directly in the approved secret manager as the
   `DISCORD_CHANNEL_WEBHOOKS` JSON object. Grant read access only to Control
   Center. Never place a URL/token in command arguments, shell history, logs,
   tickets, screenshots, test fixtures, or evidence.
4. Generate seven independent URL-safe keys of at least 32 random bytes inside
   the approved secret manager. Each producer receives only its own key as
   `DISCORD_EVENT_SOURCE_SECRET`; Control Center receives the seven canonical
   verifier references. Do not export, reuse, print, or create keys in this
   workstream.
5. Preserve the legacy alert credential until the replacement alert identity
   and canary prove equivalence. Rotation is a separately authorized change.

## Live canary acceptance criteria (not executed)

Use a new unique non-sensitive event ID for each authorized run. Submit one
fixed synthetic event per destination with `approved_publication=false`, then
approve it using a `platform.manage_content` operator. For every destination:

- independently read back and record non-secret guild ID, channel ID, webhook
  ID, message ID, timestamp, event ID, and sanitized receipt;
- require exactly one visible message in the exact named channel, no message in
  any other automated or community-only channel, no active mention, and no
  user/customer/patient/research/credential content;
- resubmit the same event ID with a fresh nonce and require no second message;
- require durable `delivered` state and a credential-free audit record;
- exercise 429 behavior only at an approved mock/nonproduction boundary;
- for all seven sources, reject a bad signature, repeated nonce, wrong source
  binding, and unauthorized event scope.

No canary may be sent until Discord administration, publication, and evidence
capture are explicitly authorized. Counters remain zero until the readback and
runtime evidence actually exist.

## Fresh isolated evidence

```text
Control Center Discord/router/IAM/process/source suites: 139 passed
RAG source suite: 10 passed
Workbench source suite: 14 passed
Video publication suite: 6 passed
Disposable in-process signed ingestion -> approval -> synchronous mock delivery: 1 passed
Total: 170/170 passed
Community exclusion in disposable integration: 3/3 passed
Python compile checks and documentation publisher Bash syntax: passed
```

The disposable integration used temporary SQLite state and synthetic mock
webhook endpoints; it made no external network request and is not live Discord
evidence.

## Final status

```text
WORKSTREAM=OMNIBIOAI_DISCORD_PRODUCTION_INTEGRATION_V10_C
CHANNEL_CONTRACTS=6/6
VERIFIED_LIVE_CHANNELS=0/6
SOURCE_CONTRACTS=7/7
QUALIFIED_LIVE_SOURCES=0/7
LEGACY_PUBLISHERS=PARTIAL
IAM_SECURITY=PASS
COMMUNITY_EXCLUSIONS=UNVERIFIED
TESTS=170/170
PRODUCTION_UNCHANGED=YES
NEXT_ACTION=Obtain authorized Discord metadata readback and secret-manager/runtime access; provision by reference only, verify six distinct non-community destinations and seven isolated source identities, then seek separate approval for six synthetic canaries.
```
