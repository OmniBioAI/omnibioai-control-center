from __future__ import annotations

import os
import subprocess

from control_center.notifications.discord import notify as _discord_notify

_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
_GPU_TEMP_THRESHOLD = 75


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
