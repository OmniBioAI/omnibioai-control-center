"""
tests/test_routes_known_issues.py

Unit tests for:
  - control_center.api.routes_known_issues
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

from control_center.core.auth import JWT_SECRET
from control_center.main import app

client = TestClient(app)


def _admin_headers() -> dict:
    token = jwt.encode({"sub": "1", "roles": ["admin"]}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user_headers() -> dict:
    token = jwt.encode({"sub": "2", "roles": ["user"]}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


class TestKnownIssuesRoutes(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        os.environ["WORKSPACE_ROOT"] = self._tmp
        self._issues_path = Path(self._tmp) / "omnibioai-work" / "known_issues.json"

    def tearDown(self) -> None:
        del os.environ["WORKSPACE_ROOT"]
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, issues: list) -> None:
        self._issues_path.parent.mkdir(parents=True, exist_ok=True)
        self._issues_path.write_text(json.dumps(issues))

    def test_get_open_no_auth_required(self) -> None:
        self._write([])
        resp = client.get("/known-issues")
        self.assertEqual(resp.status_code, 200)

    def test_get_malformed_file_returns_500(self) -> None:
        self._issues_path.parent.mkdir(parents=True, exist_ok=True)
        self._issues_path.write_text("not valid json")
        resp = client.get("/known-issues")
        self.assertEqual(resp.status_code, 500)

    def test_get_missing_file_returns_empty_list(self) -> None:
        resp = client.get("/known-issues")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"issues": []})

    def test_post_requires_admin_401(self) -> None:
        self._write([])
        resp = client.post("/known-issues", json={"title": "x"})
        self.assertEqual(resp.status_code, 401)

    def test_post_requires_admin_403_for_non_admin(self) -> None:
        self._write([])
        resp = client.post("/known-issues", json={"title": "x"}, headers=_user_headers())
        self.assertEqual(resp.status_code, 403)

    def test_post_creates_issue_as_admin(self) -> None:
        self._write([])
        resp = client.post(
            "/known-issues",
            json={"title": "New bug", "severity": "high", "area": "Backend"},
            headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["title"], "New bug")
        self.assertIn("id", data)

        get_resp = client.get("/known-issues")
        self.assertEqual(len(get_resp.json()["issues"]), 1)

    def test_put_requires_admin_401(self) -> None:
        self._write([{"id": "abc", "title": "x"}])
        resp = client.put("/known-issues/abc", json={"status": "resolved"})
        self.assertEqual(resp.status_code, 401)

    def test_put_updates_as_admin(self) -> None:
        self._write([{"id": "abc", "title": "x", "status": "open"}])
        resp = client.put(
            "/known-issues/abc", json={"status": "resolved"}, headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "resolved")

    def test_post_invalid_severity_returns_400(self) -> None:
        self._write([])
        resp = client.post(
            "/known-issues",
            json={"title": "x", "severity": "critical"},
            headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_invalid_status_returns_400(self) -> None:
        self._write([{"id": "abc", "title": "x"}])
        resp = client.put(
            "/known-issues/abc", json={"status": "wontfix"}, headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_unknown_id_returns_404(self) -> None:
        self._write([{"id": "abc", "title": "x"}])
        resp = client.put(
            "/known-issues/nope", json={"status": "resolved"}, headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 404)

    def test_delete_requires_admin_401(self) -> None:
        self._write([{"id": "abc", "title": "x"}])
        resp = client.delete("/known-issues/abc")
        self.assertEqual(resp.status_code, 401)

    def test_delete_as_admin(self) -> None:
        self._write([{"id": "abc", "title": "x"}])
        resp = client.delete("/known-issues/abc", headers=_admin_headers())
        self.assertEqual(resp.status_code, 204)
        get_resp = client.get("/known-issues")
        self.assertEqual(get_resp.json()["issues"], [])

    def test_delete_unknown_id_returns_404(self) -> None:
        self._write([{"id": "abc", "title": "x"}])
        resp = client.delete("/known-issues/nope", headers=_admin_headers())
        self.assertEqual(resp.status_code, 404)

    def test_get_reflects_backfilled_ids_from_legacy_entries(self) -> None:
        self._write([{
            "title": "GPU issue", "description": "d", "severity": "medium",
            "opened_at": "2026-07-24", "status": "acknowledged", "area": "GPU / Infra",
        }])
        data = client.get("/known-issues").json()
        issue = data["issues"][0]
        self.assertIn("id", issue)
        self.assertEqual(issue["title"], "GPU issue")
        self.assertEqual(issue["area"], "GPU / Infra")


if __name__ == "__main__":
    unittest.main()
