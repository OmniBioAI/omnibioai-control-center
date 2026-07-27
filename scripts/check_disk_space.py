# omnibioai-control-center/scripts/check_disk_space.py

#!/usr/bin/env python3
"""
check_disk_space.py — Disk space self-check for the OmniBioAI host.

Runs on the host via cron (same pattern as check_cron_health.py), not
inside the control-center container. Checks `df` usage on the mount
points that matter to this ecosystem, flags anything over 85%
(warning) or 95% (critical), and files/updates/resolves a
known_issues.json entry via the same admin API the Control Center's
Admin tab uses. Unlike check_cron_health.py, this job also auto-resolves
a previously-filed entry once usage drops back below threshold, since
"disk got fuller" and "disk got roomier again" are both real,
externally-verifiable state transitions worth reflecting immediately
(there's no equivalent "wait for a human to confirm" step the way there
might be for a job's last-run outcome).

Mount points checked (confirmed via `df -h` -- not assumed):
  - /                              root fs: all repos, work dirs, and
                                   Docker's storage dir (/var/lib/docker)
                                   live here, confirmed via `docker info`
  - /media/manish/omnibioai-data   separate ext4 drive
  - /media/manish/OmniBioAI-SIFs   separate exfat drive (autofs-mounted);
                                   `omnibioai-work`/`work` symlink targets
                                   live here
  - /media/manish itself is NOT a separate mount (df -h resolves it to
    root) -- its two subdirectories above are the real, distinct mounts.

Cron (daily at 06:00):
  0 6 * * * python3 /home/manish/Desktop/machine/omnibioai-control-center/scripts/check_disk_space.py >> /home/manish/Desktop/machine/work/backups/omnibioai-disk-space.log 2>&1
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import jwt
import requests

CONTROL_CENTER_URL = os.environ.get("CONTROL_CENTER_URL", "http://127.0.0.1:7070")

# Same shared secret used by check_cron_health.py -- read straight from
# omnibioai-studio/.env rather than requiring this cron job's own shell
# environment to export it.
STUDIO_ENV_PATH = Path("/home/manish/Desktop/machine/omnibioai-studio/.env")

# Overridable for the live-validation test run only (see the --thresholds
# note in the project's cron-health-check precedent) -- production always
# uses the real 85/95 defaults below.
WARNING_PCT = int(os.environ.get("DISK_WARNING_PCT", "85"))
CRITICAL_PCT = int(os.environ.get("DISK_CRITICAL_PCT", "95"))

MOUNTS = [
    {"id": "root", "path": "/", "label": "Root filesystem (/)"},
    {"id": "omnibioai-data", "path": "/media/manish/omnibioai-data", "label": "omnibioai-data drive"},
    {"id": "omnibioai-sifs", "path": "/media/manish/OmniBioAI-SIFs", "label": "OmniBioAI-SIFs drive"},
]


def _log(level: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{level}] {ts} {msg}", flush=True)


def _load_jwt_secret() -> str:
    env_override = os.environ.get("AUTH_SECRET_KEY") or os.environ.get("JWT_SECRET")
    if env_override:
        return env_override
    for line in STUDIO_ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("AUTH_SECRET_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"AUTH_SECRET_KEY not found in {STUDIO_ENV_PATH}")


def _admin_headers() -> dict:
    secret = _load_jwt_secret()
    token = jwt.encode({"sub": "disk-space-check", "roles": ["admin"]}, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _df_output(path: str) -> str:
    """The literal `df -h` line for this mount, embedded in known-issue
    descriptions so a human reading it doesn't have to re-run anything."""
    result = subprocess.run(["df", "-h", path], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _usage_percent(path: str) -> int:
    result = subprocess.run(["df", "--output=pcent", path], capture_output=True, text=True, check=True)
    line = result.stdout.strip().splitlines()[-1].strip()
    return int(line.rstrip("%"))


def _existing_open_issue(marker: str) -> dict | None:
    resp = requests.get(f"{CONTROL_CENTER_URL}/known-issues", timeout=10)
    resp.raise_for_status()
    for issue in resp.json().get("issues", []):
        if issue.get("title", "").startswith(marker) and issue.get("status") != "resolved":
            return issue
    return None


def _create_known_issue(title: str, description: str, severity: str) -> dict:
    resp = requests.post(
        f"{CONTROL_CENTER_URL}/known-issues",
        json={"title": title, "description": description, "severity": severity, "area": "Disk / Infra"},
        headers=_admin_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _update_known_issue(issue_id: str, **fields) -> dict:
    resp = requests.put(
        f"{CONTROL_CENTER_URL}/known-issues/{issue_id}",
        json=fields,
        headers=_admin_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _severity_for(pct: int) -> tuple[str, str] | None:
    """Returns (level, severity) or None if under the warning threshold."""
    if pct >= CRITICAL_PCT:
        return "CRITICAL", "high"
    if pct >= WARNING_PCT:
        return "WARNING", "medium"
    return None


def main() -> int:
    problems_found = 0

    for mount in MOUNTS:
        mount_id, path, label = mount["id"], mount["path"], mount["label"]
        pct = _usage_percent(path)
        marker = f"[disk-space:{mount_id}]"
        existing = _existing_open_issue(marker)
        tier = _severity_for(pct)

        if tier is None:
            if existing:
                _update_known_issue(
                    existing["id"],
                    status="resolved",
                    description=(
                        f"{existing.get('description', '')}\n\n"
                        f"Auto-resolved by disk-space-check: usage dropped to {pct}% "
                        f"(below the {WARNING_PCT}% warning threshold) as of "
                        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}."
                    ),
                )
                _log("ISSUE", f"{mount_id}: back to {pct}%, resolved known-issue {existing['id']}")
            else:
                _log("INFO", f"{mount_id}: ok ({pct}% used)")
            continue

        level, severity = tier
        problems_found += 1
        # "ISSUE", never "ERROR" -- see check_cron_health.py's own fix for
        # why: this job's own GET /cron/jobs last_status is a generic
        # case-insensitive substring("error") scan of this log's tail, and
        # correctly reporting a full disk is this job succeeding, not
        # failing. "ERROR" is reserved for this script's own crash, below.
        _log("ISSUE", f"{mount_id}: {level} -- {pct}% used (threshold {WARNING_PCT if level == 'WARNING' else CRITICAL_PCT}%)")

        df_text = _df_output(path)
        title = f"{marker} {label} at {pct}% used ({level})"
        description = (
            f"Detected by the disk-space-check self-check. {label} ({path}) is at {pct}% used, "
            f"crossing the {level.lower()} threshold ({WARNING_PCT if level == 'WARNING' else CRITICAL_PCT}%). "
            f"`df -h` output at detection time:\n\n{df_text}"
        )

        if existing:
            _update_known_issue(existing["id"], title=title, description=description, severity=severity)
            _log("ISSUE", f"{mount_id}: updated existing known-issue {existing['id']} (severity={severity})")
        else:
            issue = _create_known_issue(title, description, severity)
            _log("ISSUE", f"{mount_id}: filed known-issue {issue['id']} (severity={severity})")

    if problems_found:
        _log("ISSUE", f"disk-space-check: {problems_found} volume(s) over threshold")
    else:
        _log("INFO", "disk-space-check: all volumes healthy")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 -- cron captures stderr; any failure must be visible in the log, not silent
        _log("ERROR", f"disk-space-check crashed: {e}")
        sys.exit(1)
