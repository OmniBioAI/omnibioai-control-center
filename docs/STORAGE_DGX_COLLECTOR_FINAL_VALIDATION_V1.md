# DGX collector final validation

Workstream: `OMNIBIOAI_STORAGE_DGX_COLLECTOR_FINAL_VALIDATION_V1`

Status: actual-host collector and isolated backend verified; shared owner acknowledgment pending.

## Identity root cause and correction

The execution sandbox uses mount namespace `mnt:[4026540642]` and a synthetic
`/dev` without `/dev/disk/by-uuid`. Its read-only mount view is not the host's
mount mode. Host execution uses `mnt:[4026531832]`; UUID symlinks, `lsblk`,
`findmnt`, and mountinfo agree on all six underlying block devices. Earlier
claims that host storage was entirely read-only described the sandbox view.

The collector now reads `/proc/self/mountinfo` so metadata and filesystem
statistics describe the same namespace. It retains fstab UUID -> block-device
major/minor checks and verifies mountpoint `st_dev` before and after statvfs.
Missing device nodes continue to produce INVALID/UNAVAILABLE.

The mergerfs pool has a synthetic device identity. The collector verifies its
filesystem type and mount identity, requires every configured branch to pass
block identity checks, and compares fstab's ordered branch/mode specification
with `user.mergerfs.branches` on the synthetic `.mergerfs` control inode.
This reads filesystem metadata, not stored file contents. Missing permissions
or a runtime branch mismatch withhold pool capacity.

## Actual DGX measurements

All values below are bytes. Each capacity matched an independent subsequent
host statvfs observation exactly, including available bytes (delta zero).

| Role | Total | Available | Filesystem | Host mode |
| --- | ---: | ---: | --- | --- |
| Compute | 4031871553536 | 3072599142400 | ext4 | RW |
| Primary | 25896107933696 | 22630907428864 | ext4 | RW |
| Backup | 19919926484992 | 17985546444800 | ext4 | RW |
| Archive writable | 21912347561984 | 20812282368000 | ext4 | RW |
| Archive member A | 1967844524032 | 72638767104 | ext4 | RO |
| Archive member B | 2000334880768 | 120394350592 | exfat | RO |
| Archive pool | 25880526966784 | 20812282368000 | fuse.mergerfs | RW |

The pool is reported once; individual branches remain separate details.
These are point-in-time observations and available capacity may subsequently change.

## Signing and isolated backend

Host runs used temporary in-memory Ed25519 private keys. No private key was
written to disk. Atomic snapshots were published only under temporary `/tmp`
directories, never the production publication path. Fresh signed observations
were accepted; stale, tampered, and malformed observations were rejected.

The isolated backend used the existing candidate runtime image by immutable ID:
`sha256:5db23f1c875a4ef43cf136becd0222eede8818790418321e37c4b74c923101f5`.
Current candidate source was mounted read-only; the image was not rebuilt or
retagged. The container had no network, no capabilities, a read-only root,
and only candidate code plus temporary metadata binds. It accepted a fresh
real DGX snapshot and returned identical capacities through `/storage/overview`.
Unauthenticated, insufficient-permission, and authorized requests returned
401, 403, and 200. Restic remained UNAVAILABLE; host paths were absent from
the response. No production credentials were used.

A single-file bind would pin the old inode after atomic replacement. The local
candidate overlay now binds the dedicated metadata-only directory read-only,
with `create_host_path: false`. No keys belong in this directory. A live isolated
container successfully read two successive signed publications through this
directory bind. Effective Compose rendering passed and retained rollback image
`obai-control-center:2572cd551bdb`. Shared Compose/release-pin files were not edited.

## Regression results and SIF review

- 78/78 backend tests passed in the pinned Python 3.12.14 runtime: all four
  storage test modules plus `test_routes_docker.py`, including SIF inventory.
  Command: `python -m pytest -c /dev/null -p no:cacheprovider -o faulthandler_timeout=30
  -v test_storage_dashboard.py test_storage_snapshot.py
  test_storage_metadata_collector.py test_routes_storage.py test_routes_docker.py`
  (paths resolve under the mounted `backend/tests`). No storage route tests
  were excluded. Whole-application coverage threshold was not applied to this
  focused suite; test warnings were deprecation and test JWT key-length warnings.
- 3/3 frontend Storage Dashboard tests passed with installed Vitest 2.1.9 and
  the workspace dependencies: `npm test -- --run src/pages/StorageDashboardPage.test.tsx`.
- Systemd unit verification, effective Compose rendering, and diff whitespace
  checks passed. No unit was installed or enabled.

The proposed removal affects only Control Center's three writable SIF data
binds. SIF inventory reads the separate tool-images mount; its tests pass in a
container without the three data binds. TES and Workbench remain untouched.
No live SIF workload was executed: inventory compatibility is verified,
end-to-end workflow compatibility is not claimed. The three live binds remain.

## Ownership and remaining gates

The requested `omnibioai-dev-hub-34` owner is not reachable through the current
agent registry (only this agent is registered). No suitable communication app
is connected. The user has been asked for the owner's contact/acknowledgment.
The running Dev Hub service was observed; absence from this registry is not
evidence of inactivity or exclusive ownership.

Owner acknowledgment remains required before shared configuration edits or
bind removal. Production key provisioning, timer activation, and deployment
remain separately unauthorized. The revised collector/source must be packaged
in a new candidate image before eventual deployment; the old image was used
only as an immutable runtime for current-source validation.

Production containers, databases, storage devices, backups, authentication,
release pins, and rollback images were not changed. No backup operation,
permanent signing-key installation, or recurring timer activation occurred.
