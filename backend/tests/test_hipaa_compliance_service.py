"""tests/test_hipaa_compliance_service.py -- SQL/aggregation-level tests
for control_center.hipaa_compliance.service, against a real isolated
in-memory SQLite DB (not mocked) -- mirrors this ecosystem's own
audit_query_service test split (SQL correctness here, HTTP-level auth/
wiring in test_routes_hipaa_compliance.py)."""
from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from control_center.hipaa_compliance import service
from control_center.hipaa_compliance.db import Base
from control_center.hipaa_compliance.models import HipaaComplianceChange
from control_center.hipaa_compliance.schemas import (
    ComplianceControlCategory,
    EvidenceRef,
    HipaaComplianceChangeCreate,
    HipaaComplianceChangeUpdate,
)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = session_local()
        self.addCleanup(self.db.close)

    def _row(self, **overrides):
        defaults = {
            "change_id": "X-1",
            "title": "Test change",
            "change_date": date(2026, 1, 1),
            "repository": "omnibioai-security-audit",
            "control_category": "audit_integrity",
            "status": "verified",
            "evidence": [],
        }
        defaults.update(overrides)
        row = HipaaComplianceChange(**defaults)
        self.db.add(row)
        self.db.commit()
        return row


class ListChangesTests(ServiceTestCase):
    def test_orders_newest_first(self):
        self._row(change_id="A", change_date=date(2026, 1, 1))
        self._row(change_id="B", change_date=date(2026, 3, 1))
        self._row(change_id="C", change_date=date(2026, 2, 1))

        rows, total = service.list_changes(self.db, page=1, page_size=20)

        self.assertEqual(total, 3)
        self.assertEqual([r.change_id for r in rows], ["B", "C", "A"])

    def test_filters_by_status(self):
        self._row(change_id="A", status="verified")
        self._row(change_id="B", status="planned")

        rows, total = service.list_changes(self.db, page=1, page_size=20, status="planned")

        self.assertEqual(total, 1)
        self.assertEqual(rows[0].change_id, "B")

    def test_filters_by_control_category(self):
        self._row(change_id="A", control_category="audit_event_signing")
        self._row(change_id="B", control_category="access_control")

        rows, total = service.list_changes(
            self.db, page=1, page_size=20, control_category="access_control"
        )

        self.assertEqual(total, 1)
        self.assertEqual(rows[0].change_id, "B")

    def test_filters_by_repository(self):
        self._row(change_id="A", repository="omnibioai-security-audit")
        self._row(change_id="B", repository="omnibioai-control-center")

        rows, total = service.list_changes(
            self.db, page=1, page_size=20, repository="omnibioai-control-center"
        )

        self.assertEqual(total, 1)
        self.assertEqual(rows[0].change_id, "B")

    def test_pagination(self):
        for i in range(5):
            self._row(change_id=f"C{i}", change_date=date(2026, 1, i + 1))

        page1, total = service.list_changes(self.db, page=1, page_size=2)
        page2, _ = service.list_changes(self.db, page=2, page_size=2)

        self.assertEqual(total, 5)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        self.assertEqual({r.change_id for r in page1} & {r.change_id for r in page2}, set())


class CreateGetChangeTests(ServiceTestCase):
    def test_create_persists_all_fields(self):
        payload = HipaaComplianceChangeCreate(
            change_id="NEW-1",
            title="New change",
            change_date=date(2026, 8, 15),
            repository="omnibioai-security-audit",
            branch="feature/x",
            commit_sha="abc123",
            pr_number=42,
            description="A description",
            control_category=ComplianceControlCategory.AUDIT_EVENT_SIGNING,
            affected_component="audit/logger.py",
            status="verified",
            verification_result="10/10 passed",
            reviewer="alice",
            evidence=[EvidenceRef(type="github_pr", label="PR #42", url="https://example.com/42")],
            notes="Some notes",
        )

        created = service.create_change(self.db, payload)

        self.assertEqual(created.change_id, "NEW-1")
        self.assertEqual(created.control_category, "audit_event_signing")
        self.assertEqual(
            created.evidence,
            [{"type": "github_pr", "label": "PR #42", "url": "https://example.com/42", "identifier": None}],
        )

        fetched = service.get_change(self.db, "NEW-1")
        self.assertEqual(fetched.title, "New change")
        self.assertEqual(fetched.pr_number, 42)

    def test_create_duplicate_id_raises(self):
        self._row(change_id="DUP-1")
        payload = HipaaComplianceChangeCreate(
            change_id="DUP-1",
            title="Another",
            change_date=date(2026, 1, 1),
            repository="r",
            control_category=ComplianceControlCategory.OTHER,
            status="planned",
        )

        with self.assertRaises(service.ChangeAlreadyExistsError):
            service.create_change(self.db, payload)

    def test_get_missing_raises(self):
        with self.assertRaises(service.ChangeNotFoundError):
            service.get_change(self.db, "does-not-exist")


