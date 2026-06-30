from __future__ import annotations

import os
from typing import Any

from control_center.checks.gpu import check_gpu_temperature
from control_center.checks.http import check_http
from control_center.checks.tcp import check_tcp
from control_center.notifications.discord import notify as _discord_notify

_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")


def run_all_checks(settings: Any) -> list[dict]:
    results: list[dict] = []

    for name, cfg in (settings.services or {}).items():
        ctype = (cfg.get("type") or "").lower()

        if ctype == "http":
            result = check_http(name=name, cfg=cfg)
        elif ctype == "mysql":
            result = check_tcp(name=name, host=cfg.get("host"), port=int(cfg.get("port", 3306)), kind="mysql")
        elif ctype == "redis":
            result = check_tcp(name=name, host=cfg.get("host"), port=int(cfg.get("port", 6379)), kind="redis")
        else:
            result = {
                "name": name,
                "type": ctype or "unknown",
                "target": cfg.get("url") or f'{cfg.get("host")}:{cfg.get("port")}',
                "status": "WARN",
                "latency_ms": None,
                "message": f"Unknown check type: {ctype!r}",
            }

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
