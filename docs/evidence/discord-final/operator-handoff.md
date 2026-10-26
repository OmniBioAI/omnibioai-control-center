# Discord final workstream — consolidated operator handoff

No production action is authorized by this handoff. Do not expose webhook
tokens, use production writable storage, or send live canaries until separately
authorized.

## 1. Discord destination administrator

In the authorized Discord guild, open **Server Settings → Integrations →
Webhooks**. Create or verify one channel-scoped webhook for each exact channel:
`announcements`, `bug-reports`, `feature-requests`, `support`, `tutorials`, and
`omnibioai-alerts`. Keep `general`, `research-chat`, and `show-and-tell` out of
the automated configuration. Verify each webhook's guild and selected
channel in the Discord UI. Record only guild ID, channel ID, webhook ID,
routing name, and approved secret-manager reference in the acceptance matrix;
never paste the webhook URL/token into logs, tickets, or this evidence. Verify
that the legacy alerts webhook really targets `omnibioai-alerts` before any
fallback retirement. Acceptance: six distinct IDs, six correct channel
associations, no community destination, channel-scoped send permission only.

## 2. Secret-manager/runtime owner

Use the organization's existing approved secret manager and service identities;
this session discovered no supported secret-manager CLI/API, so no command or
interface is invented here. Provision seven independent HMAC values under the
references documented in `qualification.md`, one per source. Inject each only
into its authorized runtime; verify signing, constant-time validation,
replay rejection, cross-source isolation, rotation, and invalid-key rejection
without printing values. Acceptance: 7/7 secret references and runtime
readbacks are verified without revealing secret material.

## 3. Authorized DGX operator (read-only first)

From the authorized DGX session, run exactly:

```sh
cd /home/manish/Desktop/omnibioai-ecosystem/omnibioai-control-center
python3 scripts/qualify_discord_v8.py --mode inspect --timeout 30
```

Capture aarch64 host identity, Compose project, image IDs and immutable digests,
image architecture/build labels/source commit, runtime secret references by
name only, persistent storage references, health, logs, and metrics. Do not
change Docker socket permissions or inspect/print container environment values.
Acceptance: candidate source-to-image provenance and deployment config verified
read-only. This inspection does not deploy.

## 4. Dependency and regression owner

The CC full backend gate is now met. RAG's current `pyproject.toml` and
`requirements.txt` disagree on versions for Torch, Transformers, LangChain,
FAISS, and other dependencies; RAG also uses pinned private Git dependencies.
Workbench's full suite has collection failures; Videos browser suites require
the Playwright Chromium binary. Owners should resolve each supported manifest,
create reviewed hash-locked test requirements, and stage an authorized wheel
bundle in the approved internal artifact store. Once an approved lock exists,
install in a fresh disposable venv with:

```sh
python3 -m pip install --require-hashes -r requirements-test.lock
```

Then rerun each repository's documented full test command. Do not use the
current mismatched `/tmp` environments as full-suite qualification. Acceptance:
all cross-repository suites pass; CC remains at least 98% coverage.

## 5. Disposable Docker, crash, and rollback operator

After an authorized Docker session and candidate image digests are available,
use an isolated Compose project/network and temporary volumes only. Run the
existing V8 read-only inspect command first, then the maintained disposable
service runner in its documented mode after its CLI contract is verified from
source. Cover the 18-item fault matrix in `qualification.md`, all six routes,
three community exclusions, IAM/approval, invalid signatures, deduplication,
429/5xx/network/database failure, DLQ/replay, restart, and rollback to the
previous verified digest. Never attach production writable volumes. Acceptance:
persisted pending/ambiguous states survive; ambiguous remote deliveries are
not blindly retried; service health and legacy alerts remain intact.

The current `scripts/discord_disposable_e2e.py` is an in-process mock runner,
not Docker E2E; do not count its 6/6 routes as container acceptance.

## 6. Live canary and production approval boundaries

No live canary was sent. After all technical gates pass, obtain explicit
publication authorization, then use six new unique synthetic IDs (one per
channel), obtain central approval, read messages back from the actual channel,
and record sanitized receipts and actual destination IDs. A separate explicit
production deployment approval is required after G1–G11. Neither authorization
is present now.

Evidence destination: `docs/evidence/discord-final/`; rerun its checksum
verification after appending sanitized results. Never include webhook URLs,
tokens, source keys, or production payloads.
