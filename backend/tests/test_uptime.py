"""
tests/test_uptime.py
Unit tests for:
  - control_center.core.uptime        (recording, pruning, summaries, sampler)
  - control_center.core.runner.check_service (no alert side effects)

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from control_center.core import runner, uptime


class _Store:
    def __enter__(self) -> Path:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "uptime.json"
        self.env = patch.dict(os.environ, {"UPTIME_STORE_PATH": str(self.path)})
        self.env.start()
        return self.path

    def __exit__(self, *exc: object) -> None:
        self.env.stop()
        self.tmp.cleanup()


class TestStorePath(unittest.TestCase):
    def test_default_under_workspace(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "UPTIME_STORE_PATH"}
        env["WORKSPACE_ROOT"] = "/ws"
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(uptime.store_path(), Path("/ws/work/out/uptime/uptime.json"))


class TestRecord(unittest.TestCase):
    def test_counts_by_status_and_skips_nameless(self) -> None:
        with _Store() as path:
            day = date(2026, 9, 25)
            uptime.record([{"name": "a", "status": "UP"}, {"name": "a", "status": "WARN"},
                           {"name": "a", "status": "DOWN"}, {"status": "UP"}, {"name": ""}], today=day)
            data = json.loads(path.read_text())
        self.assertEqual(data["services"]["a"]["2026-09-25"], {"up": 1, "degraded": 1, "down": 1})
        self.assertEqual(list(data["services"]), ["a"])

    def test_prunes_days_older_than_retention(self) -> None:
        with _Store():
            uptime.record([{"name": "a", "status": "UP"}], today=date(2026, 1, 1))
            uptime.record([{"name": "a", "status": "UP"}], today=date(2026, 9, 25))
            stored = uptime._load()["services"]["a"]
        self.assertEqual(list(stored), ["2026-09-25"])

    def test_corrupt_or_wrong_shape_store_starts_fresh(self) -> None:
        with _Store() as path:
            path.parent.mkdir(parents=True)
            for bad in ("not json", "[]", '{"services": []}'):
                path.write_text(bad)
                self.assertEqual(uptime._load(), {"services": {}})


class TestSummarize(unittest.TestCase):
    def test_public_labels_daily_and_overall(self) -> None:
        with _Store():
            today = date(2026, 9, 25)
            uptime.record([{"name": "wb", "status": "UP"}] * 3 + [{"name": "wb", "status": "DOWN"}], today=today)
            uptime.record([{"name": "wb", "status": "WARN"}], today=date(2026, 9, 24))
            summary = uptime.summarize({"wb": "Workbench", "never": "Never seen"}, days=3, today=today)
        wb, never = summary["services"]
        self.assertEqual(summary["window_days"], 3)
        self.assertEqual(wb["label"], "Workbench")
        self.assertEqual([d["availability_pct"] for d in wb["days"]], [None, 100.0, 75.0])
        self.assertEqual(wb["overall_pct"], 80.0)
        self.assertIsNone(never["overall_pct"])

    def test_operator_view_lists_every_service(self) -> None:
        with _Store():
            uptime.record([{"name": "b", "status": "UP"}, {"name": "a", "status": "UP"}], today=date(2026, 9, 25))
            summary = uptime.summarize(None, days=1, today=date(2026, 9, 25))
        self.assertEqual([s["label"] for s in summary["services"]], ["a", "b"])

    def test_zero_total_day_is_none(self) -> None:
        self.assertIsNone(uptime._day_availability({"up": 0, "degraded": 0, "down": 0}))
        self.assertIsNone(uptime._day_availability(None))


class TestSampler(unittest.TestCase):
    def test_sample_once_records_every_service(self) -> None:
        settings = SimpleNamespace(services={"a": {"type": "http"}, "b": {"type": "redis"}})
        with _Store(), patch.object(uptime, "check_service",
                                    side_effect=lambda n, c: {"name": n, "status": "UP"}) as check:
            uptime.sample_once(lambda: settings)
            stored = uptime._load()["services"]
        self.assertEqual(sorted(stored), ["a", "b"])
        self.assertEqual(check.call_count, 2)

    def test_sample_once_never_raises(self) -> None:
        def boom() -> None:
            raise FileNotFoundError("/config/control_center.yaml")
        uptime.sample_once(boom)  # logged, not raised

    def test_run_forever_is_bounded_for_tests(self) -> None:
        sleep = MagicMock()
        with _Store(), patch.object(uptime, "sample_once") as sample:
            uptime.run_forever(lambda: None, sleep=sleep, iterations=2)
        self.assertEqual(sample.call_count, 2)
        sleep.assert_called_with(uptime.SAMPLE_SECONDS)


class TestSingleSampler(unittest.TestCase):
    """Every worker process runs the loop; only the holder of the sampler
    lock samples, and another takes over when it goes away."""

    def test_only_one_holder_at_a_time(self) -> None:
        with _Store():
            first = uptime.try_become_sampler()
            self.assertIsNotNone(first)
            self.assertIsNone(uptime.try_become_sampler())
            first.close()  # the holding process exits
            second = uptime.try_become_sampler()
            self.assertIsNotNone(second)
            second.close()

    def test_loop_samples_only_while_holding_the_role(self) -> None:
        with _Store(), patch.object(uptime, "sample_once") as sample:
            other = uptime.try_become_sampler()
            uptime.run_forever(lambda: None, sleep=MagicMock(), iterations=2)
            self.assertEqual(sample.call_count, 0)
            other.close()
            uptime.run_forever(lambda: None, sleep=MagicMock(), iterations=2)
            self.assertEqual(sample.call_count, 2)


class TestCheckServiceHasNoAlertSideEffect(unittest.TestCase):
    """The uptime sampler runs every few minutes; check_service must not
    send the Down alert that run_all_checks sends."""

    def test_down_result_sends_no_alert(self) -> None:
        down = {"name": "x", "status": "DOWN", "target": "t", "message": "m"}
        with patch.object(runner, "check_http", return_value=down), \
                patch.object(runner, "_discord_notify") as notify:
            self.assertEqual(runner.check_service("x", {"type": "http"}), down)
        notify.assert_not_called()

    def test_unknown_type(self) -> None:
        result = runner.check_service("x", {"type": "ftp", "host": "h", "port": 1})
        self.assertEqual(result["status"], "WARN")


if __name__ == "__main__":
    unittest.main()
