# ARM64 provenance and rollback — V11

Workstream: `OMNIBIOAI_DISCORD_ARM64_PROVENANCE_ROLLBACK_V11`  
Date: 2026-10-25  
Decision: `SOURCE_IMAGE_CHAIN=FAIL`; `ARM64_PROVENANCE=FAIL`; historical rollback
candidate is missing; rollback rehearsal was not run.

No production image was built, pushed, retagged, or deployed. No production
service, volume, database, credential, or configuration was changed. Docker
operations were read-only metadata inspection only.

## Source and build identity

| Item | Observed identity |
|---|---|
| Current repository HEAD | `f37ce8c952f917f607e9923cbb47dda8b0406a7a` |
| Branch | `main` |
| Worktree | Dirty: Discord implementation, tests, workflows, and evidence are modified/untracked; not a releasable immutable source revision |
| Discord source snapshot fingerprint | `4da310b38ca675a4482a15f3f7318c6e7b9e521fc87fe06f360d73adb3fb275c`; qualification harness algorithm over all `backend/src/control_center/**` and `scripts/discord-docker-qualification/**` files, excluding `__pycache__` |
| Release Dockerfile | Repository root `Dockerfile`, SHA-256 `7be5136e0648da766825eb7150f3ab61f97f1eb36beb7dc69853629a82327ca4`; backend target |
| Deployment build context | Repository root (`.`), target `backend`, as referenced by `omnibioai-studio/docker-compose.yml` (`MACHINE_DIR/omnibioai-control-center`); that Compose file SHA-256 is `11a4b56d9de0787afe0fda8c3a8fbea64f06288ff337155834ec500aabbffddc` |
| CI release build | `.github/actions/build-native-arch-image/action.yml`; root context, target, native `linux/arm64`, immutable per-commit staging reference, SBOM and provenance options. This is a static workflow contract; no run/result for this source snapshot was found. |
| Separate backend Dockerfile | `docker/Dockerfile`, SHA-256 `ea15be32a2c73b02b4a86832c9909b7b2ebea1388597bd6635f9295a69f017c8`; not selected by the Studio deployment Compose or release action |
| Runtime dependency lock | Missing. `backend/pyproject.toml` SHA-256 `5f80e84043888438258ee45230492ea3a4021bbf0cebcb0f3cd351c36bef6ba2`; several runtime dependencies are ranges and the Dockerfile installs from this file without a lock |
| Test lock | `backend/requirements-test.lock`, SHA-256 `353dcfd651bda5e5ba494a94d5de1ee58c74dcba5f4bc2750087255aab7fc514`; version pins only, no hashes, and not consumed by the release Dockerfile |
| Frontend lock | `frontend/cc-ui/package-lock.json`, SHA-256 `5545f6d556353d87e250a8b36e65e1dfedd671c3183ef2e9ee4b6821c86139a0`; relevant only to frontend target |
| Docker ignore | `.dockerignore`, SHA-256 `c74f415c0f9fe342d5c6def49f94aaa3349153984c2582f6d3d8b1a8cd9bb4bc` |

The root release Dockerfile also uses mutable base references (`node:20-bookworm-slim`,
`ghcr.io/omnibioai/omnibioai-base:1.0.0`, `nginx:alpine`), an unpinned apt
index/install set, a Rust installer URL, and unpinned runtime dependency ranges.
The CI workflow can bind a particular build to immutable staged digests and
attestations, but its presence does not make this local build reproducible and
does not establish provenance for the current source.

## ARM64 and image availability

This session reports host `spark-c275`, `uname -m=aarch64`, and Docker daemon
`linux/aarch64`, Docker context `default`. The local device-tree model is
unavailable, and `nvidia-smi` cannot communicate with the NVIDIA driver. Thus
the architecture is verified as ARM64, but this session cannot independently
verify the DGX Spark model/driver runtime. Existing V10_B evidence describes a
native ARM64 source compatibility smoke for an earlier source fingerprint; it
does not qualify the present dirty candidate or a release image.

The intended Studio Compose build references the current repository root and
backend target. Local image metadata confirms these available artifacts are
legacy builds:

| Local image | Immutable image ID | Platform | OCI revision |
|---|---|---|---|
| `obai-control-center:f37ce8c952f9` | `sha256:71db0e0401219e5efedb73f1aad2712af5907e49b03678db527d2c03fff9abd3` | `linux/arm64` | `f37ce8c952f917f607e9923cbb47dda8b0406a7a` |
| `obai-control-center:7a9bc36a41b8` | `sha256:30084f23cfcf6797b1080ca56a43ffadd26387efdd93e4447a057ee1739303aa` | `linux/arm64` | `7a9bc36a41b87f26eec6c9696a52de4b5c6e11f6` |

