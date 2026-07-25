from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

# Same MySQL instance /database and /license use.
MYSQL_HOST = os.environ.get("MYSQL_HOST", "mysql")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "omnibioai")
WORKBENCH_DATABASE = os.environ.get("WORKBENCH_DATABASE", "omnibioai")

RUNS_ROOT = Path(os.environ.get("WORK_DIR", "/workspace/omnibioai-work")) / "runs"

_CONNECT_TIMEOUT_S = 3
_WINDOW_DAYS = 30
_TEST_USERNAME_RE = re.compile(r"^test", re.IGNORECASE)

USERS_CAVEAT = (
    "Only a handful of accounts exist in this deployment -- usernames matching "
    "/^test/ are flagged as test/throwaway, not real product users."
)
SESSIONS_CAVEAT = (
    "django_session isn't purged automatically (no clearsessions cron confirmed "
    "running) and expire_date reflects session expiry, not when the session "
    "started -- treat this as an approximate signal, not a precise count."
)
TOP_WORKFLOWS_NOTE = (
    "workflow-level tracking not yet persisted -- DagExecutor doesn't write a "
    "durable workflow identity, only individual plugin-step runs are tracked."
)
SUCCESS_RATE_CAVEAT = (
    "computed across individual plugin-step runs (RunStore/status.json), not "
    "DAG-level workflow outcomes -- there's no separable workflow identity to "
    "compute a true workflow success rate yet."
)


def get_usage_status() -> dict[str, Any]:
    users = _user_activity()
    runs = _scan_runs()

    return {
        "active_users_7d": users["active_7d"],
        "active_users_30d": users["active_30d"],
        "total_users": users["total"],
        "test_user_count": users["test_count"],
        "users_caveat": USERS_CAVEAT,
        "total_sessions_30d": _session_count(),
        "sessions_caveat": SESSIONS_CAVEAT,
        "top_plugins": runs["top_plugins"],
        "top_workflows": [],
        "top_workflows_note": TOP_WORKFLOWS_NOTE,
        "runs_by_day": runs["runs_by_day"],
        "workflow_success_rate_pct": runs["success_rate_pct"],
        "success_rate_caveat": SUCCESS_RATE_CAVEAT,
    }


def _mysql_connect(database: str = WORKBENCH_DATABASE):
    import pymysql

    return pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
        database=database, connect_timeout=_CONNECT_TIMEOUT_S,
    )


def _user_activity() -> dict[str, Any]:
    empty = {"active_7d": 0, "active_30d": 0, "total": 0, "test_count": 0}
    try:
        conn = _mysql_connect()
    except Exception:
        return empty

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username, last_login FROM users_omnibiouser")
            rows = cur.fetchall()
    except Exception:
        return empty
    finally:
        conn.close()

    now = datetime.datetime.now(datetime.timezone.utc)
    active_7d = active_30d = test_count = 0
    for username, last_login in rows:
        if _TEST_USERNAME_RE.match(username or ""):
            test_count += 1
        if last_login is None:
            continue
        if last_login.tzinfo is None:
            last_login = last_login.replace(tzinfo=datetime.timezone.utc)
        age_days = (now - last_login).total_seconds() / 86400
        if age_days <= 7:
            active_7d += 1
        if age_days <= _WINDOW_DAYS:
            active_30d += 1

    return {"active_7d": active_7d, "active_30d": active_30d, "total": len(rows), "test_count": test_count}


def _session_count() -> int:
    try:
        conn = _mysql_connect()
    except Exception:
        return 0

    try:
        with conn.cursor() as cur:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=_WINDOW_DAYS)
            cur.execute("SELECT COUNT(*) FROM django_session WHERE expire_date >= %s", (cutoff,))
            row = cur.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


def _scan_runs() -> dict[str, Any]:
    plugin_counts: dict[str, int] = {}
    day_counts: dict[str, int] = {}
    completed = failed = 0

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=_WINDOW_DAYS)

    if RUNS_ROOT.is_dir():
        for plugin_dir in RUNS_ROOT.iterdir():
            if not plugin_dir.is_dir():
                continue
            for run_dir in plugin_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                status_file = run_dir / "status.json"
                if not status_file.exists():
                    continue
                try:
                    status = json.loads(status_file.read_text(encoding="utf-8"))
                except Exception:
                    continue

                created_at = _parse_dt(status.get("created_at"))
                if created_at is None or created_at < cutoff:
                    continue

                state = status.get("state", "UNKNOWN")
                if state == "COMPLETED":
                    completed += 1
                elif state == "FAILED":
                    failed += 1

                plugin_counts[plugin_dir.name] = plugin_counts.get(plugin_dir.name, 0) + 1
                day = created_at.date().isoformat()
                day_counts[day] = day_counts.get(day, 0) + 1

    top_plugins = [
        {"name": name, "runs_30d": count}
        for name, count in sorted(plugin_counts.items(), key=lambda kv: -kv[1])
    ]
    runs_by_day = [{"date": day, "count": count} for day, count in sorted(day_counts.items())]
    total_finished = completed + failed
    success_rate_pct = round(100 * completed / total_finished, 1) if total_finished else 0.0

    return {"top_plugins": top_plugins, "runs_by_day": runs_by_day, "success_rate_pct": success_rate_pct}


def _parse_dt(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None
