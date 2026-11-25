#!/usr/bin/env python3
"""
check_platform_health.py — alert when a NAS mount is missing or empty, or a compose
service is down.

Runs on the host via cron every minute (same pattern as check_tes_runnable.py).
Two independent checks, each with its own known issue (which alerts
#omnibioai-alerts through the central Discord router), updated while the problem
lasts and auto-resolved once it clears:

- [platform-mounts]: every expected NAS mount is mounted from its expected NFS
  export and has at least its minimum number of entries (sif-images >= 900;
  datasets and reference-genomes non-empty; models only mounted), and inside the
  TES container the SIF root shows >= 900 entries too (a bind made while a
  sub-mount was missing stays empty after the host remounts). Alerts after
  PLATFORM_MOUNTS_WINDOW_MINUTES (default 3).
- [platform-services]: Docker does not answer, the project has no containers, or a
  container of it is exited, dead, restarting, created-but-not-started, or unhealthy
  for more than
  PLATFORM_SERVICES_WINDOW_MINUTES (default 5). One-shot services (exit 0 is their
  job) are listed in PLATFORM_ONESHOT_SERVICES. While ops/locks/deploy.lock is held
  and not expired, service problems are not counted (a deploy recreates them).

Why: after the 2026-11-24 power cut the four Pool-3 NAS sub-mounts stayed failed
(their parent mount failed at boot and mount units never retry); TES came up with
an empty SIF root and workbench + rag stayed exited. Nothing alerted.

Every directory read runs in a subprocess with a timeout (a hard NFS mount whose
server is gone can hang a read), and an flock stops a stuck run from stacking.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import jwt
import requests

CONTROL_CENTER_URL = os.environ.get("CONTROL_CENTER_URL", "http://127.0.0.1:7070")
STUDIO_ENV_PATH = Path("/home/manish/Desktop/omnibioai-ecosystem/omnibioai-studio/.env")
STATE_PATH = Path(os.environ.get(
    "PLATFORM_HEALTH_STATE", "/home/manish/Desktop/omnibioai-ecosystem/work/backups/platform-health-state.json"))
LOCK_PATH = Path(os.environ.get(
    "PLATFORM_HEALTH_LOCK", "/home/manish/Desktop/omnibioai-ecosystem/work/backups/platform-health.lock"))
DEPLOY_LOCK = Path(os.environ.get(
    "PLATFORM_DEPLOY_LOCK", "/home/manish/Desktop/omnibioai-ecosystem/ops/locks/deploy.lock"))
PROJECT = os.environ.get("PLATFORM_COMPOSE_PROJECT", "omnibioai-studio")
TES_CONTAINER = os.environ.get("TES_CONTAINER", "omnibioai-studio-tes-1")
ONESHOT_SERVICES = frozenset(
    os.environ.get("PLATFORM_ONESHOT_SERVICES", "deploy-verify,redis-acl-init,db-init").split(","))
MOUNTS_WINDOW_MINUTES = float(os.environ.get("PLATFORM_MOUNTS_WINDOW_MINUTES", "3"))
SERVICES_WINDOW_MINUTES = float(os.environ.get("PLATFORM_SERVICES_WINDOW_MINUTES", "5"))
READ_TIMEOUT_SECONDS = 20

NAS = "192.168.86.24"
# (mount point, expected NFS source, minimum entries); PLATFORM_MOUNTS_JSON overrides
DEFAULT_MOUNTS = [
    ["/mnt/nas/omnibioai", f"{NAS}:/volume2/omnibioai-main", 1],
    ["/mnt/nas/tenants", f"{NAS}:/volume2/omnibioai-main/tenants", 0],
    ["/mnt/nas/omnibioai/sif-images", f"{NAS}:/volume3/omnibioai-fast/sif-images", 900],
    ["/mnt/nas/omnibioai/reference-genomes", f"{NAS}:/volume3/omnibioai-fast/reference-genomes", 1],
    ["/mnt/nas/omnibioai/datasets", f"{NAS}:/volume3/omnibioai-fast/datasets", 1],
    ["/mnt/nas/omnibioai/models", f"{NAS}:/volume3/omnibioai-fast/models", 0],   # empty by design today
]
# paths inside TES (TES_SIF_ROOT and the legacy /sif bind), minimum entries
TES_PATHS = [["/mnt/nas/omnibioai/sif-images", 900], ["/sif", 900]]

MOUNTS_MARKER = "[platform-mounts]"
SERVICES_MARKER = "[platform-services]"


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
    token = jwt.encode({"sub": "platform-health-check", "type": "access", "permissions": [ALERT_PERMISSION],
                        "exp": int(time.time()) + 300}, _load_jwt_secret(), algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=READ_TIMEOUT_SECONDS, check=False)


# ---------------------------------------------------------------------------
# Mounts
# ---------------------------------------------------------------------------


def mount_sources(path: str) -> list[str]:
    """NFS (non-autofs) sources mounted exactly at ``path``; [] when only the autofs point or nothing is there."""
    out = _run(["findmnt", "-n", "-r", "-o", "SOURCE,FSTYPE", "--mountpoint", path])
    sources = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] != "autofs":
            sources.append(parts[0])
    return sources


def entry_count(cmd_prefix: list[str], path: str) -> int | str:
    """Entries in ``path`` (via ``ls -A``, optionally inside a container), or a short error string."""
    try:
        out = _run([*cmd_prefix, "ls", "-A", "--", path])
    except subprocess.TimeoutExpired:
        return f"no answer within {READ_TIMEOUT_SECONDS}s"
    if out.returncode != 0:
        return (out.stderr.strip().splitlines() or [f"ls exit {out.returncode}"])[-1]
    return len([ln for ln in out.stdout.splitlines() if ln])


def mount_problems(mounts: list[list], tes_paths: list[list], tes_running: bool) -> list[str]:
    problems = []
    for path, source, minimum in mounts:
        count = entry_count([], path)                   # read first: it triggers an automount
        sources = mount_sources(path)
        if source not in sources:
            problems.append(f"{path}: not mounted from {source} (found {', '.join(sources) or 'nothing'})")
        elif isinstance(count, str):
            problems.append(f"{path}: unreadable ({count})")
        elif count < minimum:
            problems.append(f"{path}: {count} entries (expected >= {minimum})")
    if tes_running:
        for path, minimum in tes_paths:
            count = entry_count(["docker", "exec", TES_CONTAINER], path)
            if isinstance(count, str):
                problems.append(f"inside {TES_CONTAINER} {path}: unreadable ({count})")
            elif count < minimum:
                problems.append(f"inside {TES_CONTAINER} {path}: {count} entries (expected >= {minimum}; "
                                f"a bind made before the mount came back: recreate tes)")
    return problems


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def compose_containers() -> list[dict]:
    """``docker inspect`` of every container of the project; raises when Docker does not answer."""
    try:
        ps = _run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}"])
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"docker ps: no answer within {READ_TIMEOUT_SECONDS}s") from None
    if ps.returncode != 0:
        raise RuntimeError(f"docker ps failed: {(ps.stderr.strip().splitlines() or ['?'])[-1][:200]}")
    ids = ps.stdout.split()
    if not ids:
        return []
    out = _run(["docker", "inspect", *ids])
    if out.returncode != 0:
        raise RuntimeError(f"docker inspect failed: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def service_problems(containers: list[dict]) -> dict[str, str]:
    """service -> what is wrong, for every container that is not running (and healthy, when it has a check)."""
    problems = {}
    for c in containers:
        service = (c.get("Config", {}).get("Labels") or {}).get("com.docker.compose.service") or c.get("Name", "?")
        state = c.get("State") or {}
        status = state.get("Status")
        health = (state.get("Health") or {}).get("Status")
        if status == "exited" and service in ONESHOT_SERVICES and state.get("ExitCode") == 0:
            continue
        if status in ("exited", "dead"):
            problems[service] = f"{status} (code {state.get('ExitCode')})"
            if state.get("Error"):
                problems[service] += f": {state['Error'][:160]}"
        elif status in ("restarting", "created", "paused", "removing"):
            problems[service] = status
        elif health == "unhealthy":
            problems[service] = "unhealthy"
    return problems


def deploy_lock_held(now: float) -> bool:
    try:
        fields = dict(line.split("=", 1) for line in DEPLOY_LOCK.read_text(encoding="utf-8").splitlines() if "=" in line)
    except OSError:
        return False
    try:
        return now <= int(fields.get("expires_epoch", "0"))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# State + known issues
# ---------------------------------------------------------------------------


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


def decide_mounts(problems: list[str], state: dict, now: float) -> tuple[str, dict]:
    """Pure state step for the mount check: (ok | recovered | waiting | alert, new state)."""
    if not problems:
        return ("recovered" if state.get("bad_since") else "ok"), {}
    since = state.get("bad_since") or now
    return ("alert" if now - since >= MOUNTS_WINDOW_MINUTES * 60 else "waiting"), {"bad_since": since}


def decide_services(problems: dict[str, str], state: dict, now: float) -> tuple[str, dict, list[str]]:
    """Pure state step for services: (action, new state {service: first seen bad}, services over the window)."""
    since = {svc: state.get(svc, now) for svc in problems}
    over = sorted(svc for svc, t in since.items() if now - t >= SERVICES_WINDOW_MINUTES * 60)
    if over:
        return "alert", since, over
    if problems:
        return "waiting", since, []
    return ("recovered" if state else "ok"), {}, []


def _existing_open_issue(marker: str) -> dict | None:
    # authenticated: anonymous callers only see issues marked public (never these), so an
    # unauthenticated lookup never finds the open issue: a new one (and alert) every run, no resolve
    resp = requests.get(f"{CONTROL_CENTER_URL}/known-issues", headers=_admin_headers(), timeout=10)
    resp.raise_for_status()
    for issue in resp.json().get("issues", []):
        if issue.get("title", "").startswith(marker) and issue.get("status") != "resolved":
            return issue
    return None


def _file_or_update(marker: str, title: str, description: str, area: str) -> str:
    existing = _existing_open_issue(marker)
    if existing:
        resp = requests.put(f"{CONTROL_CENTER_URL}/known-issues/{existing['id']}",
                            json={"title": title, "description": description, "severity": "high"},
                            headers=_admin_headers(), timeout=10)
        resp.raise_for_status()
        return f"updated known-issue {existing['id']}"
    resp = requests.post(f"{CONTROL_CENTER_URL}/known-issues",
                         json={"title": title, "description": description, "severity": "high", "area": area},
                         headers=_admin_headers(), timeout=10)
    resp.raise_for_status()
    return f"filed known-issue {resp.json()['id']}"


def _resolve(marker: str, note: str) -> str | None:
    existing = _existing_open_issue(marker)
    if not existing:
        return None
    resp = requests.put(f"{CONTROL_CENTER_URL}/known-issues/{existing['id']}",
                        json={"status": "resolved",
                              "description": f"{existing.get('description', '')}\n\n{note}"},
                        headers=_admin_headers(), timeout=10)
    resp.raise_for_status()
    return existing["id"]


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def report_mounts(problems: list[str], state: dict, now: float) -> dict:
    action, new = decide_mounts(problems, state, now)
    if action == "ok":
        _log("INFO", "platform-mounts: all expected mounts present")
    elif action == "recovered":
        issue = _resolve(MOUNTS_MARKER, f"Auto-resolved by platform-health-check: all mounts present as of {_iso(now)}.")
        _log("ISSUE" if issue else "INFO", f"platform-mounts: recovered{f', resolved known-issue {issue}' if issue else ''}")
    elif action == "waiting":
        _log("ISSUE", f"platform-mounts: {len(problems)} problem(s) for "
                      f"{(now - new['bad_since']) / 60:.0f} of {MOUNTS_WINDOW_MINUTES:.0f} min: {'; '.join(problems)}")
    else:
        title = f"{MOUNTS_MARKER} {len(problems)} NAS mount problem(s): {problems[0][:120]}"
        description = (
            f"Detected by the platform-health self-check since {_iso(new['bad_since'])}:\n- " + "\n- ".join(problems)
            + "\n\nHost: `findmnt -R /mnt/nas`; start a failed sub-mount with `sudo systemctl start "
              "'mnt-nas-omnibioai-<name>.mount'`. Inside-TES problems after the host is fine need a tes recreate "
              "(deploy lock).")
        _log("ISSUE", f"platform-mounts: {_file_or_update(MOUNTS_MARKER, title, description, 'NAS / Infra')}")
    return new


def report_services(problems: dict[str, str], state: dict, now: float, lock_held: bool) -> dict:
    if lock_held:
        _log("INFO", f"platform-services: deploy lock held; {len(problems)} not-running service(s) not counted")
        return state
    action, new, over = decide_services(problems, state, now)
    if action == "ok":
        _log("INFO", "platform-services: all compose services running")
    elif action == "recovered":
        issue = _resolve(SERVICES_MARKER, f"Auto-resolved by platform-health-check: all services running as of {_iso(now)}.")
        _log("ISSUE" if issue else "INFO", f"platform-services: recovered{f', resolved known-issue {issue}' if issue else ''}")
    elif action == "waiting":
        _log("ISSUE", "platform-services: " + "; ".join(f"{s} {p}" for s, p in sorted(problems.items())))
    else:
        title = f"{SERVICES_MARKER} {len(over)} service(s) down > {SERVICES_WINDOW_MINUTES:.0f} min: {', '.join(over)[:120]}"
        description = (
            "Detected by the platform-health self-check:\n- "
            + "\n- ".join(f"{s}: {problems[s]} since {_iso(new[s])}" for s in over)
            + "\n\nCheck `docker ps -a` and the service log; a start/recreate goes through the deploy lock.")
        _log("ISSUE", f"platform-services: {_file_or_update(SERVICES_MARKER, title, description, 'Services / Infra')}")
    return new


def main() -> int:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log("ERROR", "platform-health: previous run still running (a hung NAS read?); skipped")
            return 1
        now = time.time()
        state = load_state()
        mounts = json.loads(os.environ["PLATFORM_MOUNTS_JSON"]) if os.environ.get("PLATFORM_MOUNTS_JSON") else DEFAULT_MOUNTS
        try:
            containers = compose_containers()
            down = service_problems(containers) if containers else {"(all)": f"no containers in project {PROJECT}"}
        except RuntimeError as e:                      # Docker itself is down: that is the alert
            containers, down = [], {"docker": str(e)}
        tes_running = any(c.get("Name", "").lstrip("/") == TES_CONTAINER and (c.get("State") or {}).get("Running")
                          for c in containers)
        new_state = {
            "mounts": report_mounts(mount_problems(mounts, TES_PATHS, tes_running), state.get("mounts", {}), now),
            "services": report_services(down, state.get("services", {}), now,
                                        deploy_lock_held(now)),
        }
        save_state(new_state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 -- cron captures stderr; any failure must be visible in the log, not silent
        _log("ERROR", f"platform-health-check crashed: {type(e).__name__}: {e}")
        sys.exit(1)
