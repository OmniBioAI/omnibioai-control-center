"""
tests/test_routes_cron.py

Unit tests for:
  - control_center.api.routes_cron  (GET /cron/jobs, pause/resume/schedule)
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

    def test_open_no_auth_required(self) -> None:
        resp = client.get("/cron/jobs")
        self.assertEqual(resp.status_code, 200)

    def test_returns_all_jobs(self) -> None:
        data = client.get("/cron/jobs").json()
        self.assertEqual(len(data["jobs"]), 15)

    def test_uses_workspace_root_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
            with open(os.path.join(tmp, "logs", "pubmed_sync.log"), "w") as f:
                f.write("done\n")
            try:
                data = client.get("/cron/jobs").json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        pubmed_job = next(j for j in data["jobs"] if j["id"] == "pubmed-sync")
        self.assertEqual(pubmed_job["last_status"], "ok")


class TestCronJobLogRoute(unittest.TestCase):

    def test_open_no_auth_required(self) -> None:
        resp = client.get("/cron/jobs/mysql-backup/log")
        self.assertEqual(resp.status_code, 200)

    def test_unknown_job_id_returns_404(self) -> None:
        resp = client.get("/cron/jobs/not-a-real-job/log")
        self.assertEqual(resp.status_code, 404)

    def test_returns_log_tail_from_real_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            log_dir = Path(tmp) / "work" / "backups"
            log_dir.mkdir(parents=True)
            (log_dir / "omnibioai-backup.log").write_text("a\nb\nc\n")
            try:
                data = client.get("/cron/jobs/mysql-backup/log?lines=2").json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(data["lines"], ["b", "c"])
        self.assertEqual(data["total_lines"], 3)

    def test_lines_param_clamped_to_minimum_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            log_dir = Path(tmp) / "work" / "backups"
            log_dir.mkdir(parents=True)
            (log_dir / "omnibioai-backup.log").write_text("a\nb\nc\n")
            try:
                data = client.get("/cron/jobs/mysql-backup/log?lines=0").json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(data["lines_returned"], 1)

    def test_lines_param_clamped_to_maximum_1000(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            log_dir = Path(tmp) / "work" / "backups"
            log_dir.mkdir(parents=True)
            (log_dir / "omnibioai-backup.log").write_text(
                "\n".join(f"line {i}" for i in range(1500)) + "\n"
            )
            try:
                data = client.get("/cron/jobs/mysql-backup/log?lines=5000").json()
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(data["lines_returned"], 1000)


class TestCronMutationRoutes(unittest.TestCase):

    def _set_spool(self, content: str) -> str:
        tmp = tempfile.mkdtemp()
        spool = Path(tmp) / "crontab"
        spool.write_text(content)
        os.environ["CRONTAB_SPOOL_PATH"] = str(spool)
        return str(spool)

    def tearDown(self) -> None:
        os.environ.pop("CRONTAB_SPOOL_PATH", None)

    def test_pause_requires_admin_401(self) -> None:
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/pause")
        self.assertEqual(resp.status_code, 401)

    def test_pause_requires_admin_403_for_non_admin(self) -> None:
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/pause", headers=_user_headers())
        self.assertEqual(resp.status_code, 403)

    def test_pause_403_for_admin_role_without_cron_permission(self) -> None:
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
        spool = self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/pause", headers=_admin_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": "mysql-backup", "paused": True})
        self.assertTrue(Path(spool).read_text().startswith("#"))

    def test_resume_success_as_admin(self) -> None:
        spool = self._set_spool("# 0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.post("/cron/jobs/mysql-backup/resume", headers=_admin_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"id": "mysql-backup", "paused": False})
        self.assertFalse(Path(spool).read_text().startswith("#"))

    def test_schedule_success_as_admin(self) -> None:
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
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.put("/cron/jobs/mysql-backup/schedule", json={"schedule": "30 5 * * *"})
        self.assertEqual(resp.status_code, 401)

    def test_schedule_invalid_returns_400(self) -> None:
        self._set_spool("0 4 * * * /a/omnibioai-studio/scripts/backup-mysql.sh\n")
        resp = client.put(
            "/cron/jobs/mysql-backup/schedule",
            json={"schedule": "garbage"},
            headers=_admin_headers(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_job_id_returns_404(self) -> None:
        self._set_spool("0 4 * * * echo hi\n")
        resp = client.post("/cron/jobs/not-a-real-job/pause", headers=_admin_headers())
        self.assertEqual(resp.status_code, 404)

    def test_resume_unknown_job_id_returns_404(self) -> None:
        self._set_spool("0 4 * * * echo hi\n")
        resp = client.post("/cron/jobs/not-a-real-job/resume", headers=_admin_headers())
        self.assertEqual(resp.status_code, 404)

    def test_missing_spool_file_returns_500(self) -> None:
        os.environ["CRONTAB_SPOOL_PATH"] = "/nonexistent/crontab/path"
        resp = client.post("/cron/jobs/mysql-backup/pause", headers=_admin_headers())
        self.assertEqual(resp.status_code, 500)

    def test_whitelist_only_arbitrary_job_id_rejected(self) -> None:
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
