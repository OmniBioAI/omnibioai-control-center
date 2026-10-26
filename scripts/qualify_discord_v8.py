#!/usr/bin/env python3
"""Read-only DGX inventory or isolated Discord/backend test runner.

Default mode inspects Docker metadata only. The isolated-tests mode executes
the configured backend suite and disposable mock flow. Neither mode performs
production mutations, sends live Discord messages, or reads container env vars.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
MAX_TIMEOUT = 600


def command(argv: list[str], timeout: int) -> tuple[int, str]:
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, type(exc).__name__
    if result.returncode:
        error = (result.stderr or "").lower()
        if "permission denied" in error:
            return result.returncode, "permission denied"
        if "not found" in error or "no such file" in error:
            return result.returncode, "required command/object not found"
        return result.returncode, "command failed"
    return 0, (result.stdout or "").strip()


def inspect_host(timeout: int) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "mode": "read-only-inspection",
        "host_architecture": platform.machine(),
        "docker_cli": shutil.which("docker") is not None,
        "docker_context": None,
        "docker_server": None,
        "containers": [],
        "errors": [],
        "production_mutation_performed": False,
        "source_image_provenance": "NOT_VERIFIED",
        "qualification": "NOT_VERIFIED",
    }
    if not evidence["docker_cli"]:
        evidence["errors"].append("docker CLI unavailable")
        evidence["qualification"] = "FAIL"
        return evidence

    code, output = command(["docker", "context", "show"], timeout)
    if code == 0:
        evidence["docker_context"] = output
    else:
        evidence["errors"].append(f"Docker context: {output}")

    code, output = command(
        ["docker", "info", "--format", "{{.ServerVersion}}|{{.Architecture}}"], timeout,
    )
    if code:
        evidence["errors"].append(f"Docker daemon: {output}")
        evidence["qualification"] = "FAIL"
        return evidence
    version, _, arch = output.partition("|")
    evidence["docker_server"] = {"version": version, "architecture": arch}

    code, output = command(["docker", "ps", "-a", "--format", "{{json .}}"], timeout)
    if code:
        evidence["errors"].append(f"Container inventory: {output}")
        evidence["qualification"] = "FAIL"
        return evidence

    container_template = "{{.Image}}"
    template = (
        "{{.Id}}|{{.Os}}|{{.Architecture}}|{{join .RepoDigests \",\"}}|"
        "{{index .Config.Labels \"org.opencontainers.image.revision\"}}|"
        "{{index .Config.Labels \"org.opencontainers.image.source\"}}"
    )
    for line in output.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            evidence["errors"].append("Malformed Docker inventory row")
            continue
        item: dict[str, Any] = {
            "name": row.get("Names", ""),
            "container_id": row.get("ID", ""),
            "image_reference": row.get("Image", ""),
            "state": row.get("State", ""),
            "status": row.get("Status", ""),
        }
        code, image_id = command(["docker", "inspect", "--type", "container", "--format",
                                  container_template, item["container_id"]], timeout)
        if code:
            item["image_inspection"] = image_id
            evidence["containers"].append(item)
            continue
        code, image = command(["docker", "image", "inspect", "--format", template, image_id], timeout)
        if code == 0:
            parts = image.split("|", 5)
            if len(parts) == 6:
                item["image"] = {
                    "image_id": parts[0],
                    "os": parts[1],
                    "architecture": parts[2],
                    "immutable_repo_digests": [d for d in parts[3].split(",") if d],
                    "source_revision_label": parts[4] or None,
                    "source_url_label": parts[5] or None,
                }
        else:
            item["image_inspection"] = image
        evidence["containers"].append(item)

    cc = [c for c in evidence["containers"] if "control-center" in c["name"].lower()]
    evidence["control_center_containers_found"] = len(cc)
    evidence["host_image_inventory_status"] = "PASS" if (
        evidence["host_architecture"] in {"aarch64", "arm64"}
        and cc
        and all(c.get("image", {}).get("architecture") in {"aarch64", "arm64"} for c in cc)
        and all(c.get("image", {}).get("immutable_repo_digests") for c in cc)
    ) else "FAIL"
    # A digest and OCI labels are observations, not signed build provenance.
    # Inventory may pass while overall image qualification remains unverified.
    return evidence


def isolated_tests(timeout: int, python_override: str | None) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "mode": "isolated-tests",
        "tests": [],
        "production_mutation_performed": False,
        "live_discord_messages_sent": False,
        "note": "Mocked in-process flow; not Docker service E2E or live acceptance.",
    }
    interpreter = ROOT / ".venv" / "bin" / "python"
    python = python_override or (str(interpreter) if interpreter.is_file() else sys.executable)
    child_env = os.environ.copy()
    src_path = str(BACKEND / "src")
    child_env["PYTHONPATH"] = os.pathsep.join(
        part for part in (src_path, child_env.get("PYTHONPATH", "")) if part
    )
    jobs = [
        ("control-center-backend",
         [python, "-m", "pytest", "-q", "--tb=short"], BACKEND),
        ("disposable-mock-flow",
         [python, "scripts/discord_disposable_e2e.py"], ROOT),
    ]
    for name, argv, cwd in jobs:
        started = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=cwd, env=child_env, capture_output=True,
                                    text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            evidence["tests"].append({
                "name": name, "status": "FAIL", "error": f"timed out after {timeout}s",
            })
            continue
        output = (result.stdout or "") + (result.stderr or "")
        unsafe = any(term in output.lower() for term in
                     ("api/webhooks/", "discord_event_", "secret=", "token="))
        tail = "output suppressed for safety" if unsafe else "\n".join(output.strip().splitlines()[-35:])
        evidence["tests"].append({
            "name": name,
            "status": "PASS" if result.returncode == 0 and not unsafe else "FAIL",
            "return_code": result.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "summary": tail,
        })
    evidence["qualification"] = "PASS" if all(t["status"] == "PASS" for t in evidence["tests"]) else "FAIL"
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inspect", "isolated-tests"), default="inspect")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--python", help="test environment interpreter for isolated-tests mode")
    args = parser.parse_args()
    if not 1 <= args.timeout <= MAX_TIMEOUT:
        parser.error(f"--timeout must be in 1..{MAX_TIMEOUT}")
    report = inspect_host(args.timeout) if args.mode == "inspect" else isolated_tests(args.timeout, args.python)
    print(json.dumps(report, indent=2, sort_keys=True))
    status = report.get("qualification", report.get("host_image_inventory_status"))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
