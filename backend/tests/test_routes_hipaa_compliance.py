"""tests/test_routes_hipaa_compliance.py -- HTTP-level tests for
/hipaa-compliance/changes[...], real FastAPI dependency injection against
an isolated in-memory SQLite DB (app.dependency_overrides[get_db]) plus a
real JWT signed against a patched JWT_SECRET -- mirrors test_main.py's
own `_admin_headers()` convention for this repo's other permission-gated
in-process routes.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest
from datetime import date

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from control_center.core.jwt_verify import JWT_SECRET
from control_center.hipaa_compliance.db import Base, get_db
from control_center.hipaa_compliance.models import HipaaComplianceChange
from control_center.main import app

client = TestClient(app)

VALID_CREATE_BODY = {
    "change_id": "NEW-1",
    "title": "New change",
    "change_date": "2026-08-15",
    "repository": "omnibioai-security-audit",
    "control_category": "audit_event_signing",
    "status": "verified",
}


def _headers(**claims) -> dict:
    """Authorization header for a token defaulting to manage_all_orgs,
    with any claim (including permissions) overridable by keyword."""
    permissions = claims.pop("permissions", ["manage_all_orgs"])
    token = jwt.encode({"sub": "1", "permissions": permissions, **claims}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


class HipaaComplianceRoutesTestCase(unittest.TestCase):
    """Base fixture: a real, isolated in-memory SQLite DB wired into
    the app via dependency_overrides, plus a _seed() helper."""

    def setUp(self):
        # StaticPool -- starlette's TestClient dispatches the actual
        # request on a separate thread from this one (run_in_threadpool),
        # and SQLite's default per-thread ":memory:" connection would
        # otherwise hand that thread a fresh, tableless database. Same
        # fix this ecosystem's own omnibioai-security-audit test fixtures
        # already use for the identical reason.
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        self.session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = self.session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.pop, get_db, None)

    def _seed(self, **overrides):
        """Insert and commit a HipaaComplianceChange row with sensible
        defaults, any field overridden by keyword."""
        db = self.session_local()
        defaults = {
            "change_id": "SEED-1",
            "title": "Seed change",
            "change_date": date(2026, 1, 1),
            "repository": "omnibioai-security-audit",
            "control_category": "audit_integrity",
            "status": "verified",
            "evidence": [],
        }
        defaults.update(overrides)
        db.add(HipaaComplianceChange(**defaults))
        db.commit()
        db.close()


# ---------------------------------------------------------------------------
# Authorization -- every route, reads included (this is admin-only data,
# not just admin-only writes -- see routes_hipaa_compliance.py's own
# module docstring).
# ---------------------------------------------------------------------------

class AuthorizationTests(HipaaComplianceRoutesTestCase):
    """Every route (reads included -- this is admin-only data, not just
    admin-only writes) requires manage_all_orgs."""

    def test_missing_auth_header_returns_401_on_list(self):
        """GET list with no Authorization header returns 401."""
        resp = client.get("/hipaa-compliance/changes")
        self.assertEqual(resp.status_code, 401)

    def test_missing_auth_header_returns_401_on_summary(self):
        """GET summary with no Authorization header returns 401."""
        resp = client.get("/hipaa-compliance/changes/summary")
        self.assertEqual(resp.status_code, 401)

    def test_missing_auth_header_returns_401_on_create(self):
        """POST create with no Authorization header returns 401."""
        resp = client.post("/hipaa-compliance/changes", json=VALID_CREATE_BODY)
        self.assertEqual(resp.status_code, 401)

    def test_malformed_auth_header_returns_401(self):
        """A non-Bearer Authorization header returns 401."""
        resp = client.get("/hipaa-compliance/changes", headers={"Authorization": "not-a-bearer-token"})
        self.assertEqual(resp.status_code, 401)

    def test_non_admin_permission_returns_403_on_list(self):
        """A token without manage_all_orgs returns 403 on list."""
        resp = client.get("/hipaa-compliance/changes", headers=_headers(permissions=["some.other.permission"]))
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_permission_returns_403_on_create(self):
        """A token without manage_all_orgs returns 403 on create."""
        resp = client.post(
            "/hipaa-compliance/changes", json=VALID_CREATE_BODY,
            headers=_headers(permissions=[]),
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_permission_returns_403_on_patch(self):
        """A token without manage_all_orgs returns 403 on patch."""
        self._seed()
        resp = client.patch(
            "/hipaa-compliance/changes/SEED-1", json={"status": "released"},
            headers=_headers(permissions=[]),
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_permission_returns_403_on_get_single(self):
        """A token without manage_all_orgs returns 403 on a single-item get."""
        self._seed()
        resp = client.get("/hipaa-compliance/changes/SEED-1", headers=_headers(permissions=[]))
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_permission_returns_403_on_summary(self):
        """A token without manage_all_orgs returns 403 on summary."""
        resp = client.get("/hipaa-compliance/changes/summary", headers=_headers(permissions=[]))
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

class ListAndGetTests(HipaaComplianceRoutesTestCase):
    """GET list/single/filter routes against a real seeded database."""

    def test_platform_admin_can_list_changes(self):
        """A platform admin's list request returns all seeded changes."""
        self._seed(change_id="A")
        self._seed(change_id="B")

        resp = client.get("/hipaa-compliance/changes", headers=_headers())

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual({i["change_id"] for i in body["items"]}, {"A", "B"})

    def test_get_single_change(self):
        """GET on a specific change_id returns that record's fields."""
        self._seed(change_id="A", title="A Title")

        resp = client.get("/hipaa-compliance/changes/A", headers=_headers())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], "A Title")

    def test_get_missing_change_returns_404(self):
        """GET on a nonexistent change_id returns 404."""
        resp = client.get("/hipaa-compliance/changes/does-not-exist", headers=_headers())
        self.assertEqual(resp.status_code, 404)

    def test_records_persist_across_requests(self):
        """"Compliance records persist" -- a POST followed by a separate
        GET (same client, two independent requests) sees the same data,
        not an in-memory-only echo."""
        create_resp = client.post("/hipaa-compliance/changes", json=VALID_CREATE_BODY, headers=_headers())
        self.assertEqual(create_resp.status_code, 201)

        get_resp = client.get("/hipaa-compliance/changes/NEW-1", headers=_headers())
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["title"], "New change")

    def test_list_filters_by_status_query_param(self):
        """A "status" query param filters the list to matching changes only."""
        self._seed(change_id="A", status="verified")
        self._seed(change_id="B", status="planned")

        resp = client.get("/hipaa-compliance/changes", params={"status": "planned"}, headers=_headers())

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["change_id"], "B")

    def test_evidence_round_trips_through_the_api(self):
        """An evidence entry submitted on create is returned unchanged on a later get."""
        body = {
            **VALID_CREATE_BODY,
            "change_id": "EV-1",
            "evidence": [{"type": "github_pr", "label": "PR #1", "url": "https://example.com/1"}],
        }
        create_resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(create_resp.status_code, 201)

        get_resp = client.get("/hipaa-compliance/changes/EV-1", headers=_headers())
        self.assertEqual(get_resp.json()["evidence"][0]["label"], "PR #1")


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------

