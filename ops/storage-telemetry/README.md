# Storage telemetry collector

The API container only reads the generated snapshot and its read-only storage
binds. It does not receive privileges, `/dev`, the Docker socket, or Restic
credentials. The host service uses the expected mount UUID map below; keep it
in sync with `expected_filesystem_uuid` in `config/control_center.yaml`. The
API also compares the UUID the host reports against its own config, so a
mismatch in either place shows the target as "Not mounted".
The replaced primary disk (`/mnt/wdpro26tb`) is intentionally absent from both
maps and has no bind mount.

The root filesystem is measured through an empty directory,
`/var/lib/omnibioai-storage-probe`, instead of a bind of host `/`. The
container runs as root, so binding `/` would expose `/etc` (including the
Restic password file) to the API. The probe must live on the root filesystem;
the install steps check this.

Install steps: [INSTALL.md](INSTALL.md).

Never place the Restic password in this repository. `/etc/omnibioai/storage-telemetry.conf` contains:

```ini
STORAGE_TELEMETRY_TARGETS="root|/|9f3cd4b6-f34e-435e-9fcf-ed7861f7cf99 backup|/mnt/omnibioai-backup20tb|9d872bab-a481-4fca-8ad8-8031d78c0dbc archive|/mnt/omnibioai-archive22tb|6a805bb7-2513-435f-9cd4-b9970a0e4fc4"
STORAGE_TELEMETRY_DISKS="backup:9d872bab-a481-4fca-8ad8-8031d78c0dbc archive:6a805bb7-2513-435f-9cd4-b9970a0e4fc4"
RESTIC_REPOSITORY=/mnt/omnibioai-backup20tb/restic
RESTIC_PASSWORD_FILE=/etc/omnibioai/restic-password
```

The UUIDs above are the current mapping: `/` → root filesystem UUID,
`sdd1` → backup UUID, and `sda1` → archive UUID. The collector checks each
with `findmnt -n -o UUID <path>`; re-check them the same way before installing
if disks have changed. `STORAGE_TELEMETRY_DISKS` uses the same filesystem
UUIDs, because `sdX` names can change across reboots.

What the collector runs, once an hour (`OnCalendar=hourly`):

- `lsblk -no PKNAME /dev/disk/by-uuid/<uuid>` for each SMART role, to find
  its whole disk. The result must be exactly one `sdX` or `nvmeXnY`, recorded
  as `device`; otherwise the role gets an error and SMART is not run.
- `smartctl -n standby -H -A -d sat --json=c` on that disk. A sleeping disk is
  skipped (not woken) and recorded as `"state": "standby"` with no error; the
  last attribute 199 reading is kept as `crc_baseline` for the next run.
- `findmnt -n -o UUID <path>` for each target.
- `dmesg --since "24 hours ago"`, reduced to fixed-label counts (I/O errors,
  resets, ext4 errors) and the kernel device names (`sdd`, `sda1`,
  `nvme0n1p2`, …) on matching lines. Raw dmesg lines are never stored.
- `restic snapshots --json --no-lock` and `restic stats latest --json
  --no-lock`, each with a 10-minute timeout. No other Restic command is run.

The whole service run is capped at 30 minutes. The atomically written JSON
(`root:root 0644`) contains bounded SMART values and power state, mount UUIDs and match
booleans, redacted Restic snapshot metadata and stats, and the kernel counts.
