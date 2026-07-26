"""
tests/test_routes_cron.py

Unit tests for:
  - control_center.api.routes_cron  (GET /cron/jobs)
"""

from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from control_center.main import app

client = TestClient(app)


class TestCronJobsRoute(unittest.TestCase):

    def test_open_no_auth_required(self) -> None:
        resp = client.get("/cron/jobs")
        self.assertEqual(resp.status_code, 200)

    def test_returns_four_jobs(self) -> None:
        data = client.get("/cron/jobs").json()
        self.assertEqual(len(data["jobs"]), 4)

    def test_uses_workspace_root_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
            with open(os.path.join(tmp, "logs", "pubmed_sync.log"), "w") as f:
                f.write("done\n")
            try:
                data = client.get("/cron/jobs").json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        pubmed_job = next(j for j in data["jobs"] if j["id"] == "pubmed-sync")
        self.assertEqual(pubmed_job["last_status"], "ok")


if __name__ == "__main__":
    unittest.main()
