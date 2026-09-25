"""
tests/test_showcase.py
Unit tests for:
  - control_center.core.showcase     (schema, loading, live sources)
  - control_center.api.routes_showcase (GET /showcase, GET /uptime)

The showcase file is validated strictly: unknown keys and non-https links
are rejected, and an invalid or missing file yields empty sections rather
than an error page. GET /showcase never returns the uptime allowlist or
the releases repo setting; GET /uptime shows anonymous callers only the
allowlisted services under their public labels.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import jwt
from fastapi.testclient import TestClient

from control_center.core import showcase
from control_center.core.jwt_verify import JWT_SECRET
from control_center.main import app
from control_center.regression_health import RegressionHealthUnavailable

client = TestClient(app)
_INFRA = {"Authorization": "Bearer " + jwt.encode(
    {"sub": "1", "permissions": ["platform.manage_infra"]}, JWT_SECRET, algorithm="HS256")}

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config" / "showcase.json"


class _TmpShowcase:
    """Write `content` to a temp showcase file and point SHOWCASE_PATH at it."""

    def __init__(self, content: object) -> None:
        self.content = content

    def __enter__(self) -> Path:
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "showcase.json"
        if self.content is not None:
            text = self.content if isinstance(self.content, str) else json.dumps(self.content)
            path.write_text(text, encoding="utf-8")
        self.env = patch.dict(os.environ, {"SHOWCASE_PATH": str(path)})
        self.env.start()
        return path

    def __exit__(self, *exc: object) -> None:
        self.env.stop()
        self.tmp.cleanup()


class TestShowcasePath(unittest.TestCase):
    def test_env_override(self) -> None:
        with patch.dict(os.environ, {"SHOWCASE_PATH": "/x/y.json"}):
            self.assertEqual(showcase.showcase_path(), Path("/x/y.json"))

    def test_defaults_next_to_control_center_config(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "SHOWCASE_PATH"}
        env["CONTROL_CENTER_CONFIG"] = "/config/control_center.yaml"
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(showcase.showcase_path(), Path("/config/showcase.json"))


class TestLoadShowcase(unittest.TestCase):
    def test_repository_config_is_valid(self) -> None:
        """config/showcase.json in this repo must always pass the schema."""
        with patch.dict(os.environ, {"SHOWCASE_PATH": str(REPO_CONFIG)}):
            content, error = showcase.load_showcase()
        self.assertIsNone(error)
        self.assertTrue(content.publications)

    def test_missing_file(self) -> None:
        with _TmpShowcase(None):
            content, error = showcase.load_showcase()
        self.assertEqual(error, "showcase file not found")
        self.assertEqual(content.publications, [])

    def test_unreadable_json(self) -> None:
        with _TmpShowcase("not json{"):
            _content, error = showcase.load_showcase()
        self.assertIn("unreadable", error)

    def test_unknown_key_rejected(self) -> None:
        with _TmpShowcase({"publications": [], "surprise": 1}):
            content, error = showcase.load_showcase()
        self.assertIn("invalid", error)
        self.assertEqual(content.limitations, [])

    def test_non_https_link_rejected(self) -> None:
        bad = {"publications": [{"year": 2020, "title": "t", "venue": "v", "url": "http://x.org"}]}
        with _TmpShowcase(bad):
            _content, error = showcase.load_showcase()
        self.assertIn("invalid", error)

    def test_bad_status_and_repo_rejected(self) -> None:
        for bad in ({"security_controls": [{"area": "a", "status": "done", "summary": "s"}]},
                    {"ci_repos": [{"repo": "not a repo"}]},
                    {"test_evidence": [{"suite": "s", "date": "d", "passed": -1, "failed": 0}]}):
            with _TmpShowcase(bad):
                _content, error = showcase.load_showcase()
            self.assertIn("invalid", error)

    def test_all_sections_accepted(self) -> None:
        full = {
            "releases": [{"version": "v1", "date": "2026-01-01", "url": "https://x"}],
            "benchmarks": [{"pipeline": "p", "dataset": "GIAB HG002", "metrics": {"precision": 0.99}, "date": "d"}],
            "example_runs": [{"title": "t", "dataset": "d", "description": "x", "report_url": "https://r"}],
            "tool_versions": [{"name": "STAR", "version": "2.7.11b"}],
            "test_evidence": [{"suite": "s", "date": "d", "passed": 1, "failed": 0}],
            "repo_coverage": [{"repo": "r", "coverage_pct": 90, "date": "d"}],
            "ci_repos": [{"repo": "o/r"}],
        }
        with _TmpShowcase(full):
            content, error = showcase.load_showcase()
        self.assertIsNone(error)
        self.assertEqual(content.ci_repos[0].workflow, "ci.yml")


class TestGithubReleases(unittest.TestCase):
    def setUp(self) -> None:
        showcase._releases_cache.clear()

    def test_fetches_skips_drafts_and_caches(self) -> None:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {"name": "v0.7.1-beta", "published_at": "2026-09-01T00:00:00Z", "html_url": "https://g/r"},
            {"tag_name": "v0.8.0", "draft": True},
            {"tag_name": "v0.7.0", "published_at": None, "html_url": "https://g/o"},
            "junk",
        ]
        with patch.object(showcase.httpx, "get", return_value=resp) as get:
            first = showcase.github_releases("o/r", now=1000.0)
            second = showcase.github_releases("o/r", now=1500.0)
        self.assertEqual(first, [
            {"version": "v0.7.1-beta", "date": "2026-09-01", "url": "https://g/r"},
            {"version": "v0.7.0", "date": None, "url": "https://g/o"},
        ])
        self.assertIs(first, second)
        get.assert_called_once()

    def test_failure_returns_stale_cache_or_empty(self) -> None:
        with patch.object(showcase.httpx, "get", side_effect=httpx.ConnectError("x")):
            self.assertEqual(showcase.github_releases("o/r", now=0.0), [])
        showcase._releases_cache["o/r"] = (0.0, [{"version": "v1"}])
        with patch.object(showcase.httpx, "get", side_effect=httpx.ConnectError("x")):
            self.assertEqual(showcase.github_releases("o/r", now=99999.0), [{"version": "v1"}])


class TestRegressionSummary(unittest.TestCase):
    def test_counts_only(self) -> None:
        data = {
            "generated_at": "2026-09-20T00:00:00Z",
            "freshness": {"status": "FRESH"},
            "phases": {"p1": {"status": "complete", "certification_status": "certified", "evidence": {"x": 1}},
                       "p0": {"status": "complete", "certification_status": "certified", "evidence": {}}},
            "capabilities": [{"certification_status": "certified"}, {"certification_status": "partial"},
                             {"certification_status": "certified"}],
            "findings": [{"summary": "internal detail"}],
        }
        with patch.object(showcase, "load_regression_health", return_value=data):
            summary = showcase.regression_summary()
        self.assertEqual(summary["capabilities_total"], 3)
        self.assertEqual(summary["capabilities_by_certification"], {"certified": 2, "partial": 1})
        self.assertEqual(list(summary["phases"]), ["p0", "p1"])
        self.assertNotIn("internal detail", str(summary))
        self.assertNotIn("evidence", str(summary))

    def test_unavailable(self) -> None:
        with patch.object(showcase, "load_regression_health", side_effect=RegressionHealthUnavailable("artifact_missing")):
            self.assertIsNone(showcase.regression_summary())


class TestShowcaseRoute(unittest.TestCase):
    def test_public_response(self) -> None:
        content = {"publications": [{"year": 2020, "title": "T", "venue": "V"}],
                   "releases_repo": "o/r", "uptime_services": {"workbench": "Workbench"}}
        with _TmpShowcase(content), \
                patch.object(showcase, "github_releases", return_value=[{"version": "v1", "date": None, "url": None}]), \
                patch.object(showcase, "regression_summary", return_value=None):
            data = client.get("/showcase").json()
        self.assertTrue(data["available"])
        self.assertEqual(data["releases"], [{"version": "v1", "date": None, "url": None}])
        self.assertNotIn("uptime_services", data)
        self.assertNotIn("releases_repo", data)
        self.assertIsNone(data["regression"])

    def test_listed_releases_win_over_github(self) -> None:
        content = {"releases": [{"version": "v9"}], "releases_repo": "o/r"}
        with _TmpShowcase(content), patch.object(showcase, "github_releases") as gh, \
                patch.object(showcase, "regression_summary", return_value=None):
            data = client.get("/showcase").json()
        gh.assert_not_called()
        self.assertEqual(data["releases"][0]["version"], "v9")

    def test_invalid_file_is_empty_not_an_error_page(self) -> None:
        with _TmpShowcase({"bogus": True}), patch.object(showcase, "regression_summary", return_value=None):
            resp = client.get("/showcase")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["available"])
        self.assertEqual(resp.json()["limitations"], [])
        self.assertNotIn("bogus", resp.text)


class TestUptimeRoute(unittest.TestCase):
    def test_anonymous_sees_allowlisted_labels_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                _TmpShowcase({"uptime_services": {"workbench": "Workbench"}}), \
                patch.dict(os.environ, {"UPTIME_STORE_PATH": str(Path(tmp) / "u.json")}):
            from control_center.core import uptime
            uptime.record([{"name": "workbench", "status": "UP"}, {"name": "mysql", "status": "DOWN"}])
            anonymous = client.get("/uptime").json()
            operator = client.get("/uptime", headers=_INFRA).json()
        self.assertEqual([s["label"] for s in anonymous["services"]], ["Workbench"])
        self.assertNotIn("mysql", json.dumps(anonymous))
        self.assertEqual(sorted(s["label"] for s in operator["services"]), ["mysql", "workbench"])


if __name__ == "__main__":
    unittest.main()
