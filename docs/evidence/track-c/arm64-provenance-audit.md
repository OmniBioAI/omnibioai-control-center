# Discord ARM64 source and image provenance audit

Workstream: `OMNIBIOAI_DISCORD_ARM64_ROLLBACK_V10_B`  
Audit date: 2026-10-25  
Result: `SOURCE_IMAGE_CHAIN=FAIL`; `ARM64_PROVENANCE=FAIL`

## Source identity

The multichannel router candidate is commit `7d93709fe4e0d39711d372d399f89a6778c4505a` (`Snapshot V7 Discord candidate for V10 release closure`). The workspace is currently on `main` at `f37ce8c952f917f607e9923cbb47dda8b0406a7a` and contains pre-existing Discord modifications and untracked files. The candidate Discord implementation and its runtime dependency definition match the candidate commit. The qualification harness has three later local edits (`compose.yaml`, `run_qualification.py`, and `test_ownership.py`), so it is not an exact checkout of that commit.

The qualification harness's source-tree algorithm, applied to a clean archive of the candidate commit, returned `75122fe8eba41187b76f43d4831f3bd9a216069f903aaec93440e65467072c17` twice. Applied to the current worktree it returned `03b0c52e1992579ec8d9a1fba1d721b859d1ef392be040d5b919d8ac4691d66e` twice. The latter fingerprints `backend/src/control_center/**` plus the locally evolved qualification harness; it is not a Git commit identity. Current source-file SHA-256 values:

| Source input | SHA-256 |
|---|---|
| `backend/src/control_center/notifications/discord.py` | `762dd2392514e9424f1682ed78483258238b1c935325c4c68bd761bf7a9d120c` |
| `backend/src/control_center/notifications/discord_events.py` | `af74d0f0d5d86a03bb2b0c36ccce3a28e75fb586315163e67c0b3805cfb28583` |
| `backend/src/control_center/api/routes_discord_events.py` | `874ba852860e8e2bdf70b5892ac576354d2f94d8e19fb8f6a30823a61e5af4e0` |

## Build context, Dockerfile, and dependencies

The release workflow's authoritative build is the root `Dockerfile`, repository root context (`context: .`), target `backend` or `frontend`, as defined by `.github/actions/build-native-arch-image/action.yml`. `docker/Dockerfile` is a distinct backend-only Dockerfile and is not called by the release workflow. The disposable qualification harness uses `scripts/discord-docker-qualification/Dockerfile` over the same repository-root context and overlays the candidate Python source on a pre-existing local base image; it does not build the deployable release image.

| Input at candidate commit | SHA-256 | Notes |
|---|---|---|
| `Dockerfile` | `7be5136e0648da766825eb7150f3ab61f97f1eb36beb7dc69853629a82327ca4` | Release Dockerfile; multi-stage Node, backend, nginx build |
| `backend/pyproject.toml` | `5f80e84043888438258ee45230492ea3a4021bbf0cebcb0f3cd351c36bef6ba2` | Runtime package constraints; `cryptography==46.0.3` is pinned for ARM64 compatibility |
| `backend/requirements-test.lock` | `353dcfd651bda5e5ba494a94d5de1ee58c74dcba5f4bc2750087255aab7fc514` | Exact test-environment versions, explicitly not an artifact-hash lock; not consumed by release Dockerfile |
| `frontend/cc-ui/package-lock.json` | `5545f6d556353d87e250a8b3b680a06e1d6799ee654875bc9e14c8144239aae6` | npm lock with package integrity metadata |
| `.github/workflows/ci.yml` | `7d763a53232efb48bea79fc4b2aee31a697776dd606668ce2daa954da70eb6bf` | Native per-architecture staging, assembly, verification, smoke and promotion gates |
| `.github/actions/build-native-arch-image/action.yml` | `93d4a986803bd90f8b7938e88efedfa7a94fb54d4e6367777e696c3226491bee` | Native runner assertion, immutable staging digest, SBOM/provenance build options |

