"""
tests/test_hipaa_readiness.py

Unit tests for control_center.api.routes_hipaa_readiness and
control_center.hipaa_compliance.catalog_seed's HIPAA-readiness control
tracking: manage_all_orgs-gated CRUD on controls/evidence/risks/exceptions,
the independent implementation/testing/deployment/operational-verification
lifecycle dimensions and their derived overall_status, append-only history
with actor attribution, legacy HipaaComplianceChange mapping preservation,
rejection of secret/PHI-like evidence metadata, and seed_initial_catalog()'s
idempotent, non-destructive seeding of the initial control catalog.

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
from control_center.hipaa_compliance.catalog_seed import INITIAL_CATALOG, seed_initial_catalog
from control_center.hipaa_compliance.models import HipaaComplianceChange, HipaaControl, HipaaControlEvidence, HipaaControlRisk, HipaaLegacyChangeMapping, HipaaReadinessHistory
from control_center.hipaa_compliance.seed import seed_initial_data
from control_center.main import app

client = TestClient(app)


def _headers(permissions=None, **claims):
    """A bearer-token Authorization header, defaulting to manage_all_orgs, with extra JWT claims merged in."""
    token = jwt.encode({"sub": "admin-1", "email": "admin@example.test", "permissions": ["manage_all_orgs"] if permissions is None else permissions, **claims}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


CONTROL = {
    "control_key": "IAM-001",
    "title": "Access control inventory",
    "description": "Synthetic non-PHI fixture",
    "domain": "identity_access_management",
}


class ReadinessRoutesTestCase(unittest.TestCase):
    """Base fixture: in-memory SQLite HIPAA-readiness DB, dependency-overridden into the app for the duration of each test."""

    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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

    def _create_control(self, **overrides):
        """POST a control built from the CONTROL fixture (with overrides merged in) and return the created record."""
        body = {**CONTROL, **overrides}
        resp = client.post("/hipaa-compliance/controls", json=body, headers=_headers())
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()


class AuthorizationTests(ReadinessRoutesTestCase):
    """manage_all_orgs-only access to the HIPAA-readiness control endpoints."""

    def test_unauthenticated_denied(self):
        """A request with no token is rejected with 401."""
        self.assertEqual(client.get("/hipaa-compliance/controls").status_code, 401)

    def test_ordinary_user_denied(self):
        """A token with no permissions is rejected with 403."""
        resp = client.get("/hipaa-compliance/controls", headers=_headers(permissions=[]))
        self.assertEqual(resp.status_code, 403)

    def test_org_admin_without_global_permission_denied(self):
        """An org-scoped manage_org permission is not sufficient; creation requires manage_all_orgs and is rejected with 403."""
        resp = client.post("/hipaa-compliance/controls", json=CONTROL, headers=_headers(permissions=["manage_org"]))
        self.assertEqual(resp.status_code, 403)

    def test_global_admin_success(self):
        """A manage_all_orgs token is allowed through with 200."""
        self.assertEqual(client.get("/hipaa-compliance/controls", headers=_headers()).status_code, 200)


class ControlModelTests(ReadinessRoutesTestCase):
    """The control lifecycle-status model: independent dimensions, their filtering, and their derived overall_status."""

    def test_create_defaults_to_unknown_not_pass(self):
        """A newly created control defaults every lifecycle dimension and overall_status to "unknown", with zero evidence."""
        body = self._create_control()
        self.assertEqual(body["implementation_status"], "unknown")
        self.assertEqual(body["testing_status"], "unknown")
        self.assertEqual(body["deployment_status"], "unknown")
        self.assertEqual(body["operational_verification_status"], "unknown")
        self.assertEqual(body["overall_status"], "unknown")
        self.assertEqual(body["evidence_count"], 0)

    def test_independent_lifecycle_dimensions_and_filtering(self):
        """Controls are filterable by each lifecycle dimension independently, and a mixed implemented/not_tested control's overall_status is "needs_work"."""
        self._create_control(implementation_status="implemented", testing_status="not_tested", deployment_status="deployed", operational_verification_status="not_verified")
        resp = client.get("/hipaa-compliance/controls", params={"implementation_status": "implemented", "testing_status": "not_tested"}, headers=_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)
        item = resp.json()["items"][0]
        self.assertEqual(item["overall_status"], "needs_work")

    def test_not_applicable_and_deferred_are_explicit(self):
        """A control marked not_applicable or deferred surfaces that as its overall_status rather than collapsing to unknown."""
        na = self._create_control(control_key="NA-1", applicability_status="not_applicable", implementation_status="not_applicable", testing_status="not_applicable", deployment_status="not_applicable", operational_verification_status="not_applicable")
        self.assertEqual(na["overall_status"], "not_applicable")
        deferred = self._create_control(control_key="DEF-1", applicability_status="deferred", implementation_status="deferred")
        self.assertEqual(deferred["overall_status"], "deferred")

    def test_status_validation(self):
        """An unrecognized implementation_status value ("verified") is rejected with 422."""
        resp = client.post("/hipaa-compliance/controls", json={**CONTROL, "implementation_status": "verified"}, headers=_headers())
        self.assertEqual(resp.status_code, 422)


