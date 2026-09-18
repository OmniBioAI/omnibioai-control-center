"""
tests/test_check_cron_jobs.py

Unit tests for:
  - control_center.checks.cron_jobs

Covers _last_run_status()'s log-tail parsing (never-run/ok/error
classification, case-insensitive, only within the tail window),
get_cron_jobs()'s fixed 15-job catalog with live paused/schedule state
from a real crontab spool, get_job_log()'s tail retrieval, and the
mutation helpers (pause/resume/update_schedule) editing a real crontab
file in place, preserving unrelated lines and comment/pause state.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from control_center.checks import cron_jobs


class TestLastRunStatus(unittest.TestCase):
    """_last_run_status()'s log-tail parsing into never_run/ok/error."""

    def test_missing_log_reports_never_run(self) -> None:
        """A nonexistent log file reports last_status="never_run"."""
        result = cron_jobs._last_run_status(Path("/nonexistent/path.log"))
        self.assertEqual(result, {"last_run_at": None, "last_status": "never_run"})

    def test_clean_log_reports_ok(self) -> None:
        """A log with no error lines reports last_status="ok" with a
        real last_run_at timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            log.write_text("[INFO] starting\n[INFO] done\n")
            result = cron_jobs._last_run_status(log)
        self.assertEqual(result["last_status"], "ok")
        self.assertIsNotNone(result["last_run_at"])

    def test_log_with_error_reports_error(self) -> None:
        """A log containing an ERROR line reports last_status="error"."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            log.write_text("[INFO] starting\n[ERROR] something broke\n")
            result = cron_jobs._last_run_status(log)
        self.assertEqual(result["last_status"], "error")

    def test_error_outside_tail_window_not_flagged(self) -> None:
        """An old ERROR line that falls outside the tail window is not
        flagged -- only the recent tail is checked."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            lines = ["[ERROR] old failure"] + [f"[INFO] line {i}" for i in range(50)]
            log.write_text("\n".join(lines))
            result = cron_jobs._last_run_status(log)
        self.assertEqual(result["last_status"], "ok")

    def test_case_insensitive_error_match(self) -> None:
        """"Error:" (mixed case) is still matched as an error line."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            log.write_text("Error: disk full\n")
            result = cron_jobs._last_run_status(log)
        self.assertEqual(result["last_status"], "error")

    def test_oserror_reading_log_reports_unknown(self) -> None:
        """An OSError reading the log reports last_status="unknown"
        rather than raising."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "job.log"
            log.write_text("[INFO] ok\n")
            with patch.object(cron_jobs.Path, "read_text", side_effect=OSError("permission denied")):
                result = cron_jobs._last_run_status(log)
        self.assertEqual(result, {"last_run_at": None, "last_status": "unknown"})


class TestGetCronJobs(unittest.TestCase):
    """get_cron_jobs()'s fixed job catalog, log-derived status, and
    live paused/schedule state from a real crontab spool."""

    def test_returns_all_known_jobs(self) -> None:
        """Exactly the 15 predefined job ids are returned."""
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        self.assertEqual(len(jobs), 15)
        self.assertEqual({j["id"] for j in jobs}, {
            "mysql-backup", "neo4j-backup", "system-state-backup",
            "unpushed-work-check", "nvme-backup", "coverage-nightly", "pubmed-sync",
            "reindex-check", "cron-health-check", "disk-space-check", "domain-health-check",
            "run-chunks", "base-images-check", "platform-workflows-check",
            "plugin-image-sync-check",
        })

    def test_each_job_has_expected_fields(self) -> None:
        """Every job dict has the full documented field set."""
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        for job in jobs:
            for field in ("id", "name", "schedule", "script_path", "log_path",
                          "last_run_at", "last_status"):
                self.assertIn(field, job)

    def test_never_run_when_no_logs_present(self) -> None:
        """With no log files at all, every job reports last_status="never_run"."""
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        self.assertTrue(all(j["last_status"] == "never_run" for j in jobs))

    def test_reflects_real_log_file(self) -> None:
        """A real log file for a specific job populates that job's
        last_status/last_run_at from its actual content."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "work" / "backups").mkdir(parents=True)
            (root / "work" / "backups" / "omnibioai-backup.log").write_text("[INFO] backup ok\n")
            jobs = cron_jobs.get_cron_jobs(root)
        backup_job = next(j for j in jobs if j["id"] == "mysql-backup")
        self.assertEqual(backup_job["last_status"], "ok")
        self.assertIsNotNone(backup_job["last_run_at"])

    def test_paused_none_when_no_spool_path_given(self) -> None:
        """With no spool path passed, every job's "paused" field is
        None -- unknown rather than a guess."""
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp))
        self.assertTrue(all(j["paused"] is None for j in jobs))

    def test_paused_none_when_spool_unreadable(self) -> None:
        """A nonexistent spool path also leaves "paused" as None."""
        with tempfile.TemporaryDirectory() as tmp:
            jobs = cron_jobs.get_cron_jobs(Path(tmp), Path("/nonexistent/crontab"))
        self.assertTrue(all(j["paused"] is None for j in jobs))

    def test_reflects_live_paused_and_schedule(self) -> None:
        """A real crontab spool's active line reports paused=False with
        the real schedule, and a commented-out line reports paused=True."""
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
        """A job with no matching line in the real crontab spool
        reports paused=None."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = Path(tmp) / "crontab"
            spool.write_text("0 4 * * * /path/to/omnibioai-studio/scripts/backup-mysql.sh\n")
            jobs = cron_jobs.get_cron_jobs(Path(tmp), spool)
        coverage = next(j for j in jobs if j["id"] == "coverage-nightly")
        self.assertIsNone(coverage["paused"])


class TestGetJobLog(unittest.TestCase):
    """get_job_log()'s tail retrieval and error mapping."""

    def test_unknown_job_id_raises_404(self) -> None:
        """A job id outside the predefined catalog raises CronMutationError(404)."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                cron_jobs.get_job_log(Path(tmp), "not-a-real-job")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_missing_log_file_returns_never_run_shape(self) -> None:
        """A job with no log file at all returns the never_run shape
        with an empty lines list."""
        with tempfile.TemporaryDirectory() as tmp:
            result = cron_jobs.get_job_log(Path(tmp), "mysql-backup")
        self.assertEqual(result["id"], "mysql-backup")
        self.assertEqual(result["last_status"], "never_run")
        self.assertIsNone(result["last_run_at"])
        self.assertEqual(result["lines"], [])

    def test_existing_log_returns_tail_and_status(self) -> None:
        """A real log file returns exactly the requested tail, along
        with the correct total_lines and status."""
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
        """Requesting more lines than the file has returns the whole
        file, not an error."""
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
        """An OSError reading the log raises CronMutationError(500)."""
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
    """pause_job()/resume_job()/update_schedule()'s real-crontab-file
    editing, and their supporting helpers' validation/error mapping."""

    def _spool(self, tmp: str, content: str) -> Path:
        """Write `content` to a fresh crontab spool file under `tmp`
        and return its path."""
        spool = Path(tmp) / "crontab"
        spool.write_text(content)
        return spool

    def test_get_job_unknown_id_raises_404(self) -> None:
        """_get_job() on an unknown id raises CronMutationError(404)."""
        with self.assertRaises(cron_jobs.CronMutationError) as ctx:
            cron_jobs._get_job("not-a-real-job")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_read_crontab_missing_file_raises_500(self) -> None:
        """_read_crontab_lines() on a missing spool file raises
        CronMutationError(500)."""
        with self.assertRaises(cron_jobs.CronMutationError) as ctx:
            cron_jobs._read_crontab_lines(Path("/nonexistent/crontab"))
        self.assertEqual(ctx.exception.status_code, 500)

    def test_match_line_index_not_found_raises_404(self) -> None:
        """_match_line_index() when the job's script isn't present in
        any line raises CronMutationError(404)."""
        with self.assertRaises(cron_jobs.CronMutationError) as ctx:
            cron_jobs._match_line_index(["0 4 * * * echo hi\n"], cron_jobs._get_job("mysql-backup"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_validate_schedule_wrong_field_count(self) -> None:
        """A schedule with too few fields raises CronMutationError."""
        with self.assertRaises(cron_jobs.CronMutationError):
            cron_jobs._validate_schedule("0 4 * *")

    def test_validate_schedule_invalid_characters(self) -> None:
        """A schedule containing invalid characters raises CronMutationError."""
        with self.assertRaises(cron_jobs.CronMutationError):
            cron_jobs._validate_schedule("i0 4 * * *")

    def test_validate_schedule_accepts_valid(self) -> None:
        """A well-formed 5-field cron expression (with ranges/lists/steps) passes."""
        cron_jobs._validate_schedule("*/5 1-6 * * 1,3,5")  # should not raise

    def test_pause_comments_out_line(self) -> None:
        """pause_job() comments out the job's crontab line and reports paused=True."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            result = cron_jobs.pause_job(spool, "mysql-backup")
            content = spool.read_text()
        self.assertEqual(result, {"id": "mysql-backup", "paused": True})
        self.assertTrue(content.startswith("# 0 4 * * *"))

    def test_pause_already_paused_is_noop(self) -> None:
        """Pausing an already-paused job leaves the spool file byte-for-byte unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "# 0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            original = spool.read_text()
            cron_jobs.pause_job(spool, "mysql-backup")
            self.assertEqual(spool.read_text(), original)

    def test_resume_uncomments_line(self) -> None:
        """resume_job() uncomments the job's crontab line and reports paused=False."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "# 0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            result = cron_jobs.resume_job(spool, "mysql-backup")
            content = spool.read_text()
        self.assertEqual(result, {"id": "mysql-backup", "paused": False})
        self.assertTrue(content.startswith("0 4 * * *"))
        self.assertNotIn("#", content)

    def test_resume_already_active_is_noop(self) -> None:
        """Resuming an already-active job leaves the spool file unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            original = spool.read_text()
            cron_jobs.resume_job(spool, "mysql-backup")
            self.assertEqual(spool.read_text(), original)

    def test_other_lines_untouched_by_pause(self) -> None:
        """Pausing one job's line leaves every other line in the
        spool file completely unchanged."""
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
        """update_schedule() replaces only the 5 cron time fields,
        leaving the command and its arguments intact."""
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
        """Updating the schedule of a paused job keeps it commented out."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "# 0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            cron_jobs.update_schedule(spool, "mysql-backup", "30 5 * * *")
            content = spool.read_text()
        self.assertTrue(content.startswith("# 30 5 * * *"))

    def test_update_schedule_rejects_invalid_schedule(self) -> None:
        """An invalid new schedule string raises CronMutationError."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
            with self.assertRaises(cron_jobs.CronMutationError):
                cron_jobs.update_schedule(spool, "mysql-backup", "not a schedule")

    def test_update_schedule_unknown_job_raises_404(self) -> None:
        """Updating an unknown job id raises CronMutationError(404)."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * echo hi\n")
            with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                cron_jobs.update_schedule(spool, "not-a-job", "0 4 * * *")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_spool_path_helper_uses_default(self) -> None:
        """_spool_path(None) returns the default per-user crontab spool path."""
        self.assertEqual(cron_jobs._spool_path(None), Path("/var/spool/cron/crontabs/manish"))

    def test_spool_path_helper_uses_env_value(self) -> None:
        """_spool_path() with an explicit value returns that path unchanged."""
        self.assertEqual(cron_jobs._spool_path("/custom/path"), Path("/custom/path"))

    def test_read_crontab_oserror_on_read_wraps_as_500(self) -> None:
        """An OSError reading the spool file wraps as CronMutationError(500)."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * echo hi\n")
            with patch.object(cron_jobs.Path, "read_text", side_effect=OSError("denied")):
                with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                    cron_jobs._read_crontab_lines(spool)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_write_crontab_oserror_wraps_as_500(self) -> None:
        """An OSError writing the spool file wraps as CronMutationError(500)."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "0 4 * * * echo hi\n")
            with patch.object(cron_jobs.Path, "write_text", side_effect=OSError("denied")):
                with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                    cron_jobs._write_crontab_lines(spool, ["0 4 * * * echo hi"])
        self.assertEqual(ctx.exception.status_code, 500)

    def test_update_schedule_unparseable_line_raises_500(self) -> None:
        """A crontab line that doesn't parse as a valid cron entry
        raises CronMutationError(500) rather than corrupting the file."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = self._spool(tmp, "backup-mysql.sh\n")
            with self.assertRaises(cron_jobs.CronMutationError) as ctx:
                cron_jobs.update_schedule(spool, "mysql-backup", "0 4 * * *")
        self.assertEqual(ctx.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()
