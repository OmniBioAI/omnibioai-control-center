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

# SMART is queried for whole disks by kernel name, which can change across
# reboots. Confirm backup is sdd (sdd1) and archive is sda (sda1).
lsblk -o NAME,UUID,MOUNTPOINT

# Tools the collector runs.
command -v smartctl findmnt dmesg restic python3
dmesg --help | grep -q -- --since && echo "dmesg supports --since"
```

If any UUID or disk name differs, stop. Update `config/control_center.yaml`
and the conf file in step 2 to match before continuing.

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

Do not add the primary disk (`/mnt/wdpro26tb`, `sde`) to either variable in
`/etc/omnibioai/storage-telemetry.conf`.

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
- `smart`: entries for `backup` and `archive` only, each with `"error": null`.
- `kernel`: only `counts`, `devices`, `window_hours` and `error`, with no raw
  log lines.
- `restic`: `"error": null`. Snapshot paths are reduced to `…/<name>`.

```bash
sudo systemctl enable --now omnibioai-storage-telemetry.timer
systemctl list-timers omnibioai-storage-telemetry.timer --no-pager
```

## 5. Wire the live control-center (no sudo, not part of this PR)

The live stack loads `release-candidates/compose.release-pin.yml`, whose
control-center block uses `volumes: !override`. Both changes below are needed:

1. **Binds:** merge OmniBioAI/omnibioai-ecosystem#18. It adds the four
   read-only binds and `STORAGE_TELEMETRY_PATH`. Steps 2 and 4 must be done
   first, because the binds use `create_host_path: false` and a recreate fails
   if `/var/lib/omnibioai-storage-probe` or `/var/lib/omnibioai` is missing.
2. **Image:** pin an image built from this PR. The current pin
   (`obai-control-center:2572cd551bdb`) predates it and ignores the binds.

Then, from `omnibioai-studio/`, render the config, check it, and recreate only
control-center:

```bash
docker compose config control-center | grep -E 'image:|storage-t'
docker compose up -d --no-deps control-center
docker exec omnibioai-studio-control-center-1 ls /run/storage-targets /run/storage-telemetry
```

The Admin Console Storage Dashboard should then show Root filesystem, Backup
and Archive with capacity, and Primary as "Not mounted" with "This target is
being replaced."

## Rollback

```bash
sudo systemctl disable --now omnibioai-storage-telemetry.timer
```

Revert the pin-file change and recreate control-center. The installed files
under `/usr/local/libexec/omnibioai`, `/etc/omnibioai` and `/var/lib/omnibioai*`
do nothing without the timer. Remove them only if you no longer want them.
