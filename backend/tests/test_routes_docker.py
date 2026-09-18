"""tests/test_routes_docker.py — covers routes_docker.py and routes_config.py

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from control_center.api.routes_docker import get_local_image_ids
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

# docker_router and config_router are gated at router-inclusion time
# (main.py) behind platform.manage_infra -- these tests exercise the
# routes' own logic, not authorization (see test_main.py for the 401/403
# permission checks), so the client carries a fixed, always-sufficient
# token by default.
_INFRA_TOKEN = jwt.encode({"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")
client = TestClient(app, headers={"Authorization": f"Bearer {_INFRA_TOKEN}"})


# ===========================================================================
# /docker/containers
# ===========================================================================

class TestGetContainers:
    """GET /docker/containers with the docker ps subprocess calls mocked: container list
    parsing, running and stopped counts, and error mapping."""

    def _docker_output(self, containers):
        return "\n".join(json.dumps(c) for c in containers)

    def test_returns_container_list(self):
        """A mocked docker ps line is returned in the containers list with its Names
        field intact."""
        ct = [{"Names": "/web", "Image": "nginx:latest", "State": "running", "Status": "Up 2h", "Ports": "0.0.0.0:80->80/tcp", "RunningFor": "2 hours"}]
        result = MagicMock(stdout=self._docker_output(ct), returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["containers"][0]["Names"] == "/web"

    def test_running_count_correct(self):
        """The first docker ps call's single entry gives running 1, and the second
        call's one exited container id gives stopped 1."""
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
        """A container whose State is unknown but whose Status starts with Up is counted
        as running."""
        cts = [{"Names": "/app", "State": "unknown", "Status": "Up 3 days", "Image": "x", "Ports": "", "RunningFor": "3d"}]
        result = MagicMock(stdout=self._docker_output(cts), returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        assert resp.json()["running"] == 1

    def test_empty_stdout_returns_empty_list(self):
        """Empty docker ps output returns an empty containers list and running 0."""
        result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        data = resp.json()
        assert data["containers"] == []
        assert data["running"] == 0

    def test_docker_not_found_returns_503(self):
        """A FileNotFoundError from the docker CLI returns 503 with an error containing
        'docker not found'."""
        with patch("control_center.api.routes_docker.subprocess.run", side_effect=FileNotFoundError):
            resp = client.get("/docker/containers")
        assert resp.status_code == 503
        assert "docker not found" in resp.json()["error"]

    def test_generic_exception_returns_500(self):
        """Any other exception from the docker call returns 500 with the exception
        message in the error."""
        with patch("control_center.api.routes_docker.subprocess.run", side_effect=RuntimeError("fail")):
            resp = client.get("/docker/containers")
        assert resp.status_code == 500
        assert "fail" in resp.json()["error"]

    def test_nonzero_returncode_is_an_error_not_zero_containers(self):
        """A docker CLI that exits nonzero, such as when it cannot reach the daemon, is
        reported as a 500 carrying its stderr text rather than as zero containers."""
        # DH-4 finding, live-reproduced: a docker CLI that can't reach its
        # daemon exits nonzero with empty/error output, not an exception --
        # subprocess.run doesn't raise for that. Confirm it's now reported
        # as an error (500, distinct from the docker-not-found 503),
        # not silently folded into "0 containers running".
        result = MagicMock(stdout="", stderr="Cannot connect to the Docker daemon", returncode=1)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        assert resp.status_code == 500
        assert "Cannot connect to the Docker daemon" in resp.json()["error"]

    def test_returncode_zero_empty_stdout_still_zero_containers(self):
        """A zero exit with empty output is still a valid response of zero containers
        with status 200."""
        # The legitimate case this fix must not disturb: a real, reachable
        # Docker with genuinely zero containers still exits 0.
        result = MagicMock(stdout="", stderr="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        assert resp.status_code == 200
        assert resp.json()["containers"] == []

    def test_invalid_json_lines_skipped(self):
        """A non-JSON line in docker ps output is skipped while the valid line is kept."""
        bad_output = '{"Names": "/ok", "State": "running", "Status": "Up", "Image": "x", "Ports": "", "RunningFor": "1h"}\nnot-json\n'
        result = MagicMock(stdout=bad_output, returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        data = resp.json()
        assert len(data["containers"]) == 1

    def test_whitespace_only_lines_skipped(self):
        """Blank and whitespace-only lines in docker ps output are skipped."""
        ct = [{"Names": "/app", "State": "running", "Status": "Up", "Image": "x", "Ports": "", "RunningFor": "1h"}]
        output = "\n" + json.dumps(ct[0]) + "\n  \n"
        result = MagicMock(stdout=output, returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            resp = client.get("/docker/containers")
        assert len(resp.json()["containers"]) == 1


# ===========================================================================
# get_local_image_ids (DH-5)
# ===========================================================================

class TestGetLocalImageIds:
    """get_local_image_ids() resolves image references to local image ids through a
    mocked docker CLI call, and degrades to an empty dict on failure."""
    def test_empty_refs_short_circuits_without_a_subprocess_call(self):
        """An empty reference list returns an empty dict without invoking subprocess."""
        with patch("control_center.api.routes_docker.subprocess.run") as run:
            assert get_local_image_ids([]) == {}
        run.assert_not_called()

    def test_resolves_by_repo_tag_not_argument_order(self):
        """Ids are matched to references through RepoTags, not by the order of the
        arguments."""
        payload = json.dumps([
            {"Id": "sha256:aaa", "RepoTags": ["mysql:8.0"]},
            {"Id": "sha256:bbb", "RepoTags": ["redis:7-alpine"]},
        ])
        result = MagicMock(stdout=payload, returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            ids = get_local_image_ids(["mysql:8.0", "redis:7-alpine"])
        assert ids == {"mysql:8.0": "sha256:aaa", "redis:7-alpine": "sha256:bbb"}

    def test_one_missing_reference_does_not_fail_the_batch(self):
        """A nonzero exit caused by one missing reference does not discard the ids
        resolved from the valid JSON on stdout for the others."""
        # Real docker behavior: nonzero exit, but stdout still holds a
        # valid JSON array for every reference that *did* resolve.
        payload = json.dumps([{"Id": "sha256:aaa", "RepoTags": ["mysql:8.0"]}])
        result = MagicMock(stdout=payload, returncode=1)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            ids = get_local_image_ids(["mysql:8.0", "nonexistent:latest"])
        assert ids == {"mysql:8.0": "sha256:aaa"}
        assert "nonexistent:latest" not in ids

    def test_docker_not_found_returns_empty_dict_not_raise(self):
        """A FileNotFoundError from the docker CLI returns an empty dict instead of
        raising."""
        with patch("control_center.api.routes_docker.subprocess.run", side_effect=FileNotFoundError):
            assert get_local_image_ids(["mysql:8.0"]) == {}

    def test_timeout_returns_empty_dict_not_raise(self):
        """A subprocess timeout returns an empty dict instead of raising."""
        with patch(
            "control_center.api.routes_docker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=30),
        ):
            assert get_local_image_ids(["mysql:8.0"]) == {}

    def test_malformed_json_returns_empty_dict_not_raise(self):
        """Malformed JSON on stdout returns an empty dict instead of raising."""
        result = MagicMock(stdout="not-json", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            assert get_local_image_ids(["mysql:8.0"]) == {}

    def test_empty_stdout_returns_empty_dict(self):
        """Empty stdout with a nonzero exit returns an empty dict."""
        result = MagicMock(stdout="", returncode=1)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            assert get_local_image_ids(["mysql:8.0"]) == {}

    def test_entry_without_an_id_is_skipped(self):
        """An inspect entry that has no Id is skipped."""
        payload = json.dumps([{"RepoTags": ["mysql:8.0"]}])
        result = MagicMock(stdout=payload, returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            assert get_local_image_ids(["mysql:8.0"]) == {}

    def test_image_with_multiple_repo_tags_maps_each_tag(self):
        """An image with several RepoTags maps every one of its tags to the same id."""
        payload = json.dumps([{"Id": "sha256:aaa", "RepoTags": ["mysql:8.0", "mysql:latest"]}])
        result = MagicMock(stdout=payload, returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=result):
            ids = get_local_image_ids(["mysql:8.0"])
        assert ids["mysql:8.0"] == "sha256:aaa"
        assert ids["mysql:latest"] == "sha256:aaa"


# ===========================================================================
# /docker/sif-images
# ===========================================================================

class TestGetSifImages:
    """GET /docker/sif-images with _TOOL_IMAGES_BASE pointed at a temp directory:
    Dockerfile-derived tool entries, SIF file presence, sizes and categories."""

    def test_returns_empty_when_no_dirs(self, tmp_path):
        """With no dockerfiles or sif directories, images is empty and built, missing
        and total_gb are all zero."""
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        assert data["images"] == []
        assert data["built"] == 0
        assert data["missing"] == 0
        assert data["total_gb"] == 0.0

    def test_dockerfile_creates_tool_entry(self, tmp_path):
        """A Dockerfile.bwa with no SIF file creates a bwa entry that is counted as
        missing, with built 0."""
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
        """A 5 MB bwa.sif next to Dockerfile.bwa marks bwa as existing with a positive
        size_mb and built 1."""
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
        """A SIF file with no matching Dockerfile (star.sif) is still listed as a tool
        entry."""
        sif_dir = tmp_path / "sif"
        sif_dir.mkdir()
        (sif_dir / "star.sif").write_bytes(b"X" * 1024)
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        assert any(t["tool"] == "star" for t in data["images"])

    def test_total_gb_computed(self, tmp_path):
        """A 1 GB SIF file gives total_gb 1.0."""
        sif_dir = tmp_path / "sif"
        sif_dir.mkdir()
        sif_file = sif_dir / "bigfile.sif"
        sif_file.write_bytes(b"X" * (1024 ** 3))  # 1 GB
        with patch("control_center.api.routes_docker._TOOL_IMAGES_BASE", tmp_path):
            resp = client.get("/docker/sif-images")
        data = resp.json()
        assert data["total_gb"] == 1.0

    def test_arch_suffix_stripped_from_sif_stem(self, tmp_path):
        """bwa_x86_64.sif is matched to Dockerfile.bwa once the architecture suffix is
        stripped, so bwa is reported as existing."""
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
        """bwa is categorized as alignment and an unrecognized tool (unknown_xyz) as
        general."""
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
    """_parse_docker_size_mb() converts Docker size strings (GB, MB, kB and B) to
    megabytes and returns 0.0 for unparseable input."""

    def _parse(self, s):
        from control_center.api.routes_docker import _parse_docker_size_mb
        return _parse_docker_size_mb(s)

    def test_gb_string(self):
        """1.48GB converts to 1.48 x 1024 MB."""
        assert self._parse("1.48GB") == pytest.approx(1024 * 1.48, rel=1e-3)

    def test_mb_string(self):
        """452MB converts to 452.0 MB."""
        assert self._parse("452MB") == 452.0

    def test_kb_string(self):
        """512kB converts to about 0.5 MB."""
        assert self._parse("512kB") == pytest.approx(0.5, rel=1e-2)

    def test_bytes_string(self):
        """1048576B converts to about 1.0 MB."""
        assert self._parse("1048576B") == pytest.approx(1.0, rel=1e-3)

    def test_invalid_returns_zero(self):
        """An unparseable string ('bad') returns 0.0."""
        assert self._parse("bad") == 0.0

    def test_non_numeric_with_valid_suffix_raises_value_error_internally(self):
        """A string with a recognized suffix but a non-numeric part ('abcB') returns 0.0
        by way of the ValueError handler."""
        # Ends in a recognized suffix but the numeric part can't be parsed,
        # exercising the `except ValueError` branch (not just "no suffix matched").
        assert self._parse("abcB") == 0.0

    def test_empty_string_returns_zero(self):
        """The string '0B' converts to about 0.0 MB; despite the name, the input is not
        an empty string."""
        assert self._parse("0B") == pytest.approx(0.0, abs=1e-6)

    def test_pure_bytes_large_value(self):
        """1048576B converts to about 1.0 MB, the same input and expectation as
        test_bytes_string."""
        assert self._parse("1048576B") == pytest.approx(1.0, rel=1e-3)


# ===========================================================================
# /docker/plugin-images
# ===========================================================================

class TestGetPluginImages:
    """GET /docker/plugin-images with _OMNIBIOAI_BASE at a temp directory and docker
    image output mocked: plugin.json discovery and local image presence."""

    def test_returns_empty_when_no_plugins_dir(self, tmp_path):
        """With no plugins directory, plugins is empty and present is 0."""
        docker_result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        data = resp.json()
        assert data["plugins"] == []
        assert data["present"] == 0

    def test_plugin_json_creates_entry(self, tmp_path):
        """A plugin.json creates an entry carrying its slug and category, with
        local_status missing when no matching image exists."""
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
        """A docker image line matching the plugin's image marks it present with size_mb
        120.0 and counts present as 1."""
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
        """A RuntimeError from the docker call still returns the plugin, with
        local_status missing."""
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
        """A plugin.json that is not valid JSON is skipped."""
        plugins_dir = tmp_path / "plugins" / "bad"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text("not-json")
        docker_result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"] == []

    def test_slug_fallback_to_dir_name(self, tmp_path):
        """A plugin.json with no slug falls back to the directory name (mydir) as the
        plugin id."""
        plugins_dir = tmp_path / "plugins" / "mydir"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"name": "No Slug Plugin"}))
        docker_result = MagicMock(stdout="", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"][0]["plugin"] == "mydir"

    def test_docker_image_line_invalid_json_skipped(self, tmp_path):
        """A non-JSON line in docker image output is skipped, leaving the plugin
        missing."""
        plugins_dir = tmp_path / "plugins" / "gamma"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "plugin.json").write_text(json.dumps({"slug": "gamma"}))
        docker_result = MagicMock(stdout="not-json-line\n", returncode=0)
        with patch("control_center.api.routes_docker.subprocess.run", return_value=docker_result):
            with patch("control_center.api.routes_docker._OMNIBIOAI_BASE", tmp_path):
                resp = client.get("/docker/plugin-images")
        assert resp.json()["plugins"][0]["local_status"] == "missing"

    def test_empty_lines_in_docker_output_skipped(self, tmp_path):
        """Empty and whitespace-only lines in docker output are ignored, leaving the
        plugin missing."""
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
        """A blank line between two docker image entries is skipped and the plugin is
        still reported present."""
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
        """A docker image line with an empty Tag is skipped, so the plugin stays
        missing."""
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
