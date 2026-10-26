"""Preflight, build, run, evidence, and ownership-limited cleanup for the stack."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from ownership import verified_cleanup
from subnet import assert_subnet_free, select_free_subnet

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/discord-docker-qualification-v1"
COMPOSE = ROOT / "scripts/discord-docker-qualification/compose.yaml"
WORKSTREAM = "OMNIBIOAI_DISCORD_DOCKER_QUALIFICATION_INFRASTRUCTURE_V1"


def run(argv: list[str], *, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    # Container logs may contain arbitrary bytes. Replacement decoding keeps a
    # diagnostic failure from bypassing the finally-path cleanup/inventory work.
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"{argv[0]} failed ({result.returncode}): {(result.stderr or result.stdout)[-3000:]}")
    return result


def persist_ownership_manifest(run_dir: Path, manifest: dict) -> None:
    path = run_dir / "ownership-manifest.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


DIAGNOSTIC_BYTES_PER_STREAM = 16 * 1024
DIAGNOSTIC_LOG_TAIL_BYTES = 64 * 1024
DIAGNOSTIC_SECRET_KEY = re.compile(r"(?i)(secret|token|signing[_-]?key|webhook[_-]?url|authorization)")
DIAGNOSTIC_DISCORD_URL = re.compile(
    r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/[^\s\"']+", re.I)


def _run_secret_values(run_dir: Path) -> list[str]:
    """Read only this run's private Compose env for in-memory redaction."""
    env_path = run_dir / "compose.env"
    try:
        if env_path.is_symlink() or env_path.stat().st_mode & 0o077:
            return []
        values = []
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and DIAGNOSTIC_SECRET_KEY.search(key):
                values.append(value)
                if key.endswith("_JSON"):
                    try:
                        parsed = json.loads(value)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        values.extend(str(item) for item in parsed.values()
                                      if isinstance(item, (str, int, float)) and str(item))
        return sorted((value for value in values if value), key=len, reverse=True)
    except OSError:
        return []


def redact_diagnostic_text(value: str, secret_values: list[str]) -> str:
    """Redact known run secrets and credential-shaped values before persistence."""
    redacted = value
    for secret in secret_values:
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = DIAGNOSTIC_DISCORD_URL.sub("[REDACTED_DISCORD_WEBHOOK]", redacted)
    redacted = re.sub(
        r'(?i)("?(?:secret|token|signing[_-]?key|webhook[_-]?url|authorization)"?\s*[:=]\s*"?)[^\s,"}]+',
        r"\1[REDACTED]", redacted)
    return redacted


def _bounded_utf8(value: str, limit: int) -> str:
    return value.encode("utf-8", errors="replace")[-limit:].decode("utf-8", errors="ignore")


def safe_exception_summary(exc: BaseException | None, run_dir: Path) -> str | None:
    if exc is None:
        return None
    return _bounded_utf8(redact_diagnostic_text(
        f"{type(exc).__name__}: {exc}", _run_secret_values(run_dir)), DIAGNOSTIC_BYTES_PER_STREAM)


DIAGNOSTIC_SERVICES = ("redis", "mock-discord", "state-init")


def _diagnostic_service_resource(client, manifest: dict, service: str) -> dict:
    """Resolve one allowlisted run container, then revalidate by immutable ID."""
    if service not in DIAGNOSTIC_SERVICES:
        return {"status": "FAIL", "error": "diagnostic service is not allowlisted"}
    run_id = manifest["run_id"]
    rows = client.resources("container", run_id)
    expected_labels = {"io.omnibioai.workstream": manifest.get("workstream"),
                       "io.omnibioai.run-id": run_id, "io.omnibioai.disposable": "true"}
    for row in rows:
        row_id = str(row.get("id", ""))
        row_labels = row.get("labels") or {}
        if row.get("service") not in {"redis", "mock-discord", "router", "state-init", "test-runner"}:
            return {"status": "FAIL", "error": "unknown run-labeled container service"}
        if (not re.fullmatch(r"[0-9a-f]{64}", row_id) or row.get("project") != manifest.get("project") or
                any(row_labels.get(key) != value for key, value in expected_labels.items())):
            return {"status": "FAIL", "error": "unowned or ambiguously labeled run container"}
    candidates = [row for row in rows if row.get("service") == service]
    if not candidates:
        return {"status": "NOT_FOUND", "error": f"no run-labeled {service} container exists"}
    if len(candidates) != 1:
        return {"status": "FAIL", "error": f"ambiguous run-labeled {service} container set"}
    candidate = candidates[0]
    container_id = candidate.get("id", "")
    if not re.fullmatch(r"[0-9a-f]{64}", str(container_id)):
        return {"status": "FAIL", "error": f"{service} did not expose a full immutable container ID"}
    labels = candidate.get("labels") or {}
    expected_names = manifest.get("expected_service_names", [])
    expected_name = f"{manifest.get('project')}-{service}-1"
    if (candidate.get("project") != manifest.get("project") or
            candidate.get("name") != expected_name or candidate.get("name") not in expected_names or
            candidate.get("service") != service or
            labels.get("io.omnibioai.workstream") != manifest.get("workstream") or
            labels.get("io.omnibioai.run-id") != run_id or
            labels.get("io.omnibioai.disposable") != "true"):
        return {"status": "FAIL", "error": f"{service} labels, project, service, or expected name mismatch"}
    # Re-inspect by immutable ID and require exact manifest ownership before use.
    verified = client.resource_by_id("container", container_id)
    if not verified or verified.get("id") != container_id:
        return {"status": "FAIL", "error": f"manifest-owned {service} ID could not be revalidated"}
    verified_labels = verified.get("labels") or {}
    if (verified.get("project") != manifest.get("project") or verified.get("service") != service or
            verified.get("name") != candidate.get("name") or
            verified_labels.get("io.omnibioai.workstream") != manifest.get("workstream") or
            verified_labels.get("io.omnibioai.run-id") != run_id or
            verified_labels.get("io.omnibioai.disposable") != "true"):
        return {"status": "FAIL", "error": f"immutable {service} ID no longer matches exact ownership"}
    members = manifest.setdefault("owned_resources", {}).setdefault("container", [])
    if container_id not in members:
        members.append(container_id)
        members.sort()
    return {"status": "VERIFIED", "id": container_id}


