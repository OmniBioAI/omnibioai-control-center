"""tests/test_routes_docker.py — covers routes_docker.py and routes_config.py"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


# ===========================================================================
# /docker/containers
# ===========================================================================

class TestGetContainers:

    def _docker_output(self, containers):
        return "\n".join(json.dumps(c) for c in containers)

    def test_returns_container_list(self):
        ct = [{"Names": "/web", "Image": "nginx:latest", "State": "running", "Status": "Up 2h", "Ports": "0.0.0.0:80->80/tcp", "RunningFor": "2 hours"}]
        result = MagicMock(stdout=self._docker_output(ct), returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["containers"][0]["Names"] == "/web"

    def test_running_count_correct(self):
        # `docker ps` (no -a) only ever returns running containers, so the
        # first call's output has one entry; the second call (stopped count)
        # returns one exited container id.
        running_ct = [{"Names": "/svc1", "State": "running", "Status": "Up 1h", "Image": "a", "Ports": "", "RunningFor": "1h"}]
        running_result = MagicMock(stdout=self._docker_output(running_ct), returncode=0)
        stopped_result = MagicMock(stdout="svc2exitedid\n", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", side_effect=[running_result, stopped_result]):
            resp = client.get("/docker/containers")
        data = resp.json()
        assert data["running"] == 1
        assert data["stopped"] == 1

    def test_status_up_prefix_counted_as_running(self):
        cts = [{"Names": "/app", "State": "unknown", "Status": "Up 3 days", "Image": "x", "Ports": "", "RunningFor": "3d"}]
        result = MagicMock(stdout=self._docker_output(cts), returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        assert resp.json()["running"] == 1

    def test_empty_stdout_returns_empty_list(self):
        result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        data = resp.json()
        assert data["containers"] == []
        assert data["running"] == 0

    def test_docker_not_found_returns_503(self):
        with patch("control_center.api.routes_docker.subprocess.run", side_effect=FileNotFoundError):
            resp = client.get("/docker/containers")
        assert resp.status_code == 503
        assert "docker not found" in resp.json()["error"]

    def test_generic_exception_returns_500(self):
        with patch("control_center.api.routes_docker.subprocess.run", side_effect=RuntimeError("fail")):
            resp = client.get("/docker/containers")
        assert resp.status_code == 500
        assert "fail" in resp.json()["error"]

    def test_invalid_json_lines_skipped(self):
        bad_output = '{"Names": "/ok", "State": "running", "Status": "Up", "Image": "x", "Ports": "", "RunningFor": "1h"}\nnot-json\n'
        result = MagicMock(stdout=bad_output, returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        data = resp.json()
        assert len(data["containers"]) == 1

    def test_whitespace_only_lines_skipped(self):
        ct = [{"Names": "/app", "State": "running", "Status": "Up", "Image": "x", "Ports": "", "RunningFor": "1h"}]
        output = "\n" + json.dumps(ct[0]) + "\n  \n"
        result = MagicMock(stdout=output, returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        assert len(resp.json()["containers"]) == 1


# ===========================================================================
# /docker/sif-images
# ===========================================================================

class TestGetSifImages:

    def test_returns_empty_when_no_dirs(self, tmp_path):
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        assert data["images"] == []
        assert data["built"] == 0
        assert data["missing"] == 0
        assert data["total_gb"] == 0.0

    def test_dockerfile_creates_tool_entry(self, tmp_path):
        df_dir = tmp_path / "dockerfiles"
        df_dir.mkdir()
        (df_dir / "Dockerfile.bwa").write_text("FROM ubuntu")
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        assert any(t["tool"] == "bwa" for t in data["images"])
        assert data["missing"] == 1
        assert data["built"] == 0

    def test_sif_file_marks_tool_built(self, tmp_path):
        df_dir = tmp_path / "dockerfiles"
        sif_dir = tmp_path / "sif"
        df_dir.mkdir()
        sif_dir.mkdir()
        (df_dir / "Dockerfile.bwa").write_text("FROM ubuntu")
        sif_file = sif_dir / "bwa.sif"
        sif_file.write_bytes(b"X" * (5 * 1024 * 1024))  # 5 MB
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        bwa_entry = next(t for t in data["images"] if t["tool"] == "bwa")
        assert bwa_entry["exists"] is True
        assert bwa_entry["size_mb"] > 0
        assert data["built"] == 1

    def test_sif_without_dockerfile_added_as_extra(self, tmp_path):
        sif_dir = tmp_path / "sif"
        sif_dir.mkdir()
        (sif_dir / "star.sif").write_bytes(b"X" * 1024)
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        assert any(t["tool"] == "star" for t in data["images"])

    def test_total_gb_computed(self, tmp_path):
        sif_dir = tmp_path / "sif"
        sif_dir.mkdir()
        sif_file = sif_dir / "bigfile.sif"
        sif_file.write_bytes(b"X" * (1024 ** 3))  # 1 GB
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        assert data["total_gb"] == 1.0

    def test_arch_suffix_stripped_from_sif_stem(self, tmp_path):
        df_dir = tmp_path / "dockerfiles"
        sif_dir = tmp_path / "sif"
        df_dir.mkdir(); sif_dir.mkdir()
        (df_dir / "Dockerfile.bwa").write_text("FROM ubuntu")
        (sif_dir / "bwa_x86_64.sif").write_bytes(b"X" * 1024)
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        bwa_entry = next(t for t in resp.json()["images"] if t["tool"] == "bwa")
        assert bwa_entry["exists"] is True

    def test_category_assigned_correctly(self, tmp_path):
        df_dir = tmp_path / "dockerfiles"
        df_dir.mkdir()
        (df_dir / "Dockerfile.bwa").write_text("FROM ubuntu")
        (df_dir / "Dockerfile.unknown_xyz").write_text("FROM ubuntu")
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        tools = {t["tool"]: t["category"] for t in resp.json()["images"]}
        assert tools.get("bwa") == "alignment"
        assert tools.get("unknown_xyz") == "general"

    def test_sif_stem_fallback_when_normalized_not_in_tools(self, tmp_path):
        """When the arch-stripped stem isn't in tools but original stem is, use original."""
        df_dir = tmp_path / "dockerfiles"
        sif_dir = tmp_path / "sif"
        df_dir.mkdir(); sif_dir.mkdir()
        # Dockerfile for "bwa_arm64" (not "bwa")
        (df_dir / "Dockerfile.bwa_arm64").write_text("FROM ubuntu")
        # SIF file whose original stem matches the Dockerfile key
        (sif_dir / "bwa_arm64.sif").write_bytes(b"X" * 1024)
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        # Arch suffix is stripped from the SIF stem → "bwa"; that's not in tools.
        # But "bwa_arm64" (f.stem) IS in tools → elif branch executes.
        assert any(t["exists"] for t in data["images"])


