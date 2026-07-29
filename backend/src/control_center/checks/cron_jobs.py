from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The 7 real jobs installed in the host crontab (`crontab -l`). Whitelist-only
# by design -- /cron/jobs/{id}/... endpoints only ever operate on one of
# these 7 ids, never an arbitrary new job. schedule here is the *default*
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
        "id": "neo4j-backup",
        "name": "Neo4j Backup",
        "schedule": "0 5 * * *",
        "script_path": "omnibioai-studio/scripts/backup-neo4j.sh",
        "log_path": "work/backups/omnibioai-neo4j-backup.log",
    },
    {
        # Superseded by system-state-backup (broader scope: all .env files
        # across repos, plus crontab/cloudflared/systemd, with off-site
        # push) on 2026-07-28. Left registered but not in the live
        # crontab so historical logs remain viewable via GET
        # /cron/jobs/config-backup/log.
        "id": "config-backup",
        "name": "Config Backup (superseded — see system-state-backup)",
        "schedule": "45 4 * * *",
        "script_path": "omnibioai-studio/scripts/backup-config.sh",
        "log_path": "work/backups/omnibioai-config-backup.log",
    },
    {
        "id": "system-state-backup",
        "name": "System State Backup (.env/cloudflared/systemd/crontab)",
        "schedule": "0 4 * * *",
        "script_path": "omnibioai-utils/backup-system-state.sh",
        "log_path": "work/backups/omnibioai-system-state-backup.log",
    },
    {
        "id": "unpushed-work-check",
        "name": "Unpushed Work Check",
        "schedule": "0 7 * * *",
        "script_path": "omnibioai-utils/check_unpushed_work.sh",
        "log_path": "work/backups/omnibioai-unpushed-check.log",
    },
    {
        "id": "nvme-backup",
        "name": "NVMe Data Backup",
        "schedule": "0 1 * * *",
        "script_path": "omnibioai-studio/scripts/backup-nvme.sh",
        "log_path": "work/backups/omnibioai-nvme-backup.log",
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
    {
        "id": "cron-health-check",
        "name": "Cron Health Check",
        "schedule": "0 */6 * * *",
        "script_path": "omnibioai-control-center/scripts/check_cron_health.py",
        "log_path": "work/backups/omnibioai-cron-health.log",
    },
    {
        "id": "disk-space-check",
        "name": "Disk Space Check",
        "schedule": "0 6 * * *",
        "script_path": "omnibioai-control-center/scripts/check_disk_space.py",
        "log_path": "work/backups/omnibioai-disk-space.log",
    },
    {
        "id": "domain-health-check",
        "name": "Domain & SSL Health Check",
        "schedule": "0 5 * * *",
        "script_path": "omnibioai-control-center/scripts/check_domain_health.py",
        "log_path": "work/backups/omnibioai-domain-health.log",
    },
    {
        # Not yet installed in the live crontab -- registered here so it's
        # visible via GET /cron/jobs, but pause/resume/schedule will 404
        # against it (_match_line_index finds no line) until a crontab line
        # is added. schedule below is inert until that happens.
        "id": "run-chunks",
        "name": "Run Chunks (Embedding)",
        "schedule": "0 1 * * *",
        "script_path": "omnibioai-utils/run_chunks.sh",
        "log_path": "work/backups/omnibioai-run-chunks.log",
    },
    {
        "id": "base-images-check",
        "name": "Base Docker Image Freshness Check",
        "schedule": "0 8 * * *",
        "script_path": "omnibioai-utils/check_base_images.sh",
        "log_path": "work/backups/omnibioai-base-images-check.log",
    },
    {
        "id": "platform-workflows-check",
        "name": "Platform Image CI/CD Workflow Health Check",
        "schedule": "15 8 * * *",
        "script_path": "omnibioai-utils/check_platform_workflows.sh",
        "log_path": "work/backups/omnibioai-platform-workflows-check.log",
    },
    {
        "id": "plugin-image-sync-check",
        "name": "Plugin Docker Image Sync Check",
        "schedule": "30 8 * * *",
        "script_path": "omnibioai-utils/check_plugin_image_sync.sh",
        "log_path": "work/backups/omnibioai-plugin-sync-check.log",
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

def get_job_log(workspace_root: Path, job_id: str, lines: int = 100) -> dict[str, Any]:
    """Return the last `lines` lines of a job's log file, plus the same
    last_run_at/last_status summary get_cron_jobs() already computes -- so
    the frontend can render both in one call. Read-only; no auth required
    beyond whatever routes_cron.py already enforces for GET endpoints.
    """
    job = _get_job(job_id)  # raises CronMutationError(404) if unknown id
    log_path = workspace_root / job["log_path"]

    if not log_path.exists():
        return {
            "id": job_id,
            "log_path": str(job["log_path"]),
            "last_run_at": None,
            "last_status": "never_run",
            "lines": [],
        }

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise CronMutationError(f"Cannot read log file: {e}", 500)

    all_lines = text.strip().splitlines()
    tail = all_lines[-lines:] if lines > 0 else all_lines

    status_info = _last_run_status(log_path)
    return {
        "id": job_id,
        "log_path": str(job["log_path"]),
        "total_lines": len(all_lines),
        "lines_returned": len(tail),
        **status_info,
        "lines": tail,
    }

class CronMutationError(Exception):
    """Raised by the pause/resume/reschedule helpers below; routes_cron.py
    maps status_code straight onto the HTTP response."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


_SCHEDULE_FIELD_RE = re.compile(r"^[\d*/,\-]+$")


def _get_job(job_id: str) -> dict[str, str]:
    job = next((j for j in CRON_JOBS if j["id"] == job_id), None)
    if job is None:
        raise CronMutationError(f"Unknown job id: {job_id!r}", 404)
    return job


def _read_crontab_lines(spool_path: Path) -> list[str]:
    # Path.exists() raises (rather than returning False) on a permission
    # error partway through stat-ing the path -- both "genuinely missing"
    # and "can't tell, access denied" should surface as the same
    # can't-read-the-crontab error here.
    try:
        exists = spool_path.exists()
    except OSError as e:
        raise CronMutationError(f"Cannot access crontab spool file: {e}", 500)
    if not exists:
        raise CronMutationError(f"Crontab spool file not found: {spool_path}", 500)
    try:
        return spool_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise CronMutationError(f"Cannot read crontab spool file: {e}", 500)


def _write_crontab_lines(spool_path: Path, lines: list[str]) -> None:
    content = "\n".join(lines)
    if lines:
        content += "\n"
    try:
        spool_path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise CronMutationError(f"Cannot write crontab spool file: {e}", 500)


def _match_line_index(lines: list[str], job: dict[str, str]) -> int:
    """Identifies a job's crontab line by the script's filename appearing in
    the command portion -- stable across pause (leading '#') and reschedule
    (the 5 time fields) edits, since only the command/script path never
    changes for a given job."""
    needle = job["script_path"].rsplit("/", 1)[-1]
    for i, line in enumerate(lines):
        content = line.strip().lstrip("#").strip()
        if needle and needle in content:
            return i
    raise CronMutationError(
        f"No crontab line found for job {job['id']!r} (looked for {needle!r})", 404,
    )


def _validate_schedule(schedule: str) -> None:
    fields = schedule.split()
    if len(fields) != 5:
        raise CronMutationError("Schedule must have exactly 5 whitespace-separated fields")
    for field in fields:
        if not _SCHEDULE_FIELD_RE.match(field):
            raise CronMutationError(f"Invalid cron field: {field!r}")


def _spool_path(env_value: str | None) -> Path:
    return Path(env_value or "/var/spool/cron/crontabs/manish")


def get_cron_jobs(workspace_root: Path, spool_path: Path | None = None) -> list[dict[str, Any]]:
    """Status for the 7 known jobs: last-run info from log files (always
    available, pure filesystem reads) plus live paused/schedule state read
    from the crontab spool file when it's mounted and readable -- falls
    back to the static defaults (paused=None, i.e. unknown) otherwise, so
    this endpoint still degrades gracefully rather than failing outright."""
    live_lines: list[str] | None = None
    if spool_path is not None:
        try:
            live_lines = _read_crontab_lines(spool_path)
        except CronMutationError:
            live_lines = None

    jobs = []
    for job in CRON_JOBS:
        entry: dict[str, Any] = dict(job)
        entry["paused"] = None
        if live_lines is not None:
            try:
                idx = _match_line_index(live_lines, job)
            except CronMutationError:
                idx = None
            if idx is not None:
                line = live_lines[idx]
                stripped = line.strip()
                entry["paused"] = stripped.startswith("#")
                content = stripped.lstrip("#").strip()
                parts = content.split(None, 5)
                if len(parts) >= 5:
                    entry["schedule"] = " ".join(parts[:5])

        entry.update(_last_run_status(workspace_root / job["log_path"]))
        jobs.append(entry)
    return jobs


def pause_job(spool_path: Path, job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    lines = _read_crontab_lines(spool_path)
    idx = _match_line_index(lines, job)
    if not lines[idx].strip().startswith("#"):
        lines[idx] = "# " + lines[idx]
        _write_crontab_lines(spool_path, lines)
    return {"id": job_id, "paused": True}


def resume_job(spool_path: Path, job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    lines = _read_crontab_lines(spool_path)
    idx = _match_line_index(lines, job)
    if lines[idx].strip().startswith("#"):
        lines[idx] = re.sub(r"^\s*#\s?", "", lines[idx], count=1)
        _write_crontab_lines(spool_path, lines)
    return {"id": job_id, "paused": False}


def update_schedule(spool_path: Path, job_id: str, schedule: str) -> dict[str, Any]:
    job = _get_job(job_id)
    _validate_schedule(schedule)
    lines = _read_crontab_lines(spool_path)
    idx = _match_line_index(lines, job)

    line = lines[idx]
    m = re.match(r"^(\s*#\s?)?(.*)$", line, re.DOTALL)
    prefix, body = m.group(1) or "", m.group(2)
    parts = body.split(None, 5)
    if len(parts) < 6:
        raise CronMutationError(f"Could not parse existing crontab line for {job_id!r}", 500)

    lines[idx] = f"{prefix}{schedule} {parts[5]}"
    _write_crontab_lines(spool_path, lines)
    return {"id": job_id, "schedule": schedule}
