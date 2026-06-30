from __future__ import annotations

import os
import shutil
from typing import Any

from control_center.notifications.discord import notify as _discord_notify

_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
_LOW_DISK_GB_THRESHOLD = 50


def run_disk_checks(settings: Any) -> list[dict]:
    system = settings.system or {}
    disk_cfgs = (system.get("disk_checks") or []) if isinstance(system, dict) else []
    results: list[dict] = []

    for cfg in disk_cfgs:
        path = cfg.get("path")
        warn_pct_free_below = float(cfg.get("warn_pct_free_below", 10))

        if not path:
            continue

        try:
            usage = shutil.disk_usage(path)
            free_pct = (usage.free / usage.total) * 100.0 if usage.total else 0.0
            free_gb = usage.free / (1024 ** 3)
            used_pct = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0

            status = "UP"
            msg = f"{free_pct:.1f}% free"
            if free_pct < warn_pct_free_below:
                status = "WARN"
                msg = f"Low disk: {free_pct:.1f}% free (< {warn_pct_free_below:.1f}%)"

            if free_gb < _LOW_DISK_GB_THRESHOLD:
                _discord_notify(
                    _WEBHOOK,
                    "💾 Low Disk Space",
                    f"Only {free_gb:.1f}GB remaining on `{path}`",
                    color='warning',
                    fields={
                        "Free": f"{free_gb:.1f}GB",
                        "Used": f"{used_pct}%",
                        "Path": path,
                    },
                )

            results.append(
                {
                    "name": f"disk:{path}",
                    "type": "disk",
                    "target": path,
                    "status": status,
                    "latency_ms": None,
                    "message": msg,
                }
            )
        except Exception as e:
            results.append(
                {
                    "name": f"disk:{path}",
                    "type": "disk",
                    "target": path,
                    "status": "WARN",
                    "latency_ms": None,
                    "message": f"{type(e).__name__}: {e}",
                }
            )

    return results