class CreateUpdateTests(HipaaComplianceRoutesTestCase):
    """POST/PATCH create-and-update behavior against a real seeded database."""

    def test_create_returns_201_with_body(self):
        """A valid create returns 201 with the created change_id."""
        resp = client.post("/hipaa-compliance/changes", json=VALID_CREATE_BODY, headers=_headers())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["change_id"], "NEW-1")

    def test_create_duplicate_change_id_returns_409(self):
        """Creating a change_id that already exists returns 409."""
        self._seed(change_id="NEW-1")

        resp = client.post("/hipaa-compliance/changes", json=VALID_CREATE_BODY, headers=_headers())
        self.assertEqual(resp.status_code, 409)

    def test_patch_updates_status(self):
        """A PATCH updating status persists the new value."""
        self._seed(change_id="A", status="planned")

        resp = client.patch("/hipaa-compliance/changes/A", json={"status": "verified"}, headers=_headers())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "verified")

    def test_patch_missing_change_returns_404(self):
        """PATCH on a nonexistent change_id returns 404."""
        resp = client.patch("/hipaa-compliance/changes/nope", json={"status": "verified"}, headers=_headers())
        self.assertEqual(resp.status_code, 404)

    def test_patch_does_not_change_unspecified_fields(self):
        """A PATCH that only specifies status leaves other fields
        (title) unchanged."""
        self._seed(change_id="A", title="Original", status="planned")

        client.patch("/hipaa-compliance/changes/A", json={"status": "verified"}, headers=_headers())
        resp = client.get("/hipaa-compliance/changes/A", headers=_headers())

        self.assertEqual(resp.json()["title"], "Original")


# ---------------------------------------------------------------------------
# Invalid input rejected
# ---------------------------------------------------------------------------

class InvalidInputTests(HipaaComplianceRoutesTestCase):
    """Every field-level validation rule returns 422 for a bad value."""

    def test_create_rejects_invalid_status(self):
        """An unrecognized status value on create returns 422."""
        body = {**VALID_CREATE_BODY, "status": "not-a-real-status"}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_invalid_control_category(self):
        """An unrecognized control_category value on create returns 422."""
        body = {**VALID_CREATE_BODY, "control_category": "not-a-real-category"}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_missing_required_field(self):
        """Omitting a required field (title) on create returns 422."""
        body = {k: v for k, v in VALID_CREATE_BODY.items() if k != "title"}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_invalid_change_id_characters(self):
        """A change_id containing invalid characters returns 422."""
        body = {**VALID_CREATE_BODY, "change_id": "not a valid id!"}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_negative_pr_number(self):
        """A negative pr_number returns 422."""
        body = {**VALID_CREATE_BODY, "pr_number": -5}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_invalid_evidence_type(self):
        """An unrecognized evidence type returns 422."""
        body = {**VALID_CREATE_BODY, "evidence": [{"type": "not-a-real-type", "label": "x"}]}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_patch_rejects_invalid_status(self):
        """An unrecognized status value on patch returns 422."""
        self._seed(change_id="A")
        resp = client.patch("/hipaa-compliance/changes/A", json={"status": "bogus"}, headers=_headers())
        self.assertEqual(resp.status_code, 422)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class SummaryRouteTests(HipaaComplianceRoutesTestCase):
    """GET /hipaa-compliance/changes/summary against real seeded data."""

    def test_summary_reflects_seeded_data(self):
        """verified_count/exception_count/overall_status reflect the
        real seeded rows, and every one of the 8 fixed taxonomy
        categories is always present."""
        self._seed(change_id="A", status="verified", control_category="audit_integrity")
        self._seed(change_id="B", status="exception", control_category="access_control")

        resp = client.get("/hipaa-compliance/changes/summary", headers=_headers())

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["verified_count"], 1)
        self.assertEqual(body["exception_count"], 1)
        self.assertEqual(body["overall_status"], "attention_needed")
        self.assertEqual(len(body["controls"]), 8)  # full fixed taxonomy, always present


if __name__ == "__main__":
    unittest.main()
