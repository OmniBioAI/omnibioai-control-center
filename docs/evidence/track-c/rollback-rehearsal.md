# Discord rollback candidate and rehearsal record

Workstream: `OMNIBIOAI_DISCORD_ARM64_ROLLBACK_V10_B`  
Result: `ROLLBACK_CANDIDATE=MISSING`; `ROLLBACK_REHEARSAL=NOT_RUN`

## Candidate decision

There is no verified historical multichannel Discord image that can safely roll back the current router contract. Do not substitute a new build, a mutable tag, or the old one-webhook release and call it a historical rollback.

The genuine prior source release is `v0.7.5`, commit `7e4610a91895f7291e936979b88951f1545baa40`. Its notifier source SHA-256 is `055a0ed62b6c148be622bef58029799947260d5d05d32fdbe667fad76236f49f`; the candidate notifier at `7d93709fe4e0d39711d372d399f89a6778c4505a` is `762dd2392514e9424f1682ed78483258238b1c935325c4c68bd761bf7a9d120c`. The prior notifier only has the legacy direct-webhook `notify()` contract. It has no authenticated event ingestion, event routing/approval records, replay nonce store, reconciliation fields, or v1-v3 schema migrations. It is incompatible with the multichannel feature and cannot recover its behavior.

The locally available legacy application image is `obai-control-center@sha256:71db0e0401219e5efedb73f1aad2712af5907e49b03678db527d2c03fff9abd3`, platform `linux/arm64`, OCI revision `f37ce8c952f917f607e9923cbb47dda8b0406a7a`. It predates the router candidate. A prior disposable image was recorded as `sha256:7b5be5ce3db9bb102614c04bb9dbdf1b3ebb8418cd8f0c1e864c58c628cc5345`, but it is not locally present, not a published release image, and its source-tree digest belongs to an older dirty qualification snapshot. Both are excluded as rollback candidates.

The `0.7.5` GHCR digest/availability was not freshly inspected: the approval service rejected the read-only verification request due to its usage limit. Existing release evidence must not be promoted to a fresh availability claim. This does not change the compatibility rejection, which is independently supported by the source/API/schema diff.

## Configuration and database compatibility

The new router accepts channel-specific webhook mappings, source HMAC keys, approval policy, and a persistent state directory. The legacy notifier takes a single `DISCORD_WEBHOOK_URL` or alert webhook. Reverting to the old image would stop accepting signed events and would not restore the old semantics for multichannel routes. Never render live credentials while rehearsing; use only synthetic keys and mock webhook URLs.

The new SQLite state is `deliveries.sqlite3` in `DISCORD_DELIVERY_STATE_DIR`. `DiscordEventStore` applies schema migrations 1–3 for event records/nonces, indexes, and reconciliation metadata. `DiscordPublisher` uses `discord_deliveries`. Native ARM64 smoke confirmed the current store can add those tables alongside the legacy `discord_deliveries` table. That is a forward compatibility check only; the old image has not been shown to preserve or understand candidate state. A rollback after candidate writes therefore must restore a pre-release copy of the entire database state and its WAL/SHM-consistent snapshot, or run the old service against its original unchanged state path. Never point the legacy image at the candidate-upgraded database and assume compatibility.

## Controlled first-release recovery plan for separate approval

This is a baseline/first-release recovery plan, not a historical rollback. It requires a separate release/change approval before any production execution.

1. Keep the currently running legacy image, Compose configuration, secrets, and state path as the known baseline. Record its exact local/registry digest, image config, platform, source revision, container ID, and health checks through an authorized read-only session.
2. Before the approved first release, take and verify a restorable snapshot of the application state, including SQLite database and WAL state, plus a protected copy of the active configuration/secrets by secret-manager reference (never by printing secret values). Record checksums for non-secret backup artifacts and test restore into a separate disposable location.
3. Build and verify the new release from a clean source commit. Require an immutable ARM64 manifest digest, availability, source labels/attestation, SBOM/provenance binding, native smoke, and a reviewed schema/configuration contract.
4. Rehearse the candidate from that digest in an isolated disposable project using synthetic credentials, a new labeled disposable volume/database, an internal network, and a mock Discord receiver. Verify startup, health, all schema versions, state transitions, and exactly-once/no-blind-replay behavior. Never use a production webhook or production data in rehearsal.
5. Under separate approval, deploy the first release with a new versioned state path or a reviewed additive migration and a verified backup. If acceptance fails, stop the candidate and restore the prior legacy image digest together with its original configuration and pre-release state snapshot. Keep the candidate-upgraded state isolated for diagnosis; do not attempt to downgrade its schema in place.
6. Verify the restored service identity/digest, health, configuration references, and read-only data checks. Record before/after inventories and confirm no unrelated containers, networks, volumes, or data changed.

Example immutable restore form, to be populated only after the first-release approval packet records real values:

```sh
docker pull <verified-legacy-image>@sha256:<verified-legacy-manifest-digest>
docker image inspect <verified-legacy-image>@sha256:<verified-legacy-manifest-digest>
```

The actual Compose restore command must be prepared from the then-current approved deployment manifest and exact previous configuration/state references. No command that modifies production Compose or starts/replaces production containers is authorized by this audit.

## Disposable rehearsal status and acceptance criteria

`ROLLBACK_REHEARSAL=NOT_RUN`. A rehearsal cannot honestly switch candidate to prior image because no compatible prior multichannel image exists. No containers, volumes, networks, databases, webhooks, registry tags, production data, or production Compose were changed. The one isolated smoke container ran with `--rm`, `--network none`, read-only root, and a read-only source mount; inventory comparison showed the running-container list unchanged.

The future rehearsal must use a new run ID and exact ownership manifest; prove no target-name collision, non-overlapping internal subnet, synthetic-only configuration, and new disposable volume; capture a before inventory; seed representative states (`pending_approval`, `queued`, `delivered`, `failed`, `delivery_unknown`); preserve database and mock-receiver ledgers while changing only the owned router image; and verify every row, approval/reconciliation field, migration, publisher receipt, and dead-letter hash after each switch. Ambiguous deliveries must remain ambiguous without blind replay; delivered event IDs must not produce another mock send; a new approved event must route exactly once. Cleanup may remove only exact manifest-owned IDs with matching workstream/run-ID labels and must be followed by an after inventory.

Acceptance requires both image references to be immutable and available, both runtime configs to identify the expected platform and source revision, schema compatibility to pass against a copy of candidate-created data, all state/payload checks to pass, zero real Discord sends, all disposable resources to be accounted for, and protected production inventory to remain unchanged. Provenance and rollback retain independent pass/fail decisions.

## Blocker and next action

Blocker: first multichannel release has not yet been built and qualified as an immutable ARM64 artifact, so no prior compatible multichannel image exists. Complete and approve the first release through the ARM64 provenance gate, retain its exact image digests and schema contract, and then use it as the genuine prior image for a later candidate's isolated rollback rehearsal. Do not mark the first release itself as its own rollback target.
