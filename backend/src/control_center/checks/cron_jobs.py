from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The 4 real jobs installed in the host crontab (`crontab -l`). Whitelist-only
# by design -- /cron/jobs/{id}/... endpoints only ever operate on one of
# these 4 ids, never an arbitrary new job. schedule here is the *default*
# baked-in value; PUT /cron/jobs/{id}/schedule (once implemented) updates the
# live crontab, not this list, so this is just the fallback shown before any
# live crontab read succeeds.
CRON_JOBS: list[dict[str, str]] = [
    {
        "id": "mysql-backup",
        "name": "MySQL Backup",
        "schedule": "0 4 * * *",
        "script_path": "omnibioai-studio/scripts/backup-mysql.sh",
        "log_path": "work/backups/omnibioai-backup.log",
    },
    {
        "id": "coverage-nightly",
        "name": "Coverage Collection",
        "schedule": "0 2 * * *",
        "script_path": "omnibioai-control-center/scripts/run_coverage_host.py",
        "log_path": "work/backups/omnibioai-coverage.log",
    },
    {
        "id": "pubmed-sync",
        "name": "PubMed Sync",
        "schedule": "0 3 * * *",
        "script_path": "omnibioai-utils/sync_pubmed_updates.py",
        "log_path": "logs/pubmed_sync.log",
    },
    {
        "id": "reindex-check",
        "name": "Reindex Check",
        "schedule": "0 * * * *",
        "script_path": "omnibioai-dev-hub/scripts/check_and_reindex.sh",
        "log_path": "work/backups/omnibioai-reindex.log",
    },
]

_TAIL_LINES = 40
_ERROR_RE = re.compile(r"error", re.IGNORECASE)


def _last_run_status(log_path: Path) -> dict[str, Any]:
    """Derive last-run info from a job's log file. Each of the 4 scripts
    writes a different log format (bash [INFO]/[ERROR] tags vs. plain
    Python prints), so this only looks for the word "error" anywhere in the
    tail rather than parsing a specific format -- a job that's never run
    (log file missing) is reported as such rather than guessed at."""
    if not log_path.exists():
        return {"last_run_at": None, "last_status": "never_run"}
    try:
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc).isoformat()
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"last_run_at": None, "last_status": "unknown"}

    tail = "\n".join(text.strip().splitlines()[-_TAIL_LINES:])
    status = "error" if _ERROR_RE.search(tail) else "ok"
    return {"last_run_at": mtime, "last_status": status}


def get_cron_jobs(workspace_root: Path) -> list[dict[str, Any]]:
    """Read-only status for the 4 known jobs. Pure filesystem reads under
    the mounted workspace -- no crontab/host-cron access needed for this."""
    jobs = []
    for job in CRON_JOBS:
        status = _last_run_status(workspace_root / job["log_path"])
        jobs.append({**job, **status})
    return jobs