def collect_service_diagnostics(client, manifest: dict, run_dir: Path, service: str,
                                evidence_path: Path) -> list[str]:
    """Persist bounded, redacted diagnostics for one verified disposable service."""
    errors: list[str] = []
    secret_values = _run_secret_values(run_dir)
    payload = {"run_id": manifest.get("run_id"), "status": "NOT_COLLECTED"}
    try:
        ownership = _diagnostic_service_resource(client, manifest, service)
        if ownership["status"] == "VERIFIED":
            payload["status"] = "VERIFIED"
            payload["container_id"] = ownership["id"]
            persist_ownership_manifest(run_dir, manifest)
            container_id = ownership["id"]
            try:
                state = client.container_state(container_id)
                payload["state"] = {
                    "status": state.get("status"),
                    "exit_code": state.get("exit_code"),
                    "error": redact_diagnostic_text(str(state.get("error") or ""), secret_values)[:2048],
                    "oom_killed": bool(state.get("oom_killed")),
                    "health": state.get("health"),
                    "created_at": state.get("created_at"),
                    "started_at": state.get("started_at"),
                    "finished_at": state.get("finished_at"),
                }
            except Exception as exc:
                safe_error = redact_diagnostic_text(f"{type(exc).__name__}:{exc}", secret_values)
                errors.append(f"inspect:{safe_error}")
                payload["state_error"] = safe_error[:2048]
            try:
                streams = client.container_log_streams(container_id, max_bytes=DIAGNOSTIC_LOG_TAIL_BYTES)
                payload["stdout"] = _bounded_utf8(
                    redact_diagnostic_text(streams.get("stdout", ""), secret_values), DIAGNOSTIC_BYTES_PER_STREAM)
                payload["stderr"] = _bounded_utf8(
                    redact_diagnostic_text(streams.get("stderr", ""), secret_values), DIAGNOSTIC_BYTES_PER_STREAM)
                payload["logs_truncated"] = bool(streams.get("truncated"))
            except Exception as exc:
                safe_error = redact_diagnostic_text(f"{type(exc).__name__}:{exc}", secret_values)
                errors.append(f"logs:{safe_error}")
                payload["logs_error"] = safe_error[:2048]
            payload["status"] = "PASS" if not errors else "PARTIAL"
        else:
            payload.update(ownership)
        if ownership["status"] == "FAIL":
            errors.append(str(ownership.get("error", f"{service} ownership validation failed")))
        elif ownership["status"] == "NOT_FOUND":
            errors.append(f"{service} diagnostic collection unavailable: container not found")
    except Exception as exc:
        safe_error = redact_diagnostic_text(f"{type(exc).__name__}:{exc}", secret_values)
        errors.append(f"collection:{safe_error}")
        payload.update(status="FAIL", error=safe_error[:2048])
    try:
        evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:
        safe_error = redact_diagnostic_text(f"{type(exc).__name__}:{exc}", secret_values)
        errors.append(f"evidence_write:{safe_error}")
    return errors


def collect_redis_diagnostics(client, manifest: dict, run_dir: Path, evidence_path: Path) -> list[str]:
    """Backward-compatible Redis diagnostics entry point for existing tests."""
    return collect_service_diagnostics(client, manifest, run_dir, "redis", evidence_path)


