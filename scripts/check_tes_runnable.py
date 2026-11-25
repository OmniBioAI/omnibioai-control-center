#!/usr/bin/env python3
"""
check_tes_runnable.py — alert when production TES has too few runnable HTTP tools.

Runs on the host via cron every minute (same pattern as check_disk_space.py and
check_domain_health.py). Reads TES's verification summary (the number of HTTP
tools that are verified AND advertised by a live backend right now). When it
stays below TES_RUNNABLE_MIN (default 1000) for TES_RUNNABLE_WINDOW_MINUTES
(default 10), it files a high-severity known issue through the Control Center
admin API, which alerts #omnibioai-alerts through the central Discord router.
The issue is updated while the problem lasts and auto-resolved once the count
is back above the threshold.

Why: 2026-11-22 04:21Z to 2026-11-23 21:07Z production TES had 0 runnable HTTP
tools (a failed ToolServer registration after a power loss) and nothing noticed
for ~41 h. An unreachable TES counts as 0 runnable.

State (when the count first dropped below the threshold) is kept in a small JSON
file so a single bad minute never alerts.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import jwt
import requests

CONTROL_CENTER_URL = os.environ.get("CONTROL_CENTER_URL", "http://127.0.0.1:7070")
TES_URL = os.environ.get("TES_URL", "http://127.0.0.1:8081")
STUDIO_ENV_PATH = Path("/home/manish/Desktop/omnibioai-ecosystem/omnibioai-studio/.env")
STATE_PATH = Path(os.environ.get(
    "TES_RUNNABLE_STATE", "/home/manish/Desktop/omnibioai-ecosystem/work/backups/tes-runnable-state.json"))
MIN_RUNNABLE = int(os.environ.get("TES_RUNNABLE_MIN", "1000"))
WINDOW_MINUTES = float(os.environ.get("TES_RUNNABLE_WINDOW_MINUTES", "10"))
MARKER = "[tes-runnable]"


def _log(level: str, msg: str) -> None:
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"[{level}] {ts} {msg}", flush=True)


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
    token = jwt.encode({"sub": "tes-runnable-check", "type": "access", "permissions": [ALERT_PERMISSION],
                        "exp": int(time.time()) + 300}, _load_jwt_secret(), algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def runnable_now() -> tuple[int, str]:
    """(runnable HTTP tools, how it was read); an unreachable or broken TES counts as 0."""
    try:
        resp = requests.get(f"{TES_URL}/api/tools/verification/summary", timeout=30)
        resp.raise_for_status()
        return int(resp.json().get("runnable", 0)), "verification summary"
    except Exception as e:  # noqa: BLE001 -- TES being down is exactly what this check is for
        return 0, f"TES not answering ({type(e).__name__})"


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _existing_open_issue() -> dict | None:
    resp = requests.get(f"{CONTROL_CENTER_URL}/known-issues", timeout=10)
    resp.raise_for_status()
    for issue in resp.json().get("issues", []):
        if issue.get("title", "").startswith(MARKER) and issue.get("status") != "resolved":
            return issue
    return None


def _create_known_issue(title: str, description: str) -> dict:
    resp = requests.post(
        f"{CONTROL_CENTER_URL}/known-issues",
        json={"title": title, "description": description, "severity": "high", "area": "TES / tools"},
        headers=_admin_headers(), timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _update_known_issue(issue_id: str, **fields) -> dict:
    resp = requests.put(f"{CONTROL_CENTER_URL}/known-issues/{issue_id}", json=fields,
                        headers=_admin_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def decide(runnable: int, state: dict, now: float) -> tuple[str, dict]:
    """Pure state step: returns (action, new state). Actions: ok, recovered, waiting, alert."""
    if runnable >= MIN_RUNNABLE:
        return ("recovered" if state.get("below_since") else "ok"), {}
    since = state.get("below_since") or now
    new = {"below_since": since}
    return ("alert" if now - since >= WINDOW_MINUTES * 60 else "waiting"), new


def main() -> int:
    now = datetime.now(UTC)
    runnable, source = runnable_now()
    action, state = decide(runnable, load_state(), now.timestamp())
    save_state(state)
    stamp = now.isoformat(timespec="seconds")

    if action == "ok":
        _log("INFO", f"tes-runnable: {runnable} runnable HTTP tools ({source})")
        return 0
    if action == "recovered":
        existing = _existing_open_issue()
        if existing:
            _update_known_issue(existing["id"], status="resolved", description=(
                f"{existing.get('description', '')}\n\nAuto-resolved by tes-runnable-check: "
                f"{runnable} runnable HTTP tools (threshold {MIN_RUNNABLE}) as of {stamp}."))
            _log("ISSUE", f"tes-runnable: back to {runnable}, resolved known-issue {existing['id']}")
        else:
            _log("INFO", f"tes-runnable: back to {runnable} before the alert window passed")
        return 0

    minutes = (now.timestamp() - state["below_since"]) / 60
    if action == "waiting":
        _log("ISSUE", f"tes-runnable: {runnable} runnable ({source}), below {MIN_RUNNABLE} for "
                      f"{minutes:.0f} of {WINDOW_MINUTES:.0f} min")
        return 0

    since = datetime.fromtimestamp(state["below_since"], UTC).isoformat(timespec="seconds")
    title = f"{MARKER} TES has {runnable} runnable HTTP tools (threshold {MIN_RUNNABLE})"
    description = (
        f"Detected by the tes-runnable-check self-check: production TES has had fewer than {MIN_RUNNABLE} "
        f"runnable HTTP tools since {since} ({minutes:.0f} min; now {runnable}, read from the {source}). "
        f"Check TES /health/ready (registration status) and the TES log for 'register_tools'.")
    existing = _existing_open_issue()
    if existing:
        _update_known_issue(existing["id"], title=title, description=description, severity="high")
        _log("ISSUE", f"tes-runnable: updated known-issue {existing['id']} ({runnable} runnable)")
    else:
        issue = _create_known_issue(title, description)
        _log("ISSUE", f"tes-runnable: filed known-issue {issue['id']} ({runnable} runnable)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 -- cron captures stderr; any failure must be visible in the log, not silent
        _log("ERROR", f"tes-runnable-check crashed: {type(e).__name__}: {e}")
        sys.exit(1)
