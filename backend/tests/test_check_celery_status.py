"""
tests/test_check_celery_status.py

Unit tests for:
  - control_center.checks.celery_status
"""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from control_center.checks import celery_status


class TestCollect(unittest.TestCase):

    def test_workers_online_and_offline_with_active_task_counts(self) -> None:
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

    def test_non_redis_backend_returns_empty(self) -> None:
        app = MagicMock()
        app.conf.result_backend = "rpc://"
        self.assertEqual(celery_status._recent_tasks(app), [])

    def test_parses_and_sorts_task_meta(self) -> None:
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
        app = MagicMock()
        app.conf.result_backend = "redis://redis:6379/2"

        mock_r = MagicMock()
        mock_r.scan_iter.return_value = [b"celery-task-meta-1", b"celery-task-meta-2"]
        mock_r.get.side_effect = [None, "not-json"]

        with patch("redis.from_url", return_value=mock_r):
            rows = celery_status._recent_tasks(app)

        self.assertEqual(rows, [])

    def test_limits_to_recent_tasks_limit(self) -> None:
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

    def test_success_passthrough(self) -> None:
        with patch.object(celery_status, "_collect", return_value={"workers": [], "recent_tasks": []}):
            result = celery_status.get_celery_status()
        self.assertEqual(result, {"workers": [], "recent_tasks": []})

    def test_timeout_reports_unreachable(self) -> None:
        def slow_collect():
            time.sleep(0.3)
            return {"workers": [], "recent_tasks": []}

        with patch.object(celery_status, "_OVERALL_TIMEOUT_S", 0.05):
            with patch.object(celery_status, "_collect", side_effect=slow_collect):
                result = celery_status.get_celery_status()

        self.assertEqual(result["workers"], [])
        self.assertIn("timed out", result["error"])

    def test_generic_exception_reports_unreachable(self) -> None:
        with patch.object(celery_status, "_collect", side_effect=RuntimeError("broker down")):
            result = celery_status.get_celery_status()

        self.assertEqual(result["workers"], [])
        self.assertIn("RuntimeError", result["error"])
        self.assertIn("broker down", result["error"])


if __name__ == "__main__":
    unittest.main()
