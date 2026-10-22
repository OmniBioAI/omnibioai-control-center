# Storage telemetry: host install

Run from the root of an `omnibioai-control-center` checkout that contains
this directory. Steps marked **sudo** change the host. Everything else is
read-only. See `README.md` for what the collector does and why the root
filesystem is measured through a probe directory.

The collector is already installed on the DGX (PR #108). To add the archive
pool, the 2 TB disks and NVMe SMART to that install, follow steps 1, 2b, 4 and 5.
For a fresh host, follow every step.

## 1. Pre-checks (read-only)

```bash
# Expected UUID and type of each target, matching config/control_center.yaml and
# storage-telemetry.conf.example. exFAT has the short XXXX-XXXX form.
#   /                             9f3cd4b6-f34e-435e-9fcf-ed7861f7cf99  ext4
#   /mnt/omnibioai-backup20tb     9d872bab-a481-4fca-8ad8-8031d78c0dbc  ext4
#   /mnt/omnibioai-archive22tb    6a805bb7-2513-435f-9cd4-b9970a0e4fc4  ext4
#   /media/manish/omnibioai-data  39b9324a-640e-4d64-9980-b1f1c9d5578b  ext4   (read-only)
#   /mnt/omnibioai-archive2tb-b   6A7F-D1A6                             exfat  (read-only)
for p in / /mnt/omnibioai-backup20tb /mnt/omnibioai-archive22tb /media/manish/omnibioai-data /mnt/omnibioai-archive2tb-b; do
  printf '%-30s ' "$p"; findmnt -n -o UUID,FSTYPE,OPTIONS "$p"
done

# The archive pool: fuse.mergerfs with exactly these branches, in this order.
#   /mnt/omnibioai-archive22tb=RW:/media/manish/omnibioai-data=RO:/mnt/omnibioai-archive2tb-b=RO
findmnt -n -o FSTYPE /mnt/omnibioai-archive
python3 -c "import os; print(os.getxattr('/mnt/omnibioai-archive/.mergerfs', 'user.mergerfs.branches').decode())"

# The probe directory must be on the root filesystem: this must print the root UUID.
findmnt -n -o UUID -T /var/lib

# SMART disks are configured by filesystem UUID and resolved to the whole disk
# at run time, exactly like this. Each must print exactly one line, a whole disk.
# Today: nvme0n1 (root), sdd (backup), sda (archive), sdg (data2tb), sdh (archive2tb-b).
for u in 9f3cd4b6-f34e-435e-9fcf-ed7861f7cf99 9d872bab-a481-4fca-8ad8-8031d78c0dbc \
         6a805bb7-2513-435f-9cd4-b9970a0e4fc4 39b9324a-640e-4d64-9980-b1f1c9d5578b 6A7F-D1A6; do
  printf '%-38s ' "$u"; lsblk -no PKNAME "/dev/disk/by-uuid/$u" | tr '\n' '|'; echo
done

# The Restic repository is present. Expect: config  data  index  keys  snapshots
sudo ls /mnt/omnibioai-backup20tb/restic

# Tools the collector runs.
command -v smartctl findmnt lsblk dmesg restic python3
dmesg --help | grep -q -- --since && echo "dmesg supports --since"
```

Stop if any of these is wrong:
- a UUID or filesystem type differs
- the pool is not `fuse.mergerfs`, or its branch list differs
- an `lsblk` line is not exactly one whole disk followed by `|`
- the Restic listing is missing any of its five entries

Update `config/control_center.yaml` and the conf file in step 2 to match before
continuing.

## 2. Install the collector (sudo)

### 2a. Fresh host

```bash
sudo install -d -o root -g root -m 0755 /usr/local/libexec/omnibioai /etc/omnibioai /var/lib/omnibioai
sudo install -d -o root -g root -m 0555 /var/lib/omnibioai-storage-probe
sudo install -o root -g root -m 0755 ops/storage-telemetry/collect-storage-telemetry.py /usr/local/libexec/omnibioai/collect-storage-telemetry.py
sudo install -o root -g root -m 0644 ops/storage-telemetry/omnibioai-storage-telemetry.service /etc/systemd/system/omnibioai-storage-telemetry.service
sudo install -o root -g root -m 0644 ops/storage-telemetry/omnibioai-storage-telemetry.timer /etc/systemd/system/omnibioai-storage-telemetry.timer
sudo install -o root -g root -m 0600 ops/storage-telemetry/storage-telemetry.conf.example /etc/omnibioai/storage-telemetry.conf
sudo systemd-analyze verify /etc/systemd/system/omnibioai-storage-telemetry.service /etc/systemd/system/omnibioai-storage-telemetry.timer
```

### 2b. Upgrade an existing install

The units are unchanged. Replace the script and the conf, after checking that
the conf differs only by the new targets, the pool and the extra SMART disks:

```bash
sudo diff /etc/omnibioai/storage-telemetry.conf ops/storage-telemetry/storage-telemetry.conf.example
sudo install -o root -g root -m 0755 ops/storage-telemetry/collect-storage-telemetry.py /usr/local/libexec/omnibioai/collect-storage-telemetry.py
sudo install -o root -g root -m 0600 ops/storage-telemetry/storage-telemetry.conf.example /etc/omnibioai/storage-telemetry.conf
```

The conf maps roles to filesystem UUIDs only. Never put a `/dev` name in it.
Do not add the primary disk (`/mnt/wdpro26tb`, `f9b2ec0f-…`) to any variable.

## 3. Restic password (sudo, fresh host only)

```bash
sudo install -o root -g root -m 0400 /dev/null /etc/omnibioai/restic-password
sudoedit /etc/omnibioai/restic-password   # the password only, nothing else
sudo stat -c '%U %G %a %n' /etc/omnibioai/restic-password   # root root 400
```

The collector refuses the file unless it is a regular file (not a symlink),
owned by root, with mode `0400`.

## 4. Run once, check, enable the timer (sudo)

```bash
sudo systemctl daemon-reload
sudo systemctl start omnibioai-storage-telemetry.service   # may take minutes (restic snapshots)
systemctl status omnibioai-storage-telemetry.service --no-pager
sudo stat -c '%U %G %a %n' /var/lib/omnibioai/storage-telemetry.json   # root root 644
sudo python3 -m json.tool /var/lib/omnibioai/storage-telemetry.json | less
```

Check the snapshot:

- `mounts`:
  - root, backup, archive, data2tb and archive2tb-b each show `"mounted": true`
    with the expected `uuid`, their `fstype`, and `read_only` (`true` for the
    two 2 TB disks).
  - `archive-pool` shows `"fstype": "fuse.mergerfs"`, `"mounted": true`, its
    three `branches` with modes, `create_policy` and `min_free_bytes`.
  - There is no `primary` entry.
- `smart`:
  - `root` is `/dev/nvme0n1`, with `"type": "nvme"` and `nvme.percentage_used`,
    `media_errors` and `temperature`.
  - backup and archive are `/dev/sdd` and `/dev/sda`, with `"type": "sat"`.
  - data2tb and archive2tb-b are `/dev/sdg` and `/dev/sdh`. Their enclosures
    reject SAT, so expect `"smart_mode": "scsi_health_only"`,
    `"power_state": "unknown"`, `passed` and a `checked_at` time.
  - On later runs within 6 hours, those two entries carry `"reused": true`
    and the same `checked_at`, so the disks aren't queried or woken.
  - Every entry has `"error": null`. `state` is `active` or `standby`
    (asleep: SMART was skipped so the disk isn't woken), or `null` for the
    two 2 TB disks, whose power state can't be read.
- `kernel`: only `counts`, `devices`, `window_hours` and `error`, with no raw
  log lines.
- `restic`: `"error": null`.
  - `stats` comes from the newest snapshot's backup summary: `total_size` and
    `total_file_count`.
  - It is `null`, with no error, when snapshots carry no summary. That happens
    with restic older than 0.17, which wrote no summary.

```bash
sudo systemctl enable --now omnibioai-storage-telemetry.timer
systemctl list-timers omnibioai-storage-telemetry.timer --no-pager
```

## 5. Deploy (no sudo, after this PR merges)

The live stack loads `release-candidates/compose.release-pin.yml`, whose
control-center block uses `volumes: !override`. Steps 2 and 4 must be done
first.

1. In `omnibioai-ecosystem`, merge a pin-file PR that adds these read-only
   binds to control-center's volume list. They are the same as in
   `compose/docker-compose.control-center.yml`. `create_host_path: false`
   means a recreate fails if any source is not mounted.

   ```yaml
   - type: bind
     source: /media/manish/omnibioai-data
     target: /run/storage-targets/data2tb
     read_only: true
     bind: { propagation: rslave, create_host_path: false }
   - type: bind
     source: /mnt/omnibioai-archive2tb-b
     target: /run/storage-targets/archive2tb-b
     read_only: true
     bind: { propagation: rslave, create_host_path: false }
   - type: bind
     source: /mnt/omnibioai-archive
     target: /run/storage-targets/archive-pool
     read_only: true
     bind: { propagation: rslave, create_host_path: false }
   ```

   Then confirm the live pin file differs from `origin/main` only by that PR
   before bringing it in:

   ```bash
   cd ~/Desktop/omnibioai-ecosystem && git fetch origin
   diff <(git show origin/main:release-candidates/compose.release-pin.yml) release-candidates/compose.release-pin.yml
   ```

2. Update the control-center checkout to a clean `main` that includes this PR.
   `obai-deploy` builds from its committed `HEAD`.

   ```bash
   git -C ~/Desktop/omnibioai-ecosystem/omnibioai-control-center switch main
   git -C ~/Desktop/omnibioai-ecosystem/omnibioai-control-center pull --ff-only
   ```

3. Build, pin and deploy the API, then the Admin UI:

   ```bash
   ~/bin/obai-deploy check
   ~/bin/obai-deploy release control-center
   ~/bin/obai-deploy release control-center-web
   ```

   Each one writes the new image tag into the pin file, tags the old image for
   rollback, and runs the smoke checks.

4. Open a pin PR in `omnibioai-ecosystem` with the updated image tags.

Check the result:

```bash
~/bin/obai-deploy status
docker exec omnibioai-studio-control-center-1 ls /run/storage-targets /run/storage-telemetry
```

The Storage Dashboard then shows:
- Root filesystem (with NVMe wear and temperature), Backup, and Primary as a
  grey "Replacing".
- An "Archive pool" card with the pool total and its three disks. The two 2 TB
  disks are labelled "read-only" in grey, with no warning at 94–97%.

## Rollback

```bash
sudo systemctl disable --now omnibioai-storage-telemetry.timer
```

Run `~/bin/obai-deploy rollback control-center` and
`~/bin/obai-deploy rollback control-center-web` to go back to the previous
images. Revert the pin-file change if the binds must go too. The installed
files under `/usr/local/libexec/omnibioai`, `/etc/omnibioai` and
`/var/lib/omnibioai*` do nothing without the timer. Remove them only if you no
longer want them.
