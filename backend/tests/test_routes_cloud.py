"""
tests/test_routes_cloud.py

Unit tests for:
  - control_center.api.routes_cloud  (GET /cloud)

GET /cloud always reports every provider key (aws/azure/gcp/kubernetes/
local/slurm); "local" (Docker) is always configured=True, the others are
configured based on the relevant environment variables, and slurm's host
falls back to HPC_HOST when SLURM_HOST is unset.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


class TestGetCloud(unittest.TestCase):
    """GET /cloud's provider-configuration detection, driven purely by the
    presence/absence of provider-specific environment variables."""

    def test_returns_200_with_all_providers(self) -> None:
        """The response is 200 and always includes every provider key,
        configured or not."""
        resp = client.get("/cloud")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ("aws", "azure", "gcp", "kubernetes", "local", "slurm"):
            self.assertIn(key, data)

    def test_local_docker_always_configured(self) -> None:
        """"local" (Docker) is unconditionally reported as configured."""
        data = client.get("/cloud").json()
        self.assertTrue(data["local"]["configured"])

    def test_aws_configured_when_env_set(self) -> None:
        """AWS_ACCESS_KEY_ID + AWS_DEFAULT_REGION set -> aws.configured is
        True and the reported region matches the env var."""
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "AKIA123", "AWS_DEFAULT_REGION": "us-east-1"}):
            data = client.get("/cloud").json()
        self.assertTrue(data["aws"]["configured"])
        self.assertEqual(data["aws"]["region"], "us-east-1")

    def test_aws_not_configured_without_env(self) -> None:
        """Neither AWS_ACCESS_KEY_ID nor AWS_BATCH_JOB_QUEUE set -> aws.
        configured is False."""
        env = dict(os.environ)
        env.pop("AWS_ACCESS_KEY_ID", None)
        env.pop("AWS_BATCH_JOB_QUEUE", None)
        with patch.dict(os.environ, env, clear=True):
            data = client.get("/cloud").json()
        self.assertFalse(data["aws"]["configured"])

    def test_slurm_host_falls_back_to_hpc_host(self) -> None:
        """With SLURM_HOST unset but HPC_HOST set, slurm is reported
        configured using HPC_HOST as its host."""
        env = dict(os.environ)
        env.pop("SLURM_HOST", None)
        env["HPC_HOST"] = "hpc.example.com"
        with patch.dict(os.environ, env, clear=True):
            data = client.get("/cloud").json()
        self.assertTrue(data["slurm"]["configured"])
        self.assertEqual(data["slurm"]["host"], "hpc.example.com")


if __name__ == "__main__":
    unittest.main()
