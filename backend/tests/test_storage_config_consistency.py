"""The host collector's conf and the API's control_center.yaml describe the same targets."""
from __future__ import annotations

import importlib.util
import shlex
from pathlib import Path

import pytest

from control_center.api.storage_telemetry import load_targets

REPO = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("storage_host_collector_conf", REPO / "ops/storage-telemetry/collect-storage-telemetry.py")
assert SPEC and SPEC.loader
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def conf_values() -> dict[str, str]:
    values = {}
    for line in (REPO / "ops/storage-telemetry/storage-telemetry.conf.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key] = shlex.split(value)[0]
    return values


@pytest.fixture
def host_conf(monkeypatch):
    for key, value in conf_values().items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("name", ("control_center.yaml", "control_center.example.yaml"))
def test_repository_configs_load_every_storage_target(name):
    # load_targets returns [] on any invalid target, which would silently empty the dashboard.
    roles = [target.role for target in load_targets(REPO / "config" / name)]
    assert roles == ["root", "backup", "archive", "data2tb", "archive2tb-b", "archive-pool", "primary"]


def test_host_conf_matches_the_api_configuration(host_conf):
    targets = load_targets(REPO / "config/control_center.yaml")
    filesystems = {(t.role, t.host_path, t.expected_filesystem_uuid) for t in targets if t.kind == "filesystem" and t.mount}
    pools = {(t.role, t.host_path, tuple(t.branches)) for t in targets if t.kind == "mergerfs"}
    assert set(collector.target_list()) == filesystems
    assert {(role, path, tuple(branches)) for role, path, branches in collector.pool_list()} == pools
    smart_roles = {role for role, _uuid in collector.disk_list()}
    assert smart_roles == {role for role, _path, _uuid in filesystems}
    assert dict(collector.disk_list()) == {role: uuid for role, _path, uuid in filesystems}
    # The replaced primary disk is config-only: never mounted, measured or queried.
    assert "primary" not in smart_roles | {role for role, *_ in collector.target_list()}
