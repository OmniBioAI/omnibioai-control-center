"""
tests/test_routes_storage.py

Unit tests for:
  - control_center.api.routes_storage  (GET /storage)
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from control_center.api import routes_storage
from control_center.main import app

client = TestClient(app)


class TestDu(unittest.TestCase):

    def test_nonexistent_path_returns_zero(self) -> None:
        self.assertEqual(routes_storage._du(Path("/nonexistent/path/xyz")), 0)

    def test_parses_du_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = MagicMock(returncode=0, stdout="12345\t/some/path\n")
            with patch.object(routes_storage.subprocess, "run", return_value=result):
                size = routes_storage._du(Path(tmp))
        self.assertEqual(size, 12345)

    def test_nonzero_returncode_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = MagicMock(returncode=1, stdout="")
            with patch.object(routes_storage.subprocess, "run", return_value=result):
                size = routes_storage._du(Path(tmp))
        self.assertEqual(size, 0)

    def test_exception_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(routes_storage.subprocess, "run", side_effect=RuntimeError("boom")):
                size = routes_storage._du(Path(tmp))
        self.assertEqual(size, 0)


class TestDfDisk(unittest.TestCase):

    def test_returns_total_used_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            total, used, free = routes_storage._df_disk(Path(tmp))
        self.assertGreater(total, 0)
        self.assertEqual(used, total - free)

    def test_exception_returns_zeros(self) -> None:
        with patch.object(routes_storage.os, "statvfs", side_effect=OSError("boom")):
            total, used, free = routes_storage._df_disk(Path("/nonexistent"))
        self.assertEqual((total, used, free), (0, 0, 0))


class TestComputeStorage(unittest.TestCase):

    def test_no_data_or_work_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(routes_storage, "_du", return_value=0):
                with patch.object(routes_storage.subprocess, "run",
                                   return_value=MagicMock(returncode=0, stdout="unavailable")):
                    data = routes_storage._compute_storage(Path(tmp))
        self.assertEqual(data["categories"], {})
        self.assertEqual(data["reference_indexes"], {})
        self.assertEqual(data["work_breakdown"], {})

    def test_categories_and_work_breakdown_populated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "reference").mkdir(parents=True)
            (root / "data" / "uploads").mkdir(parents=True)
            (root / "work" / "jobs").mkdir(parents=True)

            def fake_du(path):
                return 100 if "reference" in str(path) or "jobs" in str(path) else 0

            with patch.object(routes_storage, "_du", side_effect=fake_du):
                with patch.object(routes_storage.subprocess, "run",
                                   return_value=MagicMock(returncode=0, stdout="5GB")):
                    data = routes_storage._compute_storage(root)

        self.assertEqual(data["categories"].get("Reference Data"), 100)
        self.assertNotIn("Uploads", data["categories"])
        self.assertEqual(data["work_breakdown"].get("jobs"), 100)
        self.assertEqual(data["docker_raw"], "5GB")

    def test_reference_indexes_aggregated_by_organism(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            idx_root = root / "data" / "reference" / "indexes"
            (idx_root / "bwa" / "human").mkdir(parents=True)
            (idx_root / "star" / "human").mkdir(parents=True)
            (idx_root / "bwa" / "mouse").mkdir(parents=True)

            with patch.object(routes_storage, "_du", return_value=50):
                with patch.object(routes_storage.subprocess, "run",
                                   return_value=MagicMock(returncode=0, stdout="")):
                    data = routes_storage._compute_storage(root)

        self.assertEqual(data["reference_indexes"]["human"], 100)
        self.assertEqual(data["reference_indexes"]["mouse"], 50)

    def test_docker_df_exception_leaves_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(routes_storage, "_du", return_value=0):
                with patch.object(routes_storage.subprocess, "run", side_effect=RuntimeError("boom")):
                    data = routes_storage._compute_storage(Path(tmp))
        self.assertEqual(data["docker_raw"], "unavailable")

    def test_disk_pct_used_zero_when_total_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(routes_storage, "_du", return_value=0):
                with patch.object(routes_storage, "_df_disk", return_value=(0, 0, 0)):
                    with patch.object(routes_storage.subprocess, "run",
                                       return_value=MagicMock(returncode=0, stdout="")):
                        data = routes_storage._compute_storage(Path(tmp))
        self.assertEqual(data["disk"]["pct_used"], 0)


class TestGetStorageEndpoint(unittest.TestCase):

    def test_endpoint_returns_200(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                with patch.object(routes_storage, "_du", return_value=0):
                    with patch.object(routes_storage.subprocess, "run",
                                       return_value=MagicMock(returncode=0, stdout="")):
                        resp = client.get("/storage")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("disk", data)
        self.assertIn("categories", data)


if __name__ == "__main__":
    unittest.main()