Reproducible release build is not established: Python runtime dependencies are ranges rather than a release lock, the test lock has no package hashes and is not used by the Dockerfile, apt inputs are not snapshot-pinned, and the base references in the root Dockerfile are tags (`node:20-bookworm-slim`, `ghcr.io/omnibioai/omnibioai-base:1.0.0`, `nginx:alpine`). The release workflow has strong immutable staging/attestation checks, but those jobs have not produced an artifact for this Discord source revision.

## ARM64 evidence

The host reports Linux `aarch64`; the Docker daemon reports Linux `aarch64`. A single disposable container ran with `--network none`, read-only root, and the candidate source mounted read-only over local base image ID `sha256:71db0e0401219e5efedb73f1aad2712af5907e49b03678db527d2c03fff9abd3`. It imported the candidate Discord modules, reported Python package versions (`cryptography 46.0.3`, FastAPI `0.115.12`, HTTPX `0.28.1`), and applied SQLite migrations 1–3 over the legacy `discord_deliveries` schema. Expected `discord_deliveries`, `discord_event_nonces`, `discord_event_records`, and `discord_schema_migrations` tables were present. Container inventory before and after was identical. This establishes a useful native ARM64 source compatibility smoke on that base image; it is not a build of the release Dockerfile or a digest-bound candidate image runtime test.

The release workflow statically requires native `ubuntu-24.04-arm` (`uname -m == aarch64`) and builds `linux/arm64` separately from `linux/amd64`, assembles indices from immutable architecture digests, verifies OCI source/revision/version labels and subject-bound SBOM/provenance, and runs native smoke before promotion. Static workflow checks passed. The actual candidate image, ARM64 runtime manifest digest, SBOM, provenance, and native candidate image smoke are absent.

## Image identity and provenance decision

`IMAGE_DIGEST=UNAVAILABLE` for the current multichannel source. There is no current-source release image digest. The local image `sha256:71db0e0401219e5efedb73f1aad2712af5907e49b03678db527d2c03fff9abd3` is Linux ARM64 and has OCI revision `f37ce8c952f917f607e9923cbb47dda8b0406a7a`; it is a legacy base, not the `7d93709…` router candidate. A historical qualification image `sha256:7b5be5ce3db9bb102614c04bb9dbdf1b3ebb8418cd8f0c1e864c58c628cc5345` is recorded in older evidence as a local ARM64 disposable image, but it is absent from the daemon and does not have published release provenance. Neither digest is the current release artifact.

The old standalone deployed web digest `sha256:ad11b3005f2625cc5d4b65cd38fd56c20e383190f78cd570c57dbe2f904f37eb` inspected locally as Linux ARM64; its labels omit source revision. It is a frontend artifact and cannot prove backend router provenance.

Gate decision: `SOURCE_IMAGE_CHAIN=FAIL`, because no immutable image is bound to the candidate source; `ARM64_PROVENANCE=FAIL`, because no current candidate runtime manifest and attestations were verified. An image digest by itself or an ARM64 host does not close either gate.

## Checks run

- Discord focused backend tests: 149 passed, 5 warnings.
- Qualification ownership tests: 32 passed, 6 subtests passed.
- Python source compilation: 278 files compiled.
- Workflow source/image identity static test: passed.
- Release verifier digest-binding test, including bare-digest negative control: passed.
- Release verifier live GHCR contract test for historical `0.7.4`: passed; wrong expected version rejected.
- Current Discord candidate image build/provenance/runtime tests: unavailable because no image was built or published for commit `7d93709…`.
- Historical `0.7.5` GHCR verification: not run; automatic approval review rejected the read-only command after reaching a usage limit. No retry was made.

## Required closure

First obtain a clean reviewed commit containing the router and pinned release dependency/build inputs. Build the authoritative root Dockerfile on native ARM64 using the repository-root context. Retain the immutable ARM64 runtime digest and full index digest, config labels, package/image SBOM, provenance attestation bound to that runtime digest, registry availability result, and native runtime smoke output. Keep the release SHA and image digests in the release manifest. This closes only the ARM64 provenance gate; rollback remains a separate gate until a genuinely compatible earlier multichannel image is available and rehearsed.
