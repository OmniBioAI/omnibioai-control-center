"""Uptime history for the public Platform Overview.

The Control Center already knows how to check every configured service
(core/runner.check_service). This module samples those checks on a timer
and keeps per-service, per-day counts in a small JSON file, so the public
dashboard can show a 90-day availability bar without depending on an
external monitoring system.

Stored shape (UPTIME_STORE_PATH, default under the report output dir):

    {"services": {"<service>": {"<YYYY-MM-DD>": {"up": n, "degraded": n, "down": n}}}}

A sample counts as available unless its status is DOWN; WARN (responding
but degraded) is recorded separately so the page can say so. Days older
than RETENTION_DAYS are pruned on every write.

Single sampler: every worker process starts run_forever(), but only the
one holding an exclusive OS lock on `<store>.sampler.lock` samples; the
others retry each interval and take over if that process exits. Reads and
writes of the store are serialised across processes by `<store>.lock`.

Public exposure: summarize() only returns services named in the showcase
config's `uptime_services` allowlist, under their public label -- never
the internal service name, target URL, or check message.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import IO, Any

from control_center.core.runner import check_service

log = logging.getLogger("control_center.uptime")

RETENTION_DAYS = 90
SAMPLE_SECONDS = float(os.environ.get("UPTIME_SAMPLE_SECONDS", "300"))
_lock = threading.Lock()


def store_path() -> Path:
    configured = os.environ.get("UPTIME_STORE_PATH")
    if configured:
        return Path(configured)
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    return workspace / "work" / "out" / "uptime" / "uptime.json"


def _sibling(suffix: str) -> Path:
    path = store_path()
    return path.with_name(path.name + suffix)


@contextmanager
def _store_lock() -> Iterator[None]:
    """Exclusive lock across threads and processes for a store read-modify-write."""
    path = _sibling(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def try_become_sampler() -> IO[str] | None:
    """Take the sampler role if no other process holds it. Returns the open
    lock file (keep it open to keep the role) or None."""
    path = _sibling(".sampler.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a")  # noqa: SIM115 -- held open for the process lifetime
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _load() -> dict[str, Any]:
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"services": {}}
    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        return {"services": {}}
    return data


def _save(data: dict[str, Any]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _bucket(status: Any) -> str:
    status = str(status or "").upper()
    if status == "UP":
        return "up"
    if status == "DOWN":
        return "down"
    return "degraded"


def record(results: list[dict], today: date | None = None) -> None:
    """Add one sample per result to today's counts and prune old days."""
    day = (today or datetime.now(UTC).date()).isoformat()
    cutoff = ((today or datetime.now(UTC).date()) - timedelta(days=RETENTION_DAYS)).isoformat()
    with _store_lock():
        data = _load()
        services = data["services"]
        for result in results:
            name = result.get("name")
            if not isinstance(name, str) or not name:
                continue
            days = services.setdefault(name, {})
            counts = days.setdefault(day, {"up": 0, "degraded": 0, "down": 0})
            counts[_bucket(result.get("status"))] += 1
        for days in services.values():
            for old in [d for d in days if d < cutoff]:
                del days[old]
        _save(data)


def _day_availability(counts: dict[str, int] | None) -> float | None:
    if not counts:
        return None
    total = sum(int(counts.get(k, 0)) for k in ("up", "degraded", "down"))
    if total == 0:
        return None
    return round(100 * (total - int(counts.get("down", 0))) / total, 2)


def summarize(services: dict[str, str] | None, days: int = RETENTION_DAYS,
              today: date | None = None) -> dict[str, Any]:
    """Per-day availability for the given {internal name: public label}
    services over the last `days` days. Pass services=None to summarize
    every recorded service under its internal name (operators only)."""
    end = today or datetime.now(UTC).date()
    dates = [(end - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    stored = _load()["services"]
    names = services if services is not None else {name: name for name in sorted(stored)}
    rows = []
    for name, label in names.items():
        history = stored.get(name, {})
        per_day = [{"date": d, "availability_pct": _day_availability(history.get(d))} for d in dates]
        up = sum(int(c.get("up", 0)) + int(c.get("degraded", 0)) for d, c in history.items() if d in dates)
        total = up + sum(int(c.get("down", 0)) for d, c in history.items() if d in dates)
        rows.append({
            "label": label,
            "overall_pct": round(100 * up / total, 2) if total else None,
            "days": per_day,
        })
    return {"window_days": days, "sample_seconds": SAMPLE_SECONDS, "services": rows}


def sample_once(load_settings: Callable[[], Any]) -> None:
    """Check every configured service once and record the results. Never
    raises: a failure is logged and the next sample tries again."""
    try:
        settings = load_settings()
        results = [check_service(name, cfg) for name, cfg in (settings.services or {}).items()]
        record(results)
    except Exception as exc:  # noqa: BLE001 -- the sampler must keep running
        log.warning("uptime_sample_failed", extra={"extra_fields": {"error": type(exc).__name__}})


def run_forever(load_settings: Callable[[], Any], sleep: Callable[[float], None] = time.sleep,
                iterations: int | None = None) -> None:
    """Background sampler loop, run by every process; only the lock holder
    samples (see module docstring). `iterations` bounds it for tests."""
    role: IO[str] | None = None
    count = 0
    while iterations is None or count < iterations:
        if role is None:
            role = try_become_sampler()
        if role is not None:
            sample_once(load_settings)
        count += 1
        sleep(SAMPLE_SECONDS)
