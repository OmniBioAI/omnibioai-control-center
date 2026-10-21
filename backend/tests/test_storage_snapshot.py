from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from control_center.api.storage_snapshot import MAX_AGE_SECONDS, ROLES, read_snapshot


def signed_snapshot(path, *, observed_at=None, archive_complete=True):
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )).decode()
    metrics = {}
    for role in ROLES:
        metrics[role] = {
            "status": "AVAILABLE", "filesystem": "fuse.mergerfs" if role == "archive-pool" else "exfat" if role == "archive-member-b" else "ext4",
            "device_fingerprint": ("a" if role == "primary" else "b") * 64,
            "mount_mode": "READ_WRITE", "expected_mode": ("READ_WRITE" if role == "archive-writable" else "READ_ONLY") if role.startswith("archive-") and role != "archive-pool" else "UNKNOWN",
            "total_bytes": 1000, "used_bytes": 400, "available_bytes": 500,
        }
    if not archive_complete:
        metrics["archive-pool"].update(status="INVALID", filesystem=None, device_fingerprint=None,
                                        mount_mode="UNKNOWN", total_bytes=None, used_bytes=None, available_bytes=None)
    payload = {
        "schema_version": 1,
        "observed_at": (observed_at or datetime.now(timezone.utc)).isoformat(),
        "collector_status": "AVAILABLE" if archive_complete else "PARTIAL",
        "metrics": metrics,
        "archive_complete": archive_complete,
        "archive_policy": {"create_policy": "ff", "min_free_bytes": 10737418240,
                           "min_free_policy_status": "CONFIGURED", "dependency_count": 2},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    path.write_text(json.dumps({"payload": payload, "signature": base64.b64encode(private.sign(canonical)).decode()}))
    path.chmod(0o444)
    return public, payload, private


def test_signed_snapshot_passes_and_has_only_current_allowlisted_metrics(tmp_path):
    path = tmp_path / "snapshot.json"
    public, _, _ = signed_snapshot(path)
    result = read_snapshot(path, public_key=public)
    assert result is not None
    assert set(result.metrics) == ROLES
    assert result.metrics["primary"].total_bytes == 1000


def test_stale_signed_snapshot_fails_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    public, _, _ = signed_snapshot(path, observed_at=datetime.now(timezone.utc) - timedelta(seconds=MAX_AGE_SECONDS + 10))
    assert read_snapshot(path, public_key=public) is None


def test_tampered_snapshot_and_wrong_key_fail_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    public, _, private = signed_snapshot(path)
    other = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )).decode()
    assert read_snapshot(path, public_key=public) is not None
    assert read_snapshot(path, public_key=other) is None
    envelope = json.loads(path.read_text())
    envelope["payload"]["metrics"]["primary"]["total_bytes"] = 999999
    path.chmod(0o600)
    path.write_text(json.dumps(envelope))
    path.chmod(0o444)
    assert read_snapshot(path, public_key=public) is None


def test_signed_but_malformed_schema_fails_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    public, payload, private = signed_snapshot(path)
    payload["unexpected"] = "must reject"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    envelope = {"payload": payload, "signature": base64.b64encode(private.sign(canonical)).decode()}
    path.chmod(0o600)
    path.write_text(json.dumps(envelope))
    path.chmod(0o444)
    assert read_snapshot(path, public_key=public) is None


def test_incomplete_archive_cannot_claim_pool_capacity(tmp_path):
    path = tmp_path / "snapshot.json"
    public, payload, private = signed_snapshot(path, archive_complete=False)
    result = read_snapshot(path, public_key=public)
    assert result is not None
    assert result.metrics["archive-pool"].total_bytes is None
    payload["metrics"]["archive-pool"]["status"] = "AVAILABLE"
    payload["metrics"]["archive-pool"]["filesystem"] = "fuse.mergerfs"
    payload["metrics"]["archive-pool"]["device_fingerprint"] = "c" * 64
    payload["metrics"]["archive-pool"].update(total_bytes=1000, used_bytes=400, available_bytes=500)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    envelope = {"payload": payload, "signature": base64.b64encode(private.sign(canonical)).decode()}
    path.chmod(0o600)
    path.write_text(json.dumps(envelope))
    path.chmod(0o444)
    assert read_snapshot(path, public_key=public) is None


def test_group_or_world_writable_snapshot_fails_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    public, _, _ = signed_snapshot(path)
    for mode in (0o644, 0o466):
        path.chmod(mode)
        assert read_snapshot(path, public_key=public) is None


def test_snapshot_size_limit_fails_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    public, _, _ = signed_snapshot(path)
    path.chmod(0o600)
    path.write_text(" " * 65537)
    path.chmod(0o444)
    assert read_snapshot(path, public_key=public) is None
