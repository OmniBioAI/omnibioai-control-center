"""
tests/test_routes_storage.py

Unit tests for:
  - control_center.api.routes_storage  (GET /storage)

Covers the `du`-based directory-size helper (_du: parses output, fails
safe to 0 on a nonzero exit or an exception), `statvfs`-based disk-usage
helper (_df_disk: fails safe to zeros), and _compute_storage()'s
aggregation of categories/reference-index-by-organism/work-breakdown/
docker size, including its zero-division guard on pct_used.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
from fastapi.testclient import TestClient

from control_center.api import routes_storage
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

# router_storage is gated at router-inclusion time (main.py) behind
# platform.manage_infra -- same convention as test_routes_docker.py /
# test_routes_llm.py: a fixed, always-sufficient token by default, with
# the 401/403 permission checks covered separately in test_main.py.
_INFRA_TOKEN = jwt.encode({"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")
client = TestClient(app, headers={"Authorization": f"Bearer {_INFRA_TOKEN}"})


class TestDu(unittest.TestCase):
    """_du()'s `du`-subprocess-based directory size, failing safe to 0
    on a nonexistent path, a nonzero exit code, or a raised exception."""

    def test_nonexistent_path_returns_zero(self) -> None:
        """A path that doesn't exist returns 0."""
        self.assertEqual(routes_storage._du(Path("/nonexistent/path/xyz")), 0)

    def test_parses_du_output(self) -> None:
        """A successful `du` run's tab-separated byte count is parsed
        into an int."""
        with tempfile.TemporaryDirectory() as tmp:
            result = MagicMock(returncode=0, stdout="12345\t/some/path\n")
            with patch.object(routes_storage.subprocess, "run", return_value=result):
                size = routes_storage._du(Path(tmp))
        self.assertEqual(size, 12345)

    def test_nonzero_returncode_returns_zero(self) -> None:
        """A nonzero `du` exit code returns 0 rather than the empty stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            result = MagicMock(returncode=1, stdout="")
            with patch.object(routes_storage.subprocess, "run", return_value=result):
                size = routes_storage._du(Path(tmp))
        self.assertEqual(size, 0)

    def test_exception_returns_zero(self) -> None:
        """An exception raised by subprocess.run returns 0 rather than propagating."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(routes_storage.subprocess, "run", side_effect=RuntimeError("boom")):
                size = routes_storage._du(Path(tmp))
        self.assertEqual(size, 0)


class TestDfDisk(unittest.TestCase):
    """_df_disk()'s statvfs-based (total, used, free) tuple, failing
    safe to zeros on an OSError."""

    def test_returns_total_used_free(self) -> None:
        """A real path returns a positive total with used == total - free."""
        with tempfile.TemporaryDirectory() as tmp:
            total, used, free = routes_storage._df_disk(Path(tmp))
        self.assertGreater(total, 0)
        self.assertEqual(used, total - free)

    def test_exception_returns_zeros(self) -> None:
        """A statvfs OSError returns (0, 0, 0) rather than propagating."""
        with patch.object(routes_storage.os, "statvfs", side_effect=OSError("boom")):
            total, used, free = routes_storage._df_disk(Path("/nonexistent"))
        self.assertEqual((total, used, free), (0, 0, 0))


class TestComputeStorage(unittest.TestCase):
    """_compute_storage()'s aggregation of categories, reference-index-
    by-organism, work-breakdown, and docker size."""

    def test_no_data_or_work_root(self) -> None:
        """With no data/ or work/ directory present, categories/
        reference_indexes/work_breakdown are all empty dicts."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(routes_storage, "_du", return_value=0):
                with patch.object(routes_storage.subprocess, "run",
                                   return_value=MagicMock(returncode=0, stdout="unavailable")):
                    data = routes_storage._compute_storage(Path(tmp))
        self.assertEqual(data["categories"], {})
        self.assertEqual(data["reference_indexes"], {})
        self.assertEqual(data["work_breakdown"], {})

    def test_categories_and_work_breakdown_populated(self) -> None:
        """Directories that map to a known category (Reference Data) or
        work subdirectory (jobs) are aggregated; a data/ subdirectory
        with no size mapping (uploads) does not appear in categories."""
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
        """Index sizes across multiple index types (bwa, star) for the
        same organism are summed together per-organism."""
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
        """A failure computing Docker's disk usage leaves docker_raw as
        "unavailable" rather than raising or leaving the field missing."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(routes_storage, "_du", return_value=0):
                with patch.object(routes_storage.subprocess, "run", side_effect=RuntimeError("boom")):
                    data = routes_storage._compute_storage(Path(tmp))
        self.assertEqual(data["docker_raw"], "unavailable")

    def test_disk_pct_used_zero_when_total_zero(self) -> None:
        """A total disk size of 0 (e.g. statvfs failure) reports
        pct_used=0 rather than raising a ZeroDivisionError."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(routes_storage, "_du", return_value=0):
                with patch.object(routes_storage, "_df_disk", return_value=(0, 0, 0)):
                    with patch.object(routes_storage.subprocess, "run",
                                       return_value=MagicMock(returncode=0, stdout="")):
                        data = routes_storage._compute_storage(Path(tmp))
        self.assertEqual(data["disk"]["pct_used"], 0)


class TestGetStorageEndpoint(unittest.TestCase):
    """GET /storage returns 200 with the computed storage shape."""

    def test_endpoint_returns_200(self) -> None:
        """The endpoint returns 200 with "disk" and "categories" keys present."""
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
