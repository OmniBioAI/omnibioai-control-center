"""scripts/check_tes_runnable.py: alert after 10 minutes below 1000 runnable TES HTTP tools."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_tes_runnable.py"
_spec = importlib.util.spec_from_file_location("check_tes_runnable", SCRIPT)
check = importlib.util.module_from_spec(_spec)
sys.modules["check_tes_runnable"] = check
_spec.loader.exec_module(check)


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(check, "MIN_RUNNABLE", 1000)
    monkeypatch.setattr(check, "WINDOW_MINUTES", 10.0)
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret")


class TestDecide:
    def test_healthy_stays_ok_and_clears_state(self):
        assert check.decide(1305, {}, 1000.0) == ("ok", {})
        assert check.decide(1305, {"below_since": 900.0}, 1000.0) == ("recovered", {})

    def test_alerts_only_after_the_whole_window(self):
        action, state = check.decide(0, {}, 1000.0)
        assert (action, state) == ("waiting", {"below_since": 1000.0})
        assert check.decide(0, state, 1000.0 + 599)[0] == "waiting"
        assert check.decide(999, state, 1000.0 + 600)[0] == "alert"

    def test_threshold_is_inclusive(self):
        assert check.decide(1000, {}, 1.0)[0] == "ok"


def _resp(json_body=None, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.raise_for_status.return_value = None
    return r


class TestMain:
    def _run(self, runnable, issues, *, now, state=None):
        if state is not None:
            check.save_state(state)

        def get(url, **kw):
            if url.endswith("/api/tools/verification/summary"):
                if isinstance(runnable, Exception):
                    raise runnable
                return _resp({"runnable": runnable})
            return _resp({"issues": issues})

        with patch.object(check.requests, "get", side_effect=get), \
                patch.object(check.requests, "post", return_value=_resp({"id": "ki-1"})) as post, \
                patch.object(check.requests, "put", return_value=_resp({"id": "ki-1"})) as put, \
                patch.object(check, "datetime") as dt:
            dt.now.return_value = _real_dt(now)
            dt.fromtimestamp.side_effect = lambda ts, tz: _real_dt(ts)
            assert check.main() == 0
        return post, put

    def test_files_one_high_severity_issue_after_ten_minutes(self):
        post, _ = self._run(0, [], now=2000.0, state={"below_since": 1000.0})
        body = post.call_args.kwargs["json"]
        assert body["severity"] == "high" and body["title"].startswith("[tes-runnable] TES has 0 runnable")
        assert "Bearer " in post.call_args.kwargs["headers"]["Authorization"]

    def test_unreachable_tes_counts_as_zero(self):
        import requests
        post, _ = self._run(requests.ConnectionError("down"), [], now=2000.0, state={"below_since": 1000.0})
        assert "TES not answering (ConnectionError)" in post.call_args.kwargs["json"]["description"]

    def test_existing_issue_is_updated_not_duplicated(self):
        post, put = self._run(5, [{"id": "ki-9", "title": "[tes-runnable] old", "status": "open"}],
                              now=2000.0, state={"below_since": 1000.0})
        post.assert_not_called()
        assert put.call_args.args[0].endswith("/known-issues/ki-9")

    def test_recovery_resolves_the_open_issue(self):
        post, put = self._run(1305, [{"id": "ki-9", "title": "[tes-runnable] old", "status": "open",
                                      "description": "x"}], now=2000.0, state={"below_since": 1000.0})
        post.assert_not_called()
        assert put.call_args.kwargs["json"]["status"] == "resolved"
        assert check.load_state() == {}

    def test_short_dip_never_alerts(self):
        post, put = self._run(0, [], now=1000.0)
        post.assert_not_called()
        put.assert_not_called()
        assert check.load_state() == {"below_since": 1000.0}


def _real_dt(ts):
    from datetime import UTC, datetime
    return datetime.fromtimestamp(ts, UTC)
