"""
tests/test_routes_cloud.py

Unit tests for:
  - control_center.api.routes_cloud  (GET /cloud)
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


class TestGetCloud(unittest.TestCase):

    def test_returns_200_with_all_providers(self) -> None:
        resp = client.get("/cloud")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ("aws", "azure", "gcp", "kubernetes", "local", "slurm"):
            self.assertIn(key, data)

    def test_local_docker_always_configured(self) -> None:
        data = client.get("/cloud").json()
        self.assertTrue(data["local"]["configured"])

    def test_aws_configured_when_env_set(self) -> None:
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "AKIA123", "AWS_DEFAULT_REGION": "us-east-1"}):
            data = client.get("/cloud").json()
        self.assertTrue(data["aws"]["configured"])
        self.assertEqual(data["aws"]["region"], "us-east-1")

    def test_aws_not_configured_without_env(self) -> None:
        env = dict(os.environ)
        env.pop("AWS_ACCESS_KEY_ID", None)
        env.pop("AWS_BATCH_JOB_QUEUE", None)
        with patch.dict(os.environ, env, clear=True):
            data = client.get("/cloud").json()
        self.assertFalse(data["aws"]["configured"])

    def test_slurm_host_falls_back_to_hpc_host(self) -> None:
        env = dict(os.environ)
        env.pop("SLURM_HOST", None)
        env["HPC_HOST"] = "hpc.example.com"
        with patch.dict(os.environ, env, clear=True):
            data = client.get("/cloud").json()
        self.assertTrue(data["slurm"]["configured"])
        self.assertEqual(data["slurm"]["host"], "hpc.example.com")


if __name__ == "__main__":
    unittest.main()
