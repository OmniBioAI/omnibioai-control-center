from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

# Same broker the workbench/celery-worker services use (see the "workbench"
# and "celery-worker" services in docker-compose.yml). CELERY_RESULT_BACKEND
# isn't set as an env var there -- Django's settings.py default assumes the
# backend lives on the same redis instance as the broker, one db index over,
# so that's the default we match here too.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

_INSPECT_TIMEOUT_S = 3   # per Celery broadcast (ping/active) -- a worker that
                         # doesn't answer within this counts as "offline"
_OVERALL_TIMEOUT_S = 5   # hard ceiling so a dead broker can never hang report gen
_RECENT_TASKS_LIMIT = 20


def get_celery_status() -> dict[str, Any]:
    """Live worker + recent-task status for the /celery endpoint.

    Workers/active_tasks come from Celery's control.inspect() API against the
    real broker. recent_tasks reads the redis result backend directly (its
    task-meta-<id> keys) -- django_celery_results is installed in this stack
    but isn't the configured CELERY_RESULT_BACKEND, so it holds no task
    history; redis is the backend that's actually live.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_collect)
        try:
            return future.result(timeout=_OVERALL_TIMEOUT_S)
        except FutureTimeoutError:
            return {"workers": [], "recent_tasks": [], "error": "celery unreachable: inspect timed out"}
        except Exception as e:
            return {"workers": [], "recent_tasks": [], "error": f"celery unreachable: {type(e).__name__}: {e}"}


def _collect() -> dict[str, Any]:
    from celery import Celery

    app = Celery(broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
    insp = app.control.inspect(timeout=_INSPECT_TIMEOUT_S)

    # ping() and active() are each their own broadcast that blocks for the
    # *entire* inspect timeout collecting replies (kombu can't know when every
    # worker has answered) -- run them concurrently so the combined wall time
    # stays near _INSPECT_TIMEOUT_S instead of doubling it.
    with ThreadPoolExecutor(max_workers=2) as pool:
        pong_future = pool.submit(insp.ping)
        active_future = pool.submit(insp.active)
        pong = pong_future.result() or {}
        active = active_future.result() or {}

    worker_names = sorted(set(pong) | set(active))
    workers = [
        {
            "name": name,
            "status": "online" if name in pong else "offline",
            "active_tasks": len(active.get(name) or []),
        }
        for name in worker_names
    ]

    return {"workers": workers, "recent_tasks": _recent_tasks(app)}


def _recent_tasks(app: Any) -> list[dict]:
    """Vanilla Celery has no 'list all results' API -- with redis as the
    result backend, results are just JSON blobs under celery-task-meta-<id>
    keys, so we scan for those directly."""
    backend_url = app.conf.result_backend or ""
    if not backend_url.startswith("redis"):
        return []

    import redis
    r = redis.from_url(backend_url, socket_connect_timeout=_INSPECT_TIMEOUT_S,
                        socket_timeout=_INSPECT_TIMEOUT_S)

    rows: list[dict] = []
    for key in r.scan_iter(match="celery-task-meta-*", count=200):
        raw = r.get(key)
        if not raw:
            continue
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError):
            continue
        row = {
            "name": meta.get("name") or meta.get("task_id") or "unknown",
            "state": meta.get("status") or "UNKNOWN",
            "_date_done": meta.get("date_done") or "",
        }
        runtime = meta.get("runtime")
        if runtime is not None:
            row["runtime_s"] = round(float(runtime), 2)
        rows.append(row)

    rows.sort(key=lambda t: t["_date_done"], reverse=True)
    for row in rows:
        row.pop("_date_done", None)
    return rows[:_RECENT_TASKS_LIMIT]
