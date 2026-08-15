"""tests/test_hipaa_compliance_db.py -- control_center.hipaa_compliance.db

Covers the lazy-init/memoization behavior directly (the real module-level
`engine`/`SessionLocal` is never exercised by test_routes_hipaa_compliance.py,
which overrides `get_db` outright) -- see db.py's own module docstring for
why that split exists.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from control_center.hipaa_compliance import db as db_module


class InitDbTests(unittest.TestCase):
    def test_init_db_creates_table_on_given_engine(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        with patch.object(db_module, "engine", engine):
            db_module.init_db()
        inspector = inspect(engine)
        self.assertIn("hipaa_compliance_changes", inspector.get_table_names())

    def test_init_db_is_idempotent(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        with patch.object(db_module, "engine", engine):
            db_module.init_db()
            db_module.init_db()  # must not raise on the second call
        inspector = inspect(engine)
        self.assertIn("hipaa_compliance_changes", inspector.get_table_names())


class EnsureInitializedTests(unittest.TestCase):
    def setUp(self):
        # Isolate the module-level `_initialized` flag per test -- other
        # test modules in this file/suite must not see it as already
        # True (or False) because of ordering.
        self._flag_patcher = patch.object(db_module, "_initialized", False)
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.engine_patcher = patch.object(db_module, "engine", engine)
        self.engine_patcher.start()
        self.addCleanup(self.engine_patcher.stop)
        self.session_patcher = patch.object(db_module, "SessionLocal", session_local)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

    def test_ensure_initialized_creates_table_and_seeds_once(self):
        from control_center.hipaa_compliance.models import HipaaComplianceChange

        db_module._ensure_initialized()
        self.assertTrue(db_module._initialized)

        session = db_module.SessionLocal()
        try:
            count = session.query(HipaaComplianceChange).count()
        finally:
            session.close()
        self.assertGreater(count, 0)  # seed.py's SEED_CHANGES landed

    def test_ensure_initialized_second_call_is_a_no_op(self):
        # wraps=... -- init_db's real body still runs (the table must
        # actually exist for _ensure_initialized's own seed_initial_data
        # call not to blow up on the second, memoization-only check
        # below), this only counts how many times it was invoked.
        with patch.object(db_module, "init_db", wraps=db_module.init_db) as mock_init:
            db_module._ensure_initialized()
            db_module._ensure_initialized()
        mock_init.assert_called_once()

    def test_get_db_yields_a_working_session_and_closes_it(self):
        gen = db_module.get_db()
        session = next(gen)
        self.assertIsNotNone(session)
        with self.assertRaises(StopIteration):
            next(gen)
