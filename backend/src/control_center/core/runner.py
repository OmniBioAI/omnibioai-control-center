from __future__ import annotations

import os
from typing import Any

from control_center.checks.gpu import check_gpu_temperature
from control_center.checks.http import check_http
from control_center.checks.tcp import check_tcp
from control_center.notifications.discord import notify as _discord_notify

_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")


def check_service(name: str, cfg: dict) -> dict:
    """Run one configured service check and return its result -- no side
    effects (run_all_checks below sends the Down alerts). Also used by the
    uptime recorder (core/uptime.py), which samples every few minutes and
    must not re-alert on every sample."""
    ctype = (cfg.get("type") or "").lower()
    if ctype == "http":
        return check_http(name=name, cfg=cfg)
    if ctype == "mysql":
        return check_tcp(name=name, host=cfg.get("host"), port=int(cfg.get("port", 3306)), kind="mysql")
    if ctype == "redis":
        return check_tcp(name=name, host=cfg.get("host"), port=int(cfg.get("port", 6379)), kind="redis")
    return {
        "name": name,
        "type": ctype or "unknown",
        "target": cfg.get("url") or f'{cfg.get("host")}:{cfg.get("port")}',
        "status": "WARN",
        "latency_ms": None,
        "message": f"Unknown check type: {ctype!r}",
    }


def run_all_checks(settings: Any) -> list[dict]:
    results: list[dict] = []

    for name, cfg in (settings.services or {}).items():
        result = check_service(name, cfg)

        if result.get("status") == "DOWN":
            _discord_notify(
                _WEBHOOK,
                "🔴 Service Down",
                f"`{name}` is not responding",
                color='error',
                fields={
                    "Service": name,
                    "Target": result.get("target", "-"),
                    "Error": result.get("message", ""),
                },
            )

        results.append(result)

    results.extend(check_gpu_temperature())
    return results