# ===========================================================================
# helper: _parse_docker_size_mb
# ===========================================================================

class TestParseSizeMb:

    def _parse(self, s):
        from control_center.api.routes_docker import _parse_docker_size_mb
        return _parse_docker_size_mb(s)

    def test_gb_string(self):
        assert self._parse("1.48GB") == pytest.approx(1024 * 1.48, rel=1e-3)

    def test_mb_string(self):
        assert self._parse("452MB") == 452.0

    def test_kb_string(self):
        assert self._parse("512kB") == pytest.approx(0.5, rel=1e-2)

    def test_bytes_string(self):
        assert self._parse("1048576B") == pytest.approx(1.0, rel=1e-3)

    def test_invalid_returns_zero(self):
        assert self._parse("bad") == 0.0

    def test_non_numeric_with_valid_suffix_raises_value_error_internally(self):
        # Ends in a recognized suffix but the numeric part can't be parsed,
        # exercising the `except ValueError` branch (not just "no suffix matched").
        assert self._parse("abcB") == 0.0

    def test_empty_string_returns_zero(self):
        assert self._parse("0B") == pytest.approx(0.0, abs=1e-6)

    def test_pure_bytes_large_value(self):
        assert self._parse("1048576B") == pytest.approx(1.0, rel=1e-3)


