# Storage telemetry: host install

Run from the root of an `omnibioai-control-center` checkout that contains
this directory (PR #108 or later). Steps marked **sudo** change the host.
Everything else is read-only. See `README.md` for what the collector does and
why the root filesystem is measured through a probe directory.

## 1. Pre-checks (read-only)

```bash
# Expected UUIDs, matching config/control_center.yaml and storage-telemetry.conf.example:
#   /                          9f3cd4b6-f34e-435e-9fcf-ed7861f7cf99
#   /mnt/omnibioai-backup20tb  9d872bab-a481-4fca-8ad8-8031d78c0dbc
#   /mnt/omnibioai-archive22tb 6a805bb7-2513-435f-9cd4-b9970a0e4fc4
findmnt -n -o UUID /
findmnt -n -o UUID /mnt/omnibioai-backup20tb
findmnt -n -o UUID /mnt/omnibioai-archive22tb

# The probe directory must be on the root filesystem: this must print the root UUID.
findmnt -n -o UUID -T /var/lib

# SMART disks are configured by filesystem UUID and resolved to the whole disk
# at run time, exactly like this. Each must print exactly one line, a whole disk
# (today: sdd for backup, sda for archive). Anything else, and the collector
# records an error for that role instead of guessing.
lsblk -no PKNAME /dev/disk/by-uuid/9d872bab-a481-4fca-8ad8-8031d78c0dbc
lsblk -no PKNAME /dev/disk/by-uuid/6a805bb7-2513-435f-9cd4-b9970a0e4fc4

# The Restic repository is present. Expect: config  data  index  keys  snapshots
sudo ls /mnt/omnibioai-backup20tb/restic

# Tools the collector runs.
command -v smartctl findmnt dmesg restic python3
dmesg --help | grep -q -- --since && echo "dmesg supports --since"
```

If any UUID differs, a `lsblk` line is not a single whole disk, or the Restic
listing is missing any of those five entries, stop. Update
`config/control_center.yaml` and the conf file in step 2 to match before
continuing.

## 2. Install the collector (sudo)

```bash
sudo install -d -o root -g root -m 0755 /usr/local/libexec/omnibioai /etc/omnibioai /var/lib/omnibioai
sudo install -d -o root -g root -m 0555 /var/lib/omnibioai-storage-probe
sudo install -o root -g root -m 0755 ops/storage-telemetry/collect-storage-telemetry.py /usr/local/libexec/omnibioai/collect-storage-telemetry.py
sudo install -o root -g root -m 0644 ops/storage-telemetry/omnibioai-storage-telemetry.service /etc/systemd/system/omnibioai-storage-telemetry.service
sudo install -o root -g root -m 0644 ops/storage-telemetry/omnibioai-storage-telemetry.timer /etc/systemd/system/omnibioai-storage-telemetry.timer
sudo install -o root -g root -m 0600 ops/storage-telemetry/storage-telemetry.conf.example /etc/omnibioai/storage-telemetry.conf
sudo systemd-analyze verify /etc/systemd/system/omnibioai-storage-telemetry.service /etc/systemd/system/omnibioai-storage-telemetry.timer
```

The installed conf maps roles to filesystem UUIDs only:
`STORAGE_TELEMETRY_DISKS="backup:9d872bab-… archive:6a805bb7-…"`. Never put a
`/dev/sdX` name there. Do not add the primary disk (`/mnt/wdpro26tb`,
`f9b2ec0f-…`) to either variable.

## 3. Restic password (sudo)

```bash
sudo install -o root -g root -m 0400 /dev/null /etc/omnibioai/restic-password
sudoedit /etc/omnibioai/restic-password   # the password only, nothing else
sudo stat -c '%U %G %a %n' /etc/omnibioai/restic-password   # root root 400
```

The collector refuses the file unless it is a regular file (not a symlink),
owned by root, with mode `0400`.

## 4. First run, then enable the timer (sudo)

```bash
sudo systemctl daemon-reload
sudo systemctl start omnibioai-storage-telemetry.service   # may take minutes (restic stats)
systemctl status omnibioai-storage-telemetry.service --no-pager
journalctl -u omnibioai-storage-telemetry.service -n 50 --no-pager

sudo stat -c '%U %G %a %n' /var/lib/omnibioai/storage-telemetry.json   # root root 644
sudo python3 -m json.tool /var/lib/omnibioai/storage-telemetry.json | less
```

Check the snapshot before enabling the timer:

- `mounts`: root, backup and archive each show `"mounted": true` with the
  expected `uuid`. There is no `primary` entry.
- `smart`: entries for `backup` and `archive` only, each with the resolved
  `device` (`/dev/sdd`, `/dev/sda`) and `"error": null`. `state` is `active`
  (with attributes) or `standby` (disk asleep, SMART skipped so it isn't woken,
  previous attribute 199 kept as `crc_baseline`). The dashboard shows
  `standby` as a neutral "Standby".
- `kernel`: only `counts`, `devices`, `window_hours` and `error`, with no raw
  log lines.
- `restic`: `"error": null`. Snapshot paths are reduced to `…/<name>`.

```bash
sudo systemctl enable --now omnibioai-storage-telemetry.timer
systemctl list-timers omnibioai-storage-telemetry.timer --no-pager
```

## 5. Deploy control-center (no sudo, after #108 merges)

The live stack loads `release-candidates/compose.release-pin.yml`, whose
control-center block uses `volumes: !override`. Steps 2 and 4 must be done
first: the new binds use `create_host_path: false`, so a recreate fails if
`/var/lib/omnibioai-storage-probe` or `/var/lib/omnibioai` is missing.

1. Merge OmniBioAI/omnibioai-ecosystem#18 (the four read-only binds and
   `STORAGE_TELEMETRY_PATH`). Then confirm the live pin file differs from
   `origin/main` only by #18 before bringing that change in:

   ```bash
   cd ~/Desktop/omnibioai-ecosystem && git fetch origin
   git diff --no-index release-candidates/compose.release-pin.yml <(git show origin/main:release-candidates/compose.release-pin.yml)
   ```

2. Update the control-center checkout to a clean `main` that includes #108.
   `obai-deploy` builds from its committed `HEAD`.

   ```bash
   git -C ~/Desktop/omnibioai-ecosystem/omnibioai-control-center switch main
   git -C ~/Desktop/omnibioai-ecosystem/omnibioai-control-center pull --ff-only
   ```

3. Build, pin and deploy control-center only:

   ```bash
   ~/bin/obai-deploy check
   ~/bin/obai-deploy release control-center
   ```

   This writes the new image tag into the pin file, tags the old image for
   rollback, and waits for the service to be healthy.

4. Open a pin PR in `omnibioai-ecosystem` with the updated
   `release-candidates/compose.release-pin.yml` (the new control-center image
   tag).

Check the result:

```bash
~/bin/obai-deploy status
docker exec omnibioai-studio-control-center-1 ls /run/storage-targets /run/storage-telemetry
```

The Admin Console Storage Dashboard should then show Root filesystem, Backup
and Archive with capacity, and Primary as "Not mounted" with "This target is
being replaced."

## Rollback

```bash
sudo systemctl disable --now omnibioai-storage-telemetry.timer
```

Run `~/bin/obai-deploy rollback control-center` to go back to the previous
image. Revert the pin-file change if the binds must go too. The installed files
under `/usr/local/libexec/omnibioai`, `/etc/omnibioai` and `/var/lib/omnibioai*`
do nothing without the timer. Remove them only if you no longer want them.
