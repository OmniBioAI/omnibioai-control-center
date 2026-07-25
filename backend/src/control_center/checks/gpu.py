from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Optional

import httpx

from control_center.notifications.discord import notify as _discord_notify

_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
_GPU_TEMP_THRESHOLD = 75
_OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")


def check_gpu_temperature() -> list[dict]:
    """Query nvidia-smi for GPU temperatures and fire alerts if above threshold."""
    results: list[dict] = []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return results

        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            idx, name, temp_str = parts[0], parts[1], parts[2]
            try:
                gpu_temp = int(temp_str)
            except ValueError:
                continue

            status = "UP"
            msg = f"{gpu_temp}°C"
            if gpu_temp > _GPU_TEMP_THRESHOLD:
                status = "WARN"
                msg = f"High temp: {gpu_temp}°C"
                _discord_notify(
                    _WEBHOOK,
                    "🌡️ High Temperature Alert",
                    f"GPU {idx} ({name}) temperature critical: {gpu_temp}°C",
                    color='error',
                    fields={
                        "Temperature": f"{gpu_temp}°C",
                        "Threshold": f"{_GPU_TEMP_THRESHOLD}°C",
                        "GPU": f"[{idx}] {name}",
                        "Action": "Reduce workload immediately",
                    },
                )

            results.append({
                "name": f"gpu:{idx}",
                "type": "gpu",
                "target": name,
                "status": status,
                "latency_ms": None,
                "message": msg,
            })
    except FileNotFoundError:
        pass  # nvidia-smi not available
    except Exception as exc:
        results.append({
            "name": "gpu:check",
            "type": "gpu",
            "target": "-",
            "status": "WARN",
            "latency_ms": None,
            "message": f"{type(exc).__name__}: {exc}",
        })

    return results


def _parse_nvidia_value(raw: str) -> Optional[float]:
    raw = raw.strip()
    if not raw or raw.upper().startswith("[N/A") or raw == "N/A":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _is_unsupported_field(raw: str) -> bool:
    """True when nvidia-smi itself reports a field as not queryable on this
    GPU (e.g. "[N/A]", "N/A", "[Not Supported]", "Not Supported" -- the
    literal text nvidia-smi prints for memory.total/memory.used on GB10-class
    unified-memory hardware), as opposed to the field being missing for some
    other, genuinely anomalous reason."""
    normalized = raw.strip().strip("[]").strip().lower()
    return normalized in ("n/a", "not supported")


def get_gpu_status() -> dict[str, Any]:
    """Full GPU status for the /gpu endpoint (richer than check_gpu_temperature,
    which only feeds the summary/services health checks)."""
    if shutil.which("nvidia-smi") is None:
        return {"reachable": False, "error": "nvidia-smi not found in this container"}

    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        return {"reachable": False, "error": f"{type(e).__name__}: {e}"}

    if out.returncode != 0 or not out.stdout.strip():
        return {"reachable": False, "error": out.stderr.strip() or "nvidia-smi returned no output"}

    # nvidia-smi CSV memory.total/used are already in MiB (matches memory_*_mb contract)
    fields = [f.strip() for f in out.stdout.strip().splitlines()[0].split(",")]
    name = fields[0] if len(fields) > 0 else "unknown"
    mem_total_raw = fields[1] if len(fields) > 1 else ""
    mem_used_raw = fields[2] if len(fields) > 2 else ""
    mem_total = _parse_nvidia_value(mem_total_raw)
    mem_used = _parse_nvidia_value(mem_used_raw)
    util_pct = _parse_nvidia_value(fields[3]) if len(fields) > 3 else None
    temp_c = _parse_nvidia_value(fields[4]) if len(fields) > 4 else None
    power_w = _parse_nvidia_value(fields[5]) if len(fields) > 5 else None

    # A missing memory reading is a stronger signal than "unknown" -- it's the
    # exact symptom observed during a prior CUDA OOM incident where the driver
    # stopped reporting memory at all. Surface it explicitly rather than as a
    # generic null.
    #
    # But GB10-class (DGX Spark) unified-memory hardware legitimately reports
    # memory.total/memory.used as "[N/A]" on every query -- that's documented
    # behavior for this architecture, not a fault. Only raise the driver
    # warning when memory is missing for some other reason.
    memory_unsupported = mem_used is None and _is_unsupported_field(mem_used_raw)
    error = None
    if mem_used is None and not memory_unsupported:
        error = "nvidia-smi returned N/A for memory -- driver may be in a bad state"

    processes: list[dict[str, Any]] = []
    try:
        papps = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        for line in papps.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            pid_val = _parse_nvidia_value(parts[0])
            mem_val = _parse_nvidia_value(parts[2])
            processes.append({
                "pid": int(pid_val) if pid_val is not None else None,
                "name": parts[1],
                "memory_mb": mem_val,
            })
    except Exception:
        pass

    ollama_models: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=3) as client:
            r = client.get(f"{_OLLAMA_URL}/api/ps")
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    ollama_models.append({
                        "name": m.get("name") or m.get("model"),
                        "size_gb": round((m.get("size") or 0) / 1e9, 1),
                        "until": m.get("expires_at"),
                    })
    except Exception:
        pass

    return {
        "reachable": True,
        "gpu_name": name,
        "memory_total_mb": int(mem_total) if mem_total is not None else None,
        "memory_used_mb": int(mem_used) if mem_used is not None else None,
        "utilization_pct": util_pct,
        "temperature_c": temp_c,
        "power_draw_w": power_w,
        "processes": processes,
        "ollama_loaded_models": ollama_models,
        "memory_unsupported": memory_unsupported,
        "error": error,
    }
