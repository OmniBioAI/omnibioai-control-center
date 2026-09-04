"""tests/test_main.py"""
from __future__ import annotations
import os, subprocess, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
from fastapi.testclient import TestClient
import control_center.main as main_module
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import _JobState, _workspace_root, app

client = TestClient(app)


def _admin_headers():
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


def _cron_only_headers():
    """PR3D isolation fixture: holds platform.manage_cron only -- proves it
    does not satisfy report/coverage generation's platform.manage_content
    requirement."""
    token = jwt.encode({"sub": "3", "permissions": ["platform.manage_cron"]}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}

def _reset_job():
    j = main_module._job
    with j._lock:
        j.status = "idle"
        j.started_at = None
        j.finished_at = None
        j.message = ""

class TestJobState(unittest.TestCase):
    def _fresh(self): return _JobState()
    def setUp(self): _reset_job()
    def test_initial_idle(self): self.assertEqual(self._fresh().as_dict()["status"], "idle")
    def test_initial_started_at_none(self): self.assertIsNone(self._fresh().as_dict()["started_at"])
    def test_initial_finished_at_none(self): self.assertIsNone(self._fresh().as_dict()["finished_at"])
    def test_initial_message_empty(self): self.assertEqual(self._fresh().as_dict()["message"], "")
    def test_start_sets_running(self):
        j = self._fresh(); j.start()
        self.assertEqual(j.as_dict()["status"], "running")
    def test_start_sets_started_at(self):
        j = self._fresh(); j.start()
        self.assertIsNotNone(j.as_dict()["started_at"])
    def test_start_clears_finished_at(self):
        j = self._fresh(); j.start(); j.finish(); j.start()
        self.assertIsNone(j.as_dict()["finished_at"])
    def test_start_clears_message(self):
        j = self._fresh(); j.fail("old"); j.start()
        self.assertEqual(j.as_dict()["message"], "")
    def test_finish_sets_done(self):
        j = self._fresh(); j.start(); j.finish("x")
        self.assertEqual(j.as_dict()["status"], "done")
    def test_finish_sets_message(self):
        j = self._fresh(); j.start(); j.finish("done msg")
        self.assertEqual(j.as_dict()["message"], "done msg")
    def test_finish_sets_finished_at(self):
        j = self._fresh(); j.start(); j.finish()
        self.assertIsNotNone(j.as_dict()["finished_at"])
    def test_finish_empty_message_ok(self):
        j = self._fresh(); j.start(); j.finish()
        self.assertEqual(j.as_dict()["message"], "")
    def test_fail_sets_error(self):
        j = self._fresh(); j.start(); j.fail("err")
        self.assertEqual(j.as_dict()["status"], "error")
    def test_fail_sets_message(self):
        j = self._fresh(); j.start(); j.fail("FileNotFoundError")
        self.assertIn("FileNotFoundError", j.as_dict()["message"])
    def test_fail_sets_finished_at(self):
        j = self._fresh(); j.start(); j.fail("e")
        self.assertIsNotNone(j.as_dict()["finished_at"])
    def test_as_dict_has_all_keys(self):
        d = self._fresh().as_dict()
        for k in ("status","started_at","finished_at","message"):
            self.assertIn(k, d)
    def test_thread_safety(self):
        j = self._fresh(); errors = []
        def w():
            try: j.start(); time.sleep(0.005); j.finish("ok")
            except Exception as e: errors.append(e)
        ts = [threading.Thread(target=w) for _ in range(10)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(errors, [])

class TestWorkspaceRoot(unittest.TestCase):
    def test_default(self):
        os.environ.pop("WORKSPACE_ROOT", None)
        self.assertEqual(_workspace_root(), Path("/workspace"))
    def test_env_var(self):
        os.environ["WORKSPACE_ROOT"] = "/x"
        try: self.assertEqual(_workspace_root(), Path("/x"))
        finally: del os.environ["WORKSPACE_ROOT"]
    def test_returns_path(self): self.assertIsInstance(_workspace_root(), Path)

class TestDashboard(unittest.TestCase):
    def setUp(self): _reset_job()
    def test_200(self): self.assertEqual(client.get("/", headers=_admin_headers()).status_code, 200)
    def test_html(self): self.assertIn("text/html", client.get("/", headers=_admin_headers()).headers["content-type"])
    def test_generate_button(self): self.assertIn("Generate Report", client.get("/", headers=_admin_headers()).text)
    def test_status_poll(self): self.assertIn("/report/status", client.get("/", headers=_admin_headers()).text)
    def test_login_form_present_when_no_report(self):
        resp = client.get("/", headers=_admin_headers())
        self.assertIn("login-email", resp.text)
        self.assertIn("login-password", resp.text)
    def test_no_dashboard_link_when_no_report(self):
        # The old "View Dashboard" link is gone now that /dashboard just
        # redirects back to / -- nothing should link to it anymore.
        self.assertNotIn("View Dashboard", client.get("/", headers=_admin_headers()).text)
    def test_401_when_no_token(self):
        # / previously had no auth requirement at all -- this is the exact
        # gap control.omnibioai.org exposed by routing directly to this
        # backend, bypassing nginx-router's auth_request gate.
        self.assertEqual(client.get("/").status_code, 401)


class TestDashboardRedirect(unittest.TestCase):
    def test_redirects_to_root(self):
        resp = client.get("/dashboard", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/")


class TestRootWithReport(unittest.TestCase):
    def setUp(self):
        _reset_job()
        self._tmp = tempfile.mkdtemp()
        p = Path(self._tmp) / "work" / "out" / "reports"
        p.mkdir(parents=True)
        self._report_file = p / "omnibioai_ecosystem_report.html"
        self._report_file.write_text("<html><body><h1>My Report</h1></body></html>")
        os.environ["WORKSPACE_ROOT"] = self._tmp

    def tearDown(self):
        del os.environ["WORKSPACE_ROOT"]
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_200(self): self.assertEqual(client.get("/", headers=_admin_headers()).status_code, 200)
    def test_html(self): self.assertIn("text/html", client.get("/", headers=_admin_headers()).headers["content-type"])
    def test_injects_sticky_bar(self): self.assertIn("omni-header", client.get("/", headers=_admin_headers()).text)
    def test_report_content_preserved(self): self.assertIn("<h1>My Report</h1>", client.get("/", headers=_admin_headers()).text)
    def test_summary_in_sticky_bar(self): self.assertIn("/summary", client.get("/", headers=_admin_headers()).text)
    def test_setInterval_in_sticky_bar(self): self.assertIn("setInterval", client.get("/", headers=_admin_headers()).text)

    def test_no_body_tag_prepends_bar(self):
        self._report_file.write_text("<h1>No Body Tag</h1>")
        response = client.get("/", headers=_admin_headers())
        self.assertIn("<h1>No Body Tag</h1>", response.text)
        self.assertIn("omni-header", response.text)

class TestReportGenerate(unittest.TestCase):
    def setUp(self): _reset_job()
    def _post(self):
        with patch("control_center.main.threading.Thread") as m:
            m.return_value = MagicMock()
            return client.post("/report/generate", headers=_admin_headers()), m
    def test_200_when_idle(self): self.assertEqual(self._post()[0].status_code, 200)
    def test_started_status(self): self.assertEqual(self._post()[0].json()["status"], "started")
    def test_409_when_running(self):
        main_module._job.start()
        self.assertEqual(client.post("/report/generate", headers=_admin_headers()).status_code, 409)
    def test_409_has_error_key(self):
        main_module._job.start()
        self.assertIn("error", client.post("/report/generate", headers=_admin_headers()).json())
    def test_job_set_running(self):
        self._post()
        self.assertEqual(main_module._job.as_dict()["status"], "running")
    def test_thread_started(self):
        _, m = self._post()
        m.return_value.start.assert_called_once()
    def test_thread_is_daemon(self):
        with patch("control_center.main.threading.Thread") as m:
            m.return_value = MagicMock()
            client.post("/report/generate", headers=_admin_headers())
        self.assertTrue(m.call_args[1].get("daemon", False))
    def test_401_when_no_token(self):
        self.assertEqual(client.post("/report/generate").status_code, 401)
    def test_403_when_not_admin(self):
        token = jwt.encode({"sub": "2", "roles": ["user"]}, JWT_SECRET, algorithm="HS256")
        resp = client.post("/report/generate", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)
    def test_403_for_cron_permission_only(self):
        """Isolation: platform.manage_cron must not satisfy the
        platform.manage_content check this route requires."""
        resp = client.post("/report/generate", headers=_cron_only_headers())
        self.assertEqual(resp.status_code, 403)

class TestReportStatus(unittest.TestCase):
    def setUp(self): _reset_job()
    def test_200(self): self.assertEqual(client.get("/report/status", headers=_admin_headers()).status_code, 200)
    def test_has_status(self): self.assertIn("status", client.get("/report/status", headers=_admin_headers()).json())
    def test_has_report_exists(self): self.assertIn("report_exists", client.get("/report/status", headers=_admin_headers()).json())
    def test_has_generated_at(self): self.assertIn("report_generated_at", client.get("/report/status", headers=_admin_headers()).json())
    def test_idle_by_default(self): self.assertEqual(client.get("/report/status", headers=_admin_headers()).json()["status"], "idle")
    def test_200_when_no_token(self):
        # DELIBERATELY PUBLIC (restored): commit 8705cbf gated this route
        # behind platform.manage_infra, which broke ControlApp's anonymous
        # Ecosystem Report page (PublicEcosystemPage.tsx polls it). The
        # 2026-09-02 public/admin-split investigation reverted that gate.
        # Was `test_401_when_no_token` asserting 401 here.
        resp = client.get("/report/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("status", resp.json())
        self.assertIn("report_exists", resp.json())
    def test_report_exists_false(self):
        os.environ["WORKSPACE_ROOT"] = "/nonexistent"
        try: self.assertFalse(client.get("/report/status", headers=_admin_headers()).json()["report_exists"])
        finally: del os.environ["WORKSPACE_ROOT"]
    def test_report_generated_at_none(self):
        os.environ["WORKSPACE_ROOT"] = "/nonexistent"
        try: self.assertIsNone(client.get("/report/status", headers=_admin_headers()).json()["report_generated_at"])
        finally: del os.environ["WORKSPACE_ROOT"]
    def test_report_exists_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"work"/"out"/"reports"; p.mkdir(parents=True)
            (p/"omnibioai_ecosystem_report.html").write_text("<html/>")
            os.environ["WORKSPACE_ROOT"] = tmp
            try: self.assertTrue(client.get("/report/status", headers=_admin_headers()).json()["report_exists"])
            finally: del os.environ["WORKSPACE_ROOT"]
    def test_generated_at_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"work"/"out"/"reports"; p.mkdir(parents=True)
            (p/"omnibioai_ecosystem_report.html").write_text("<html/>")
            os.environ["WORKSPACE_ROOT"] = tmp
            try: self.assertIsNotNone(client.get("/report/status", headers=_admin_headers()).json()["report_generated_at"])
            finally: del os.environ["WORKSPACE_ROOT"]
    def test_reflects_running(self):
        main_module._job.start()
        self.assertEqual(client.get("/report/status", headers=_admin_headers()).json()["status"], "running")
    def test_reflects_done(self):
        main_module._job.start(); main_module._job.finish("ok")
        self.assertEqual(client.get("/report/status", headers=_admin_headers()).json()["status"], "done")
    def test_reflects_error(self):
        main_module._job.start(); main_module._job.fail("bad")
        self.assertEqual(client.get("/report/status", headers=_admin_headers()).json()["status"], "error")
    def test_message_in_response(self):
        main_module._job.start(); main_module._job.fail("Script not found")
        self.assertIn("Script not found", client.get("/report/status", headers=_admin_headers()).json()["message"])


def _reset_coverage_job():
    j = main_module._coverage_job
    with j._lock:
        j.status = "idle"
        j.started_at = None
        j.finished_at = None
        j.message = ""


class TestCoverageGenerate(unittest.TestCase):
    def setUp(self): _reset_coverage_job()
    def _post(self):
        with patch("control_center.main.threading.Thread") as m:
            m.return_value = MagicMock()
            return client.post("/coverage/generate", headers=_admin_headers()), m
    def test_200_when_idle(self): self.assertEqual(self._post()[0].status_code, 200)
    def test_started_status(self): self.assertEqual(self._post()[0].json()["status"], "started")
    def test_409_when_running(self):
        main_module._coverage_job.start()
        self.assertEqual(client.post("/coverage/generate", headers=_admin_headers()).status_code, 409)
    def test_409_has_error_key(self):
        main_module._coverage_job.start()
        self.assertIn("error", client.post("/coverage/generate", headers=_admin_headers()).json())
    def test_job_set_running(self):
        self._post()
        self.assertEqual(main_module._coverage_job.as_dict()["status"], "running")
    def test_thread_started(self):
        _, m = self._post()
        m.return_value.start.assert_called_once()
    def test_thread_is_daemon(self):
        with patch("control_center.main.threading.Thread") as m:
            m.return_value = MagicMock()
            client.post("/coverage/generate", headers=_admin_headers())
        self.assertTrue(m.call_args[1].get("daemon", False))
    def test_401_when_no_token(self):
        self.assertEqual(client.post("/coverage/generate").status_code, 401)
    def test_403_when_not_admin(self):
        token = jwt.encode({"sub": "2", "roles": ["user"]}, JWT_SECRET, algorithm="HS256")
        resp = client.post("/coverage/generate", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)
    def test_403_for_cron_permission_only(self):
        """Isolation: platform.manage_cron must not satisfy the
        platform.manage_content check this route requires."""
        resp = client.post("/coverage/generate", headers=_cron_only_headers())
        self.assertEqual(resp.status_code, 403)


class TestCoverageStatus(unittest.TestCase):
    def setUp(self): _reset_coverage_job()
    def test_200(self): self.assertEqual(client.get("/coverage/status", headers=_admin_headers()).status_code, 200)
    def test_has_status(self): self.assertIn("status", client.get("/coverage/status", headers=_admin_headers()).json())
    def test_has_result_exists(self): self.assertIn("result_exists", client.get("/coverage/status", headers=_admin_headers()).json())
    def test_has_generated_at(self): self.assertIn("result_generated_at", client.get("/coverage/status", headers=_admin_headers()).json())
    def test_idle_by_default(self): self.assertEqual(client.get("/coverage/status", headers=_admin_headers()).json()["status"], "idle")
    def test_401_when_no_token(self):
        # Previously open to everyone (no admin gate) -- closed as part of
        # the same fix as /report/status, /storage, /cron/jobs, etc.
        self.assertEqual(client.get("/coverage/status").status_code, 401)
    def test_result_exists_true_and_generated_at_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "omnibioai-work" / "out" / "coverage"
            p.mkdir(parents=True)
            (p / f"{main_module._COVERAGE_REPO}.json").write_text("{}")
            with patch("control_center.main._workspace_root", return_value=Path(tmp)):
                data = client.get("/coverage/status", headers=_admin_headers()).json()
        self.assertTrue(data["result_exists"])
        self.assertIsNotNone(data["result_generated_at"])


class TestRunCoverageJob(unittest.TestCase):
    def setUp(self):
        _reset_coverage_job()
        self._tmp = tempfile.mkdtemp()
        script_dir = Path(self._tmp) / "omnibioai-control-center" / "scripts"
        script_dir.mkdir(parents=True)
        (script_dir / "run_coverage_host.py").write_text("# fake\n")
        self._workspace_patch = patch("control_center.main._workspace_root", return_value=Path(self._tmp))
        self._workspace_patch.start()

    def tearDown(self):
        self._workspace_patch.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_script_fails_job(self):
        with patch("control_center.main._workspace_root", return_value=Path("/nonexistent")):
            main_module._run_coverage_job()
        self.assertEqual(main_module._coverage_job.as_dict()["status"], "error")
        self.assertIn("not found", main_module._coverage_job.as_dict()["message"])

    def test_success_sets_done(self):
        result = MagicMock(returncode=0, stdout="Done — 1 ok, 0 with issues, 0 skipped\n", stderr="")
        with patch("control_center.main.subprocess.run", return_value=result):
            main_module._run_coverage_job()
        self.assertEqual(main_module._coverage_job.as_dict()["status"], "done")

    def test_nonzero_returncode_fails_job(self):
        result = MagicMock(returncode=1, stdout="", stderr="boom")
        with patch("control_center.main.subprocess.run", return_value=result):
            main_module._run_coverage_job()
        state = main_module._coverage_job.as_dict()
        self.assertEqual(state["status"], "error")
        self.assertIn("boom", state["message"])

    def test_timeout_fails_job(self):
        with patch("control_center.main.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 600)):
            main_module._run_coverage_job()
        self.assertEqual(main_module._coverage_job.as_dict()["status"], "error")

    def test_unexpected_exception_fails_job(self):
        with patch("control_center.main.subprocess.run", side_effect=RuntimeError("boom")):
            main_module._run_coverage_job()
        state = main_module._coverage_job.as_dict()
        self.assertEqual(state["status"], "error")
        self.assertIn("RuntimeError", state["message"])

class TestResetJobToIdle(unittest.TestCase):
    def setUp(self): _reset_job()

    def test_resets_done_to_idle(self):
        main_module._job.start(); main_module._job.finish("ok")
        main_module._reset_job_to_idle(delay_s=0)
        self.assertEqual(main_module._job.as_dict()["status"], "idle")

    def test_resets_error_to_idle(self):
        main_module._job.start(); main_module._job.fail("bad")
        main_module._reset_job_to_idle(delay_s=0)
        self.assertEqual(main_module._job.as_dict()["status"], "idle")

    def test_does_not_reset_running(self):
        main_module._job.start()
        main_module._reset_job_to_idle(delay_s=0)
        self.assertEqual(main_module._job.as_dict()["status"], "running")

    def test_does_not_reset_idle(self):
        main_module._reset_job_to_idle(delay_s=0)
        self.assertEqual(main_module._job.as_dict()["status"], "idle")


class TestRunReportJob(unittest.TestCase):
    def setUp(self): _reset_job(); main_module._job.start()
    def test_fails_script_not_found(self):
        os.environ["WORKSPACE_ROOT"] = "/nonexistent"
        try:
            main_module._run_report_job()
            self.assertEqual(main_module._job.as_dict()["status"], "error")
            self.assertIn("not found", main_module._job.as_dict()["message"])
        finally: del os.environ["WORKSPACE_ROOT"]
    def test_succeeds_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)/"omnibioai-control-center"/"scripts"; d.mkdir(parents=True)
            (d/"generate_report.py").write_text('print("done")')
            os.environ["WORKSPACE_ROOT"] = tmp
            try: main_module._run_report_job(); self.assertEqual(main_module._job.as_dict()["status"], "done")
            finally: del os.environ["WORKSPACE_ROOT"]
    def test_last_stdout_line_as_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)/"omnibioai-control-center"/"scripts"; d.mkdir(parents=True)
            (d/"generate_report.py").write_text('print("line1")\nprint("✓ Report written")')
            os.environ["WORKSPACE_ROOT"] = tmp
            try: main_module._run_report_job(); self.assertIn("✓ Report written", main_module._job.as_dict()["message"])
            finally: del os.environ["WORKSPACE_ROOT"]
    def test_fails_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)/"omnibioai-control-center"/"scripts"; d.mkdir(parents=True)
            (d/"generate_report.py").write_text('import sys; sys.exit(1)')
            os.environ["WORKSPACE_ROOT"] = tmp
            try: main_module._run_report_job(); self.assertEqual(main_module._job.as_dict()["status"], "error")
            finally: del os.environ["WORKSPACE_ROOT"]
    def test_stderr_as_error_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)/"omnibioai-control-center"/"scripts"; d.mkdir(parents=True)
            (d/"generate_report.py").write_text('import sys; sys.stderr.write("cloc not found"); sys.exit(1)')
            os.environ["WORKSPACE_ROOT"] = tmp
            try: main_module._run_report_job(); self.assertIn("cloc not found", main_module._job.as_dict()["message"])
            finally: del os.environ["WORKSPACE_ROOT"]
    def test_timeout_sets_error(self):
        with patch("control_center.main.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="p", timeout=600)):
            with tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)/"omnibioai-control-center"/"scripts"; d.mkdir(parents=True)
                (d/"generate_report.py").write_text("pass")
                os.environ["WORKSPACE_ROOT"] = tmp
                try: main_module._run_report_job(); self.assertIn("timed out", main_module._job.as_dict()["message"])
                finally: del os.environ["WORKSPACE_ROOT"]
    def test_oserror_sets_error(self):
        with patch("control_center.main.subprocess.run", side_effect=OSError("disk full")):
            with tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)/"omnibioai-control-center"/"scripts"; d.mkdir(parents=True)
                (d/"generate_report.py").write_text("pass")
                os.environ["WORKSPACE_ROOT"] = tmp
                try: main_module._run_report_job(); self.assertIn("disk full", main_module._job.as_dict()["message"])
                finally: del os.environ["WORKSPACE_ROOT"]
    def test_done_message_generic_when_no_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)/"omnibioai-control-center"/"scripts"; d.mkdir(parents=True)
            (d/"generate_report.py").write_text("")
            os.environ["WORKSPACE_ROOT"] = tmp
            try: main_module._run_report_job(); self.assertEqual(main_module._job.as_dict()["message"], "Done")
            finally: del os.environ["WORKSPACE_ROOT"]


