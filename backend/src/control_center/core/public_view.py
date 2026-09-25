"""Anonymous-safe shapes for the public read-only routes.

control.omnibioai.org serves these routes to anyone, while operators (a
token carrying platform.manage_infra, see core.auth.infra_viewer) need the
full detail. Each function below takes the full response a route already
computes and returns what an anonymous visitor may see: aggregate counts
and statuses only -- no hostnames, queue/account/project names, filesystem
paths, container, database or worker names, route inventories, or raw
error strings (which can embed internal URLs).

Fail closed: every function builds a new dict from an allowlist of keys
rather than deleting known-sensitive ones, so a field added to a check
later stays private until it is deliberately added here.
"""
from __future__ import annotations

from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []

# Execution-backend keys an anonymous caller may see (label + configured).
_CLOUD_PUBLIC_KEYS = ("label", "configured")


def public_cloud(data: Any) -> dict[str, Any]:
    return {
        name: {k: info.get(k) for k in _CLOUD_PUBLIC_KEYS}
        for name, info in _dict(data).items()
        if isinstance(info, dict)
    }


def public_reference(data: Any) -> dict[str, Any]:
    data = _dict(data)
    return {
        "available": bool(data.get("available")),
        "organisms": [
            {
                "organism": o.get("organism"),
                "assembly": o.get("assembly"),
                "indexes": _dict(o.get("indexes")),
                "variants": _dict(o.get("variants")),
            }
            for o in _dicts(data.get("organisms"))
        ],
        "databases": _dict(data.get("databases")),
        "annotation": {org: _dict(sources) for org, sources in _dict(data.get("annotation")).items()},
    }


def public_integrity(checks: Any) -> dict[str, Any]:
    checks = _dicts(checks)
    statuses = [str(c.get("status", "")).upper() for c in checks]
    return {
        "total": len(checks),
        "ok": sum(s == "OK" for s in statuses),
        "problems": sum(s != "OK" for s in statuses),
    }


def _sum(values: list[float | None]) -> float:
    return round(sum(v for v in values if isinstance(v, (int, float))), 2)


_HOST_PUBLIC_KEYS = (
    "cpu_system_pct", "cpu_user_pct", "cpu_idle_pct",
    "memory_total_gb", "memory_available_gb",
)


def public_activity(data: Any) -> dict[str, Any]:
    data = _dict(data)
    containers = _dicts(data.get("containers"))
    host = _dict(data.get("host"))
    return {
        "reachable": bool(data.get("reachable")),
        "container_count": len(containers),
        "total_cpu_pct": _sum([c.get("cpu_pct") for c in containers]),
        "total_memory_used_mb": _sum([c.get("memory_used_mb") for c in containers]),
        "host": {k: host.get(k) for k in _HOST_PUBLIC_KEYS} if host else None,
    }


def public_database(data: Any) -> dict[str, Any]:
    data = _dict(data)
    mysql = _dict(data.get("mysql"))
    redis = _dict(data.get("redis"))
    neo4j = _dict(data.get("neo4j"))
    return {
        "mysql": None if not mysql else {
            "connections": mysql.get("connections"),
            "max_connections": mysql.get("max_connections"),
            "slow_queries": mysql.get("slow_queries"),
            "database_count": len(_dicts(mysql.get("databases"))),
            "total_size_mb": _sum([d.get("size_mb") for d in _dicts(mysql.get("databases"))]),
        },
        "redis": None if not redis else {
            "hit_rate_pct": redis.get("hit_rate_pct"),
            "connected_clients": redis.get("connected_clients"),
        },
        "neo4j": None if not neo4j else {
            "node_count": neo4j.get("node_count"),
            "relationship_count": neo4j.get("relationship_count"),
        },
    }


def public_celery(data: Any) -> dict[str, Any]:
    data = _dict(data)
    workers = _dicts(data.get("workers"))
    return {
        "reachable": not data.get("error"),
        "workers_total": len(workers),
        "workers_online": sum(w.get("status") == "online" for w in workers),
        "active_tasks": int(_sum([w.get("active_tasks") for w in workers])),
    }


def public_image_freshness(data: Any) -> dict[str, Any]:
    images = _dicts(_dict(data).get("images"))
    return {
        "images_checked": len(images),
        "stale": sum(bool(i.get("stale")) for i in images),
    }


_GATEWAY_PUBLIC_KEYS = (
    "requests_7d", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms",
    "auth_failure_rate_pct", "status_code_breakdown",
)


def public_gateway_traffic(data: Any) -> dict[str, Any]:
    data = _dict(data)
    return {k: data.get(k) for k in _GATEWAY_PUBLIC_KEYS}


def public_gpu(results: Any) -> list[dict[str, Any]]:
    # GPU model name (e.g. "NVIDIA GB10") and status are public; the free-text
    # message can carry exception text, so it is dropped.
    return [
        {"name": r.get("name"), "model": r.get("target"), "status": r.get("status")}
        for r in _dicts(results)
        if r.get("name") != "gpu:check"
    ]
