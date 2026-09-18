"""
tests/test_check_celery_status.py

Unit tests for:
  - control_center.checks.celery_status

Covers worker online/offline classification and active-task counts
(_collect), recent-task-history reconstruction from a Redis result
backend (_recent_tasks: non-Redis backend, sorting by date_done
descending, skipping missing/malformed entries, and the fixed history
limit), and get_celery_status()'s overall timeout/exception fail-safe
wrapper around _collect().

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import celery_status


class TestCollect(unittest.TestCase):
    """_collect()'s worker online/offline classification and active-task counting."""

    def test_workers_online_and_offline_with_active_task_counts(self) -> None:
        """A worker that responded to ping is "online" with its active
        task count; one that didn't respond (absent from ping but
        present in active) is "offline" with its task count still reported."""
        mock_insp = MagicMock()
        mock_insp.ping.return_value = {"worker1@host": {"ok": "pong"}}
        mock_insp.active.return_value = {
            "worker1@host": [{"id": "t1"}],
            "worker2@host": [{"id": "t2"}, {"id": "t3"}],
        }
        mock_app = MagicMock()
        mock_app.control.inspect.return_value = mock_insp

        with patch("celery.Celery", return_value=mock_app):
            with patch.object(celery_status, "_recent_tasks", return_value=[]):
                result = celery_status._collect()

        workers = {w["name"]: w for w in result["workers"]}
        self.assertEqual(workers["worker1@host"]["status"], "online")
        self.assertEqual(workers["worker1@host"]["active_tasks"], 1)
        self.assertEqual(workers["worker2@host"]["status"], "offline")
        self.assertEqual(workers["worker2@host"]["active_tasks"], 2)

    def test_no_workers_returns_empty_list(self) -> None:
        """When ping/active both return None (no workers at all), the
        result's "workers" list is empty."""
        mock_insp = MagicMock()
        mock_insp.ping.return_value = None
        mock_insp.active.return_value = None
        mock_app = MagicMock()
        mock_app.control.inspect.return_value = mock_insp

        with patch("celery.Celery", return_value=mock_app):
            with patch.object(celery_status, "_recent_tasks", return_value=[]):
                result = celery_status._collect()

        self.assertEqual(result["workers"], [])


class TestRecentTasks(unittest.TestCase):
    """_recent_tasks()'s Redis-result-backend scan/parse/sort behavior."""

    def test_non_redis_backend_returns_empty(self) -> None:
        """A non-Redis result_backend (e.g. "rpc://") returns an empty
        list rather than attempting a Redis scan."""
        app = MagicMock()
        app.conf.result_backend = "rpc://"
        self.assertEqual(celery_status._recent_tasks(app), [])

    def test_parses_and_sorts_task_meta(self) -> None:
        """Task metadata is parsed from each "celery-task-meta-*" key,
        sorted by date_done descending, with runtime rounded to 2
        decimals and the internal "_date_done" sort key not leaking into
        the returned rows."""
        app = MagicMock()
        app.conf.result_backend = "redis://redis:6379/2"

        mock_r = MagicMock()
        mock_r.scan_iter.return_value = [b"celery-task-meta-1", b"celery-task-meta-2"]

        def fake_get(key):
            if key == b"celery-task-meta-1":
                return json.dumps({
                    "name": "tasks.run_plugin", "status": "SUCCESS",
                    "date_done": "2026-01-01T00:00:00", "runtime": 1.2345,
                })
            return json.dumps({
                "task_id": "abc123", "status": "FAILURE",
                "date_done": "2026-02-01T00:00:00",
            })

        mock_r.get.side_effect = fake_get

        with patch("redis.from_url", return_value=mock_r):
            rows = celery_status._recent_tasks(app)

        self.assertEqual(len(rows), 2)
        # sorted by date_done descending -> Feb before Jan
        self.assertEqual(rows[0]["name"], "abc123")
        self.assertEqual(rows[0]["state"], "FAILURE")
        self.assertNotIn("_date_done", rows[0])
        self.assertEqual(rows[1]["name"], "tasks.run_plugin")
        self.assertEqual(rows[1]["runtime_s"], 1.23)

    def test_skips_missing_and_malformed_entries(self) -> None:
        """A key that GETs to None, and one that returns non-JSON text,
        are both skipped rather than raising or producing a garbage row."""
        app = MagicMock()
        app.conf.result_backend = "redis://redis:6379/2"

        mock_r = MagicMock()
        mock_r.scan_iter.return_value = [b"celery-task-meta-1", b"celery-task-meta-2"]
        mock_r.get.side_effect = [None, "not-json"]

        with patch("redis.from_url", return_value=mock_r):
            rows = celery_status._recent_tasks(app)

        self.assertEqual(rows, [])

    def test_limits_to_recent_tasks_limit(self) -> None:
        """More scanned entries than _RECENT_TASKS_LIMIT still returns
        at most that many rows."""
        app = MagicMock()
        app.conf.result_backend = "redis://redis:6379/2"

        n = celery_status._RECENT_TASKS_LIMIT + 5
        keys = [f"celery-task-meta-{i}".encode() for i in range(n)]
        mock_r = MagicMock()
        mock_r.scan_iter.return_value = keys
        mock_r.get.side_effect = [
            json.dumps({"name": f"t{i}", "status": "SUCCESS", "date_done": f"2026-01-{i+1:02d}T00:00:00"})
            for i in range(n)
        ]

        with patch("redis.from_url", return_value=mock_r):
            rows = celery_status._recent_tasks(app)

        self.assertEqual(len(rows), celery_status._RECENT_TASKS_LIMIT)


class TestGetCeleryStatus(unittest.TestCase):
    """get_celery_status()'s timeout/exception fail-safe wrapper around _collect()."""

    def test_success_passthrough(self) -> None:
        """A successful _collect() result is returned unchanged."""
        with patch.object(celery_status, "_collect", return_value={"workers": [], "recent_tasks": []}):
            result = celery_status.get_celery_status()
        self.assertEqual(result, {"workers": [], "recent_tasks": []})

    def test_timeout_reports_unreachable(self) -> None:
        """A _collect() call that exceeds _OVERALL_TIMEOUT_S returns an
        empty workers list with a "timed out" error message rather than
        blocking indefinitely."""
        def slow_collect():
            time.sleep(0.3)
            return {"workers": [], "recent_tasks": []}

        with patch.object(celery_status, "_OVERALL_TIMEOUT_S", 0.05):
            with patch.object(celery_status, "_collect", side_effect=slow_collect):
                result = celery_status.get_celery_status()

        self.assertEqual(result["workers"], [])
        self.assertIn("timed out", result["error"])

    def test_generic_exception_reports_unreachable(self) -> None:
        """A _collect() exception returns an empty workers list with an
        error message naming the exception type and its message."""
        with patch.object(celery_status, "_collect", side_effect=RuntimeError("broker down")):
            result = celery_status.get_celery_status()

        self.assertEqual(result["workers"], [])
        self.assertIn("RuntimeError", result["error"])
        self.assertIn("broker down", result["error"])


if __name__ == "__main__":
    unittest.main()
