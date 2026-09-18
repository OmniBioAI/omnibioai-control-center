"""
tests/test_routes_known_issues.py

Unit tests for:
  - control_center.api.routes_known_issues

Covers GET (anonymous, empty/missing/malformed file handling, backfilled
ids for legacy entries) and the admin-gated POST/PUT/DELETE mutations
(401 with no token, 403 for a non-admin or a PR3D-style admin-role-
without-permission or wrong-permission token, validation errors, 404 for
an unknown id, and successful create/update/delete).

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

client = TestClient(app)


def _admin_headers() -> dict:
    """Authorization header for a token holding all three platform.*
    permissions this route family checks."""
    token = jwt.encode(
        {
            "sub": "1",
            "roles": ["admin"],
            "permissions": [
                "platform.manage_infra",
                "platform.manage_cron",
                "platform.manage_content",
            ],
        },
        JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _user_headers() -> dict:
    """Authorization header for a plain, unprivileged user token."""
    token = jwt.encode({"sub": "2", "roles": ["user"], "permissions": []}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _admin_role_without_content_permission_headers() -> dict:
    """PR3D regression fixture: an "admin"-role token that lacks the
    platform.manage_content permission specifically -- proves the route no
    longer falls back to a role-string check."""
    token = jwt.encode(
        {"sub": "3", "roles": ["admin"], "permissions": ["platform.manage_infra"]},
        JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _cron_only_headers() -> dict:
    """PR3D isolation fixture: holds platform.manage_cron but not
    platform.manage_content -- must not be able to mutate known issues."""
    token = jwt.encode(
        {"sub": "4", "permissions": ["platform.manage_cron"]},
        JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class TestKnownIssuesRoutes(unittest.TestCase):
    """GET (open, no auth) and admin-gated POST/PUT/DELETE mutation
    routes for known_issues.json, backed by a real temp file per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        os.environ["WORKSPACE_ROOT"] = self._tmp
        self._issues_path = Path(self._tmp) / "omnibioai-work" / "known_issues.json"

    def tearDown(self) -> None:
        del os.environ["WORKSPACE_ROOT"]
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, issues: list) -> None:
        """Write `issues` as the backing known_issues.json fixture file."""
        self._issues_path.parent.mkdir(parents=True, exist_ok=True)
        self._issues_path.write_text(json.dumps(issues))

    def test_get_open_no_auth_required(self) -> None:
        """GET /known-issues succeeds without any Authorization header."""
        self._write([])
        resp = client.get("/known-issues")
        self.assertEqual(resp.status_code, 200)

    def test_get_malformed_file_returns_500(self) -> None:
        """A known_issues.json file that isn't valid JSON returns 500."""
        self._issues_path.parent.mkdir(parents=True, exist_ok=True)
        self._issues_path.write_text("not valid json")
        resp = client.get("/known-issues")
        self.assertEqual(resp.status_code, 500)

    def test_get_missing_file_returns_empty_list(self) -> None:
        """A missing known_issues.json file returns an empty issues list,
        not an error."""
        resp = client.get("/known-issues")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"issues": []})

    def test_post_requires_admin_401(self) -> None:
        """POST with no Authorization header returns 401."""
        self._write([])
        resp = client.post("/known-issues", json={"title": "x"})
        self.assertEqual(resp.status_code, 401)

    def test_post_requires_admin_403_for_non_admin(self) -> None:
        """POST with a plain user token returns 403."""
        self._write([])
        resp = client.post("/known-issues", json={"title": "x"}, headers=_user_headers())
        self.assertEqual(resp.status_code, 403)

    def test_post_403_for_admin_role_without_content_permission(self) -> None:
        """POST with an "admin"-role token that lacks platform.manage_
        content specifically still returns 403 -- no role-string fallback."""
        self._write([])
        resp = client.post(
            "/known-issues", json={"title": "x"}, headers=_admin_role_without_content_permission_headers(),
        )
        self.assertEqual(resp.status_code, 403)

    def test_post_403_for_cron_permission_only(self) -> None:
        """Isolation: platform.manage_cron must not satisfy the
        platform.manage_content check this route requires."""
        self._write([])
        resp = client.post("/known-issues", json={"title": "x"}, headers=_cron_only_headers())
        self.assertEqual(resp.status_code, 403)

    def test_post_creates_issue_as_admin(self) -> None:
        """An admin's POST creates the issue with a generated id, and it
        shows up on a subsequent GET."""
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
        """PUT with no Authorization header returns 401."""
        self._write([{"id": "abc", "title": "x"}])
        resp = client.put("/known-issues/abc", json={"status": "resolved"})
        self.assertEqual(resp.status_code, 401)

    def test_put_updates_as_admin(self) -> None:
        """An admin's PUT updates the issue's status."""
        self._write([{"id": "abc", "title": "x", "status": "open"}])
        resp = client.put(
            "/known-issues/abc", json={"status": "resolved"}, headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "resolved")

    def test_post_invalid_severity_returns_400(self) -> None:
        """An unrecognized severity value returns 400."""
        self._write([])
        resp = client.post(
            "/known-issues",
            json={"title": "x", "severity": "critical"},
            headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_invalid_status_returns_400(self) -> None:
        """An unrecognized status value returns 400."""
        self._write([{"id": "abc", "title": "x"}])
        resp = client.put(
            "/known-issues/abc", json={"status": "wontfix"}, headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_unknown_id_returns_404(self) -> None:
        """PUT on an id not present in the file returns 404."""
        self._write([{"id": "abc", "title": "x"}])
        resp = client.put(
            "/known-issues/nope", json={"status": "resolved"}, headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 404)

    def test_delete_requires_admin_401(self) -> None:
        """DELETE with no Authorization header returns 401."""
        self._write([{"id": "abc", "title": "x"}])
        resp = client.delete("/known-issues/abc")
        self.assertEqual(resp.status_code, 401)

    def test_delete_as_admin(self) -> None:
        """An admin's DELETE removes the issue, confirmed by a follow-up GET."""
        self._write([{"id": "abc", "title": "x"}])
        resp = client.delete("/known-issues/abc", headers=_admin_headers())
        self.assertEqual(resp.status_code, 204)
        get_resp = client.get("/known-issues")
        self.assertEqual(get_resp.json()["issues"], [])

    def test_delete_unknown_id_returns_404(self) -> None:
        """DELETE on an id not present in the file returns 404."""
        self._write([{"id": "abc", "title": "x"}])
        resp = client.delete("/known-issues/nope", headers=_admin_headers())
        self.assertEqual(resp.status_code, 404)

    def test_get_reflects_backfilled_ids_from_legacy_entries(self) -> None:
        """A legacy issue entry with no "id" field at all still gets an
        id backfilled on read, with its other fields unchanged."""
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
