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

    def test_returns_all_known_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        # 16, not 15 -- coverage-ondemand-watcher is a new entry, the
        # host-side half of POST /coverage/ecosystem/generate.
        self.assertEqual(len(jobs), 16)
        self.assertEqual({j["id"] for j in jobs}, {
            "mysql-backup", "neo4j-backup", "system-state-backup",
            "unpushed-work-check", "nvme-backup", "coverage-nightly", "pubmed-sync",
            "reindex-check", "cron-health-check", "disk-space-check", "domain-health-check",
            "run-chunks", "base-images-check", "platform-workflows-check",
            "plugin-image-sync-check", "coverage-ondemand-watcher",
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

    def test_paused_none_when_no_spool_path_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        self.assertTrue(all(j["paused"] is None for j in jobs))

    def test_paused_none_when_spool_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp), Path("/nonexistent/crontab"))
        self.assertTrue(all(j["paused"] is None for j in jobs))

    def test_reflects_live_paused_and_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = Path(tmp) / "crontab"
            spool.write_text(
                "0 4 * * * /path/to/omnibioai-studio/scripts/backup-mysql.sh >> log 2>&1\n"
                "# 0 2 * * * python3 /path/to/omnibioai-control-center/scripts/run_coverage_host.py >> log 2>&1\n"
            )
            jobs = cron_jobs.get_cron_jobs(Path(tmp), spool)
        backup = next(j for j in jobs if j["id"] == "mysql-backup")
        coverage = next(j for j in jobs if j["id"] == "coverage-nightly")
        self.assertFalse(backup["paused"])
        self.assertEqual(backup["schedule"], "0 4 * * *")
        self.assertTrue(coverage["paused"])

    def test_job_missing_from_live_crontab_reports_paused_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = Path(tmp) / "crontab"
            spool.write_text("0 4 * * * /path/to/omnibioai-studio/scripts/backup-mysql.sh\n")
            jobs = cron_jobs.get_cron_jobs(Path(tmp), spool)
        coverage = next(j for j in jobs if j["id"] == "coverage-nightly")
        self.assertIsNone(coverage["paused"])


class TestGetJobLog(unittest.TestCase):

    def test_unknown_job_id_raises_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                cron_jobs.get_job_log(Path(tmp), "not-a-real-job")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_missing_log_file_returns_never_run_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = cron_jobs.get_job_log(Path(tmp), "mysql-backup")
        self.assertEqual(result["id"], "mysql-backup")
        self.assertEqual(result["last_status"], "never_run")
        self.assertIsNone(result["last_run_at"])
        self.assertEqual(result["lines"], [])

    def test_existing_log_returns_tail_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "work" / "backups"
            log_dir.mkdir(parents=True)
            (log_dir / "omnibioai-backup.log").write_text(
                "\n".join(f"line {i}" for i in range(5)) + "\n"
            )
            result = cron_jobs.get_job_log(root, "mysql-backup", lines=3)
        self.assertEqual(result["total_lines"], 5)
        self.assertEqual(result["lines_returned"], 3)
        self.assertEqual(result["lines"], ["line 2", "line 3", "line 4"])
        self.assertEqual(result["last_status"], "ok")
        self.assertIsNotNone(result["last_run_at"])

    def test_lines_param_larger_than_file_returns_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "work" / "backups"
            log_dir.mkdir(parents=True)
            (log_dir / "omnibioai-backup.log").write_text("only line\n")
            result = cron_jobs.get_job_log(root, "mysql-backup", lines=100)
        self.assertEqual(result["total_lines"], 1)
        self.assertEqual(result["lines_returned"], 1)
        self.assertEqual(result["lines"], ["only line"])

    def test_oserror_on_read_raises_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "work" / "backups"
            log_dir.mkdir(parents=True)
            log_path = log_dir / "omnibioai-backup.log"
            log_path.write_text("x\n")
            with patch.object(cron_jobs.Path, "read_text", side_effect=OSError("denied")):
                with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                    cron_jobs.get_job_log(root, "mysql-backup")
        self.assertEqual(ctx.exception.status_code, 500)


