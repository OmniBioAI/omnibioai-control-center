# ARM64 provenance — Master V1

Status: `FAIL` for current-source provenance; native host architecture alone
does not qualify a release image.

Observed platform is `aarch64` on `spark-c275`. No current-source release image
digest, verified SBOM, or provenance attestation bound to an immutable subject
digest exists in the inspected evidence. Historical images are legacy or
disposable artifacts and are not bound to the dirty multichannel source.

The release Dockerfile uses mutable base references, an unpinned apt package
index/install set, a live Rust installer input, and runtime dependencies
installed from ranged `pyproject.toml` constraints. The available
`backend/requirements-test.lock` is version-only, unhashed, test-scoped, and is
not consumed by the release image. Existing CI describes a native ARM64
build/attestation path, but no execution artifact qualifies this source.

The current source tree is dirty and its exact source digest is recorded in
`source-snapshot.md`. An
independent provenance review has not passed. Safe next steps require a
scoped clean candidate revision, immutable base-image digests, reproducible
system/Rust inputs, a hash-locked runtime dependency set, native ARM64 CI build,
image digest, SBOM, provenance, and independent subject/input verification.
Do not label a local architecture observation or mutable tag as provenance.
