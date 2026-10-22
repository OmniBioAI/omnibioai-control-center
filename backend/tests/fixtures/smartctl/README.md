# smartctl fixtures

**Captured** (real output from `sdg`, the Seagate-bridged `data2tb` disk, on
2026-10-22, with no serial numbers):

- `sdg-sat-captured.json`: `smartctl -H -A -d sat --json=c /dev/sdg`. Exit 2,
  no `smartctl.messages`, no SMART table. The bridge fails SAT silently.
- `sdg-scsi-captured.json`: `smartctl -H -d scsi --json=c /dev/sdg`. Exit 0,
  `smart_status.passed: true`.

The other files are **built, not captured**. Each uses the JSON envelope smartctl 7.4
(svn 5530) printed on this host for an unprivileged run. The message strings are
copied verbatim from the installed binary (`strings $(command -v smartctl)`):

- `Read Device Identity failed: %s`
- `A mandatory SMART command failed: exiting. To continue, add one or more '-T permissive' options.`
- `CHECK POWER MODE not implemented, ignoring -n option`
- `Device is in SLEEP mode, exit(2)`: what the Seagate bridges on `sdg`/`sdh` report for
  `-n standby` even when the disk is awake (`sdg-sat-sleep-mode-false.json`)

To replace them with real output from the 2 TB disks (read-only; may spin them up):

```bash
sudo smartctl -n standby -H -A -d sat --json=c /dev/sdg > sdg-sat-read-device-identity-failed.json
sudo smartctl -n standby -H -A -d sat --json=c /dev/sdh > sdh-sat-mandatory-command-failed.json
sudo smartctl -H -d scsi --json=c /dev/sdg > sdg-scsi-health-ok.json
```

Check each one for serial numbers before committing, and redact them:
`-H` prints none, but `-d scsi` can include `serial_number`.
