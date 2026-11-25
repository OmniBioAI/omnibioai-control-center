#!/usr/bin/env python3
"""
check_redis_aof_autofix.py — alert when Redis repaired its AOF at start.

Runs on the host via cron every 5 minutes (same pattern as check_tes_runnable.py).
omnibioai-studio's scripts/redis-start-guarded.sh repairs one known power-loss failure
(a malformed tail on the last AOF incr file) at Redis start, after backing up the AOF,
and logs one line containing REDIS-AOF-AUTOFIX. Each such repair discards a few bytes of
the last writes, so a human must know: this files one high-severity known issue per
repair (which alerts #omnibioai-alerts). Repairs already reported are remembered in a
small state file; nothing is auto-resolved (a human closes it after checking the backup).

Reads the container log with `docker logs --tail` (not --since): after an unclean
shutdown the log file can end in a torn record that stops a forward read.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import jwt
import requests

CONTROL_CENTER_URL = os.environ.get("CONTROL_CENTER_URL", "http://127.0.0.1:7070")
CONTAINER = os.environ.get("REDIS_CONTAINER", "omnibioai-studio-redis-1")
STUDIO_ENV_PATH = Path("/home/manish/Desktop/omnibioai-ecosystem/omnibioai-studio/.env")
STATE_PATH = Path(os.environ.get(
    "REDIS_AOF_AUTOFIX_STATE", "/home/manish/Desktop/omnibioai-ecosystem/work/backups/redis-aof-autofix-state.json"))
TAIL_LINES = os.environ.get("REDIS_AOF_AUTOFIX_TAIL", "20000")
MARKER = "[redis-aof-autofix]"
LINE = re.compile(r"REDIS-AOF-AUTOFIX: repaired (?P<file>\S+) \(discarded (?P<bytes>\d+) bytes.*?backup (?P<backup>\S+?);")


def _log(level: str, msg: str) -> None:
    print(f"[{level}] {datetime.now(UTC).isoformat(timespec='seconds')} {msg}", flush=True)


def _load_jwt_secret() -> str:
    env_override = os.environ.get("AUTH_SECRET_KEY") or os.environ.get("JWT_SECRET")
    if env_override:
        return env_override
    for line in STUDIO_ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("AUTH_SECRET_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"AUTH_SECRET_KEY not found in {STUDIO_ENV_PATH}")


# The known-issues write routes check the `permissions` claim (CC 7887ea6, 2026-08-03); a
# `roles: ["admin"]` token is rejected with 403, so no self-check could file an issue after that.
ALERT_PERMISSION = "platform.manage_content"


def _admin_headers() -> dict:
    token = jwt.encode({"sub": "redis-aof-autofix-check", "type": "access", "permissions": [ALERT_PERMISSION],
                        "exp": int(time.time()) + 300}, _load_jwt_secret(), algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def repairs_in_log(text: str) -> list[dict]:
    """Every REDIS-AOF-AUTOFIX repair in the log text; the backup path identifies each one."""
    return [m.groupdict() for m in LINE.finditer(text)]


def container_log() -> str:
    out = subprocess.run(["docker", "logs", "--tail", TAIL_LINES, CONTAINER],
                         capture_output=True, text=True, timeout=60, check=True)
    return out.stdout + out.stderr


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"reported": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _create_known_issue(repair: dict) -> dict:
    title = f"{MARKER} Redis repaired its AOF at start ({repair['bytes']} bytes discarded)"
    description = (
        f"Detected by the redis-aof-autofix self-check: at its last start Redis found a malformed tail on "
        f"{repair['file']} (typically after a power loss), and redis-start-guarded.sh backed up the AOF to "
        f"{repair['backup']} (inside the redis_data volume) and ran redis-check-aof --fix, discarding "
        f"{repair['bytes']} bytes of the last writes. Redis is running. Check what was lost if it matters, "
        f"then remove the backup once it is no longer needed, and close this issue.")
    resp = requests.post(
        f"{CONTROL_CENTER_URL}/known-issues",
        json={"title": title, "description": description, "severity": "high", "area": "Redis / Infra"},
        headers=_admin_headers(), timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    state = load_state()
    reported = set(state.get("reported", []))
    new = [r for r in repairs_in_log(container_log()) if r["backup"] not in reported]
    for repair in new:
        issue = _create_known_issue(repair)
        reported.add(repair["backup"])
        save_state({"reported": sorted(reported)})
        _log("ISSUE", f"redis-aof-autofix: filed known-issue {issue['id']} for {repair['backup']}")
    if not new:
        _log("INFO", "redis-aof-autofix: no new AOF repairs")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 -- cron captures stderr; any failure must be visible in the log, not silent
        _log("ERROR", f"redis-aof-autofix-check crashed: {type(e).__name__}: {e}")
        sys.exit(1)