class TestCronMutations(unittest.TestCase):

    def _spool(self, tmp: str, content: str) -> Path:
        spool = Path(tmp) / "crontab"
        spool.write_text(content)
        return spool

    def test_get_job_unknown_id_raises_404(self) -> None:
        with self.assertRaises(cron_jobs.CronMutationError) as ctx:
            cron_jobs._get_job("not-a-real-job")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_read_crontab_missing_file_raises_500(self) -> None:
        with self.assertRaises(cron_jobs.CronMutationError) as ctx:
            cron_jobs._read_crontab_lines(Path("/nonexistent/crontab"))
        self.assertEqual(ctx.exception.status_code, 500)

    def test_match_line_index_not_found_raises_404(self) -> None:
        with self.assertRaises(cron_jobs.CronMutationError) as ctx:
            cron_jobs._match_line_index(["0 4 * * * echo hi\n"], cron_jobs._get_job("mysql-backup"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_validate_schedule_wrong_field_count(self) -> None:
        with self.assertRaises(cron_jobs.CronMutationError):
            cron_jobs._validate_schedule("0 4 * *")

    def test_validate_schedule_invalid_characters(self) -> None:
        with self.assertRaises(cron_jobs.CronMutationError):
            cron_jobs._validate_schedule("i0 4 * * *")

    def test_validate_schedule_accepts_valid(self) -> None:
        cron_jobs._validate_schedule("*/5 1-6 * * 1,3,5")  # should not raise

    def test_pause_comments_out_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            result = cron_jobs.pause_job(spool, "mysql-backup")
            content = spool.read_text()
        self.assertEqual(result, {"id": "mysql-backup", "paused": True})
        self.assertTrue(content.startswith("# 0 4 * * *"))

    def test_pause_already_paused_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "# 0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            original = spool.read_text()
            cron_jobs.pause_job(spool, "mysql-backup")
            self.assertEqual(spool.read_text(), original)

    def test_resume_uncomments_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "# 0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            result = cron_jobs.resume_job(spool, "mysql-backup")
            content = spool.read_text()
        self.assertEqual(result, {"id": "mysql-backup", "paused": False})
        self.assertTrue(content.startswith("0 4 * * *"))
        self.assertNotIn("#", content)

    def test_resume_already_active_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            original = spool.read_text()
            cron_jobs.resume_job(spool, "mysql-backup")
            self.assertEqual(spool.read_text(), original)

    def test_other_lines_untouched_by_pause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(
                tmp,
                "0 3 * * * /a/omnibioai-utils/sync_pubmed_updates.py\n"
                "0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n",
            )
            cron_jobs.pause_job(spool, "mysql-backup")
            lines = spool.read_text().splitlines()
        self.assertEqual(lines[0], "0 3 * * * /a/omnibioai-utils/sync_pubmed_updates.py")
        self.assertTrue(lines[1].startswith("#"))

    def test_update_schedule_replaces_time_fields_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(
                tmp, "0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh >> log.txt 2>&1\n",
            )
            result = cron_jobs.update_schedule(spool, "mysql-backup", "30 5 * * *")
            content = spool.read_text()
        self.assertEqual(result, {"id": "mysql-backup", "schedule": "30 5 * * *"})
        self.assertEqual(
            content.strip(),
            "30 5 * * * /a/omnibioai-studio/scripts/backup-mysql.sh >> log.txt 2>&1",
        )

    def test_update_schedule_preserves_paused_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "# 0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            cron_jobs.update_schedule(spool, "mysql-backup", "30 5 * * *")
            content = spool.read_text()
        self.assertTrue(content.startswith("# 30 5 * * *"))

    def test_update_schedule_rejects_invalid_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            with self.assertRaises(cron_jobs.CronMutationError):
                cron_jobs.update_schedule(spool, "mysql-backup", "not a schedule")

    def test_update_schedule_unknown_job_raises_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * echo hi\n")
            with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                cron_jobs.update_schedule(spool, "not-a-job", "0 4 * * *")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_spool_path_helper_uses_default(self) -> None:
        self.assertEqual(cron_jobs._spool_path(None), Path("/var/spool/cron/crontabs/manish"))

    def test_spool_path_helper_uses_env_value(self) -> None:
        self.assertEqual(cron_jobs._spool_path("/custom/path"), Path("/custom/path"))

    def test_read_crontab_oserror_on_read_wraps_as_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * echo hi\n")
            with patch.object(cron_jobs.Path, "read_text", side_effect=OSError("denied")):
                with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                    cron_jobs._read_crontab_lines(spool)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_write_crontab_oserror_wraps_as_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * echo hi\n")
            with patch.object(cron_jobs.Path, "write_text", side_effect=OSError("denied")):
                with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                    cron_jobs._write_crontab_lines(spool, ["0 4 * * * echo hi"])
        self.assertEqual(ctx.exception.status_code, 500)

    def test_update_schedule_unparseable_line_raises_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "backup-mysql.sh\n")
            with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                cron_jobs.update_schedule(spool, "mysql-backup", "0 4 * * *")
        self.assertEqual(ctx.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()