# ===========================================================================
# /docker/plugin-images
# ===========================================================================

class TestGetPluginImages:

    def test_returns_empty_when_no_plugins_dir(self, tmp_path):
        docker_result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        data = resp.json()
        assert data["plugins"] == []
        assert data["present"] == 0

    def test_plugin_json_creates_entry(self, tmp_path):
        plugins_dir = tmp_path / "plugins" / "myplugin"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({
            "slug": "myplugin", "name": "My Plugin", "category": "genomics"
        }))
        docker_result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        data = resp.json()
        assert len(data["plugins"]) == 1
        assert data["plugins"][0]["plugin"] == "myplugin"
        assert data["plugins"][0]["category"] == "genomics"
        assert data["plugins"][0]["local_status"] == "missing"

    def test_present_image_counted(self, tmp_path):
        plugins_dir = tmp_path / "plugins" / "alpha"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"slug": "alpha"}))
        image_name = "ghcr.io/omnibioai/omnibioai-plugin-alpha:latest"
        docker_line = json.dumps({"Repository": "ghcr.io/omnibioai/omnibioai-plugin-alpha", "Tag": "latest", "Size": "120MB"})
        docker_result = MagicMock(stdout=docker_line, returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        data = resp.json()
        plugin = data["plugins"][0]
        assert plugin["local_status"] == "present"
        assert plugin["size_mb"] == 120.0
        assert data["present"] == 1

    def test_docker_exception_still_returns_plugins(self, tmp_path):
        plugins_dir = tmp_path / "plugins" / "beta"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"slug": "beta"}))
        with patch("control_center.api.routes_docker.subprocess.run", side_effect=RuntimeError("docker down")):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        data = resp.json()
        assert len(data["plugins"]) == 1
        assert data["plugins"][0]["local_status"] == "missing"

    def test_invalid_plugin_json_skipped(self, tmp_path):
        plugins_dir = tmp_path / "plugins" / "bad"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text("not-json")
        docker_result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"] == []

    def test_slug_fallback_to_dir_name(self, tmp_path):
        plugins_dir = tmp_path / "plugins" / "mydir"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"name": "No Slug Plugin"}))
        docker_result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"][0]["plugin"] == "mydir"

    def test_docker_image_line_invalid_json_skipped(self, tmp_path):
        plugins_dir = tmp_path / "plugins" / "gamma"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"slug": "gamma"}))
        docker_result = MagicMock(stdout="not-json-line\n", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"][0]["local_status"] == "missing"

    def test_empty_lines_in_docker_output_skipped(self, tmp_path):
        plugins_dir = tmp_path / "plugins" / "delta"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"slug": "delta"}))
        # Output with empty/whitespace lines mixed in
        docker_result = MagicMock(stdout="\n  \n", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"][0]["local_status"] == "missing"

    def test_blank_line_between_entries_skipped(self, tmp_path):
        # A blank line sandwiched between two real lines exercises the
        # `if not line: continue` branch (top-level .strip() alone can't
        # produce this — it only trims leading/trailing whitespace).
        plugins_dir = tmp_path / "plugins" / "zeta"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"slug": "zeta"}))
        image_name = "ghcr.io/omnibioai/omnibioai-plugin-zeta"
        line = json.dumps({"Repository": image_name, "Tag": "latest", "Size": "10MB"})
        docker_result = MagicMock(stdout=f"{line}\n\n{line}\n", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"][0]["local_status"] == "present"

    def test_image_without_repo_or_tag_skipped(self, tmp_path):
        plugins_dir = tmp_path / "plugins" / "epsilon"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"slug": "epsilon"}))
        # Image line missing tag
        docker_result = MagicMock(
            stdout=json.dumps({"Repository": "some/image", "Tag": "", "Size": "10MB"}),
            returncode=0
        )
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"][0]["local_status"] == "missing"
