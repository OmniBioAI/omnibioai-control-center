"""tests/test_routes_hipaa_compliance.py -- HTTP-level tests for
/hipaa-compliance/changes[...], real FastAPI dependency injection against
an isolated in-memory SQLite DB (app.dependency_overrides[get_db]) plus a
real JWT signed against a patched JWT_SECRET -- mirrors test_main.py's
own `_admin_headers()` convention for this repo's other permission-gated
in-process routes.
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
    permissions = claims.pop("permissions", ["manage_all_orgs"])
    token = jwt.encode({"sub": "1", "permissions": permissions, **claims}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


class HipaaComplianceRoutesTestCase(unittest.TestCase):
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
    def test_missing_auth_header_returns_401_on_list(self):
        resp = client.get("/hipaa-compliance/changes")
        self.assertEqual(resp.status_code, 401)

    def test_missing_auth_header_returns_401_on_summary(self):
        resp = client.get("/hipaa-compliance/changes/summary")
        self.assertEqual(resp.status_code, 401)

    def test_missing_auth_header_returns_401_on_create(self):
        resp = client.post("/hipaa-compliance/changes", json=VALID_CREATE_BODY)
        self.assertEqual(resp.status_code, 401)

    def test_malformed_auth_header_returns_401(self):
        resp = client.get("/hipaa-compliance/changes", headers={"Authorization": "not-a-bearer-token"})
        self.assertEqual(resp.status_code, 401)

    def test_non_admin_permission_returns_403_on_list(self):
        resp = client.get("/hipaa-compliance/changes", headers=_headers(permissions=["some.other.permission"]))
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_permission_returns_403_on_create(self):
        resp = client.post(
            "/hipaa-compliance/changes", json=VALID_CREATE_BODY,
            headers=_headers(permissions=[]),
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_permission_returns_403_on_patch(self):
        self._seed()
        resp = client.patch(
            "/hipaa-compliance/changes/SEED-1", json={"status": "released"},
            headers=_headers(permissions=[]),
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_permission_returns_403_on_get_single(self):
        self._seed()
        resp = client.get("/hipaa-compliance/changes/SEED-1", headers=_headers(permissions=[]))
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_permission_returns_403_on_summary(self):
        resp = client.get("/hipaa-compliance/changes/summary", headers=_headers(permissions=[]))
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

class ListAndGetTests(HipaaComplianceRoutesTestCase):
    def test_platform_admin_can_list_changes(self):
        self._seed(change_id="A")
        self._seed(change_id="B")

        resp = client.get("/hipaa-compliance/changes", headers=_headers())

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual({i["change_id"] for i in body["items"]}, {"A", "B"})

    def test_get_single_change(self):
        self._seed(change_id="A", title="A Title")

        resp = client.get("/hipaa-compliance/changes/A", headers=_headers())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], "A Title")

    def test_get_missing_change_returns_404(self):
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
        self._seed(change_id="A", status="verified")
        self._seed(change_id="B", status="planned")

        resp = client.get("/hipaa-compliance/changes", params={"status": "planned"}, headers=_headers())

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["change_id"], "B")

    def test_evidence_round_trips_through_the_api(self):
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
    def test_create_returns_201_with_body(self):
        resp = client.post("/hipaa-compliance/changes", json=VALID_CREATE_BODY, headers=_headers())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["change_id"], "NEW-1")

    def test_create_duplicate_change_id_returns_409(self):
        self._seed(change_id="NEW-1")

        resp = client.post("/hipaa-compliance/changes", json=VALID_CREATE_BODY, headers=_headers())
        self.assertEqual(resp.status_code, 409)

    def test_patch_updates_status(self):
        self._seed(change_id="A", status="planned")

        resp = client.patch("/hipaa-compliance/changes/A", json={"status": "verified"}, headers=_headers())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "verified")

    def test_patch_missing_change_returns_404(self):
        resp = client.patch("/hipaa-compliance/changes/nope", json={"status": "verified"}, headers=_headers())
        self.assertEqual(resp.status_code, 404)

    def test_patch_does_not_change_unspecified_fields(self):
        self._seed(change_id="A", title="Original", status="planned")

        client.patch("/hipaa-compliance/changes/A", json={"status": "verified"}, headers=_headers())
        resp = client.get("/hipaa-compliance/changes/A", headers=_headers())

        self.assertEqual(resp.json()["title"], "Original")


# ---------------------------------------------------------------------------
# Invalid input rejected
# ---------------------------------------------------------------------------

class InvalidInputTests(HipaaComplianceRoutesTestCase):
    def test_create_rejects_invalid_status(self):
        body = {**VALID_CREATE_BODY, "status": "not-a-real-status"}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_invalid_control_category(self):
        body = {**VALID_CREATE_BODY, "control_category": "not-a-real-category"}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_missing_required_field(self):
        body = {k: v for k, v in VALID_CREATE_BODY.items() if k != "title"}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_invalid_change_id_characters(self):
        body = {**VALID_CREATE_BODY, "change_id": "not a valid id!"}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_negative_pr_number(self):
        body = {**VALID_CREATE_BODY, "pr_number": -5}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_invalid_evidence_type(self):
        body = {**VALID_CREATE_BODY, "evidence": [{"type": "not-a-real-type", "label": "x"}]}
        resp = client.post("/hipaa-compliance/changes", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_patch_rejects_invalid_status(self):
        self._seed(change_id="A")
        resp = client.patch("/hipaa-compliance/changes/A", json={"status": "bogus"}, headers=_headers())
        self.assertEqual(resp.status_code, 422)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class SummaryRouteTests(HipaaComplianceRoutesTestCase):
    def test_summary_reflects_seeded_data(self):
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
