"""
tests/test_check_license_status.py

Unit tests for:
  - control_center.checks.license_status
"""

from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import license_status


def _cursor_ctx(cursor: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestParseDate(unittest.TestCase):

    def test_parses_iso_date(self) -> None:
        self.assertEqual(license_status._parse_date("2026-01-15"), datetime.date(2026, 1, 15))

    def test_none_returns_none(self) -> None:
        self.assertIsNone(license_status._parse_date(None))

    def test_malformed_returns_none(self) -> None:
        self.assertIsNone(license_status._parse_date("not-a-date"))


class TestDeriveStatus(unittest.TestCase):

    def setUp(self) -> None:
        self.today = datetime.date(2026, 6, 1)

    def test_no_expiry_is_expired(self) -> None:
        self.assertEqual(license_status._derive_status(None, 1, self.today), "expired")

    def test_inactive_is_expired_even_if_not_past_expiry(self) -> None:
        self.assertEqual(license_status._derive_status("2027-01-01", 0, self.today), "expired")

    def test_past_expiry_is_expired_even_if_active_flag_set(self) -> None:
        self.assertEqual(license_status._derive_status("2025-01-01", 1, self.today), "expired")

    def test_within_30_days_is_expiring(self) -> None:
        self.assertEqual(license_status._derive_status("2026-06-20", 1, self.today), "expiring")

    def test_far_future_is_active(self) -> None:
        self.assertEqual(license_status._derive_status("2027-01-01", 1, self.today), "active")

    def test_exactly_on_boundary_is_expiring(self) -> None:
        boundary = self.today + datetime.timedelta(days=license_status._EXPIRING_SOON_DAYS)
        self.assertEqual(license_status._derive_status(boundary.isoformat(), 1, self.today), "expiring")


class TestGetLicenseStatus(unittest.TestCase):

    def test_connect_failure_returns_empty(self) -> None:
        with patch("pymysql.connect", side_effect=ConnectionError("down")):
            result = license_status.get_license_status()
        self.assertEqual(result, dict(license_status._EMPTY))

    def test_query_failure_returns_empty_and_closes_conn(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("bad query")
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)
        with patch("pymysql.connect", return_value=conn):
            result = license_status.get_license_status()
        self.assertEqual(result, dict(license_status._EMPTY))
        conn.close.assert_called_once()

    def test_computes_seats_and_statuses(self) -> None:
        today = datetime.date.today()
        far_future = (today + datetime.timedelta(days=400)).isoformat()
        soon = (today + datetime.timedelta(days=5)).isoformat()
        past = (today - datetime.timedelta(days=5)).isoformat()

        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("active@example.com", "pro", far_future, 1),
            ("expiring@example.com", "pro", soon, 1),
            ("expired@example.com", "pro", past, 1),
            ("inactive@example.com", "pro", far_future, 0),
        ]
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)

        with patch("pymysql.connect", return_value=conn):
            result = license_status.get_license_status()

        self.assertEqual(result["seats_total"], 4)
        self.assertEqual(result["seats_used"], 1)
        statuses = {lic["org"]: lic["status"] for lic in result["licenses"]}
        self.assertEqual(statuses["active@example.com"], "active")
        self.assertEqual(statuses["expiring@example.com"], "expiring")
        self.assertEqual(statuses["expired@example.com"], "expired")
        self.assertEqual(statuses["inactive@example.com"], "expired")
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
