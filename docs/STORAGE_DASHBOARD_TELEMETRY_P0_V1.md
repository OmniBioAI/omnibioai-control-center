# Storage Dashboard metadata-only telemetry V1

The Control Center reads a single bounded JSON snapshot produced by
`scripts/storage_metadata_collector.py`. The host collector reads only the
fixed host mount table, fstab entries, block-device identity metadata, and
`statvfs` counters for configured mountpoints. It does not walk storage trees,
open stored files, or access Restic repositories or credentials.

## Snapshot trust and schema

The host collector signs canonical JSON with an Ed25519 private key at
`/etc/omnibioai/storage-telemetry-ed25519.pem`. Provision that key root-owned
with mode `0400`; the public key is pinned as the non-secret
`STORAGE_TELEMETRY_PUBLIC_KEY` Control Center environment value. The output is
atomically replaced at `/run/omnibioai/storage-telemetry/snapshot.json`,
owned by root and mode `0444`. The collector should run on a short systemd
timer (candidate unit files are in `ops/`) and replace the snapshot only after
a complete serialization, fsync, and atomic rename. The unit uses a read-only
system view, no Linux capabilities, a private network namespace, and a single
write location under `/run`.

Schema version 1 contains only the collection timestamp, overall collection
status, archive completeness, and a fixed seven-role map: compute, primary,
backup, archive writable branch, archive member A, archive member B, and
archive pool. Each role contains status, filesystem type, a one-way device
fingerprint, observed and expected mount modes, and total/used/available byte
counters. It contains no host mount paths, fstab text, filenames, directory
contents, UUIDs, serial numbers, secrets, or Restic data.
The archive policy object preserves the allowlisted create policy, minimum
free bytes, dependency declaration count, and policy status without returning
branch paths or other fstab options.

The API reader rejects unknown or missing roles, unexpected fields, invalid
counter relationships, wrong signatures, non-regular or writable files,
multiple hard links, oversized snapshots, observations older than 120 seconds,
and timestamps more than 30 seconds in the future. It checks the open file
identity after `O_NOFOLLOW` and does not cache old values, so missing, stale,
malformed, or tampered input returns UNKNOWN/UNAVAILABLE immediately.

The host collector compares each fixed mountpoint and filesystem type with
fstab and the kernel mount table, verifies block-device identity through the
configured UUID/device source, and calls `statvfs` only after those checks.
mergerfs capacity comes from the pool mount once; branch capacities remain
separate. If any configured archive branch or pool identity is incomplete,
the pool counters are withheld.

## Isolated validation

The API candidate has no host storage path probes and does not call `statvfs`,
Restic, or Docker. The candidate Compose overlay binds only the single signed
snapshot file read-only and pins the collector public key. It contains no
directory bind, Docker socket, repository, or credential.

The isolated storage regression command runs in a disposable container with
network disabled, read-only root, and source/tests mounted read-only. It covers
the signed reader, stale and tampered observations, key mismatch, unsafe file
permissions, size limits, filesystem/device mismatch, missing mounts,
disconnected archive branches, and mergerfs aggregation. Production containers,
databases, storage devices, shared Compose files, and release pins are outside
this validation.

Restic inventory remains UNAVAILABLE. No credentials or repositories are
read. Storage 1.0 readiness remains NOT VERIFIED until the remaining health,
backup, and restore gates have evidence.
