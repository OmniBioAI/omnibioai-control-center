# Operator actions required to close remaining gates

No operator permission is inferred. These steps are gated on the actual
owners' access and approval; do not send a live canary or deploy production
under this handoff alone.

## Discord administrator

1. In the approved guild, use Discord **Server Settings → Integrations →
   Webhooks** to create or inspect six channel-scoped webhooks for
   `announcements`, `bug-reports`, `feature-requests`, `support`, `tutorials`,
   and `omnibioai-alerts`.
2. Verify the guild and selected channel in the UI. Record only guild ID,
   channel ID, webhook ID, routing name, and secret-manager reference in
   `channel-verification.md`. Never copy webhook URLs/tokens into evidence,
   tickets, or logs. Ensure all six destinations are distinct and have only
   required channel-scoped send permissions.
3. Confirm `general`, `research-chat`, and `show-and-tell` are excluded.
   Inspect `DISCORD_ALERT_WEBHOOK_URL` using the approved secret manager's
   metadata/Discord interface and verify its destination without printing its
   value. Preserve it until the `omnibioai-alerts` replacement is verified.
4. Acceptance: six destination associations and permissions independently
   verified; `CHANNELS_CONFIGURED=6/6`, `VERIFIED_CHANNEL_MAPPINGS=6/6`.

## Secret-manager and source-runtime owner

1. In the organization's approved secret-manager UI/API (not available in
   this session), provision seven independent secure HMAC keys under the exact
   references in `source-runtime-verification.md`. Do not reuse a key.
2. Inject each key only into its authorized producer runtime and record the
   reference and runtime identity, not the value. Exercise signed synthetic
   events and verify schema, HMAC, replay rejection, source isolation, IAM,
   approval, persistence, route, deduplication, retry, audit, metrics, and
   rotation. Acceptance is 7/7 configured and runtime qualified.

## Authorized DGX operator — read-only first

Run the already-supported command:

```sh
cd /home/manish/Desktop/omnibioai-ecosystem/omnibioai-control-center
python3 scripts/qualify_discord_v8.py --mode inspect --timeout 30
```

If it succeeds in an authorized session, preserve sanitized output for host
identity, Compose projects, immutable image IDs/digests, architecture,
source/build provenance, config references by name only, persistent storage,
health, logs, and metrics. Never change Docker permissions or print container
environment values. Re-run after read-only acceptance and store output in this
directory. No production mutations are involved.

## Regression/dependency owner

1. Resolve and hash-lock the supported RAG, Workbench, Videos, and Docs test
   dependencies in reviewed repository locks; reconcile conflicting RAG
   `pyproject.toml` and `requirements.txt` constraints. Do not use mismatched
   `/tmp` environments as full-suite proof.
2. Stage reviewed wheels in the approved internal artifact store. In fresh
   disposable venvs install with `python3 -m pip install --require-hashes -r
   requirements-test.lock`.
3. Install the browser with the approved Playwright tooling in the test host:
   `python -m playwright install chromium`. Do not install browsers into the
   production host or bypass network policy.
4. Run full suites. For Control Center the already-verified command is
   `cd omnibioai-control-center/backend && PYTHONPATH=src python -m pytest -q`;
   use the reviewed Python 3.12-compatible test environment and preserve the
   established 98% coverage threshold.

## Docker E2E, crash matrix, rollback, live canaries, and production

After Docker and images are authorized, run disposable-only Compose services
with temporary volumes, isolated network/database, nonproduction keys, and
mock Discord. Verify all six routes, community exclusion, seven source
clients, failure matrix, durable state, audit/metrics, and rollback to the
previous verified digest. The existing
`scripts/discord_disposable_e2e.py` is in-process mock only and cannot satisfy
this gate. Do not connect production writable volumes.

Live canaries require separate explicit publication authorization and actual
Discord readback. Production deployment requires separate explicit approval
after G1–G11. Neither authorization is provided by this prompt.
