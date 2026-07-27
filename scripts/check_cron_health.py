# omnibioai-control-center/scripts/check_cron_health.py

#!/usr/bin/env python3
"""
check_cron_health.py — Self-check for the OmniBioAI cron job registry.

Runs on the host via cron (like the other 4 whitelisted jobs), not inside
the control-center container. For each job returned by GET /cron/jobs
(mysql-backup, coverage-nightly, pubmed-sync, reindex-check, and this job
itself), flags a job whose log is missing, stale for its own schedule, or
whose last run reported an error, and files a known_issues.json entry via
the same admin API the Control Center's Admin tab uses -- so a log-path
mismatch or a silently-failing job surfaces even if nobody happens to open
the UI. Deliberately reuses GET /cron/jobs's own last_run_at/last_status
computation (rather than re-parsing log files itself) so this check can
never disagree with what the dashboard shows.

Cron (every 6 hours):
  0 */6 * * * python3 /home/manish/Desktop/machine/omnibioai-control-center/scripts/check_cron_health.py >> /home/manish/Desktop/machine/work/backups/omnibioai-cron-health.log 2>&1
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import jwt
import requests

CONTROL_CENTER_URL = os.environ.get("CONTROL_CENTER_URL", "http://127.0.0.1:7070")

# AUTH_SECRET_KEY signs admin JWTs ecosystem-wide (same key wired into
# every service via docker-compose.yml's JWT_SECRET env var). Read it
# straight from omnibioai-studio/.env rather than requiring this cron
# job's own shell environment to export it -- mirrors backup-mysql.sh's
# own "source .env" pattern for a script invoked straight from crontab.
STUDIO_ENV_PATH = Path("/home/manish/Desktop/machine/omnibioai-studio/.env")

# How stale a job's log is allowed to get before it's suspicious, keyed to
# each job's own schedule (hourly job: 3h; daily jobs: 36h; this job's own
# 6-hourly schedule: 9h). These 5 ids are the entire whitelist, so there's
# no need for generic cron-expression parsing here.
STALENESS_HOURS = {
    "mysql-backup": 36,
    "coverage-nightly": 36,
    "pubmed-sync": 36,
    "reindex-check": 3,
    "cron-health-check": 9,
    "disk-space-check": 36,
    "domain-health-check": 36,
}

# mysql-backup silently failing loses real data protection; reindex-check
# running a bit late is low-stakes by comparison.
SEVERITY = {
    "mysql-backup": "high",
    "coverage-nightly": "medium",
    "pubmed-sync": "medium",
    "reindex-check": "low",
    "cron-health-check": "medium",
    "disk-space-check": "medium",
    "domain-health-check": "medium",
}

DEFAULT_STALENESS_HOURS = 24
DEFAULT_SEVERITY = "medium"


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
    token = jwt.encode({"sub": "cron-health-check", "roles": ["admin"]}, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _fetch_jobs() -> list[dict]:
    resp = requests.get(f"{CONTROL_CENTER_URL}/cron/jobs", timeout=10)
    resp.raise_for_status()
    return resp.json()["jobs"]


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
        json={"title": title, "description": description, "severity": severity, "area": "Cron / Ops"},
        headers=_admin_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _diagnose(job: dict) -> str | None:
    """Returns a human-readable problem description, or None if healthy."""
    status = job.get("last_status")
    last_run_at = job.get("last_run_at")

    if status == "never_run":
        return f"log file at {job['log_path']} does not exist -- job has no recorded run at all"

    if status == "error":
        return f"most recent entry in {job['log_path']} (last run {last_run_at}) indicates a failed run"

    try:
        last_run = datetime.fromisoformat(last_run_at)
    except (TypeError, ValueError):
        return None

    threshold = STALENESS_HOURS.get(job["id"], DEFAULT_STALENESS_HOURS)
    age_hours = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
    if age_hours > threshold:
        return (
            f"log at {job['log_path']} hasn't been updated in {age_hours:.1f}h "
            f"(expected within {threshold}h for schedule {job.get('schedule')!r})"
        )
    return None


def main() -> int:
    jobs = _fetch_jobs()
    problems_found = 0

    for job in jobs:
        job_id = job["id"]
        problem = _diagnose(job)

        if problem is None:
            _log("INFO", f"{job_id}: ok")
            continue

        problems_found += 1
        # "ISSUE", never "ERROR" -- this job's own GET /cron/jobs last_status
        # is computed by a generic case-insensitive search for the substring
        # "error" in this log's own tail (see checks/cron_jobs.py's
        # _last_run_status). Reporting *other* jobs' problems is this job
        # doing its work correctly, not a failure of this job -- tagging it
        # "ERROR" would make cron-health-check falsely flag itself as
        # unhealthy every time it correctly reports bad news about a peer.
        # "ERROR" is reserved for this script's own genuine crash, below.
        _log("ISSUE", f"{job_id}: {problem}")

        marker = f"[cron-health:{job_id}]"
        if _existing_open_issue(marker):
            _log("INFO", f"{job_id}: already tracked by an open known-issue, not filing a duplicate")
            continue

        since = job.get("last_run_at") or "never (no run on record)"
        title = f"{marker} {job['name']} looks unhealthy"
        description = (
            f"Detected by the cron-health-check self-check. Job {job_id!r} ({job['name']}): "
            f"{problem}. Configured schedule: {job.get('schedule')!r}. Last known good run: {since}."
        )
        severity = SEVERITY.get(job_id, DEFAULT_SEVERITY)
        issue = _create_known_issue(title, description, severity)
        _log("ISSUE", f"{job_id}: filed known-issue {issue['id']} (severity={severity})")

    if problems_found:
        _log("ISSUE", f"cron-health-check: {problems_found} job(s) unhealthy")
    else:
        _log("INFO", "cron-health-check: all jobs healthy")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 -- cron captures stderr; any failure must be visible in the log, not silent
        _log("ERROR", f"cron-health-check crashed: {e}")
        sys.exit(1)
