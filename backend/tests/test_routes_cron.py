"""
tests/test_routes_cron.py

Unit tests for:
  - control_center.api.routes_cron  (GET /cron/jobs, pause/resume/schedule)

Covers platform.manage_infra-gated read routes (job list, log tail with
line-count clamping) and platform.manage_cron-gated mutation routes
(pause/resume/schedule against a real crontab spool file), including
PR3D's permission-isolation checks (an admin-role token missing the
specific permission, and a different platform.* permission holder, must
both still be denied) and the fixed job-id allowlist (an arbitrary new
job id is always 404, never silently accepted).

Developer:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app

client = TestClient(app)


def _admin_headers() -> dict:
    """Authorization header for a token holding all three platform.*
    permissions this route family checks."""
    token = jwt.encode(
        {
            "sub": "1",
            "roles": ["admin"],
            "permissions": [
                "platform.manage_infra",
                "platform.manage_cron",
                "platform.manage_content",
            ],
        },
        JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _user_headers() -> dict:
    """Authorization header for a plain, unprivileged user token."""
    token = jwt.encode({"sub": "2", "roles": ["user"], "permissions": []}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _admin_role_without_cron_permission_headers() -> dict:
    """PR3D regression fixture: an "admin"-role token that lacks the
    platform.manage_cron permission specifically -- proves the route no
    longer falls back to a role-string check."""
    token = jwt.encode(
        {"sub": "3", "roles": ["admin"], "permissions": ["platform.manage_infra"]},
        JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _content_only_headers() -> dict:
    """PR3D isolation fixture: holds platform.manage_content but not
    platform.manage_cron -- must not be able to mutate cron jobs."""
    token = jwt.encode(
        {"sub": "4", "permissions": ["platform.manage_content"]},
        JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class TestCronJobsRoute(unittest.TestCase):
    """GET /cron/jobs's platform.manage_infra gating and job-list content."""

    def test_401_when_no_token(self) -> None:
        """No Authorization header returns 401."""
        resp = client.get("/cron/jobs")
        self.assertEqual(resp.status_code, 401)

    def test_403_for_cron_permission_only(self) -> None:
        """Isolation: platform.manage_cron (the write-route permission)
        must not satisfy this read route's platform.manage_infra check."""
        token = jwt.encode({"sub": "5", "permissions": ["platform.manage_cron"]}, JWT_SECRET, algorithm="HS256")
        resp = client.get("/cron/jobs", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)

    def test_returns_all_jobs(self) -> None:
        """The response lists all 15 predefined cron jobs."""
        data = client.get("/cron/jobs", headers=_admin_headers()).json()
        self.assertEqual(len(data["jobs"]), 15)

    def test_uses_workspace_root_env_var(self) -> None:
        """A job's last_status is derived from a real log file under
        WORKSPACE_ROOT/logs, not a hardcoded value."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
            with open(os.path.join(tmp, "logs", "pubmed_sync.log"), "w") as f:
                f.write("done\n")
            try:
                data = client.get("/cron/jobs", headers=_admin_headers()).json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        pubmed_job = next(j for j in data["jobs"] if j["id"] == "pubmed-sync")
        self.assertEqual(pubmed_job["last_status"], "ok")


class TestCronJobLogRoute(unittest.TestCase):
    """GET /cron/jobs/{job_id}/log's gating, unknown-job handling, and
    real-file log-tail behavior including the lines-param clamp."""

    def test_401_when_no_token(self) -> None:
        """No Authorization header returns 401."""
        resp = client.get("/cron/jobs/mysql-backup/log")
        self.assertEqual(resp.status_code, 401)

    def test_403_for_cron_permission_only(self) -> None:
        """platform.manage_cron alone does not satisfy this read
        route's platform.manage_infra check."""
        token = jwt.encode({"sub": "5", "permissions": ["platform.manage_cron"]}, JWT_SECRET, algorithm="HS256")
        resp = client.get("/cron/jobs/mysql-backup/log", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)

    def test_unknown_job_id_returns_404(self) -> None:
        """A job id outside the predefined allowlist returns 404."""
        resp = client.get("/cron/jobs/not-a-real-job/log", headers=_admin_headers())
        self.assertEqual(resp.status_code, 404)

    def test_returns_log_tail_from_real_file(self) -> None:
        """The response's "lines" is the requested tail of a real log
        file, with the correct total_lines count."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            log_dir = Path(tmp) / "work" / "backups"
            log_dir.mkdir(parents=True)
            (log_dir / "omnibioai-backup.log").write_text("a\nb\nc\n")
            try:
                data = client.get("/cron/jobs/mysql-backup/log?lines=2", headers=_admin_headers()).json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(data["lines"], ["b", "c"])
        self.assertEqual(data["total_lines"], 3)

    def test_lines_param_clamped_to_minimum_one(self) -> None:
        """A requested lines=0 is clamped up to a minimum of 1."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            log_dir = Path(tmp) / "work" / "backups"
            log_dir.mkdir(parents=True)
            (log_dir / "omnibioai-backup.log").write_text("a\nb\nc\n")
            try:
                data = client.get("/cron/jobs/mysql-backup/log?lines=0", headers=_admin_headers()).json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(data["lines_returned"], 1)

    def test_lines_param_clamped_to_maximum_1000(self) -> None:
        """A requested lines=5000 is clamped down to a maximum of 1000."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            log_dir = Path(tmp) / "work" / "backups"
            log_dir.mkdir(parents=True)
            (log_dir / "omnibioai-backup.log").write_text(
                "\n".join(f"line {i}" for i in range(1500)) + "\n"
            )
            try:
                data = client.get("/cron/jobs/mysql-backup/log?lines=5000", headers=_admin_headers()).json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(data["lines_returned"], 1000)


class TestCronMutationRoutes(unittest.TestCase):
    """Pause/resume/schedule mutation routes: platform.manage_cron
    gating (with PR3D role/permission isolation), a fixed job-id
    allowlist, and real crontab-spool-file edits."""

    def _set_spool(self, content: str) -> str:
        """Write `content` to a fresh temp crontab spool file, point
        CRONTAB_SPOOL_PATH at it, and return its path."""
        tmp = tempfile.mkdtemp()
        spool = Path(tmp) / "crontab"
        spool.write_text(content)
        os.environ["CRONTAB_SPOOL_PATH"] = str(spool)
        return str(spool)

    def tearDown(self) -> None:
        os.environ.pop("CRONTAB_SPOOL_PATH", None)

    def test_pause_requires_admin_401(self) -> None:
        """Pause with no Authorization header returns 401."""
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/pause")
        self.assertEqual(resp.status_code, 401)

    def test_pause_requires_admin_403_for_non_admin(self) -> None:
        """Pause with a plain user token returns 403."""
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/pause", headers=_user_headers())
        self.assertEqual(resp.status_code, 403)

    def test_pause_403_for_admin_role_without_cron_permission(self) -> None:
        """Pause with an "admin"-role token lacking platform.manage_cron
        specifically still returns 403 -- no role-string fallback."""
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post(
            "/cron/jobs/mysql-backup/pause", headers=_admin_role_without_cron_permission_headers(),
        )
        self.assertEqual(resp.status_code, 403)

    def test_pause_403_for_content_permission_only(self) -> None:
        """Isolation: platform.manage_content must not satisfy the
        platform.manage_cron check this route requires."""
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/pause", headers=_content_only_headers())
        self.assertEqual(resp.status_code, 403)

    def test_pause_success_as_admin(self) -> None:
        """An admin's pause comments out the job line in the real spool file."""
        spool = self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/pause", headers=_admin_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": "mysql-backup", "paused": True})
        self.assertTrue(Path(spool).read_text().startswith("#"))

    def test_resume_success_as_admin(self) -> None:
        """An admin's resume uncomments the job line in the real spool file."""
        spool = self._set_spool("# 0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/resume", headers=_admin_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": "mysql-backup", "paused": False})
        self.assertFalse(Path(spool).read_text().startswith("#"))

    def test_schedule_success_as_admin(self) -> None:
        """An admin's schedule update rewrites the job's cron
        expression in the real spool file."""
        spool = self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.put(
            "/cron/jobs/mysql-backup/schedule",
            json={"schedule": "30 5 * * *"},
            headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": "mysql-backup", "schedule": "30 5 * * *"})
        self.assertTrue(Path(spool).read_text().startswith("30 5 * * *"))

    def test_schedule_requires_admin_401(self) -> None:
        """Schedule with no Authorization header returns 401."""
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.put("/cron/jobs/mysql-backup/schedule", json={"schedule": "30 5 * * *"})
        self.assertEqual(resp.status_code, 401)

    def test_schedule_invalid_returns_400(self) -> None:
        """An invalid (non-cron) schedule expression returns 400."""
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.put(
            "/cron/jobs/mysql-backup/schedule",
            json={"schedule": "garbage"},
            headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_job_id_returns_404(self) -> None:
        """Pausing a job id outside the allowlist returns 404."""
        self._set_spool("0 4 * * * echo hi\n")
        resp = client.post("/cron/jobs/not-a-real-job/pause", headers=_admin_headers())
        self.assertEqual(resp.status_code, 404)

    def test_resume_unknown_job_id_returns_404(self) -> None:
        """Resuming a job id outside the allowlist returns 404."""
        self._set_spool("0 4 * * * echo hi\n")
        resp = client.post("/cron/jobs/not-a-real-job/resume", headers=_admin_headers())
        self.assertEqual(resp.status_code, 404)

    def test_missing_spool_file_returns_500(self) -> None:
        """A CRONTAB_SPOOL_PATH pointing at a nonexistent file returns 500."""
        os.environ["CRONTAB_SPOOL_PATH"] = "/nonexistent/crontab/path"
        resp = client.post("/cron/jobs/mysql-backup/pause", headers=_admin_headers())
        self.assertEqual(resp.status_code, 500)

    def test_whitelist_only_arbitrary_job_id_rejected(self) -> None:
        """Scheduling a brand-new, non-predefined job id is always 404
        -- never silently accepted as a new job."""
        # Never accepts an arbitrary new job -- only the 15 predefined ids.
        self._set_spool("0 4 * * * echo hi\n")
        resp = client.put(
            "/cron/jobs/my-custom-job/schedule",
            json={"schedule": "0 0 * * *"},
            headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
