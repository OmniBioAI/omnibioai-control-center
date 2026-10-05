"""
OmniBioAI backend.src.control_center.checks.tcp.

Purpose:
    Defines check_tcp for backend.src.control_center.checks.tcp.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import socket
import time


def check_tcp(name: str, host: str | None, port: int, kind: str) -> dict:
    target = f"{host}:{port}"
    if not host:
        return {
            "name": name,
            "type": kind,
            "target": target,
            "status": "DOWN",
            "latency_ms": None,
            "message": "Missing host",
        }

    start = time.perf_counter()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect((host, port))
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "name": name,
            "type": kind,
            "target": target,
            "status": "UP",
            "latency_ms": latency_ms,
            "message": "TCP connect ok",
        }
    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "name": name,
            "type": kind,
            "target": target,
            "status": "DOWN",
            "latency_ms": latency_ms,
            "message": f"{type(e).__name__}: {e}",
        }
    finally:
        try:
            s.close()
        except Exception:
            pass