class LinkageAndHistoryTests(ReadinessRoutesTestCase):
    """Evidence/risk/exception linkage onto a control, and its append-only, actor-attributed history log."""

    def test_evidence_risk_exception_linkage_and_exception_does_not_verify(self):
        """Evidence, an open risk, and an approved exception each increment the control's respective counts, but none of that flips operational_verification_status off "unknown"."""
        self._create_control()
        ev = client.post("/hipaa-compliance/controls/IAM-001/evidence", json={"evidence_type": "github_pr", "reference": "https://example.test/pr/1", "verification_result": "pass"}, headers=_headers())
        self.assertEqual(ev.status_code, 201, ev.text)
        risk = client.post("/hipaa-compliance/controls/IAM-001/risks", json={"description": "Synthetic gap", "severity": "medium"}, headers=_headers())
        self.assertEqual(risk.status_code, 201, risk.text)
        exc = client.post("/hipaa-compliance/controls/IAM-001/exceptions", json={"rationale": "Temporary synthetic exception", "scope": "test only", "status": "approved"}, headers=_headers())
        self.assertEqual(exc.status_code, 201, exc.text)

        control = client.get("/hipaa-compliance/controls/IAM-001", headers=_headers()).json()
        self.assertEqual(control["evidence_count"], 1)
        self.assertEqual(control["open_risk_count"], 1)
        self.assertEqual(control["active_exception_count"], 1)
        self.assertEqual(control["operational_verification_status"], "unknown")
        self.assertEqual(control["overall_status"], "unknown")

    def test_append_only_history_and_actor_attribution(self):
        """A patch is recorded in history attributed to the caller's email, and the history table rejects in-place row mutation."""
        self._create_control()
        client.patch("/hipaa-compliance/controls/IAM-001", json={"owner": "security", "change_reason": "assign owner"}, headers=_headers())
        history = client.get("/hipaa-compliance/history", params={"entity_type": "control", "entity_id": "IAM-001"}, headers=_headers()).json()
        self.assertEqual(len(history), 2)
        self.assertTrue(all(h["actor"] == "admin@example.test" for h in history))
        db = self.session_local()
        row = db.query(HipaaReadinessHistory).first()
        row.reason = "mutated"
        with self.assertRaises(ValueError):
            db.commit()
        db.close()


class LegacyAndSecurityTests(ReadinessRoutesTestCase):
    """Preservation of pre-existing HipaaComplianceChange rows as unmapped legacy data, and rejection of unsafe evidence metadata."""

    def test_legacy_data_preserved_and_unmapped(self):
        """A pre-existing legacy change is exposed via /legacy-mappings as unmapped, and remains readable via /changes/{id}."""
        db = self.session_local()
        db.add(HipaaComplianceChange(change_id="LEG-1", title="Legacy", change_date=date(2026, 1, 1), repository="repo", control_category="audit_integrity", status="verified", evidence=[]))
        db.commit()
        db.close()
        resp = client.get("/hipaa-compliance/legacy-mappings", headers=_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["legacy_change_id"], "LEG-1")
        self.assertEqual(resp.json()[0]["mapping_status"], "unmapped")

        changes = client.get("/hipaa-compliance/changes/LEG-1", headers=_headers())
        self.assertEqual(changes.status_code, 200)

    def test_evidence_rejects_secret_or_phi_like_metadata(self):
        """Evidence whose reference looks like a credential (a "password=" value) is rejected with 422."""
        self._create_control()
        resp = client.post("/hipaa-compliance/controls/IAM-001/evidence", json={"evidence_type": "documentation", "reference": "password=abc123"}, headers=_headers())
        self.assertEqual(resp.status_code, 422)


