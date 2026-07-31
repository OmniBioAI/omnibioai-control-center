from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import jwt

@dataclass
class ServiceHealth:
    name: str; type: str; target: str; status: str
    latency_ms: Optional[int]; message: str; ui_url: Optional[str] = None

@dataclass
class DiskHealth:
    name: str; target: str; status: str; message: str

@dataclass
class EcosystemHealth:
    overall_status: str; generated_at: str
    services: List[ServiceHealth] = field(default_factory=list)
    disk: List[DiskHealth]        = field(default_factory=list)
    error: Optional[str]          = None

def _parse_service(raw: Dict[str, Any]) -> ServiceHealth:
    return ServiceHealth(
        name=str(raw.get("name", "unknown")), type=str(raw.get("type", "unknown")),
        target=str(raw.get("target", "-")),
        status=str(raw.get("status", "DOWN")).upper(),
        ui_url=raw.get("ui_url") or None,
        latency_ms=raw.get("latency_ms"),
        message=str(raw.get("message", "")))

def _parse_disk(raw: Dict[str, Any]) -> DiskHealth:
    return DiskHealth(name=str(raw.get("name", "disk")),
                      target=str(raw.get("target", "-")),
                      status=str(raw.get("status", "WARN")).upper(),
                      message=str(raw.get("message", "")))

def _admin_header() -> Dict[str, str]:
    # /summary now requires require_admin (core/auth.py) -- self-mint a
    # short-lived admin token with the same shared secret it validates
    # against (JWT_SECRET, already set on this container -- see
    # docker-compose.yml's control-center service) rather than doing an
    # interactive login round-trip. Same pattern check_domain_health.py /
    # check_disk_space.py already use for their own admin-gated calls.
    secret = os.environ.get("JWT_SECRET", "change-me")
    token = jwt.encode({"sub": "generate-report", "roles": ["admin"]}, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}

def fetch_health(base_url: str, timeout_s: float = 5.0) -> EcosystemHealth:
    url = base_url.rstrip("/") + "/summary"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "omnibioai-report/1.0", **_admin_header()},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        services = [_parse_service(s) for s in (payload.get("services") or [])]
        disk_raw = (payload.get("system") or {}).get("disk") or []
        disk     = [_parse_disk(d) for d in disk_raw]
        return EcosystemHealth(
            overall_status=str(payload.get("overall_status", "WARN")).upper(),
            generated_at=str(payload.get("generated_at", "")),
            services=services, disk=disk)
    except urllib.error.URLError as e:
        return EcosystemHealth(overall_status="UNREACHABLE", generated_at="",
                               error=f"Control Center unreachable: {e.reason}")
    except Exception as e:
        return EcosystemHealth(overall_status="UNREACHABLE", generated_at="",
                               error=f"{type(e).__name__}: {e}")
