"""
tests/test_check_license_status.py

Unit tests for:
  - control_center.checks.license_status

Covers date parsing (_parse_date), status derivation from expiry/active
flag (_derive_status: expired/expiring/active, including the exact
30-day boundary), and get_license_status()'s end-to-end MySQL query with
fail-safe handling of a connect or query failure (returns the empty
shape rather than raising, and always closes the connection).

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import license_status


def _cursor_ctx(cursor: MagicMock) -> MagicMock:
    """A context-manager mock wrapping a fake DB-API cursor."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestParseDate(unittest.TestCase):
    """_parse_date()'s ISO-date parsing, with None for missing/malformed input."""

    def test_parses_iso_date(self) -> None:
        """A valid "YYYY-MM-DD" string parses to the matching date object."""
        self.assertEqual(license_status._parse_date("2026-01-15"), datetime.date(2026, 1, 15))

    def test_none_returns_none(self) -> None:
        """A None input returns None rather than raising."""
        self.assertIsNone(license_status._parse_date(None))

    def test_malformed_returns_none(self) -> None:
        """An unparseable string returns None rather than raising."""
        self.assertIsNone(license_status._parse_date("not-a-date"))


class TestDeriveStatus(unittest.TestCase):
    """_derive_status()'s expired/expiring/active classification rules."""

    def setUp(self) -> None:
        self.today = datetime.date(2026, 6, 1)

    def test_no_expiry_is_expired(self) -> None:
        """No expiry date at all is treated as expired."""
        self.assertEqual(license_status._derive_status(None, 1, self.today), "expired")

    def test_inactive_is_expired_even_if_not_past_expiry(self) -> None:
        """An inactive (active_flag=0) license is expired even with a
        future expiry date."""
        self.assertEqual(license_status._derive_status("2027-01-01", 0, self.today), "expired")

    def test_past_expiry_is_expired_even_if_active_flag_set(self) -> None:
        """A past expiry date is expired even if the active flag is set."""
        self.assertEqual(license_status._derive_status("2025-01-01", 1, self.today), "expired")

    def test_within_30_days_is_expiring(self) -> None:
        """An expiry within the 30-day warning window is "expiring", not
        "active"."""
        self.assertEqual(license_status._derive_status("2026-06-20", 1, self.today), "expiring")

    def test_far_future_is_active(self) -> None:
        """An expiry well beyond the warning window is "active"."""
        self.assertEqual(license_status._derive_status("2027-01-01", 1, self.today), "active")

    def test_exactly_on_boundary_is_expiring(self) -> None:
        """An expiry exactly _EXPIRING_SOON_DAYS out is still classified
        "expiring", not "active" (inclusive boundary)."""
        boundary = self.today + datetime.timedelta(days=license_status._EXPIRING_SOON_DAYS)
        self.assertEqual(license_status._derive_status(boundary.isoformat(), 1, self.today), "expiring")


class TestGetLicenseStatus(unittest.TestCase):
    """get_license_status()'s end-to-end query, fail-safe error handling,
    and per-license status/seat computation."""

    def test_connect_failure_returns_empty(self) -> None:
        """A MySQL connection failure returns the documented empty shape
        rather than raising."""
        with patch("pymysql.connect", side_effect=ConnectionError("down")):
            result = license_status.get_license_status()
        self.assertEqual(result, dict(license_status._EMPTY))

    def test_query_failure_returns_empty_and_closes_conn(self) -> None:
        """A query execution failure returns the empty shape and still
        closes the connection rather than leaking it."""
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("bad query")
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)
        with patch("pymysql.connect", return_value=conn):
            result = license_status.get_license_status()
        self.assertEqual(result, dict(license_status._EMPTY))
        conn.close.assert_called_once()

    def test_computes_seats_and_statuses(self) -> None:
        """seats_total/seats_used and each license's derived status are
        computed correctly across a mix of active/expiring/expired/
        inactive rows, and the connection is closed afterward."""
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