class CatalogSeedTests(ReadinessRoutesTestCase):
    """seed_initial_catalog()'s idempotent, honest, non-destructive seeding of INITIAL_CATALOG into the readiness DB."""

    def test_catalog_seed_is_idempotent_with_stable_keys_and_no_duplicates(self):
        """A first seed inserts len(INITIAL_CATALOG) unique-keyed rows; a rerun inserts nothing further."""
        db = self.session_local()
        seed_initial_data(db)
        first = seed_initial_catalog(db)
        second = seed_initial_catalog(db)
        self.assertEqual(first["controls"], len(INITIAL_CATALOG))
        self.assertEqual(second, {"controls": 0, "evidence": 0, "risks": 0, "legacy_mappings": 0})
        self.assertEqual(db.query(HipaaControl).count(), len(INITIAL_CATALOG))
        keys = [row.control_key for row in db.query(HipaaControl).all()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), {control.control_key for control in INITIAL_CATALOG})
        db.close()

    def test_seed_does_not_overwrite_reviewed_state_on_rerun(self):
        """A control's manually reviewed testing_status/owner survive a re-run of seed_initial_catalog()."""
        db = self.session_local()
        seed_initial_data(db)
        seed_initial_catalog(db)
        control = db.query(HipaaControl).filter(HipaaControl.control_key == "REPORT-SOURCES-UNAVAILABLE-NOT-ZERO").one()
        control.testing_status = "partial"
        control.owner = "review-board"
        db.commit()
        seed_initial_catalog(db)
        db.refresh(control)
        self.assertEqual(control.testing_status, "partial")
        self.assertEqual(control.owner, "review-board")
        db.close()

    def test_unknown_and_partial_seed_states_remain_honest(self):
        """Seeded controls carry only the lifecycle states actually known: deployment/operational-verification stay "unknown" even when implementation/testing are set, and a partially-implemented control seeds as "partial" not "implemented"."""
        db = self.session_local()
        seed_initial_data(db)
        seed_initial_catalog(db)
        producer = db.query(HipaaControl).filter(HipaaControl.control_key == "AUD-SECURITY-AUDIT-PRODUCER-SIGNING").one()
        self.assertEqual(producer.implementation_status, "implemented")
        self.assertEqual(producer.testing_status, "tested")
        self.assertEqual(producer.deployment_status, "unknown")
        self.assertEqual(producer.operational_verification_status, "unknown")
        redis = db.query(HipaaControl).filter(HipaaControl.control_key == "REDIS-RAG-ROLE-SEPARATION").one()
        self.assertEqual(redis.implementation_status, "partial")
        self.assertEqual(redis.testing_status, "tested")
        self.assertEqual(redis.deployment_status, "unknown")
        db.close()

    def test_evidence_does_not_automatically_imply_verification(self):
        """A seeded control with evidence attached still has operational_verification_status "unknown" — evidence existing does not imply verification."""
        db = self.session_local()
        seed_initial_data(db)
        seed_initial_catalog(db)
        report = db.query(HipaaControl).filter(HipaaControl.control_key == "REPORT-CSV-FORMULA-INJECTION-SAFE").one()
        self.assertGreater(db.query(HipaaControlEvidence).filter(HipaaControlEvidence.control_id == report.id).count(), 0)
        self.assertEqual(report.operational_verification_status, "unknown")
        db.close()

    def test_legacy_verified_does_not_imply_all_lifecycle_states(self):
        """A legacy mapping's high-confidence "verified" status maps its control to implemented+tested, but leaves deployment and operational-verification "unknown" rather than assuming them."""
        db = self.session_local()
        seed_initial_data(db)
        seed_initial_catalog(db)
        mapping = db.query(HipaaLegacyChangeMapping).filter(HipaaLegacyChangeMapping.legacy_change_id == "SECURITY-AUDIT-PR8").one()
        control = db.get(HipaaControl, mapping.control_id)
        self.assertEqual(mapping.mapping_status, "mapped")
        self.assertIn("confidence=high", mapping.mapping_rationale)
        self.assertIn("legacy_status", mapping.mapping_rationale)
        self.assertEqual(control.implementation_status, "implemented")
        self.assertEqual(control.testing_status, "tested")
        self.assertEqual(control.deployment_status, "unknown")
        self.assertEqual(control.operational_verification_status, "unknown")
        db.close()

    def test_seeded_risks_are_linked_and_exceptions_are_not_fabricated(self):
        """Seeding creates risks only for the two controls that genuinely have known gaps, and creates zero exceptions for a control with a risk but no approved exception."""
        db = self.session_local()
        seed_initial_data(db)
        seed_initial_catalog(db)
        risk_controls = {row.control_key for row in db.query(HipaaControl).join(HipaaControlRisk).all()}
        self.assertEqual(risk_controls, {"AUD-RETENTION-CLEANUP-GUARDED", "REDIS-RAG-ROLE-SEPARATION"})
        self.assertEqual(db.query(HipaaControlRisk).count(), 2)
        db.close()
        risks = client.get("/hipaa-compliance/controls/REDIS-RAG-ROLE-SEPARATION/risks", headers=_headers()).json()
        self.assertEqual(len(risks), 1)
        exceptions = client.get("/hipaa-compliance/controls/REDIS-RAG-ROLE-SEPARATION/exceptions", headers=_headers()).json()
        self.assertEqual(exceptions, [])

    def test_catalog_filtering_by_partial_implementation(self):
        """Filtering the seeded catalog by implementation_status="partial" returns exactly the two partially-implemented controls."""
        db = self.session_local()
        seed_initial_data(db)
        seed_initial_catalog(db)
        db.close()
        resp = client.get("/hipaa-compliance/controls", params={"implementation_status": "partial", "page_size": 50}, headers=_headers())
        self.assertEqual(resp.status_code, 200)
        keys = {item["control_key"] for item in resp.json()["items"]}
        self.assertEqual(keys, {"AUD-RETENTION-CLEANUP-GUARDED", "REDIS-RAG-ROLE-SEPARATION"})

    def test_history_created_for_seeded_controls(self):
        """Seeding writes at least one history row per catalog control, all attributed to the "catalog-seed" actor and source."""
        db = self.session_local()
        seed_initial_data(db)
        seed_initial_catalog(db)
        history = db.query(HipaaReadinessHistory).filter(HipaaReadinessHistory.actor == "catalog-seed").all()
        self.assertGreaterEqual(len(history), len(INITIAL_CATALOG))
        self.assertTrue(all(h.source == "control-center-phase-c-catalog-seed" for h in history))
        db.close()

    def test_seed_rejects_unsafe_evidence_metadata(self):
        """_validate_seed_evidence() raises ValueError for a seed evidence reference that looks like a credential."""
        from control_center.hipaa_compliance.catalog_seed import CatalogEvidence, _validate_seed_evidence
        with self.assertRaises(ValueError):
            _validate_seed_evidence(CatalogEvidence("documentation", "password=abc123"))

    def test_api_evidence_deduplicates_same_reference(self):
        """Posting the same evidence reference twice for a control returns the same evidence id both times, not a duplicate."""
        self._create_control()
        body = {"evidence_type": "github_pr", "reference": "https://example.test/pr/1", "verification_result": "pass"}
        first = client.post("/hipaa-compliance/controls/IAM-001/evidence", json=body, headers=_headers())
        second = client.post("/hipaa-compliance/controls/IAM-001/evidence", json=body, headers=_headers())
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["id"], second.json()["id"])
        evidence = client.get("/hipaa-compliance/controls/IAM-001/evidence", headers=_headers()).json()
        self.assertEqual(len(evidence), 1)


if __name__ == "__main__":
    unittest.main()
