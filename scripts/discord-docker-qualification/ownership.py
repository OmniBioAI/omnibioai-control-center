"""Label-verified, idempotent disposable resource cleanup primitives."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

LABEL_WORKSTREAM = "io.omnibioai.workstream"
LABEL_RUN = "io.omnibioai.run-id"
LABEL_DISPOSABLE = "io.omnibioai.disposable"


class DockerResources(Protocol):
    def resources(self, kind: str, run_id: str) -> list[dict]: ...
    def resource_by_id(self, kind: str, resource_id: str) -> dict | None: ...
    def remove(self, kind: str, resource_id: str) -> None: ...


def persist_manifest(path: Path, manifest: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def verified_cleanup(client: DockerResources, manifest_path: Path, manifest: dict) -> list[str]:
    """Discover only exact run-labeled objects, persist IDs, then remove by ID.

    Missing objects are idempotent. Any label/project/name mismatch aborts before
    the first removal. Container IDs include compose-run one-offs. Networks and
    volumes are handled individually; project names are never cleanup authority.
    """
    run_id, project = manifest["run_id"], manifest["project"]
    expected_labels = {LABEL_WORKSTREAM: manifest["workstream"], LABEL_RUN: run_id,
                       LABEL_DISPOSABLE: "true"}
    current = {kind: client.resources(kind, run_id) for kind in ("container", "network", "volume", "image")}
    members = manifest.setdefault("owned_resources", {})
    errors: list[str] = []

    def validate(kind: str, row: dict, rid: str) -> None:
        labels = row.get("labels") or {}
        if str(row.get("id", "")) != rid or labels.get(LABEL_WORKSTREAM) != expected_labels[LABEL_WORKSTREAM] or \
                labels.get(LABEL_RUN) != run_id or labels.get(LABEL_DISPOSABLE) != "true":
            raise RuntimeError(f"refusing cleanup of unowned or ambiguously labeled {kind}")
        if kind == "container":
            if row.get("project") != project:
                raise RuntimeError("refusing cleanup of a container outside the exact Compose project")
            if row.get("service") not in {"redis", "mock-discord", "router", "state-init", "test-runner"}:
                raise RuntimeError("refusing cleanup of unknown compose service")
        if kind == "network" and (row.get("name") != manifest["expected_network"] or row.get("driver") != "bridge" or
                                    row.get("ipam_config") != [{"Subnet": manifest.get("network_subnet"),
                                                                "Gateway": manifest.get("network_gateway")}] or
                                    row.get("driver_options") not in ({}, None)):
            raise RuntimeError("refusing cleanup of unexpected network")
        if kind == "volume" and row.get("name") != manifest["expected_volume"]:
            raise RuntimeError("refusing cleanup of unexpected volume")
        if kind == "image" and rid != manifest.get("built_image_id"):
            raise RuntimeError("refusing cleanup of image not recorded as built by this run")

    for kind, rows in current.items():
        known = set(members.get(kind, []))
        for row in rows:
            rid = str(row.get("id", ""))
            validate(kind, row, rid)
            known.add(rid)
        members[kind] = sorted(known)
    persist_manifest(manifest_path, manifest)
    targets: list[tuple[str, str]] = []
    # Two-phase preflight: validate the complete target set before the first
    # destructive operation, including IDs retained from interrupted cleanup.
    for kind in ("container", "network", "volume", "image"):
        for rid in members.get(kind, []):
            row = client.resource_by_id(kind, rid)
            if row is None:
                continue
            validate(kind, row, rid)
            targets.append((kind, rid))
    for kind, rid in targets:
        # IDs and complete ownership attributes were checked in the preflight.
        # The immutable ID prevents a name reuse from redirecting removal.
        try:
            client.remove(kind, rid)
        except Exception as exc:  # retain manifest so an operator can inspect/retry
            errors.append(f"{kind}:{rid}:{type(exc).__name__}:{exc}")
    return errors
