#!/usr/bin/env python3
"""
coverage_ondemand_watcher.py — cron-invoked every minute on the host.

Checks for an on-demand full-ecosystem coverage-collection request and
runs run_coverage_host.py if one is pending. Exists because control-
center's backend runs in a container (see docker-compose.yml's
control-center service: a real `build:` context, not a host process),
and run_coverage_host.py must run on the host -- see that script's own
docstring: it needs every repo's Python deps already installed, which
only the host has, not this container.

The container can't invoke a host process directly, so
POST /coverage/ecosystem/generate (control_center/main.py) just drops a
trigger file on the /workspace mount it already shares with the host.
This script is the host-side half of that handoff -- the same "cron
polls, checks a condition, acts" shape check_cron_health.py/
check_disk_space.py/check_domain_health.py in this same directory
already use, not a new pattern.

State directory (STATE_DIR below), all under the same host path the
container has mounted at /workspace/omnibioai-work:
  trigger      Created by POST /coverage/ecosystem/generate to request a
               run. Consumed (deleted) by this script the instant it's
               picked up, so a request only ever runs once even though
               this script itself fires every minute regardless.
  running      Created the moment a run starts, deleted when it ends.
               Its own presence is this script's overlap guard -- see
               main() below. Its mtime is also what
               GET /coverage/ecosystem/status reports as started_at
               while a run is in flight.
  result.json  {"status": "done"|"error", "finished_at": ..., "message": ...}
               written when a run finishes. GET /coverage/ecosystem/status
               reads this (once `running` is gone) to answer the
               frontend's poll, in the same {status, started_at,
               finished_at, message} shape /report/status's in-process
               _JobState already produces for the (unrelated, in-
               container, self-scoped) /report/generate job -- so the
               frontend polling logic didn't need anything new to
               support this too.

Installed as its own host crontab entry -- see cron_jobs.py's
CRON_JOBS list ("coverage-ondemand-watcher"), same mechanism (and same
file) every other job on that list already goes through for status/
pause/resume/reschedule via routes_cron.py, not a separate systemd
timer or new artifact:

  * * * * * python3 .../coverage_ondemand_watcher.py >> .../omnibioai-coverage-ondemand.log 2>&1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ.get("OMNIBIOAI_ROOT", str(Path.home() / "Desktop" / "machine")))
STATE_DIR = ROOT / "omnibioai-work" / "out" / "coverage" / ".ondemand"
TRIGGER = STATE_DIR / "trigger"
RUNNING = STATE_DIR / "running"
RESULT = STATE_DIR / "result.json"
SCRIPT = ROOT / "omnibioai-control-center" / "scripts" / "run_coverage_host.py"

# Empirically measured, not guessed: a real full-ecosystem run (every
# tracked repo, unlike /coverage/generate's single-repo, in-container
# job that 600s was originally sized for) did not finish within 10
# minutes in live testing -- subprocess.run's own TimeoutExpired fired
# correctly, proving the handling path works, but 600s itself was too
# tight for the actual workload. 1800s (30 min) gives real headroom;
# STALE_AFTER stays comfortably above it so the overlap guard in main()
# never fires while a run is still legitimately in progress.
RUN_TIMEOUT_SECONDS = 1800

# Longer than RUN_TIMEOUT_SECONDS above -- a `running` marker older than
# this means the process that created it is gone (crashed, host
# rebooted, etc.), not still working within its own timeout budget.
# Cleared rather than left to block every future minute's invocation
# forever.
STALE_AFTER = timedelta(minutes=40)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if RUNNING.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(RUNNING.stat().st_mtime, tz=timezone.utc)
        if age < STALE_AFTER:
            return 0  # a run is already in flight this minute -- don't overlap it
        print(f"[coverage_ondemand_watcher] stale running marker ({age}), clearing", file=sys.stderr)
        RUNNING.unlink()

    if not TRIGGER.exists():
        return 0  # nothing requested

    TRIGGER.unlink()
    RUNNING.write_text(_now_iso())
    print(f"[coverage_ondemand_watcher] picked up trigger, running {SCRIPT}")

    try:
        proc = subprocess.run(
            ["python3", str(SCRIPT), "--root", str(ROOT)],
            capture_output=True, text=True, timeout=RUN_TIMEOUT_SECONDS,
        )
        if proc.returncode == 0:
            status = "done"
            message = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "Done"
        else:
            status = "error"
            message = proc.stderr.strip() or proc.stdout.strip() or "run_coverage_host.py failed"
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
    except subprocess.TimeoutExpired:
        status = "error"
        message = f"Coverage collection timed out after {RUN_TIMEOUT_SECONDS // 60} minutes"
        print(f"[coverage_ondemand_watcher] {message}", file=sys.stderr)
    except Exception as e:
        status = "error"
        message = f"{type(e).__name__}: {e}"
        print(f"[coverage_ondemand_watcher] {message}", file=sys.stderr)

    RESULT.write_text(json.dumps({
        "status": status,
        "finished_at": _now_iso(),
        "message": message,
    }))
    RUNNING.unlink(missing_ok=True)
    print(f"[coverage_ondemand_watcher] {status}: {message}")
    return 0 if status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
