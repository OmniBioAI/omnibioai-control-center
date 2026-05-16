"""tests/test_routes_config.py — covers routes_config.py"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


# ===========================================================================
# GET /config
# ===========================================================================

class TestGetConfig:

    def test_returns_yaml_content(self, tmp_path):
        cfg = tmp_path / "control_center.yaml"
        cfg.write_text("services:\n  redis:\n    type: redis\n")
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", str(cfg)):
            resp = client.get("/config")
        assert resp.status_code == 200
        assert "redis" in resp.text

    def test_content_type_is_text_plain(self, tmp_path):
        cfg = tmp_path / "cc.yaml"
        cfg.write_text("key: value\n")
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", str(cfg)):
            resp = client.get("/config")
        assert "text/plain" in resp.headers["content-type"]

    def test_missing_config_returns_404(self, tmp_path):
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", str(tmp_path / "nonexistent.yaml")):
            resp = client.get("/config")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_returns_full_file_content(self, tmp_path):
        content = "services:\n  mysql:\n    host: db\n    port: 3306\n"
        cfg = tmp_path / "cc.yaml"
        cfg.write_text(content)
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", str(cfg)):
            resp = client.get("/config")
        assert resp.text == content


# ===========================================================================
# POST /config/service
# ===========================================================================

class TestAddService:

    def _write_config(self, tmp_path, data=None):
        cfg = tmp_path / "cc.yaml"
        cfg.write_text(yaml.dump(data or {"services": {}}))
        return str(cfg)

    def test_adds_service_to_config(self, tmp_path):
        cfg_path = self._write_config(tmp_path)
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", cfg_path):
            resp = client.post("/config/service", json={"name": "redis", "url": "http://redis:6379", "type": "tcp"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["name"] == "redis"
        raw = yaml.safe_load(Path(cfg_path).read_text())
        assert "redis" in raw["services"]

    def test_service_fields_written_correctly(self, tmp_path):
        cfg_path = self._write_config(tmp_path)
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", cfg_path):
            client.post("/config/service", json={"name": "myapi", "url": "http://api:8080/health", "type": "http"})
        raw = yaml.safe_load(Path(cfg_path).read_text())
        svc = raw["services"]["myapi"]
        assert svc["type"] == "http"
        assert svc["url"] == "http://api:8080/health"
        assert svc["timeout_s"] == 2

    def test_default_type_is_http(self, tmp_path):
        cfg_path = self._write_config(tmp_path)
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", cfg_path):
            client.post("/config/service", json={"name": "svc", "url": "http://svc/health"})
        raw = yaml.safe_load(Path(cfg_path).read_text())
        assert raw["services"]["svc"]["type"] == "http"

    def test_missing_name_returns_422(self, tmp_path):
        cfg_path = self._write_config(tmp_path)
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", cfg_path):
            resp = client.post("/config/service", json={"url": "http://svc/health"})
        assert resp.status_code == 422

    def test_missing_url_returns_422(self, tmp_path):
        cfg_path = self._write_config(tmp_path)
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", cfg_path):
            resp = client.post("/config/service", json={"name": "svc"})
        assert resp.status_code == 422

    def test_empty_name_returns_422(self, tmp_path):
        cfg_path = self._write_config(tmp_path)
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", cfg_path):
            resp = client.post("/config/service", json={"name": "  ", "url": "http://svc"})
        assert resp.status_code == 422

    def test_missing_config_file_returns_404(self, tmp_path):
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", str(tmp_path / "missing.yaml")):
            resp = client.post("/config/service", json={"name": "svc", "url": "http://svc"})
        assert resp.status_code == 404

    def test_config_without_services_key_initialised(self, tmp_path):
        cfg = tmp_path / "cc.yaml"
        cfg.write_text("system:\n  disk_checks: []\n")
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", str(cfg)):
            resp = client.post("/config/service", json={"name": "new", "url": "http://new/health"})
        assert resp.status_code == 200
        raw = yaml.safe_load(cfg.read_text())
        assert "new" in raw["services"]

    def test_multiple_services_can_be_added(self, tmp_path):
        cfg_path = self._write_config(tmp_path)
        with patch("control_center.api.routes_config._DEFAULT_CONFIG", cfg_path):
            client.post("/config/service", json={"name": "svc1", "url": "http://s1"})
            client.post("/config/service", json={"name": "svc2", "url": "http://s2"})
        raw = yaml.safe_load(Path(cfg_path).read_text())
        assert "svc1" in raw["services"]
        assert "svc2" in raw["services"]
