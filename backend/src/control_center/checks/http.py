"""
OmniBioAI backend.src.control_center.checks.http.

Purpose:
    Defines check_http for backend.src.control_center.checks.http.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import time
import urllib.request
from typing import Any


def check_http(name: str, cfg: dict[str, Any]) -> dict:
    url = cfg.get("url")
    timeout_s = float(cfg.get("timeout_s", 2))

    if not url:
        return {
            "name": name,
            "type": "http",
            "target": "-",
            "status": "DOWN",
            "latency_ms": None,
            "message": "Missing 'url' in config",
        }

    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omnibioai-control-center/0.1"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            _ = resp.read(64)  # small read just to validate response body exists
            code = getattr(resp, "status", 200)
        latency_ms = int((time.perf_counter() - start) * 1000)

        if 200 <= int(code) < 400:
            return {
                "name": name,
                "type": "http",
                "target": url,
                "status": "UP",
                "latency_ms": latency_ms,
                "message": f"HTTP {code}",
            }

        return {
            "name": name,
            "type": "http",
            "target": url,
            "status": "WARN",
            "latency_ms": latency_ms,
            "message": f"HTTP {code}",
        }

    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "name": name,
            "type": "http",
            "target": url,
            "status": "DOWN",
            "latency_ms": latency_ms,
            "message": f"{type(e).__name__}: {e}",
        }
