# Storage metadata telemetry production gates

Workstream: `OMNIBIOAI_STORAGE_METADATA_ONLY_PRODUCTION_GATES_V1`

## SIF bind audit

The active Studio Compose source is
`/home/manish/Desktop/omnibioai-ecosystem/omnibioai-studio/docker-compose.yml`.
Its `control-center` service and the effective release-pin override
(`/home/manish/Desktop/omnibioai-ecosystem/release-candidates/compose.release-pin.yml`)
each declare the same three writable host directory binds:

```yaml
- /media/manish/OmniBioAI-SIFs/work:/media/manish/OmniBioAI-SIFs/work
- /media/manish/OmniBioAI-SIFs/reference:/media/manish/OmniBioAI-SIFs/reference
- /media/manish/OmniBioAI-SIFs/omnibioai-test-data:/media/manish/OmniBioAI-SIFs/omnibioai-test-data
```

Searches of Control Center Python, scripts, UI sources, and relevant Workbench
sources found no consumer of these exact paths. The Control Center SIF inventory
uses the separate, read-only
`${MACHINE_DIR}/omnibioai-tool-images/sif:/workspace/omnibioai-tool-images/sif:ro`
bind, while the TES service has its own SIF image mount. The Control Center's
Docker client integration inspects containers and images; it does not create
containers that could implicitly inherit these three paths. A comment in the
Workbench volume section records a historical workspace symlink exposure; it
is not proof that Control Center has no indirect consumers. Exact-path searches
alone cannot establish full workflow compatibility. The final-validation
report below distinguishes passing SIF inventory tests from unexecuted workloads.

The minimum proposed remediation is to delete only the three SIF data-directory
bind entries from `control-center` in both Compose files. The release-pin file
uses `volumes: !override`, so changing only the base file would not affect the
effective pinned configuration. Keep the separate SIF image mounts used by the
execution services. This proposal has not been applied to either shared file;
shared owner acknowledgment is still required.

## Isolated change proposal

The Compose edit is limited to deleting the three entries listed above from
`control-center.volumes` in the base and release-pin files. Do not alter the
SIF image binds, TES service, or image selection. Validate the full effective
configuration with the existing base, override, release-pin, and storage
snapshot overlay before any deployment. No production deployment is authorized
by this report.

## Signing and collector installation plan

On the DGX host, provision a new Ed25519 private key at
`/etc/omnibioai/storage-telemetry-ed25519.pem`, owned by root with mode `0400`,
on the host's protected root filesystem. Pin only the corresponding raw public
key in the Control Center configuration. Validate the keypair and a single
snapshot publication in a controlled one-shot run; do not enable the systemd
timer. Install the collector and unit files only after shared ownership review.
Timer activation and production deployment require separate authorization.

The earlier one-shot validation attempted in the sandbox produced an
UNAVAILABLE collector snapshot: its mount namespace has the storage mounts but
does not expose the host `/dev/disk/by-uuid` block identities. This is a
fail-closed result, not proof of DGX validation. Docker socket access is denied
in that sandbox. This blocker was resolved by an approved read-only host
execution outside the sandbox. See `STORAGE_DGX_COLLECTOR_FINAL_VALIDATION_V1.md`
for successful actual-host validation and the remaining owner acknowledgment.

## Preserved constraints

- Restic remains `UNAVAILABLE`; no credential or repository access was made.
- No key was installed and no recurring timer was enabled.
- No production service, database, disk, backup, or release pin was changed.
- The candidate storage implementation remains in the workspace.
