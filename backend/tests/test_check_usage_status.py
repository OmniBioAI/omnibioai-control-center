"""
tests/test_check_usage_status.py

Unit tests for:
  - control_center.checks.usage_status
"""

from __future__ import annotations

import datetime
import json
import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import usage_status


def _cursor_ctx(cursor: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestParseDt(unittest.TestCase):

    def test_none_returns_none(self) -> None:
        self.assertIsNone(usage_status._parse_dt(None))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(usage_status._parse_dt(""))

    def test_malformed_returns_none(self) -> None:
        self.assertIsNone(usage_status._parse_dt("not-a-date"))

    def test_naive_datetime_gets_utc(self) -> None:
        dt = usage_status._parse_dt("2026-01-01T00:00:00")
        self.assertEqual(dt.tzinfo, datetime.timezone.utc)

    def test_aware_datetime_preserved(self) -> None:
        dt = usage_status._parse_dt("2026-01-01T00:00:00+05:00")
        self.assertEqual(dt.utcoffset(), datetime.timedelta(hours=5))


class TestUserActivity(unittest.TestCase):

    def test_connect_failure_returns_empty(self) -> None:
        with patch("pymysql.connect", side_effect=ConnectionError("down")):
            result = usage_status._user_activity()
        self.assertEqual(result, {"active_7d": 0, "active_30d": 0, "total": 0, "test_count": 0})

    def test_query_failure_returns_empty_and_closes(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("bad query")
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)
        with patch("pymysql.connect", return_value=conn):
            result = usage_status._user_activity()
        self.assertEqual(result["total"], 0)
        conn.close.assert_called_once()

    def test_classifies_recency_and_test_users(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("alice", now - datetime.timedelta(days=1)),
            ("bob", now - datetime.timedelta(days=15)),
            ("carol", now - datetime.timedelta(days=90)),
            ("dave", None),
            ("testuser1", now - datetime.timedelta(days=1)),
        ]
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)
        with patch("pymysql.connect", return_value=conn):
            result = usage_status._user_activity()

        self.assertEqual(result["total"], 5)
        self.assertEqual(result["active_7d"], 2)   # alice, testuser1
        self.assertEqual(result["active_30d"], 3)  # alice, bob, testuser1
        self.assertEqual(result["test_count"], 1)

    def test_naive_last_login_treated_as_utc(self) -> None:
        naive_recent = datetime.datetime.now() - datetime.timedelta(hours=1)
        cursor = MagicMock()
        cursor.fetchall.return_value = [("alice", naive_recent)]
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)
        with patch("pymysql.connect", return_value=conn):
            result = usage_status._user_activity()
        self.assertEqual(result["active_7d"], 1)


