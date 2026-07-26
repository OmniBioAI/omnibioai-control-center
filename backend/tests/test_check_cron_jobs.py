"""
tests/test_check_cron_jobs.py

Unit tests for:
  - control_center.checks.cron_jobs
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from control_center.checks import cron_jobs


class TestLastRunStatus(unittest.TestCase):

    def test_missing_log_reports_never_run(self) -> None:
        result = cron_jobs._last_run_status(Path("/nonexistent/path.log"))
        self.assertEqual(result, {"last_run_at": None, "last_status": "never_run"})

    def test_clean_log_reports_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            log.write_text("[INFO] starting\n[INFO] done\n")
            result = cron_jobs._last_run_status(log)
        self.assertEqual(result["last_status"], "ok")
        self.assertIsNotNone(result["last_run_at"])

    def test_log_with_error_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            log.write_text("[INFO] starting\n[ERROR] something broke\n")
            result = cron_jobs._last_run_status(log)
        self.assertEqual(result["last_status"], "error")

    def test_error_outside_tail_window_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            lines = ["[ERROR] old failure"] + [f"[INFO] line {i}" for i in range(50)]
            log.write_text("\n".join(lines))
            result = cron_jobs._last_run_status(log)
        self.assertEqual(result["last_status"], "ok")

    def test_case_insensitive_error_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            log.write_text("Error: disk full\n")
            result = cron_jobs._last_run_status(log)
        self.assertEqual(result["last_status"], "error")

    def test_oserror_reading_log_reports_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            log.write_text("[INFO] ok\n")
            with patch.object(cron_jobs.Path, "read_text", side_effect=OSError("permission denied")):
                result = cron_jobs._last_run_status(log)
        self.assertEqual(result, {"last_run_at": None, "last_status": "unknown"})


class TestGetCronJobs(unittest.TestCase):

    def test_returns_all_four_known_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        self.assertEqual(len(jobs), 4)
        self.assertEqual({j["id"] for j in jobs}, {
            "mysql-backup", "coverage-nightly", "pubmed-sync", "reindex-check",
        })

    def test_each_job_has_expected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        for job in jobs:
            for field in ("id", "name", "schedule", "script_path", "log_path",
                          "last_run_at", "last_status"):
                self.assertIn(field, job)

    def test_never_run_when_no_logs_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        self.assertTrue(all(j["last_status"] == "never_run" for j in jobs))

    def test_reflects_real_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "work" / "backups").mkdir(parents=True)
            (root / "work" / "backups" / "omnibioai-backup.log").write_text("[INFO] backup ok\n")
            jobs = cron_jobs.get_cron_jobs(root)
        backup_job = next(j for j in jobs if j["id"] == "mysql-backup")
        self.assertEqual(backup_job["last_status"], "ok")
        self.assertIsNotNone(backup_job["last_run_at"])


if __name__ == "__main__":
    unittest.main()
