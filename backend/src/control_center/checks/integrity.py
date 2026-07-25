from __future__ import annotations

import os
from typing import Any


def run_integrity_checks(settings: Any) -> list[dict]:
    """Checks configured symlinks/mounts (system.integrity_checks in config)
    resolve to a real, non-empty target."""
    system = settings.system or {}
    cfgs = (system.get("integrity_checks") or []) if isinstance(system, dict) else []
    results: list[dict] = []

    for cfg in cfgs:
        path = cfg.get("path")
        if not path:
            continue
        name = cfg.get("name") or path

        is_symlink = os.path.islink(path)
        resolves_to = os.path.realpath(path) if is_symlink else None
        target_exists = os.path.exists(path)
        target_readable = os.access(path, os.R_OK) if target_exists else False

        target_nonempty = False
        if target_exists:
            try:
                if os.path.isdir(path):
                    target_nonempty = any(os.scandir(path))
                else:
                    target_nonempty = os.path.getsize(path) > 0
            except OSError:
                target_nonempty = False

        if not target_exists:
            status = "broken" if is_symlink else "missing"
        elif not target_nonempty:
            status = "empty"
        else:
            status = "ok"

        results.append({
            "name": name,
            "path": path,
            "is_symlink": is_symlink,
            "resolves_to": resolves_to,
            "target_exists": target_exists,
            "target_readable": target_readable,
            "target_nonempty": target_nonempty,
            "status": status,
        })

    return results