The first image is the local legacy base used by the qualification harness. It
is not bound to the current dirty multichannel source. No current-source
release image or registry digest was found or built. The older recorded
disposable Discord image ID `sha256:7b5be5ce3db9bb102614c04bb9dbdf1b3ebb8418cd8f0c1e864c58c628cc5345`
is absent from the local daemon. No registry availability check was made.

`SOURCE_IMAGE_CHAIN=FAIL`: the current source is dirty, no release image digest
is bound to it, and no provenance/SBOM attestation was inspected for it.
`ARM64_PROVENANCE=FAIL`: host and daemon architecture are ARM64, but neither a
candidate image build nor a candidate image runtime/attestation exists here.

## Rollback candidate and compatibility

`ROLLBACK_CANDIDATE=MISSING`. The local images above predate the multichannel
router. The recorded prior source release `v0.7.5` (`7e4610a91895f7291e936979b88951f1545baa40`)
has only the single direct-webhook notifier contract. It has no signed event
ingestion API, six-channel route table, source verifier, approval lifecycle,
nonce store, or event-store migrations. The old image cannot preserve the
multichannel service contract and is not a compatible rollback image.

The candidate adds `DISCORD_CHANNEL_WEBHOOKS`, seven source verifier keys, and
`DISCORD_DELIVERY_STATE_DIR`. SQLite event schema migrations 1–3 add nonce,
event-record, index, and reconciliation state alongside the delivery table.
The old image neither accepts the new API/configuration nor knows how to read
those event records. A shared upgraded database must not be mounted into the
legacy image as a rollback strategy. The V11 candidate has not completed a
container-level dependency/config/schema rehearsal.

`ROLLBACK_REHEARSAL=NOT_RUN`. A rehearsal that switches between a candidate
and an incompatible legacy image would test the wrong contract and is not
reported as a pass.

## Safe first-release recovery plan

This is recovery for the first multichannel release, not historical rollback.
Before a separately approved production release:

1. Record the exact active legacy image digest, Compose/config revision, secret
   references, state path, and health/read-only state. Preserve the original
   image/config/state as the recovery baseline.
2. Take and restore-test a consistent backup of the existing database and any
   WAL state; record secret-manager references only. Keep this backup outside
   the candidate's writable state path.
3. Build a reviewed clean commit on native ARM64. Pin base images by digest,
   pin apt/Rust inputs, produce a hash-locked runtime dependency file, and have
   CI build/publish the backend target with the exact source SHA, SBOM, and
   provenance bound to the immutable image digest.
4. Verify that digest is available in the deployment registry, inspect the
   `linux/arm64` manifest and OCI source/revision labels, verify attestation
   subjects, then run the candidate in a new isolated Compose project with
   synthetic keys, mock webhooks, and a separate disposable database/volume.
5. For first-release failure, stop the candidate and restore the saved legacy
   image digest, original Compose/config references, and pre-release database
   snapshot on the original state path. Keep candidate-upgraded state isolated
   for diagnosis; do not downgrade it in place.
6. Verify restored image digest, config references, service health, and
   read-only data checks; compare protected-resource inventories before and
   after. A future rollback rehearsal becomes valid only after a compatible
   multichannel release has been qualified and retained as an immutable
   previous image.

## Review and evidence status

The evidence includes the exact HEAD, current source fingerprint, Dockerfile,
dependency and context hashes, local image IDs/platform labels, compatibility
decision, and first-release recovery procedure. The evidence manifest can be
verified using `SHA256SUMS` in this directory.

Independent review of this V11 provenance/rollback report: `NOT_RUN`. The
existing V11 independent review covers the disposable harness's security
changes and explicitly records Docker as not run; it is not an independent
review of this provenance decision or of a release image.

```text
WORKSTREAM=OMNIBIOAI_DISCORD_ARM64_PROVENANCE_ROLLBACK_V11
SOURCE_SHA=f37ce8c952f917f607e9923cbb47dda8b0406a7a (dirty; source fingerprint 4da310b38ca675a4482a15f3f7318c6e7b9e521fc87fe06f360d73adb3fb275c)
IMAGE_DIGEST=UNAVAILABLE
ARCHITECTURE=linux/arm64 (host and daemon aarch64; DGX model/driver unverified)
SOURCE_IMAGE_CHAIN=FAIL
ARM64_PROVENANCE=FAIL
ROLLBACK_CANDIDATE=MISSING
ROLLBACK_REHEARSAL=NOT_RUN
PRODUCTION_UNCHANGED=YES
NEXT_ACTION=Commit and review a clean source snapshot, pin all release build inputs, produce and verify an immutable native ARM64 image with SBOM/provenance, then rehearse first-release recovery on a disposable copy; retain that qualified image as the genuine rollback target for the next release.
```
