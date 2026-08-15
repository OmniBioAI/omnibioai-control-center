"""tests/test_hipaa_compliance_seed.py -- control_center.hipaa_compliance.seed

Verifies the seed is idempotent and that every seeded record's status
reflects real, GitHub-verifiable state -- in particular, that no
unmerged change is ever seeded as "released" (this feature's own
explicit, non-negotiable rule)."""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from control_center.hipaa_compliance import seed as seed_module
from control_center.hipaa_compliance.db import Base
from control_center.hipaa_compliance.models import HipaaComplianceChange
from control_center.hipaa_compliance.schemas import (
    ComplianceControlCategory,
    ComplianceStatus,
    EvidenceType,
)

EXPECTED_SEED_IDS = {"SECURITY-AUDIT-PR8", "SECURITY-AUDIT-PR9", "CC-PR45", "CC-PR46"}


class SeedTestCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = session_local()
        self.addCleanup(self.db.close)


class SeedDataShapeTests(unittest.TestCase):
    """Static checks on SEED_CHANGES itself -- every field must validate
    against this feature's own schema, not just happen to insert
    successfully."""

    def test_exactly_the_four_verified_changes(self):
        ids = {c["change_id"] for c in seed_module.SEED_CHANGES}
        self.assertEqual(ids, EXPECTED_SEED_IDS)

    def test_every_status_is_a_valid_enum_value(self):
        for change in seed_module.SEED_CHANGES:
            ComplianceStatus(change["status"])  # raises ValueError if invalid

    def test_every_control_category_is_a_valid_enum_value(self):
        for change in seed_module.SEED_CHANGES:
            ComplianceControlCategory(change["control_category"])

    def test_every_evidence_type_is_valid(self):
        for change in seed_module.SEED_CHANGES:
            for ev in change["evidence"]:
                EvidenceType(ev["type"])

    def test_no_seeded_record_has_a_reviewer_that_was_never_verified(self):
        # None of the 4 source PRs had a recorded GitHub review -- see
        # seed.py's own module docstring. reviewer must stay None, not an
        # invented approver.
        for change in seed_module.SEED_CHANGES:
            self.assertIsNone(change["reviewer"])

    def test_every_seeded_record_has_at_least_one_evidence_entry(self):
        for change in seed_module.SEED_CHANGES:
            self.assertGreater(len(change["evidence"]), 0, change["change_id"])


class SeedInsertionTests(SeedTestCase):
    def test_inserts_all_four_on_empty_table(self):
        inserted = seed_module.seed_initial_data(self.db)

        self.assertEqual(inserted, 4)
        ids = {row.change_id for row in self.db.query(HipaaComplianceChange).all()}
        self.assertEqual(ids, EXPECTED_SEED_IDS)

    def test_idempotent_second_call_inserts_nothing(self):
        seed_module.seed_initial_data(self.db)
        second_pass = seed_module.seed_initial_data(self.db)

        self.assertEqual(second_pass, 0)
        self.assertEqual(self.db.query(HipaaComplianceChange).count(), 4)

    def test_does_not_overwrite_a_row_a_platform_admin_already_edited(self):
        seed_module.seed_initial_data(self.db)
        row = self.db.get(HipaaComplianceChange, "CC-PR46")
        row.notes = "Edited by an admin after seeding"
        self.db.commit()

        seed_module.seed_initial_data(self.db)  # re-run, e.g. on a restart

        row = self.db.get(HipaaComplianceChange, "CC-PR46")
        self.assertEqual(row.notes, "Edited by an admin after seeding")

    def test_no_unmerged_change_is_ever_seeded_as_released_without_evidence(self):
        """Every seeded 'released' record must carry a github_pr evidence
        entry -- this is the closest this test suite can get to
        mechanically enforcing "never mark an unmerged change Released"
        without making a live network call in a unit test."""
        for change in seed_module.SEED_CHANGES:
            if change["status"] == "released":
                types = {ev["type"] for ev in change["evidence"]}
                self.assertIn("github_pr", types, change["change_id"])


if __name__ == "__main__":
    unittest.main()