class TestReportData(unittest.TestCase):
    """DELIBERATELY PUBLIC (2026-09-03 decision, reversing part of commit
    8705cbf): restores ControlApp's full Projects/Languages/Coverage/
    Ecosystem-Status dashboard, accepting gitStatus[] (branch names,
    modified/untracked/unpushed commit counts) becoming publicly visible
    as a conscious tradeoff -- see report_data()'s own docstring in
    main.py. Was `test_401_when_no_token` asserting 401 here, same
    pattern as TestReportStatus.test_200_when_no_token /
    TestLlmsPublicAccess. Every case below now runs with no auth header
    at all, proving the route doesn't require one at any point in its
    logic (missing file, present file, malformed file)."""

    def test_200_when_no_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "work" / "out" / "reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "report_data.json").write_text('{"projects": 3, "languages": ["python"]}')
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/report/data")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"projects": 3, "languages": ["python"]})

    def test_200_with_token_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "work" / "out" / "reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "report_data.json").write_text('{"projects": 3}')
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/report/data", headers=_admin_headers())
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(resp.status_code, 200)

    def test_404_when_no_report_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/report/data")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.json())

    def test_returns_parsed_json_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "work" / "out" / "reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "report_data.json").write_text('{"projects": 3, "languages": ["python"]}')
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/report/data")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"projects": 3, "languages": ["python"]})

    def test_500_on_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "work" / "out" / "reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "report_data.json").write_text("not-json{")
            os.environ["WORKSPACE_ROOT"] = tmp
            try:
                resp = client.get("/report/data")
            finally:
                del os.environ["WORKSPACE_ROOT"]
        self.assertEqual(resp.status_code, 500)
        self.assertIn("error", resp.json())


class TestSchedulerLoop(unittest.TestCase):
    def setUp(self):
        _reset_job()

    def test_triggers_report_job_when_idle(self):
        # Break out of the infinite loop after the first triggering pass by
        # raising from the second `sleep` call.
        sleep_calls = {"n": 0}

        def fake_sleep(_seconds):
            sleep_calls["n"] += 1
            if sleep_calls["n"] >= 2:
                raise SystemExit("stop loop")

        with patch("control_center.main._time_mod.sleep", side_effect=fake_sleep):
            with patch("control_center.main.threading.Thread") as mock_thread:
                with self.assertRaises(SystemExit):
                    main_module._scheduler_loop()

        mock_thread.assert_called_once()
        self.assertEqual(mock_thread.call_args.kwargs.get("target"), main_module._run_report_job)

    def test_skips_when_job_already_running(self):
        main_module._job.start()
        sleep_calls = {"n": 0}

        def fake_sleep(_seconds):
            sleep_calls["n"] += 1
            if sleep_calls["n"] >= 2:
                raise SystemExit("stop loop")

        with patch("control_center.main._time_mod.sleep", side_effect=fake_sleep):
            with patch("control_center.main.threading.Thread") as mock_thread:
                with self.assertRaises(SystemExit):
                    main_module._scheduler_loop()

        mock_thread.assert_not_called()

    def test_exception_in_loop_body_is_caught(self):
        sleep_calls = {"n": 0}

        def fake_sleep(_seconds):
            sleep_calls["n"] += 1
            if sleep_calls["n"] >= 2:
                raise SystemExit("stop loop")

        with patch("control_center.main._time_mod.sleep", side_effect=fake_sleep):
            with patch.object(main_module._job, "as_dict", side_effect=RuntimeError("boom")):
                with self.assertRaises(SystemExit):
                    main_module._scheduler_loop()
        # No exception propagated from the RuntimeError itself — only our
        # SystemExit sentinel used to stop the loop — proving it was caught.


class TestOnStartup(unittest.TestCase):
    def test_starts_scheduler_thread(self):
        with patch("control_center.main.threading.Thread") as mock_thread:
            asyncio_run = __import__("asyncio").run
            asyncio_run(main_module.on_startup())
        mock_thread.assert_called_once()
        self.assertEqual(mock_thread.call_args.kwargs.get("target"), main_module._scheduler_loop)
        mock_thread.return_value.start.assert_called_once()


class TestPlatformManageInfraAuth(unittest.TestCase):
    """PR3D: docker_router/services_router/summary_router/config_router are
    gated at router-inclusion time (main.py) behind
    platform.manage_infra, not per-route -- test_routes_docker.py,
    test_runner.py, and test_routes_config.py cover each route's own
    logic with an always-sufficient token, so these regression tests
    cover only the authorization layer itself: missing token, wrong
    permission, and correct permission, once per gated router.

    Extended (control.omnibioai.org direct-tunnel audit, commit 8705cbf)
    to cover routes that were found reachable with no auth at all: /,
    /report, /report/data, /coverage/status, /knowledge-base, /storage,
    /cron/jobs, /cron/jobs/{id}/log.

    NOTE (2026-09-02 public/admin-split investigation): /report/status and
    /llms were in this list but have been removed -- 8705cbf's audit
    over-gated them. Both are part of the Public Read-Only Control Center
    design (91755fb, docs/public-control-center.md): /report/status backs
    ControlApp's anonymous Ecosystem Report page and /llms its anonymous
    LLMs page. Their "public, no token needed" behavior is now asserted by
    TestReportStatus.test_200_when_no_token and TestLlmsPublicAccess
    respectively.

    NOTE (2026-09-03 decision): /report/data has also been removed from
    this list, for the same reason -- see report_data()'s own docstring
    in main.py and TestReportData above. Unlike the 09-02 cases, this one
    is a conscious, accepted tradeoff (gitStatus[] becoming public), not a
    correction of an over-gate. Everything still in _cases() below stays
    gated -- that is the regression guard this decision must not weaken."""

    def _cases(self):
        return (
            ("GET", "/docker/containers"),
            ("GET", "/services"),
            ("GET", "/summary"),
            ("GET", "/config"),
            ("GET", "/"),
            ("GET", "/report"),
            ("GET", "/coverage/status"),
            ("GET", "/knowledge-base"),
            ("GET", "/storage"),
            ("GET", "/cron/jobs"),
            ("GET", "/cron/jobs/mysql-backup/log"),
        )

    def test_401_when_no_token(self):
        for method, path in self._cases():
            with self.subTest(path=path):
                resp = client.request(method, path)
                self.assertEqual(resp.status_code, 401)

    def test_403_for_cron_permission_only(self):
        """Isolation: platform.manage_cron must not satisfy the
        platform.manage_infra check these routers require."""
        for method, path in self._cases():
            with self.subTest(path=path):
                resp = client.request(method, path, headers=_cron_only_headers())
                self.assertEqual(resp.status_code, 403)

    def test_not_401_or_403_with_infra_permission(self):
        for method, path in self._cases():
            with self.subTest(path=path):
                resp = client.request(method, path, headers=_admin_headers())
                self.assertNotIn(resp.status_code, (401, 403))


# A fully-populated report_data.json: every array that must NEVER reach
# /report/public-stats is present and non-empty here, plus realistic
# aggregate scalars. Shared by the negative-leak tests below.
_FULL_REPORT_DATA = {
    "generated_at": "2026-09-02T04:00:00+00:00",
    "grand": {"files": 14820, "code": 1863200, "comment": 240100, "blank": 190500},
    "projects": [
        {"name": "tes", "full": "omnibioai-tes", "cat": "execution", "catLabel": "Execution",
         "files": 900, "code": 120000, "comment": 15000, "blank": 12000, "pct": 6.44},
        {"name": "auth", "full": "omnibioai-auth", "cat": "security", "catLabel": "Security",
         "files": 300, "code": 40000, "comment": 5000, "blank": 4000, "pct": 2.15},
    ],
    "languages": [
        {"name": "Python", "type": "backend", "typeLabel": "Backend",
         "files": 6000, "code": 900000, "comment": 120000, "blank": 90000, "pct": 48.3},
        {"name": "TypeScript", "type": "frontend", "typeLabel": "Frontend",
         "files": 4000, "code": 500000, "comment": 40000, "blank": 50000, "pct": 26.8},
    ],
    "coverage": [
        {"repo": "omnibioai-tes", "status": "ok", "pct": 92.5,
         "stmts": 4000, "missed": 300, "branches": 800, "failUnder": 90.0},
        {"repo": "omnibioai-auth", "status": "ok", "pct": 61.0,
         "stmts": 2000, "missed": 780, "branches": 400, "failUnder": 85.0},
        {"repo": "omnibioai-rag", "status": "no_total_found", "pct": None,
         "stmts": None, "missed": None, "branches": None, "failUnder": None},
    ],
    "gitStatus": [
        {"repo": "omnibioai-tes", "branch": "feat/secret-internal-branch", "nonMain": True,
         "clean": False, "modified": 3, "untracked": 1, "unpushed": 2, "details": "3 modified, 1 untracked, 2 unpushed"},
    ],
}

# The exact set of keys /report/public-stats is allowed to return, and
# every substring that would prove a per-repo array leaked in.
_PUBLIC_STATS_KEYS = {
    "generated_at", "total_lines", "total_files",
    "ecosystem_coverage_percent", "repos_measured",
}
# Substrings that would only be present if a per-repo array leaked in.
# Deliberately avoids bare "coverage"/"repos" -- those collide with the
# legitimate keys ecosystem_coverage_percent / repos_measured. Uses the
# JSON-quoted array keys plus distinctive per-repo values instead.
_LEAK_MARKERS = (
    '"projects"', '"languages"', '"gitStatus"', '"coverage":',
    "omnibioai-tes", "omnibioai-auth", "omnibioai-rag",
    "feat/secret-internal-branch", "unpushed", "failUnder",
)


class TestReportPublicStats(unittest.TestCase):
    """PART 1 (2026-09-02 investigation): the new deliberately-public
    GET /report/public-stats. No token, five aggregate keys only, and --
    critically -- the per-repo arrays from report_data.json can never
    appear in it under any code path."""

    def _get_with_data(self, data, *, headers=None):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "work" / "out" / "reports"
            reports_dir.mkdir(parents=True)
            import json as _json
            (reports_dir / "report_data.json").write_text(_json.dumps(data))
            with patch("control_center.main._workspace_root", return_value=Path(tmp)):
                return client.get("/report/public-stats", headers=headers or {})

    def test_200_no_token_exact_keys(self):
        resp = self._get_with_data(_FULL_REPORT_DATA)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json().keys()), _PUBLIC_STATS_KEYS)

    def test_values_from_fixture(self):
        body = self._get_with_data(_FULL_REPORT_DATA).json()
        self.assertEqual(body["generated_at"], "2026-09-02T04:00:00+00:00")
        self.assertEqual(body["total_lines"], 1863200)
        self.assertEqual(body["total_files"], 14820)
        # statement-weighted: (4000-300)+(2000-780) = 4920 covered of
        # 6000 total stmts -> 82.0%. NOT the unweighted mean of
        # (92.5, 61.0) = 76.75 the HTML report would show.
        self.assertEqual(body["ecosystem_coverage_percent"], 82.0)
        # two rows have a non-null pct; the third (pct=None) does not.
        self.assertEqual(body["repos_measured"], 2)

    def test_never_leaks_per_repo_arrays_even_when_populated(self):
        """The critical negative test: a fully-populated report_data.json
        (projects/languages/coverage/gitStatus all present) must still
        produce a response with none of them, by key or by value."""
        resp = self._get_with_data(_FULL_REPORT_DATA)
        body = resp.json()
        self.assertEqual(set(body.keys()), _PUBLIC_STATS_KEYS)
        raw_text = resp.text
        for marker in _LEAK_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, raw_text)
        # and nothing list/dict-shaped snuck through as a value
        for v in body.values():
            self.assertNotIsInstance(v, (list, dict))

    def test_token_does_not_change_shape(self):
        """Presence of a valid admin token must not widen the response --
        this endpoint has exactly one shape for everyone."""
        anon = self._get_with_data(_FULL_REPORT_DATA).json()
        authed = self._get_with_data(_FULL_REPORT_DATA, headers=_admin_headers()).json()
        self.assertEqual(anon, authed)

    def test_no_report_data_returns_200_null_shape_not_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("control_center.main._workspace_root", return_value=Path(tmp)):
                resp = client.get("/report/public-stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {
            "generated_at": None,
            "total_lines": None,
            "total_files": None,
            "ecosystem_coverage_percent": None,
            "repos_measured": 0,
        })

    def test_malformed_report_data_returns_200_null_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "work" / "out" / "reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "report_data.json").write_text("not-json{")
            with patch("control_center.main._workspace_root", return_value=Path(tmp)):
                resp = client.get("/report/public-stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["repos_measured"], 0)
        self.assertIsNone(resp.json()["ecosystem_coverage_percent"])

    def test_no_coverage_rows_with_data_gives_null_percent(self):
        data = dict(_FULL_REPORT_DATA)
        data["coverage"] = [
            {"repo": "x", "status": "no_total_found", "pct": None,
             "stmts": None, "missed": None, "branches": None, "failUnder": None},
        ]
        body = self._get_with_data(data).json()
        self.assertIsNone(body["ecosystem_coverage_percent"])
        self.assertEqual(body["repos_measured"], 0)

    def test_non_dict_top_level_json_returns_null_shape(self):
        # report_data.json is valid JSON but not an object (e.g. a bare
        # list) -- treated the same as absent/malformed.
        body = self._get_with_data([1, 2, 3]).json()
        self.assertEqual(body["repos_measured"], 0)
        self.assertIsNone(body["total_lines"])

    def test_non_dict_coverage_row_is_skipped(self):
        data = dict(_FULL_REPORT_DATA)
        data["coverage"] = [
            "junk",
            {"repo": "omnibioai-tes", "pct": 90.0, "stmts": 1000, "missed": 100},
        ]
        body = self._get_with_data(data).json()
        self.assertEqual(body["repos_measured"], 1)
        self.assertEqual(body["ecosystem_coverage_percent"], 90.0)

    def test_grand_missing_gives_null_totals_but_still_computes_coverage(self):
        data = {k: v for k, v in _FULL_REPORT_DATA.items() if k != "grand"}
        body = self._get_with_data(data).json()
        self.assertIsNone(body["total_lines"])
        self.assertIsNone(body["total_files"])
        self.assertEqual(body["ecosystem_coverage_percent"], 82.0)

    def test_registered_directly_on_app_not_report_router(self):
        """report_router carries a platform.manage_infra include-time gate;
        this route must not be on it (it 200s with no token, proven
        above). Guard the structural placement too."""
        import control_center.api.routes_report as routes_report
        report_router_paths = {r.path for r in routes_report.router.routes}
        self.assertNotIn("/report/public-stats", report_router_paths)


class TestLlmsPublicAccess(unittest.TestCase):
    """PART 2 (2026-09-02 investigation): GET /llms restored to public.
    Commit 8705cbf's blanket llm_router gate collapsed it into the admin
    tier; it backs ControlApp's anonymous LLMs page (91755fb,
    docs/public-control-center.md). GET /knowledge-base on the same
    router stays gated -- see TestKnowledgeBaseStillGated below and
    TestPlatformManageInfraAuth."""

    def test_200_when_no_token(self):
        resp = client.get("/llms")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("ollama", body)
        self.assertIn("api_keys", body)
        # boolean-only for secrets: no key value ever, just `configured`.
        for provider in body["api_keys"].values():
            self.assertIn("configured", provider)
            self.assertIsInstance(provider["configured"], bool)

    def test_200_with_token_too(self):
        self.assertEqual(client.get("/llms", headers=_admin_headers()).status_code, 200)


class TestOverGateRegressionGuard(unittest.TestCase):
    """The 2026-09-02 revert must not spill past /report/status + /llms,
    and the 2026-09-03 decision must not spill past /report/data on top
    of those. Every route below stays platform.manage_infra-gated (401
    w/o token) exactly as commit 8705cbf left it. Overlaps
    TestPlatformManageInfraAuth on purpose -- this one is the named,
    human-readable list from the change's own scope statement."""

    STILL_GATED = (
        "/",
        "/coverage/status",
        "/knowledge-base",
        "/storage",
        "/cron/jobs",
        "/cron/jobs/mysql-backup/log",
    )

    def test_still_401_without_token(self):
        for path in self.STILL_GATED:
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 401)


if __name__ == "__main__":
    unittest.main()