class UpdateChangeTests(ServiceTestCase):
    def test_partial_update(self):
        self._row(change_id="U-1", status="planned", title="Original title")

        updated = service.update_change(
            self.db, "U-1", HipaaComplianceChangeUpdate(status="verified")
        )

        self.assertEqual(updated.status, "verified")
        self.assertEqual(updated.title, "Original title")

    def test_update_control_category(self):
        self._row(change_id="U-2", control_category="other")

        updated = service.update_change(
            self.db, "U-2",
            HipaaComplianceChangeUpdate(control_category=ComplianceControlCategory.ACCESS_CONTROL),
        )

        self.assertEqual(updated.control_category, "access_control")

    def test_missing_raises(self):
        with self.assertRaises(service.ChangeNotFoundError):
            service.update_change(self.db, "nope", HipaaComplianceChangeUpdate(status="verified"))


class SummaryTests(ServiceTestCase):
    def test_empty_table(self):
        summary = service.build_summary(self.db)

        self.assertEqual(summary.overall_status, "no_data")
        self.assertEqual(summary.total_controls_tracked, 0)
        self.assertEqual(summary.verified_count, 0)
        self.assertEqual(summary.pending_count, 0)
        self.assertEqual(summary.exception_count, 0)
        self.assertIsNone(summary.latest_change_id)
        self.assertEqual(len(summary.controls), len(ComplianceControlCategory))
        self.assertTrue(all(c.total == 0 for c in summary.controls))

    def test_counts_and_latest(self):
        self._row(change_id="A", status="verified", control_category="audit_integrity",
                   change_date=date(2026, 1, 1))
        self._row(change_id="B", status="released", control_category="access_control",
                   change_date=date(2026, 3, 1), title="Latest one")
        self._row(change_id="C", status="planned", control_category="access_control",
                   change_date=date(2026, 2, 1))
        self._row(change_id="D", status="exception", control_category="data_integrity",
                   change_date=date(2026, 1, 15))

        summary = service.build_summary(self.db)

        self.assertEqual(summary.verified_count, 2)
        self.assertEqual(summary.pending_count, 1)
        self.assertEqual(summary.exception_count, 1)
        self.assertEqual(summary.total_controls_tracked, 3)
        self.assertEqual(summary.overall_status, "attention_needed")
        self.assertEqual(summary.latest_change_id, "B")
        self.assertEqual(summary.latest_change_title, "Latest one")

    def test_on_track_when_all_verified_no_exceptions(self):
        self._row(change_id="A", status="verified")
        self._row(change_id="B", status="released")

        summary = service.build_summary(self.db)

        self.assertEqual(summary.overall_status, "on_track")

    def test_in_progress_when_pending_present_no_exceptions(self):
        self._row(change_id="A", status="verified")
        self._row(change_id="B", status="planned")

        summary = service.build_summary(self.db)

        self.assertEqual(summary.overall_status, "in_progress")

    def test_control_summary_counts_per_category(self):
        self._row(change_id="A", control_category="audit_event_signing", status="verified")
        self._row(change_id="B", control_category="audit_event_signing", status="planned")

        summary = service.build_summary(self.db)

        signing = next(c for c in summary.controls if c.category.value == "audit_event_signing")
        self.assertEqual(signing.total, 2)
        self.assertEqual(signing.verified, 1)
        self.assertEqual(signing.pending, 1)
        self.assertEqual(signing.exceptions, 0)


if __name__ == "__main__":
    unittest.main()