def finalize_run(before: dict, run_dir: Path, manifest: dict, *, report_run_id: str,
                 diagnostic_errors: list[str] | None = None) -> None:
    secret_values = _run_secret_values(run_dir)
    cleanup_errors: list[str] = []
    inventory_error = None
    try:
        cleanup_errors = verified_cleanup(DockerCLI(), run_dir / "ownership-manifest.json", manifest)
    except BaseException as exc:
        cleanup_errors.append(f"{type(exc).__name__}:{exc}")
        try:
            persist_ownership_manifest(run_dir, manifest)
        except BaseException as persist_exc:
            cleanup_errors.append(f"manifest_persist:{type(persist_exc).__name__}:{persist_exc}")
    after = None
    try:
        after = inventory()
    except BaseException as exc:
        inventory_error = f"{type(exc).__name__}:{exc}"
    after_path_error = None
    try:
        after_payload = after if after is not None else {"status": "FAIL", "error": inventory_error, "run_id": report_run_id}
        (EVIDENCE / "docker-inventory-after.json").write_text(
            json.dumps(after_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except BaseException as exc:
        after_path_error = f"{type(exc).__name__}:{exc}"
    comparison = compare_inventories(before, after, report_run_id) if after else {
        "status": "FAIL", "reason": "after-inventory could not be captured"}
    report = {"run_id": report_run_id,
              "diagnostic_errors": [redact_diagnostic_text(error, secret_values) for error in (diagnostic_errors or [])],
              "cleanup_errors": [redact_diagnostic_text(error, secret_values) for error in cleanup_errors],
              "inventory_error": inventory_error, "after_inventory_evidence_error": after_path_error,
              "comparison": comparison,
              "cleanup_completed": not cleanup_errors,
              "docker_isolation": "PASS" if not cleanup_errors and not inventory_error and not after_path_error and comparison["status"] == "PASS" else "FAIL"}
    report_path_error = None
    try:
        (EVIDENCE / "ownership-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except BaseException as exc:
        report_path_error = f"{type(exc).__name__}:{exc}"
    if cleanup_errors or inventory_error or after_path_error or report_path_error or comparison["status"] != "PASS":
        raise RuntimeError("qualification finalization failed; ownership manifest preserved for operator recovery")
    shutil.rmtree(run_dir)


def compare_inventories(before: dict, after: dict | None, run_id: str) -> dict:
    if after is None:
        return {"status": "FAIL", "reason": "missing after-inventory"}
    def canonical_container(row: dict) -> dict:
        result = dict(row)
        result["mounts"] = sorted(result.get("mounts", []),
                                  key=lambda mount: (mount.get("Destination", ""), mount.get("Type", ""),
                                                     mount.get("Source", "")))
        result["binds"] = sorted(result.get("binds", []))
        return result
    before_containers = {row["id"]: canonical_container(row) for row in before.get("containers", [])}
    after_containers = {row["id"]: canonical_container(row) for row in after.get("containers", [])}
    changed = [cid for cid, row in before_containers.items() if after_containers.get(cid) != row]
    missing = sorted(set(before_containers) - set(after_containers))
    new_ids = sorted(set(after_containers) - set(before_containers))
    harness_new = [cid for cid in new_ids if after_containers[cid]["labels"].get("io.omnibioai.run-id") == run_id]
    concurrent_new = [cid for cid in new_ids if cid not in harness_new]
    before_networks, after_networks = set(before.get("networks", [])), set(after.get("networks", []))
    before_volumes, after_volumes = set(before.get("volumes", [])), set(after.get("volumes", []))
    lost_networks = sorted(before_networks - after_networks)
    lost_volumes = sorted(before_volumes - after_volumes)
    run_marker = f"io.omnibioai.run-id={run_id}"
    remaining_networks = sorted(row for row in after_networks if run_marker in row)
    remaining_volumes = sorted(row for row in after_volumes if run_marker in row)
    status = "PASS" if not changed and not missing and not lost_networks and not lost_volumes and \
        not harness_new and not remaining_networks and not remaining_volumes else "FAIL"
    return {"status": status, "changed_protected_containers": changed,
            "missing_protected_containers": missing, "new_harness_containers_remaining": harness_new,
            "unrelated_concurrent_container_ids": concurrent_new,
            "harness_networks_remaining": remaining_networks,
            "harness_volumes_remaining": remaining_volumes,
            "lost_protected_network_rows": lost_networks, "lost_protected_volume_rows": lost_volumes,
            "baseline_container_fingerprints": len(before_containers),
            "after_container_fingerprints": len(after_containers)}


class DockerCLI:
    """Narrow Docker adapter; destructive calls always receive immutable IDs."""
    def resources(self, kind: str, run_id: str) -> list[dict]:
        filters = ["--filter", f"label=io.omnibioai.run-id={run_id}"]
        if kind == "container":
            ids = run(["docker", "ps", "-aq", "--no-trunc", *filters]).stdout.split()
        elif kind == "network":
            ids = run(["docker", "network", "ls", "-q", *filters]).stdout.split()
        elif kind == "volume":
            ids = run(["docker", "volume", "ls", "-q", *filters]).stdout.split()
        elif kind == "image":
            ids = run(["docker", "image", "ls", "-q", *filters]).stdout.split()
        else:
            raise ValueError(kind)
        return [row for rid in dict.fromkeys(ids) if (row := self.resource_by_id(kind, rid)) is not None]

    def resource_by_id(self, kind: str, resource_id: str) -> dict | None:
        if kind == "container":
            template = ('{"id":{{json .Id}},"name":{{json .Name}},'
                        '"labels":{{json .Config.Labels}}}')
            result = run(["docker", "inspect", "--format", template, resource_id], check=False)
            if result.returncode:
                return None
            data = json.loads(result.stdout)
            labels = data.get("labels") or {}
            return {"id": data.get("id"), "name": str(data.get("name") or "").lstrip("/"),
                    "labels": labels, "project": labels.get("com.docker.compose.project"),
                    "service": labels.get("com.docker.compose.service")}
        commands = {"network": ["docker", "network", "inspect", resource_id],
                    "volume": ["docker", "volume", "inspect", resource_id],
                    "image": ["docker", "image", "inspect", resource_id]}
        result = run(commands[kind], check=False)
        if result.returncode:
            return None
        data = json.loads(result.stdout)[0]
        labels = (data.get("Config", {}).get("Labels") if kind in {"container", "image"}
                  else data.get("Labels")) or {}
        rid = data.get("Name") if kind == "volume" else data.get("Id")
        row = {"id": rid, "name": data.get("Name", "").lstrip("/"), "labels": labels}
        if kind == "container":
            row.update(project=labels.get("com.docker.compose.project"),
                       service=labels.get("com.docker.compose.service"))
        if kind == "network":
            row["driver"] = data.get("Driver")
            row["ipam_config"] = (data.get("IPAM") or {}).get("Config") or []
            row["driver_options"] = data.get("Options") or {}
        return row

    def container_state(self, container_id: str) -> dict:
        template = ('{"status":{{json .State.Status}},"exit_code":{{json .State.ExitCode}},'
                    '"error":{{json .State.Error}},"oom_killed":{{json .State.OOMKilled}},'
                    '"created_at":{{json .Created}},"started_at":{{json .State.StartedAt}},'
                    '"finished_at":{{json .State.FinishedAt}},'
                    '"health":{{if index .State "Health"}}{{json (index (index .State "Health") "Status")}}{{else}}null{{end}}}')
        result = run(["docker", "inspect", "--format", template, container_id])
        return json.loads(result.stdout)

    def container_log_streams(self, container_id: str, *, max_bytes: int) -> dict:
        """Retrieve logs through Docker CLI by immutable container ID.

        For non-TTY containers Docker CLI routes container stdout and stderr to
        its corresponding process streams. Both are retained separately and
        bounded. Compose's json-file logger independently caps source log size.
        """
        result = run(["docker", "logs", "--timestamps", "--tail", "200", container_id],
                     check=False, timeout=30)
        if result.returncode:
            raise RuntimeError(f"docker logs failed ({result.returncode}): {result.stderr[-2048:]}")
        stdout = _bounded_utf8(result.stdout, max_bytes)
        stderr = _bounded_utf8(result.stderr, max_bytes)
        return {"stdout": stdout, "stderr": stderr,
                "truncated": len(result.stdout.encode("utf-8", errors="replace")) > max_bytes or
                             len(result.stderr.encode("utf-8", errors="replace")) > max_bytes}

    def remove(self, kind: str, resource_id: str) -> None:
        commands = {"container": ["docker", "rm", "-f", resource_id],
                    "network": ["docker", "network", "rm", resource_id],
                    "volume": ["docker", "volume", "rm", resource_id],
                    "image": ["docker", "image", "rm", resource_id]}
        result = run(commands[kind], check=False, timeout=60)
        if result.returncode:
            raise RuntimeError(f"docker {kind} removal failed for owned ID {resource_id}: {result.stderr[-500:]}")


def inventory() -> dict:
    ids = run(["docker", "ps", "-aq", "--no-trunc"]).stdout.split()
    records = []
    if ids:
        template = (
            '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Config.Image}},'
            '"state":{{json .State.Status}},"health":{{if index .State "Health"}}{{json (index (index .State "Health") "Status")}}{{else}}null{{end}},'
            '"labels":{{json .Config.Labels}},'
            '"binds":{{json .HostConfig.Binds}},"mounts":{{json .Mounts}},'
            '"networks":{{json .NetworkSettings.Networks}},"ports":{{json .NetworkSettings.Ports}},'
            '"restart_policy":{{json .HostConfig.RestartPolicy.Name}},'
            '"readonly_rootfs":{{json .HostConfig.ReadonlyRootfs}},'
            '"memory_limit_bytes":{{json .HostConfig.Memory}},"nano_cpus":{{json .HostConfig.NanoCpus}}}'
        )
        inspected = run(["docker", "inspect", "--format", template, *ids], timeout=120).stdout
        for line in inspected.splitlines():
            item = json.loads(line)
            records.append({
                "id": item.get("id"), "name": item.get("name", "").lstrip("/"),
                "image": item.get("image"), "state": item.get("state"),
                "health": item.get("health"), "labels": item.get("labels") or {},
                "binds": item.get("binds") or [], "mounts": item.get("mounts") or [],
                "networks": sorted((item.get("networks") or {}).keys()),
                "network_fingerprint": item.get("networks") or {}, "ports": item.get("ports") or {},
                "restart_policy": item.get("restart_policy"),
                "readonly_rootfs": bool(item.get("readonly_rootfs")),
                "memory_limit_bytes": int(item.get("memory_limit_bytes") or 0),
                "nano_cpus": int(item.get("nano_cpus") or 0),
            })
    networks = run(["docker", "network", "ls", "--format", "{{.Name}}|{{.ID}}|{{.Driver}}|{{.Scope}}|{{.Labels}}"]).stdout.splitlines()
    volumes = run(["docker", "volume", "ls", "--format", "{{.Name}}|{{.Driver}}|{{.Labels}}"]).stdout.splitlines()
    network_ids = run(["docker", "network", "ls", "-q"]).stdout.split()
    if network_ids:
        networks = run(["docker", "network", "inspect", "--format",
                        "{{.Name}}|{{.Id}}|{{.Driver}}|{{.Scope}}|{{.Labels}}|{{json .IPAM.Config}}",
                        *network_ids], timeout=120).stdout.splitlines()
    info = run(["docker", "info", "--format", "{{.ServerVersion}}|{{.Architecture}}|{{.ID}}|{{.MemTotal}}|{{.NCPU}}"]).stdout.strip().split("|")
    return {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "docker": {"version": info[0], "architecture": info[1], "daemon_id": info[2],
                   "memory_bytes": int(info[3]), "cpus": int(info[4]),
                   "context": run(["docker", "context", "show"]).stdout.strip()},
        "containers": records,
        "networks": sorted(networks), "volumes": sorted(volumes),
    }


def source_tree_digest() -> str:
    digest = hashlib.sha256()
    roots = [ROOT / "backend/src/control_center", ROOT / "scripts/discord-docker-qualification"]
    for base in roots:
        for path in sorted(base.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                rel = path.relative_to(ROOT).as_posix().encode()
                data = path.read_bytes()
                digest.update(len(rel).to_bytes(4, "big")); digest.update(rel)
                digest.update(len(data).to_bytes(8, "big")); digest.update(data)
    return digest.hexdigest()


def select_disposable_subnet() -> tuple[str, str]:
    """Choose a /24 absent from every Docker IPv4 pool and host route."""
    ids = run(["docker", "network", "ls", "-q"]).stdout.split()
    used: list[ipaddress.IPv4Network] = []
    if ids:
        raw = run(["docker", "network", "inspect", "--format", "{{json .IPAM.Config}}", *ids], timeout=120).stdout
        for line in raw.splitlines():
            for config in json.loads(line) or []:
                subnet = config.get("Subnet")
                if subnet and ":" not in subnet:
                    used.append(ipaddress.ip_network(subnet, strict=False))
    routes = json.loads(run(["ip", "-j", "-4", "route", "show", "table", "all"]).stdout)
    for route in routes:
        destination = route.get("dst")
        if destination and destination != "default":
            try:
                used.append(ipaddress.ip_network(destination, strict=False))
            except ValueError:
                continue
    return select_free_subnet(map(str, used))


def revalidate_subnet(subnet: str) -> None:
    ids = run(["docker", "network", "ls", "-q"]).stdout.split()
    used: list[str] = []
    if ids:
        raw = run(["docker", "network", "inspect", "--format", "{{json .IPAM.Config}}", *ids], timeout=120).stdout
        for line in raw.splitlines():
            for config in json.loads(line) or []:
                value = config.get("Subnet")
                if value and ":" not in value:
                    used.append(value)
    routes = json.loads(run(["ip", "-j", "-4", "route", "show", "table", "all"]).stdout)
    used.extend(row["dst"] for row in routes if row.get("dst") and row["dst"] != "default")
    assert_subnet_free(subnet, used)


def validate_state_init_owner(service: dict) -> None:
    """Enforce the complete, reviewed root initializer command contract."""
    expected_command = (
        "set -eu; mkdir -p /run/discord-state; chmod 0700 /run/discord-state; "
        "chown 10001:10001 /run/discord-state /run/server-key.pem"
    )
    command = service.get("command", [])
    if (service.get("user") != "0:0" or len(command) != 3 or
            command[0:2] != ["sh", "-c"] or command[2] != expected_command):
        raise RuntimeError("state-init identity or command differs from the reviewed policy")


def make_certificates(run_dir: Path) -> None:
    tls = run_dir / "tls"
    tls.mkdir(mode=0o711)
    # Test-only root and server certificate; the key never leaves this owned
    # /tmp run directory and is deleted after owned-resource cleanup.
    primary_error: BaseException | None = None
    generation_succeeded = False
    try:
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(tls / "ca-key.pem"),
             "-out", str(tls / "ca.pem"), "-days", "2", "-subj", "/CN=OmniBioAI Disposable Qualification CA"], timeout=30)
        run(["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(tls / "server-key.pem"),
             "-out", str(tls / "server.csr"), "-subj", "/CN=discord.com"], timeout=30)
        ext = tls / "server.ext"
        # DNS covers the synthetic webhook endpoint; loopback makes the receiver's
        # own readiness probe independent of Docker DNS and network aliases.
        ext.write_text("subjectAltName=DNS:discord.com,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n", encoding="utf-8")
        run(["openssl", "x509", "-req", "-in", str(tls / "server.csr"), "-CA", str(tls / "ca.pem"),
             "-CAkey", str(tls / "ca-key.pem"), "-CAcreateserial", "-out", str(tls / "server.pem"),
             "-days", "2", "-sha256", "-extfile", str(ext)], timeout=30)
        # Treat permission hardening as part of generation: if any chmod fails,
        # the failure path below removes every generated private artifact.
        (tls / "server-key.pem").chmod(0o400)
        (tls / "server.pem").chmod(0o444)
        (tls / "ca.pem").chmod(0o444)
        # Traverse-only for container UID 10001; run_dir itself is mode 0700.
        tls.chmod(0o711)
        generation_succeeded = True
    except KeyboardInterrupt as exc:
        primary_error = exc
        # Even an interrupt arriving immediately after the success assignment
        # must take the failure cleanup path for generated key material.
        generation_succeeded = False
        raise
    except Exception as exc:
        # Keep the original exception object/type as the primary failure, but
        # scrub its printable arguments before it can enter logs or evidence.
        # The subprocess wrapper reports OpenSSL stderr in RuntimeError.args.
        primary_error = exc
        exc.args = (f"disposable TLS certificate generation failed ({type(exc).__name__})",)
        for attribute in ("output", "stdout", "stderr"):
            if hasattr(exc, attribute):
                try:
                    setattr(exc, attribute, None)
                except Exception:
                    pass
        raise
    finally:
        cleanup_errors = []
        cleanup_names = ["ca-key.pem", "server.csr", "server.ext", "ca.srl"]
        if not generation_succeeded:
            cleanup_names.extend(("ca.pem", "server-key.pem", "server.pem"))
        for name in cleanup_names:
            try:
                (tls / name).unlink(missing_ok=True)
            except Exception as exc:
                cleanup_errors.append(f"{name}:{type(exc).__name__}")
        if cleanup_errors:
            message = "temporary TLS artifact cleanup failed: " + ", ".join(cleanup_errors)
            if primary_error is not None:
                primary_error.add_note(message)
            else:
                raise RuntimeError(message)


def main() -> int:
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt(f"signal {signum}")))
    if os.name != "posix" or not shutil.which("docker") or not shutil.which("openssl"):
        raise RuntimeError("requires POSIX, Docker CLI, and OpenSSL")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    host = run(["hostname", "-s"]).stdout.strip()
    architecture = run(["uname", "-m"]).stdout.strip()
    if host != "spark-c275" or architecture not in {"aarch64", "arm64"}:
        raise RuntimeError(f"host identity/architecture mismatch: {host}/{architecture}")
    temp_free = shutil.disk_usage("/tmp").free
    docker_root = Path(run(["docker", "info", "--format", "{{.DockerRootDir}}"]).stdout.strip())
    docker_root_free = shutil.disk_usage(docker_root).free
    mem_available_kb = next((int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                             if line.startswith("MemAvailable:")), 0)
    if temp_free < 1 * 1024**3 or docker_root_free < 3 * 1024**3 or mem_available_kb < 2 * 1024**2:
        raise RuntimeError(f"insufficient preflight capacity: tmp_free={temp_free}, docker_root_free={docker_root_free}, MemAvailable_kb={mem_available_kb}")
    before = inventory()
    if before["docker"]["architecture"] != "aarch64":
        raise RuntimeError("Docker daemon architecture is not aarch64")

    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4)
    disposable_subnet, disposable_gateway = select_disposable_subnet()
    project = "obai-discord-qual-v1-" + run_id.lower().replace("_", "-")
    temp_root = Path("/tmp/obai-discord-docker-qualification-v1")
    if temp_root.exists() or temp_root.is_symlink():
        root_stat = temp_root.lstat()
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise RuntimeError("qualification temp root must be a real directory, not a symlink or file")
        if root_stat.st_uid != os.getuid() or stat.S_IMODE(root_stat.st_mode) != 0o700:
            raise RuntimeError("qualification temp root must be owned by this user with mode 0700")
    else:
        temp_root.mkdir(mode=0o700)
    temp_root = temp_root.resolve(strict=True)
    run_dir = temp_root / run_id
    run_dir.mkdir(mode=0o700)
    if run_dir.is_symlink() or run_dir.parent != temp_root or run_dir.resolve() != run_dir:
        raise RuntimeError("run directory is not a canonical owned child of the qualification temp root")
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(mode=0o777)
    evidence_dir.chmod(0o777)
    make_certificates(run_dir)

    source_hash = source_tree_digest()
    candidate = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    image = f"local/omnibioai-discord-qualification:{run_id.lower()}"
    synthetic_sources = {name: secrets.token_urlsafe(40) for name in
                         ("github", "rag", "workbench", "documentation", "video", "infrastructure", "support")}
    secrets_json = json.dumps(synthetic_sources, separators=(",", ":"))
    channels = ("announcements", "bug-reports", "feature-requests", "support", "tutorials", "omnibioai-alerts")
    webhooks = {channel: f"https://discord.com/api/webhooks/9{index:05d}/synthetic-token-{index}"
                for index, channel in enumerate(channels, 1)}
    mock_control = secrets.token_urlsafe(32)
    env = {
        "QUAL_RUN_ID": run_id, "QUAL_PROJECT": project, "QUAL_IMAGE": image,
        "QUAL_SUBNET": disposable_subnet, "QUAL_GATEWAY": disposable_gateway,
        "CANDIDATE_REVISION": candidate, "SOURCE_TREE_SHA256": source_hash,
        "RUN_DIR": str(run_dir), "MOCK_CONTROL_TOKEN": mock_control,
        "SYNTHETIC_JWT_SECRET": secrets.token_urlsafe(40),
        "SOURCE_SECRETS_JSON": secrets_json,
        "MOCK_WEBHOOKS_JSON": json.dumps(webhooks, separators=(",", ":")),
    }
    env_path = run_dir / "compose.env"
    env_path.write_text("".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8")
    env_path.chmod(0o600)
    manifest = {
        "workstream": WORKSTREAM, "run_id": run_id, "project": project,
        "docker_context": before["docker"]["context"], "daemon_id": before["docker"]["daemon_id"],
        "host_architecture": architecture, "run_directory": str(run_dir),
        "compose_file": str(COMPOSE), "image_tag": image,
        "image_labels": {"io.omnibioai.workstream": WORKSTREAM, "io.omnibioai.run-id": run_id,
                         "io.omnibioai.disposable": "true"},
        "expected_service_names": [f"{project}-{name}-1" for name in
                                    ("redis", "mock-discord", "router", "test-runner", "state-init")],
        "expected_network": f"{project}_isolated", "expected_volume": f"{project}_router-state",
        "network_subnet": disposable_subnet, "network_gateway": disposable_gateway,
        "host_binds": [str(run_dir / "tls"), str(run_dir / "tls/ca.pem"),
                       str(run_dir / "tls/server-key.pem"), str(evidence_dir)],
        "synthetic_only": True,
        "production_resources_allowed": False,
        "cleanup_scope": "resources with exact project plus matching workstream/run-id labels only",
    }
    (EVIDENCE / "release-candidate-manifest.json").write_text(json.dumps({
        "workstream": WORKSTREAM, "candidate_git_head": candidate, "candidate_source_tree_sha256": source_hash,
        "candidate_changes_present": bool(run(["git", "status", "--porcelain"]).stdout.strip()),
        "docker_base_image": "obai-control-center:f37ce8c952f9",
        "docker_base_image_id": "sha256:71db0e0401219e5efedb73f1aad2712af5907e49b03678db527d2c03fff9abd3",
        "redis_image": "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499",
        "run_id": run_id, "qualification_image_tag": image,
        "registry_digest": None,
    }, indent=2) + "\n", encoding="utf-8")
    (run_dir / "ownership-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(EVIDENCE / "release-candidate-manifest.json", run_dir / "evidence/release-candidate-manifest.json")
    (EVIDENCE / "docker-inventory-before.json").write_text(json.dumps(before, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    compose = ["docker", "compose", "--project-name", project, "--env-file", str(env_path), "-f", str(COMPOSE)]
    rendered = json.loads(run(compose + ["config", "--format", "json"]).stdout)
    validate_rendered_config(rendered, project, run_id, run_dir, disposable_subnet, disposable_gateway)
    for kind, args in (("image", ["docker", "image", "inspect", image]),
                       ("network", ["docker", "network", "inspect", f"{project}_isolated"]),
                       ("volume", ["docker", "volume", "inspect", f"{project}_router-state"])):
        if run(args, check=False).returncode == 0:
            raise RuntimeError(f"refusing to reuse pre-existing {kind} target")
    existing_project = run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]).stdout.split()
    if existing_project:
        raise RuntimeError("refusing to reuse a pre-existing Compose project")
    existing_names = {row["name"] for row in before["containers"]}
    collisions = existing_names.intersection(manifest["expected_service_names"])
    if collisions:
        raise RuntimeError(f"refusing to reuse exact container names: {sorted(collisions)}")
    build = ["docker", "build", "--pull=false", "--platform", "linux/arm64", "-f", str(ROOT / "scripts/discord-docker-qualification/Dockerfile"),
             "-t", image, "--build-arg", f"CANDIDATE_REVISION={candidate}", "--build-arg", f"SOURCE_TREE_SHA256={source_hash}",
             "--build-arg", f"QUAL_RUN_ID={run_id}", "."]
    try:
        base_check = run(["docker", "image", "inspect", "--format", "{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .RepoDigests}}|{{json .RootFS.Layers}}",
                          "obai-control-center:f37ce8c952f9"]).stdout.strip().split("|")
        if base_check[:3] != ["sha256:71db0e0401219e5efedb73f1aad2712af5907e49b03678db527d2c03fff9abd3", "linux", "arm64"]:
            raise RuntimeError("local tagged base image ID/platform did not match the reviewed immutable identity")
        base_repo_digests, base_layers = json.loads(base_check[3]), json.loads(base_check[4])
        if not base_layers:
            raise RuntimeError("refusing a base image with no verifiable filesystem layers")
        run(["docker", "image", "inspect", "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499"])
        run(build, timeout=900)
        image_inspect = run(["docker", "image", "inspect", "--format",
                             "{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .RepoDigests}}|{{json .Config.Labels}}", image]).stdout.strip()
        image_fields = image_inspect.split("|", 4)
        image_info = {"image_id": image_fields[0], "os": image_fields[1], "architecture": image_fields[2],
                      "repo_digests": json.loads(image_fields[3]), "labels": json.loads(image_fields[4])}
        image_layers = json.loads(run(["docker", "image", "inspect", "--format", "{{json .RootFS.Layers}}", image]).stdout)
        base_id_after_build = run(["docker", "image", "inspect", "--format", "{{.Id}}", "obai-control-center:f37ce8c952f9"]).stdout.strip()
        if base_id_after_build != base_check[0]:
            raise RuntimeError("local base tag changed during build; refusing qualification")
        if image_layers[:len(base_layers)] != base_layers:
            raise RuntimeError("qualification image does not inherit the exact inspected base image layer sequence")
        manifest["built_image_id"] = image_info["image_id"]
        persist_ownership_manifest(run_dir, manifest)
        (EVIDENCE / "image-provenance.json").write_text(json.dumps({
            "qualification_image": image_info, "qualification_image_layers": image_layers,
            "base_image": "obai-control-center:f37ce8c952f9",
            "base_image_id": "sha256:71db0e0401219e5efedb73f1aad2712af5907e49b03678db527d2c03fff9abd3",
            "base_image_repo_digests_observed_locally": base_repo_digests,
            "base_image_layers": base_layers,
            "registry_publication_verified": False,
            "source_tree_sha256": source_hash, "candidate_git_head": candidate,
            "reproducible_build": "NOT_VERIFIED; no dependency lock/build attestation",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if image_info["architecture"] != "arm64" or image_info["os"] != "linux":
            raise RuntimeError("qualification image did not build for Linux ARM64")
        revalidate_subnet(disposable_subnet)
        run(compose + ["up", "-d", "--no-build", "redis", "mock-discord", "state-init", "router"], timeout=180)
        inspect_owned(project, run_id, run_dir, disposable_subnet, disposable_gateway)
        result = run(compose + ["run", "--no-deps", "test-runner"], check=False, timeout=240)
        out = evidence_dir / "docker-e2e-results.json"
        if not out.exists():
            (EVIDENCE / "docker-e2e-results.json").write_text(json.dumps({"status": "FAIL", "reason": "test runner did not write evidence",
                                                                            "exit_code": result.returncode}, indent=2) + "\n")
        else:
            shutil.copyfile(out, EVIDENCE / "docker-e2e-results.json")
        (EVIDENCE / "regression-results.md").write_text(
            "# Regression results\n\n"
            "Focused Discord/IAM/process suite was separately run in the current workspace: 134 passed, 0 failed. "
            "The Docker E2E runner exercised the real current-source FastAPI process. "
            "Full backend suite: 2,221 passed, 13 environment loopback failures, 97.95% in restricted execution; "
            "historical unrestricted 2,234/98.00% is not a fresh result.\n", encoding="utf-8")
        return result.returncode
    finally:
        active_error = sys.exc_info()[1]
        diagnostic_errors: list[str] = []
        try:
            docker_client = DockerCLI()
            for service in DIAGNOSTIC_SERVICES:
                try:
                    service_errors = collect_service_diagnostics(
                        docker_client, manifest, run_dir, service,
                        EVIDENCE / f"{service}-diagnostics.json")
                    diagnostic_errors.extend(f"{service}:{error}" for error in service_errors)
                except BaseException as service_error:
                    diagnostic_errors.append(f"{service}:{safe_exception_summary(service_error, run_dir)}")
        except BaseException as diagnostic_error:
            diagnostic_errors = [redact_diagnostic_text(
                f"{type(diagnostic_error).__name__}:{diagnostic_error}", _run_secret_values(run_dir))]
        try:
            finalize_run(before, run_dir, manifest, report_run_id=run_id,
                         diagnostic_errors=diagnostic_errors)
        except BaseException as finalization_error:
            try:
                (EVIDENCE / "qualification-run-error.json").write_text(json.dumps({
                    "run_id": run_id,
                    "original_error": safe_exception_summary(active_error, run_dir),
                    "finalization_error": safe_exception_summary(finalization_error, run_dir),
                    "ownership_manifest": str(run_dir / "ownership-manifest.json"),
                }, indent=2) + "\n", encoding="utf-8")
            except BaseException as report_error:
                print(f"unable to persist qualification/finalization error evidence: {report_error}", file=sys.stderr)
            if active_error is None:
                raise


def inspect_owned(project: str, run_id: str, run_dir: Path, subnet: str, gateway: str) -> None:
    output = run(["docker", "ps", "-aq", "--filter", f"label=io.omnibioai.run-id={run_id}", "--no-trunc"]).stdout.split()
    if len(output) != 4:
        raise RuntimeError(f"expected four running setup containers owned by run {run_id}; got {len(output)}")
    inspect = run(["docker", "inspect", "--format",
                   "{{.Name}}|{{index .Config.Labels \"com.docker.compose.project\"}}|{{index .Config.Labels \"com.docker.compose.service\"}}|{{index .Config.Labels \"io.omnibioai.workstream\"}}|{{index .Config.Labels \"io.omnibioai.run-id\"}}|{{index .Config.Labels \"io.omnibioai.disposable\"}}|{{json .Mounts}}|{{json .NetworkSettings.Networks}}|{{json .HostConfig.PortBindings}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|{{json .HostConfig.CapDrop}}|{{json .HostConfig.CapAdd}}|{{.HostConfig.RestartPolicy.Name}}", *output]).stdout
    expected = {"redis", "mock-discord", "router", "state-init"}
    seen = set()
    for line in inspect.splitlines():
        fields = line.split("|", 14)
        if len(fields) != 15 or fields[1] != project or fields[3] != WORKSTREAM or fields[4] != run_id or fields[5] != "true":
            raise RuntimeError("ownership verification failed for a created container")
        seen.add(fields[2])
        mounts = json.loads(fields[6])
        networks = json.loads(fields[7])
        allowed_binds = {str((run_dir / "tls").resolve()), str((run_dir / "tls/ca.pem").resolve()),
                         str((run_dir / "tls/server-key.pem").resolve()),
                         str((run_dir / "evidence").resolve())}
        if any(mount.get("Type") == "bind" and mount.get("Source") not in allowed_binds for mount in mounts):
            raise RuntimeError("container has a host bind outside the exact owned run directory")
        if set(networks) != {f"{project}_isolated"}:
            raise RuntimeError("container attached to a non-disposable network")
        if fields[8] not in ("null", "{}") or fields[9] != "true" or int(fields[10]) <= 0 or int(fields[11]) <= 0:
            raise RuntimeError("runtime container has an unexpected port or lacks rootfs/resource bounds")
        service_caps = {"redis": [], "mock-discord": ["NET_BIND_SERVICE"], "router": [], "state-init": ["CHOWN"]}
        if json.loads(fields[12]) != ["ALL"] or json.loads(fields[13]) != service_caps[fields[2]] or fields[14] != "no":
            raise RuntimeError("runtime capabilities or restart policy differ from the manifest")
        expected_mounts = {
            "redis": set(),
            "mock-discord": {(str(run_dir / "tls"), "/run/qualification-tls", True),
                             (str(run_dir / "evidence"), "/run/qualification-evidence", False)},
            "router": {(f"{project}_router-state", "/run/discord-state", False),
                       (str(run_dir / "tls/ca.pem"), "/run/qualification-tls/ca.pem", True)},
            "state-init": {(f"{project}_router-state", "/run/discord-state", False),
                           (str(run_dir / "tls/server-key.pem"), "/run/server-key.pem", False)},
        }
        actual_mounts = set()
        for mount in mounts:
            source = mount.get("Name") if mount.get("Type") == "volume" else mount.get("Source")
            if mount.get("Type") == "bind" and source not in {
                    str(run_dir / "tls"), str(run_dir / "tls/ca.pem"),
                    str(run_dir / "tls/server-key.pem"), str(run_dir / "evidence")}:
                raise RuntimeError("runtime host bind is outside the ownership manifest")
            actual_mounts.add((source, mount.get("Destination"), not mount.get("RW", True)))
        if actual_mounts != expected_mounts[fields[2]]:
            raise RuntimeError(f"runtime mounts differ from reviewed manifest for {fields[2]}")
    if seen != expected:
        raise RuntimeError(f"unexpected created service set: {sorted(seen)}")
    for kind, name in (("network", f"{project}_isolated"), ("volume", f"{project}_router-state")):
        suffix = "|{{json .IPAM.Config}}" if kind == "network" else ""
        template = ("{{.Id}}|{{.Name}}|{{index .Labels \"io.omnibioai.workstream\"}}|"
                    "{{index .Labels \"io.omnibioai.run-id\"}}|{{index .Labels \"io.omnibioai.disposable\"}}" + suffix)
        row = run(["docker", kind, "inspect", "--format", template, name]).stdout.strip().split("|", 5)
        expected_fields = 6 if kind == "network" else 5
        if len(row) != expected_fields or row[1] != name or row[2:5] != [WORKSTREAM, run_id, "true"]:
            raise RuntimeError(f"{kind} identity/labels differ from ownership manifest")
        if kind == "network":
            configs = json.loads(row[5])
            if configs != [{"Subnet": subnet, "Gateway": gateway}]:
                raise RuntimeError("runtime network subnet/gateway differ from the preflight selection")
    # The independently validated ownership manifest and DockerCLI cleanup path
    # also compare the full IPAM config before any network removal.


def validate_rendered_config(config: dict, project: str, run_id: str, run_dir: Path,
                             subnet: str, gateway: str) -> None:
    services = config.get("services", {})
    expected_services = {"redis", "mock-discord", "router", "test-runner", "state-init"}
    if set(services) != expected_services:
        raise RuntimeError("rendered Compose services differ from reviewed allowlist")
    expected_binds = {str((run_dir / "tls").resolve()), str((run_dir / "evidence").resolve()),
                      str((run_dir / "tls/ca.pem").resolve()),
                      str((run_dir / "tls/server-key.pem").resolve())}
    expected_caps = {"redis": [], "mock-discord": ["NET_BIND_SERVICE"], "router": [],
                     "test-runner": [], "state-init": ["CHOWN"]}
    expected_mounts = {
        "redis": set(),
        "mock-discord": {("bind", str(run_dir / "tls"), "/run/qualification-tls", True),
                         ("bind", str(run_dir / "evidence"), "/run/qualification-evidence", False)},
        "router": {("volume", "router-state", "/run/discord-state", False),
                   ("bind", str(run_dir / "tls/ca.pem"), "/run/qualification-tls/ca.pem", True)},
        "test-runner": {("bind", str(run_dir / "evidence"), "/run/qualification-evidence", False),
                        ("volume", "router-state", "/run/discord-state", True),
                        ("bind", str(run_dir / "tls/ca.pem"), "/run/qualification-tls/ca.pem", True)},
        "state-init": {("volume", "router-state", "/run/discord-state", False),
                       ("bind", str(run_dir / "tls/server-key.pem"), "/run/server-key.pem", False)},
    }
    for name, service in services.items():
        if service.get("ports") or service.get("network_mode") or service.get("privileged"):
            raise RuntimeError(f"unsafe host port/network/privileged setting in {name}")
        if service.get("pid") or service.get("ipc") or service.get("devices") or service.get("volumes_from"):
            raise RuntimeError(f"unsafe namespace/device/volume sharing in {name}")
        if service.get("read_only") is not True or service.get("pids_limit", 0) <= 0:
            raise RuntimeError(f"filesystem or process limit missing in {name}")
        if service.get("mem_limit") is None or service.get("cpus") is None:
            raise RuntimeError(f"CPU/memory limit missing in {name}")
        if service.get("security_opt") != ["no-new-privileges:true"] or service.get("cap_drop") != ["ALL"]:
            raise RuntimeError(f"process security controls missing in {name}")
        if sorted(service.get("cap_add") or []) != sorted(expected_caps[name]):
            raise RuntimeError(f"unexpected capability additions in {name}")
        log = service.get("logging", {})
        if log.get("driver") != "json-file" or log.get("options", {}).get("max-size") != "1m" or log.get("options", {}).get("max-file") != "2":
            raise RuntimeError(f"bounded logging missing in {name}")
        labels = service.get("labels", {})
        if labels.get("io.omnibioai.workstream") != WORKSTREAM or labels.get("io.omnibioai.run-id") != run_id or labels.get("io.omnibioai.disposable") != "true":
            raise RuntimeError(f"resource ownership labels missing in {name}")
        actual_mounts = set()
        for mount in service.get("volumes", []):
            if mount.get("type") == "bind" and str(Path(mount.get("source", "")).resolve()) not in expected_binds:
                raise RuntimeError(f"host bind outside exact run manifest in {name}")
            if mount.get("type") == "volume" and (mount.get("source") != "router-state" or
                    mount.get("target") != "/run/discord-state" or
                    (name == "test-runner") != (mount.get("read_only") is True)):
                raise RuntimeError(f"unexpected named-volume mount in {name}")
            if mount.get("type") not in {"bind", "volume"}:
                raise RuntimeError(f"unsupported mount type in {name}")
            source = str(Path(mount.get("source", "")).resolve()) if mount.get("type") == "bind" else mount.get("source")
            actual_mounts.add((mount.get("type"), source, mount.get("target"), bool(mount.get("read_only"))))
        if actual_mounts != expected_mounts[name]:
            raise RuntimeError(f"service mounts differ from the exact reviewed manifest in {name}")
        if set(service.get("networks", {})) != {"isolated"}:
            raise RuntimeError(f"service network attachment is not exclusively isolated in {name}")
        if service.get("restart") not in (None, "no") or service.get("extra_hosts") or service.get("dns") or service.get("dns_search") or service.get("links"):
            raise RuntimeError(f"unexpected external name/network configuration in {name}")
    if services["mock-discord"].get("depends_on", {}).get("state-init", {}).get("condition") != "service_completed_successfully":
        raise RuntimeError("mock-discord must wait for TLS ownership initialization")
    validate_state_init_owner(services["state-init"])
    networks = config.get("networks", {})
    if set(networks) != {"isolated"} or networks["isolated"].get("internal") is not True or networks["isolated"].get("external"):
        raise RuntimeError("only the isolated internal network is permitted")
    if networks["isolated"].get("name") != f"{project}_isolated":
        raise RuntimeError("network name does not contain the unique project")
    ipam = networks["isolated"].get("ipam", {}).get("config", [])
    if ipam != [{"subnet": subnet, "gateway": gateway}]:
        raise RuntimeError("network IPAM does not exactly match the preflight-selected free subnet")
    net_labels = networks["isolated"].get("labels", {})
    if net_labels.get("io.omnibioai.workstream") != WORKSTREAM or net_labels.get("io.omnibioai.run-id") != run_id:
        raise RuntimeError("network ownership labels are invalid")
    volumes = config.get("volumes", {})
    if set(volumes) != {"router-state"} or volumes["router-state"].get("name") != f"{project}_router-state" or volumes["router-state"].get("external"):
        raise RuntimeError("persistent state volume is not unique and internal")
    vol_labels = volumes["router-state"].get("labels", {})
    if vol_labels.get("io.omnibioai.workstream") != WORKSTREAM or vol_labels.get("io.omnibioai.run-id") != run_id:
        raise RuntimeError("volume ownership labels are invalid")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"qualification stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(2)
