"""
tests/test_public_dashboard_no_leak.py

Public Read-Only Control Center architecture: contract/regression tests
proving the endpoints deliberately left anonymous never carry the
identifiers that made /audit-trail and /license unsafe to leave open
(see routes_infra.py's own module comment). These are response-*shape*
assertions, not endpoint-behavior tests -- the individual checks/*.py
modules already have their own full unit-test coverage elsewhere
(test_check_*.py); this file only guards the cross-cutting "never leaks
a real identifier" property a future edit to any of them could
otherwise silently reintroduce.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from control_center.api import routes_infra
from control_center.checks import gateway_traffic
from control_center.main import app

client = TestClient(app)

# Forbidden anywhere in a public response body -- key names (recursively)
# or, for the raw-text checks below, literal substrings. Deliberately
# broad/case-insensitive: this is a regression guard, not a precise
# classifier, so a false positive (an unrelated field that happens to
# share a substring) is an acceptable cost for never missing a real leak.
_FORBIDDEN_KEYS = {
    "user_id", "email", "jwt", "access_token", "refresh_token",
    "password", "api_key", "secret", "hostname", "lan_ip",
}


def _find_forbidden_keys(obj: object, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_l = str(k).lower()
            if any(bad in key_l for bad in _FORBIDDEN_KEYS):
                hits.append(f"{path}.{k}")
            hits.extend(_find_forbidden_keys(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(_find_forbidden_keys(v, f"{path}[{i}]"))
    return hits


class TestGatewayTrafficIsAggregateOnly(unittest.TestCase):
    """Section 9's explicit requirement: /gateway-traffic must remain
    aggregate-only and must never surface a raw event list or a
    per-event user identifier, even when the underlying audit:events
    stream itself contains real user_id values (unlike /audit-trail,
    which is exactly why that route is gated and this one isn't)."""

    def _entry(self, eid: str, **fields: object) -> tuple[str, dict]:
        return (eid, {"data": json.dumps(fields)})

    def test_real_user_ids_in_the_stream_never_reach_the_response(self) -> None:
        entries = [
            self._entry(
                "1-0", event_type="request", action="/compliance/hipaa-report",
                user_id="admin@omnibioai.org", decision="allow", status_code=200, latency_ms=12,
            ),
            self._entry(
                "2-0", event_type="request", action="/orgs/7", user_id="7",
                decision="allow", status_code=200, latency_ms=8,
            ),
        ]
        mock_r = MagicMock()
        mock_r.xrange.return_value = entries
        with patch("redis.Redis.from_url", return_value=mock_r):
            resp = client.get("/gateway-traffic")
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertNotIn("admin@omnibioai.org", body)
        self.assertNotIn("user_id", body)
        self.assertNotIn("events", resp.json())

    def test_response_shape_has_no_raw_event_list(self) -> None:
        with patch("redis.Redis.from_url", side_effect=ConnectionError("down")):
            result = gateway_traffic.get_gateway_traffic()
        self.assertNotIn("events", result)
        self.assertNotIn("user_id", result)


class TestPublicInfraEndpointsCarryNoForbiddenKeys(unittest.TestCase):
    """gpu/celery/database/image-freshness/usage/activity/integrity are
    aggregate operational telemetry by design (see routes_infra.py's
    module comment) -- exercised here with the same realistic
    return-value fixtures test_routes_infra.py itself uses, recursively
    scanned for any of the identifiers that would make a response
    unsafe to leave anonymous."""

    def test_gpu(self) -> None:
        with patch.object(
            routes_infra, "get_gpu_status",
            return_value={"reachable": True, "utilization_pct": 12, "memory_used_mb": 1024},
        ):
            data = client.get("/gpu").json()
        self.assertEqual(_find_forbidden_keys(data), [])

    def test_celery(self) -> None:
        with patch.object(
            routes_infra, "get_celery_status",
            return_value={"workers": [{"name": "worker1", "active": 2}], "recent_tasks": []},
        ):
            data = client.get("/celery").json()
        self.assertEqual(_find_forbidden_keys(data), [])

    def test_database(self) -> None:
        with patch.object(
            routes_infra, "get_database_status",
            return_value={"mysql": {"status": "UP"}, "redis": {"status": "UP"}},
        ):
            data = client.get("/database").json()
        self.assertEqual(_find_forbidden_keys(data), [])

    def test_image_freshness(self) -> None:
        with patch.object(
            routes_infra, "get_image_freshness",
            return_value={"images": [{"name": "bwa", "built_days_ago": 3}]},
        ):
            data = client.get("/image-freshness").json()
        self.assertEqual(_find_forbidden_keys(data), [])

    def test_usage(self) -> None:
        with patch.object(
            routes_infra, "get_usage_status",
            return_value={"active_7d": 5, "active_30d": 20, "total": 30},
        ):
            data = client.get("/usage").json()
        self.assertEqual(_find_forbidden_keys(data), [])

    def test_activity(self) -> None:
        with patch.object(
            routes_infra, "get_activity_status",
            return_value={"containers": [], "reachable": True},
        ):
            data = client.get("/activity").json()
        self.assertEqual(_find_forbidden_keys(data), [])

    def test_integrity(self) -> None:
        with patch("control_center.api.routes_infra.load_settings", return_value=object()):
            with patch(
                "control_center.api.routes_infra.run_integrity_checks",
                return_value=[{"name": "reference-data", "status": "ok"}],
            ):
                data = client.get("/integrity").json()
        self.assertEqual(_find_forbidden_keys(data), [])


class TestReportPublicStatsCarriesNoForbiddenKeys(unittest.TestCase):
    """2026-09-02 public/admin-split investigation: GET /report/public-stats
    is deliberately anonymous. Its whole design is that it returns only
    ecosystem-wide aggregate scalars -- so beyond the forbidden-key sweep
    every other public endpoint gets, assert the per-repo arrays from
    report_data.json never appear in it even when that file is fully
    populated with them."""

    _FULL = {
        "generated_at": "2026-09-02T04:00:00+00:00",
        "grand": {"files": 14820, "code": 1863200, "comment": 240100, "blank": 190500},
        "projects": [{"full": "omnibioai-tes", "code": 120000, "pct": 6.44}],
        "languages": [{"name": "Python", "code": 900000, "pct": 48.3}],
        "coverage": [
            {"repo": "omnibioai-tes", "pct": 92.5, "stmts": 4000, "missed": 300},
            {"repo": "omnibioai-auth", "pct": 61.0, "stmts": 2000, "missed": 780},
        ],
        "gitStatus": [{"repo": "omnibioai-tes", "branch": "feat/wip", "unpushed": 2}],
    }

    def _get(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "work" / "out" / "reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "report_data.json").write_text(json.dumps(self._FULL))
            with patch("control_center.main._workspace_root", return_value=Path(tmp)):
                return client.get("/report/public-stats")

    def test_no_forbidden_keys(self) -> None:
        self.assertEqual(_find_forbidden_keys(self._get().json()), [])

    def test_no_per_repo_arrays_or_repo_names(self) -> None:
        resp = self._get()
        body = resp.json()
        self.assertEqual(
            set(body),
            {"generated_at", "total_lines", "total_files",
             "ecosystem_coverage_percent", "repos_measured"},
        )
        for marker in ('"projects"', '"languages"', '"gitStatus"', '"coverage":',
                       "omnibioai-tes", "omnibioai-auth", "feat/wip", "unpushed"):
            self.assertNotIn(marker, resp.text)


if __name__ == "__main__":
    unittest.main()