class TestSessionCount(unittest.TestCase):

    def test_connect_failure_returns_zero(self) -> None:
        with patch("pymysql.connect", side_effect=ConnectionError("down")):
            self.assertEqual(usage_status._session_count(), 0)

    def test_query_failure_returns_zero_and_closes(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("boom")
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)
        with patch("pymysql.connect", return_value=conn):
            result = usage_status._session_count()
        self.assertEqual(result, 0)
        conn.close.assert_called_once()

    def test_returns_count_from_row(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = (42,)
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)
        with patch("pymysql.connect", return_value=conn):
            result = usage_status._session_count()
        self.assertEqual(result, 42)

    def test_no_row_returns_zero(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value = _cursor_ctx(cursor)
        with patch("pymysql.connect", return_value=conn):
            result = usage_status._session_count()
        self.assertEqual(result, 0)


class TestScanRuns(unittest.TestCase):

    def _write_status(self, run_dir, **fields) -> None:
        run_dir.mkdir(parents=True)
        (run_dir / "status.json").write_text(json.dumps(fields))

    def test_missing_runs_root_returns_empty(self, ) -> None:
        import pathlib
        with patch.object(usage_status, "RUNS_ROOT", pathlib.Path("/nonexistent/runs")):
            result = usage_status._scan_runs()
        self.assertEqual(result, {"top_plugins": [], "runs_by_day": [], "success_rate_pct": 0.0})

    def test_aggregates_completed_and_failed_runs(self, tmp_path=None) -> None:
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            now = datetime.datetime.now(datetime.timezone.utc)
            self._write_status(root / "bwa" / "run1", state="COMPLETED",
                                created_at=now.isoformat())
            self._write_status(root / "bwa" / "run2", state="FAILED",
                                created_at=now.isoformat())
            self._write_status(root / "samtools" / "run1", state="COMPLETED",
                                created_at=now.isoformat())

            with patch.object(usage_status, "RUNS_ROOT", root):
                result = usage_status._scan_runs()

        plugin_counts = {p["name"]: p["runs_30d"] for p in result["top_plugins"]}
        self.assertEqual(plugin_counts, {"bwa": 2, "samtools": 1})
        self.assertEqual(result["success_rate_pct"], round(100 * 2 / 3, 1))
        self.assertEqual(len(result["runs_by_day"]), 1)

    def test_old_runs_excluded_by_window(self) -> None:
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=usage_status._WINDOW_DAYS + 5)
            self._write_status(root / "bwa" / "old_run", state="COMPLETED", created_at=old.isoformat())

            with patch.object(usage_status, "RUNS_ROOT", root):
                result = usage_status._scan_runs()

        self.assertEqual(result["top_plugins"], [])
        self.assertEqual(result["success_rate_pct"], 0.0)

    def test_missing_status_file_skipped(self) -> None:
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "bwa" / "run_no_status").mkdir(parents=True)

            with patch.object(usage_status, "RUNS_ROOT", root):
                result = usage_status._scan_runs()

        self.assertEqual(result["top_plugins"], [])

    def test_malformed_status_json_skipped(self) -> None:
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            run_dir = root / "bwa" / "run1"
            run_dir.mkdir(parents=True)
            (run_dir / "status.json").write_text("not-json")

            with patch.object(usage_status, "RUNS_ROOT", root):
                result = usage_status._scan_runs()

        self.assertEqual(result["top_plugins"], [])

    def test_missing_created_at_skipped(self) -> None:
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._write_status(root / "bwa" / "run1", state="COMPLETED")

            with patch.object(usage_status, "RUNS_ROOT", root):
                result = usage_status._scan_runs()

        self.assertEqual(result["top_plugins"], [])

    def test_non_directory_entries_in_root_and_plugin_dir_skipped(self) -> None:
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            root.mkdir(exist_ok=True)
            (root / "stray_file.txt").write_text("x")
            plugin_dir = root / "bwa"
            plugin_dir.mkdir()
            (plugin_dir / "stray.txt").write_text("x")

            with patch.object(usage_status, "RUNS_ROOT", root):
                result = usage_status._scan_runs()

        self.assertEqual(result["top_plugins"], [])

    def test_unknown_state_not_counted_as_completed_or_failed(self) -> None:
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            now = datetime.datetime.now(datetime.timezone.utc)
            self._write_status(root / "bwa" / "run1", state="RUNNING", created_at=now.isoformat())

            with patch.object(usage_status, "RUNS_ROOT", root):
                result = usage_status._scan_runs()

        self.assertEqual(result["success_rate_pct"], 0.0)
        plugin_counts = {p["name"]: p["runs_30d"] for p in result["top_plugins"]}
        self.assertEqual(plugin_counts, {"bwa": 1})


class TestGetUsageStatus(unittest.TestCase):

    def test_combines_all_sources(self) -> None:
        with patch.object(usage_status, "_user_activity",
                           return_value={"active_7d": 1, "active_30d": 2, "total": 3, "test_count": 0}):
            with patch.object(usage_status, "_session_count", return_value=7):
                with patch.object(usage_status, "_scan_runs",
                                   return_value={"top_plugins": [], "runs_by_day": [], "success_rate_pct": 0.0}):
                    result = usage_status.get_usage_status()

        self.assertEqual(result["active_users_7d"], 1)
        self.assertEqual(result["active_users_30d"], 2)
        self.assertEqual(result["total_users"], 3)
        self.assertEqual(result["total_sessions_30d"], 7)
        self.assertEqual(result["top_workflows"], [])
        self.assertIn("users_caveat", result)
        self.assertIn("sessions_caveat", result)


if __name__ == "__main__":
    unittest.main()
