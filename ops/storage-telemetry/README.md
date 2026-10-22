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

Never place the Restic password in this repository. The host conf,
`/etc/omnibioai/storage-telemetry.conf`, is a copy of
[`storage-telemetry.conf.example`](storage-telemetry.conf.example). Its targets,
pool and UUIDs must match `config/control_center.yaml`;
`backend/tests/test_storage_config_consistency.py` fails if they drift apart.

UUIDs, not `sdX` names, identify every disk, because kernel names can change
across reboots. exFAT volumes have a short `XXXX-XXXX` UUID.

What the collector runs, once an hour (`OnCalendar=hourly`):

- `findmnt -n -o UUID,FSTYPE <path>` for each target. A target counts as mounted
  only when its UUID matches. Its filesystem type and whether the host mount is
  read-only (`statvfs`) are recorded too.
- For the mergerfs archive pool, `findmnt -n -o FSTYPE <path>`, which must be
  `fuse.mergerfs`.
  - The pool's settings are read from its control file,
    `<path>/.mergerfs`: `user.mergerfs.branches`, `category.create`,
    `minfreespace` and `version`.
  - These are the same `getxattr` calls `getfattr -n` makes. `getfattr` itself
    is not installed on the DGX.
  - The branch list must match the configured paths exactly, in order.
  - Branches are stored by target role name, never by path.
  - mergerfs has no UUID. findmnt's SOURCE for it is a shortened fsname, so it
    is not used.
- `lsblk -no PKNAME /dev/disk/by-uuid/<uuid>` for each SMART role, to find its
  whole disk. The result must be exactly one `sdX` or `nvmeXnY`, recorded as
  `device`; otherwise the role gets an error and SMART is not run.
- `smartctl -n standby -H -A --json=c` on that disk, with `-d nvme` for NVMe
  and `-d sat` otherwise.
  - A sleeping disk is skipped (not woken) and recorded as
    `"state": "standby"` with no error.
  - For SATA disks: attributes 5/197/198/199 and temperature. The last
    attribute 199 reading is kept as `crc_baseline` for the next run.
  - For NVMe: `percentage_used`, `media_errors` and `temperature`. The
    dashboard warns when media errors are above 0 or wear reaches 80%.
  - **SCSI fallback:** some USB enclosures reject SAT pass-through. On this
    host that's `sdg` and `sdh`, the two 2 TB disks. When smartctl reports
    `Read Device Identity failed` or `A mandatory SMART command failed`, the
    collector runs `smartctl -H -d scsi --json=c` instead.
    - It records `"smart_mode": "scsi_health_only"`, with `passed` from the
      SCSI health status and no attributes.
    - It never uses `-T permissive`.
  - **Unknown power state:** when the bridge rejects the power-mode check
    (ILLEGAL REQUEST, sense 05/24, or `CHECK POWER MODE not implemented`), or
    the SCSI fallback is used, the disk is recorded as
    `"power_state": "unknown"`, never `standby`.
    - Any query could wake such a disk, so it is checked at most once every 6
      hours (`checked_at`).
    - Runs in between keep the last record unchanged (`"reused": true`), and
      resolving its UUID with `lsblk` doesn't wake it.
    - With the hourly timer the check lands every 6–7 hours, because a run a
      few seconds early waits for the next one.
    - The dashboard shows a passed check as a neutral
      "Health OK (basic, enclosure limits SMART)".
  - **Bridges that misreport power mode:** the Seagate bridges on `sdg`
    (`data2tb`) and `sdh` (`archive2tb-b`) answer `-n standby` with
    `Device is in SLEEP mode, exit(2)`, even right after a read woke the disk.
    - That would record them as asleep forever and the SCSI fallback would
      never run.
    - Roles listed in `STORAGE_TELEMETRY_NO_POWER_CHECK` skip `-n standby`.
      The collector runs `-d sat`, records `"power_state": "unknown"`, and
      keeps the 6-hour limit.
    - These bridges can fail SAT silently: the captured `sdg` answer is exit 2,
      with no message and no SMART table. So for these roles the collector
      falls back to `-H -d scsi` when either is true, whatever the message text:
      - exit-status bit 1 is set (the device couldn't be opened or identified)
      - there is no `ata_smart_attributes` table
    - `passed` comes from `smart_status.passed`.
    - Within the 6 hours, an earlier result is reused only if it has a
      `smart_mode` and a boolean `passed`. Anything incomplete is queried again
      on the next run.
    - For every other disk, "SLEEP mode" counts the same as "STANDBY".
- `dmesg --since "24 hours ago"`, reduced to fixed-label counts (I/O errors,
  resets, ext4 errors) and the kernel device names (`sdd`, `sda1`,
  `nvme0n1p2`, …) on matching lines. Raw dmesg lines are never stored.
- `restic snapshots --json --no-lock`, with a 10-minute timeout. No other
  Restic command is run.
  - Size and file count come from the newest snapshot's backup summary
    (`total_bytes_processed`, `total_files_processed`).
  - Without a summary, which restic older than 0.17 doesn't write, `stats` is
    `null` with no error.

The whole service run is capped at 30 minutes. The atomically written JSON
(`root:root 0644`) contains:
- bounded SMART values and power state
- mount UUIDs, types and read-only flags
- the pool's branch roles and settings
- redacted Restic snapshot metadata and latest-snapshot stats
- the kernel counts

Read-only disks (the two 2 TB archive members) never raise a capacity warning:
they are full by design.
