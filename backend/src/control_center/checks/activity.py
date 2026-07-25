from __future__ import annotations

import os
from typing import Any, Optional

import httpx

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")


def _prom_query(client: httpx.Client, query: str) -> list[dict]:
    r = client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        return []
    return data["data"]["result"]


def _scalar(client: httpx.Client, query: str) -> Optional[float]:
    res = _prom_query(client, query)
    if not res:
        return None
    try:
        return float(res[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return None


def _by_name(client: httpx.Client, query: str) -> dict[str, float]:
    res = _prom_query(client, query)
    out: dict[str, float] = {}
    for r in res:
        name = r["metric"].get("name")
        if not name:
            continue
        try:
            out[name] = float(r["value"][1])
        except (KeyError, ValueError):
            continue
    return out


def get_activity_status() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=10) as client:
            cpu_pct = _by_name(client, 'sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[1m]))*100')
            mem_used = _by_name(client, 'container_memory_usage_bytes{name!=""}')
            mem_limit = _by_name(client, 'container_spec_memory_limit_bytes{name!=""}')
            net_rx = _by_name(client, 'sum by (name) (container_network_receive_bytes_total{name!=""})')
            net_tx = _by_name(client, 'sum by (name) (container_network_transmit_bytes_total{name!=""})')
            # container_tasks_state exists in this cAdvisor's metric set but has
            # been observed returning 0 for every container (including ones
            # clearly alive) -- a known collection gap, not real data. A 0 here
            # is treated as "unavailable" (-> None) rather than fact.
            pids = _by_name(client, 'sum by (name) (container_tasks_state{name!=""})')

            names = set(mem_used) | set(cpu_pct)
            containers = []
            for name in sorted(names):
                used = mem_used.get(name)
                limit = mem_limit.get(name)
                mem_pct = round(used / limit * 100, 2) if used is not None and limit else None
                pid_count = pids.get(name)
                containers.append({
                    "name": name,
                    "cpu_pct": round(cpu_pct.get(name, 0.0), 2),
                    "memory_used_mb": round((used or 0.0) / 1e6, 1),
                    "memory_limit_mb": round(limit / 1e6, 1) if limit else None,
                    "memory_pct": mem_pct,
                    "net_rx_mb": round(net_rx.get(name, 0.0) / 1e6, 2),
                    "net_tx_mb": round(net_tx.get(name, 0.0) / 1e6, 2),
                    "pids": int(pid_count) if pid_count else None,
                })

            host = None
            host_error = None
            node_up = _scalar(client, 'up{job="node"}')
            if node_up == 1.0:
                cpu_system = _scalar(client, 'avg(rate(node_cpu_seconds_total{mode="system"}[1m]))*100')
                cpu_user = _scalar(client, 'avg(rate(node_cpu_seconds_total{mode="user"}[1m]))*100')
                cpu_idle = _scalar(client, 'avg(rate(node_cpu_seconds_total{mode="idle"}[1m]))*100')
                load1 = _scalar(client, 'node_load1')
                load5 = _scalar(client, 'node_load5')
                load15 = _scalar(client, 'node_load15')
                mem_total = _scalar(client, 'node_memory_MemTotal_bytes')
                mem_avail = _scalar(client, 'node_memory_MemAvailable_bytes')
                swap_total = _scalar(client, 'node_memory_SwapTotal_bytes')
                swap_free = _scalar(client, 'node_memory_SwapFree_bytes')
                procs = _scalar(client, 'node_processes_pids')
                threads = _scalar(client, 'node_processes_threads')

                host = {
                    "cpu_system_pct": round(cpu_system, 2) if cpu_system is not None else None,
                    "cpu_user_pct": round(cpu_user, 2) if cpu_user is not None else None,
                    "cpu_idle_pct": round(cpu_idle, 2) if cpu_idle is not None else None,
                    "load_1m": round(load1, 2) if load1 is not None else None,
                    "load_5m": round(load5, 2) if load5 is not None else None,
                    "load_15m": round(load15, 2) if load15 is not None else None,
                    "memory_total_gb": round(mem_total / 1e9, 1) if mem_total is not None else None,
                    "memory_available_gb": round(mem_avail / 1e9, 1) if mem_avail is not None else None,
                    "swap_used_gb": (round((swap_total - swap_free) / 1e9, 2)
                                     if swap_total is not None and swap_free is not None else None),
                    "swap_total_gb": round(swap_total / 1e9, 2) if swap_total is not None else None,
                    "processes_total": int(procs) if procs is not None else None,
                    "threads_total": int(threads) if threads is not None else None,
                }
            else:
                host_error = "node_exporter not configured -- see docker-compose.yml addition"

            return {
                "containers": containers,
                "host": host,
                "reachable": True,
                "error": host_error,
            }
    except Exception as e:
        return {"containers": [], "host": None, "reachable": False, "error": f"{type(e).__name__}: {e}"}
