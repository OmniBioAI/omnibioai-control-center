# Track E integration and security qualification

Workstream: `OMNIBIOAI_DISCORD_PARALLEL_COMPLETION_V7`  
Date: 2026-10-25  
Scope: source inspection and Docker-free tests only. No Discord webhook, secret,
credential, production service, database, or deployment was created or changed.

## Result

Track E is **PARTIAL** because every source-level control in scope is present
and tested, but production webhook identity, runtime secret injection, and live
canaries require separately authorized operator access.

- Automated route contract: **6/6** destinations represented and exercised by
  local mocked delivery (`announcements`, `bug-reports`, `feature-requests`,
  `support`, `tutorials`, `omnibioai-alerts`). Remote Discord identity: **0/6
  verified**. The community-owned `general`, `research-chat`, and
  `show-and-tell` channels remain non-automatable.
- Trusted-source contract: **7/7** identities represented, independently
  authorized by event type, and covered by signing/schema tests (`github`,
  `rag`, `workbench`, `documentation`, `video`, `infrastructure`, `support`).
  Production runtime qualification: **0/7** because no production source keys
  or authorized runtime/secret-manager session were available.
- Security controls: **5/5 source-level controls verified**: IAM-separated
  approval/replay/read operations; HMAC-SHA256 signed ingestion with timestamp,
  nonce replay defense, source isolation, and two-key rotation; payload
  minimization/redaction and mention suppression; bounded outbound Discord 429
  handling; and durable central-first legacy migration behavior.
- Historical publisher paths: **4/5 migrated or safely retired**, conservative
  classification. RAG, Workbench, Documentation, and ecosystem/source adapters
  use central signing or intentionally retire private public-notification paths.
  Control Center retains the direct alert webhook only as a compatibility
  fallback until the replacement alert webhook's live identity is verified.
- Mock success is not live Discord verification. `QUALIFIED_SOURCES=0/7` and
  `VERIFIED_CHANNELS=0/6` remain the release-report values.

## Safe correction

The central-first compatibility client now rejects non-finite `Retry-After`
values and bounds accepted delay values to four seconds, matching the existing
outer bound. The main publisher likewise treats a non-finite header as absent.
Focused tests cover the non-finite and extreme-header cases plus the defensive
unvalidated-webhook-path rejection. Routing, approval, secrets, and production
state are unchanged.

## Fresh evidence

Commands used the isolated Python 3.12 environment supplied by Track B.

```text
PYTHONPATH=src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q -o addopts='' -p no:cacheprovider \
  tests/test_discord.py tests/test_discord_events.py tests/test_discord_routing.py \
  tests/test_discord_event_client.py tests/test_discord_iam_api.py \
  tests/test_github_discord_event_adapter.py tests/test_support_discord_publisher.py
Result: 131 passed, 1 deprecation warning

PYTHONPATH=src /tmp/omnibioai-control-center-system-312/bin/python -m pytest -q -p no:cacheprovider
Result (authorized loopback context): 2238 passed, 0 failed, 72 subtests passed;
9163 statements, 182 missed, 98.01% coverage
Discord modules: discord.py 347/347 and discord_events.py 276/276 statements covered;
routes_discord_events.py 126/126 statements covered

RAG focused source tests: 10 passed
Workbench focused source tests: 14 passed
Videos publication source tests: 6 passed
Python compile and documentation publisher Bash syntax checks: passed
```

The first sandboxed full-suite attempt was not qualification evidence: 13
loopback-socket tests failed because socket creation was denied. The same
candidate then passed in the authorized loopback context above.

## Production secret provisioning procedure (operator-only)

This is a procedure, not authorization to execute it.

1. A Discord administrator creates or inspects exactly one channel-scoped
   incoming webhook for each of the six automated destinations. Record only
   guild ID, channel ID, webhook ID, and approved secret-manager reference;
   never place a webhook token in logs, evidence, tickets, or shell history.
2. Independently confirm all six webhook IDs are distinct, each webhook is
   attached to its named channel, and no webhook targets `general`,
   `research-chat`, or `show-and-tell`.
3. Store the six complete webhook URLs as one secret JSON object named
   `DISCORD_CHANNEL_WEBHOOKS`, keyed by the six canonical channel names. Grant
   read access only to the Control Center runtime identity. Preserve
   `DISCORD_ALERT_WEBHOOK_URL` until the `omnibioai-alerts` replacement passes
   identity readback and canary acceptance.
4. Generate seven independent cryptographically random URL-safe HMAC keys of
   at least 32 bytes directly inside the approved secret manager. Store them
   under exactly `DISCORD_EVENT_GITHUB_SECRET`, `DISCORD_EVENT_RAG_SECRET`,
   `DISCORD_EVENT_WORKBENCH_SECRET`, `DISCORD_EVENT_DOCUMENTATION_SECRET`,
   `DISCORD_EVENT_VIDEO_SECRET`, `DISCORD_EVENT_INFRASTRUCTURE_SECRET`, and
   `DISCORD_EVENT_SUPPORT_SECRET`. Never reuse or export a key.
5. Grant each producer runtime read access only to its own current key and
   inject it there as `DISCORD_EVENT_SOURCE_SECRET`. Grant Control Center read
   access to all seven canonical references. Configure
   `DISCORD_EVENT_ROUTER_URL` to the authenticated Control Center origin.
6. For rotation, create the new current key first, inject the old key only as
   `DISCORD_EVENT_<SOURCE>_PREVIOUS_SECRET` at Control Center, roll the producer,
   verify a signed synthetic event with the new key, then remove the previous
   key reference. At no point configure more than current plus previous.
7. Leave `DISCORD_EVENT_APPROVAL_SOURCES` empty unless an owner documents an
   event-type-specific preapproval policy. HMAC authentication alone must not
   imply editorial approval.

## Live canary acceptance procedure (separate publication authorization)

1. Snapshot credential-name/config metadata and the pending-event queue; do
   not print values. Obtain explicit approval for six public synthetic posts.
2. Submit one unique, sanitized, non-production-data event per destination
   through the signed central ingestion API, using the source/event pair
   authorized for that route. Keep `approved_publication=false`, then approve
   through an operator identity holding only `platform.manage_content`.
3. For each post, independently read back Discord metadata and visible content.
   Record event ID, guild ID, channel ID, webhook ID, timestamp, and sanitized
   receipt; record no webhook URL/token or HMAC material.
4. Assert exact destination, one visible message, no cross-channel message,
   suppressed mentions, no email/PHI/query/prompt/credential content, and a
   durable `delivered` receipt. Re-submit the same event ID and assert no second
   post.
5. Exercise one 429 in an approved nonproduction/mock boundary and confirm
   bounded `Retry-After` handling; do not force a live Discord rate limit.
6. Submit a duplicate nonce and bad signature for every source and require
   rejection; test cross-source event types and require rejection. Confirm
   content approval and infrastructure replay/reconciliation remain separate
   IAM permissions.
7. Accept only when all six channel identities pass, all seven runtime
   identities pass signature/replay/isolation checks, audit/metrics contain no
   secret material, and the old alerts webhook has either been preserved or
   retired only after verified equivalence. Otherwise stop with no deployment.

Production deployment remains a separate explicit decision after all release
gates pass.
