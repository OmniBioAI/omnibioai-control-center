"""
tests/test_public_view.py
Unit tests for:
  - control_center.core.public_view  (anonymous-safe response shapes)
  - control_center.core.auth.has_permission / infra_viewer

Every public_view function builds its output from an allowlist, so these
tests feed each one realistic full check output (names, paths, hosts,
error text) and assert only the intended aggregates come back -- and that
malformed input degrades to an empty/zero shape instead of raising.

Developer:
    Manish Kumar <manish@omnibioai.org>
"""
from __future__ import annotations

import unittest

import jwt

from control_center.core import public_view as pv
from control_center.core.auth import has_permission, infra_viewer
from control_center.core.jwt_verify import JWT_SECRET


def _bearer(permissions: list[str]) -> str:
    token = jwt.encode({"sub": "1", "permissions": permissions}, JWT_SECRET, algorithm="HS256")
    return f"Bearer {token}"


class TestHasPermission(unittest.TestCase):
    """has_permission never raises; it answers True only for a valid
    bearer token that carries the requested permission."""

    def test_missing_or_malformed_header(self) -> None:
        self.assertFalse(has_permission(None, "platform.manage_infra"))
        self.assertFalse(has_permission("", "platform.manage_infra"))
        self.assertFalse(has_permission("Basic abc", "platform.manage_infra"))

    def test_invalid_token(self) -> None:
        self.assertFalse(has_permission("Bearer not-a-jwt", "platform.manage_infra"))

    def test_permission_present_and_absent(self) -> None:
        self.assertTrue(has_permission(_bearer(["platform.manage_infra"]), "platform.manage_infra"))
        self.assertFalse(has_permission(_bearer(["other"]), "platform.manage_infra"))

    def test_infra_viewer(self) -> None:
        self.assertTrue(infra_viewer(_bearer(["platform.manage_infra"])))
        self.assertFalse(infra_viewer(None))


class TestPublicCloud(unittest.TestCase):
    def test_keeps_label_and_configured_only(self) -> None:
        full = {"slurm": {"label": "Slurm HPC", "configured": True, "host": "hpc.internal"},
                "local": {"label": "Local Docker", "configured": True, "note": "Always available"},
                "bogus": "not-a-dict"}
        self.assertEqual(pv.public_cloud(full), {
            "slurm": {"label": "Slurm HPC", "configured": True},
            "local": {"label": "Local Docker", "configured": True},
        })

    def test_malformed(self) -> None:
        self.assertEqual(pv.public_cloud(None), {})


class TestPublicReference(unittest.TestCase):
    def test_drops_ref_root_and_unknown_keys(self) -> None:
        full = {"available": True, "ref_root": "/srv/ref", "extra": "x",
                "organisms": [{"organism": "human", "assembly": "GRCh38", "path": "/srv/ref/h",
                               "indexes": {"star": True}, "variants": {"dbsnp": False}}, "junk"],
                "databases": {"clinvar": True},
                "annotation": {"human": {"gencode": True}}}
        self.assertEqual(pv.public_reference(full), {
            "available": True,
            "organisms": [{"organism": "human", "assembly": "GRCh38",
                           "indexes": {"star": True}, "variants": {"dbsnp": False}}],
            "databases": {"clinvar": True},
            "annotation": {"human": {"gencode": True}},
        })

    def test_malformed(self) -> None:
        self.assertEqual(pv.public_reference("x"),
                         {"available": False, "organisms": [], "databases": {}, "annotation": {}})


class TestPublicIntegrity(unittest.TestCase):
    def test_counts(self) -> None:
        checks = [{"status": "ok", "path": "/a"}, {"status": "broken"}, {"status": "empty"}, 1]
        self.assertEqual(pv.public_integrity(checks), {"total": 3, "ok": 1, "problems": 2})

    def test_malformed(self) -> None:
        self.assertEqual(pv.public_integrity(None), {"total": 0, "ok": 0, "problems": 0})


class TestPublicActivity(unittest.TestCase):
    def test_aggregates_and_host_allowlist(self) -> None:
        full = {"reachable": True, "error": "http://prometheus:9090 timeout",
                "containers": [{"name": "a", "cpu_pct": 1.25, "memory_used_mb": 10.0},
                               {"name": "b", "cpu_pct": None, "memory_used_mb": "n/a"}],
                "host": {"cpu_idle_pct": 80.0, "memory_total_gb": 128.0, "threads_total": 900}}
        data = pv.public_activity(full)
        self.assertEqual(data["container_count"], 2)
        self.assertEqual(data["total_cpu_pct"], 1.25)
        self.assertEqual(data["total_memory_used_mb"], 10.0)
        self.assertEqual(data["host"]["memory_total_gb"], 128.0)
        self.assertNotIn("threads_total", data["host"])
        self.assertNotIn("error", data)

    def test_no_host(self) -> None:
        data = pv.public_activity({"containers": [], "host": None, "reachable": False})
        self.assertIsNone(data["host"])
        self.assertFalse(data["reachable"])


class TestPublicDatabase(unittest.TestCase):
    def test_all_stores(self) -> None:
        full = {"mysql": {"connections": 1, "max_connections": 10, "slow_queries": 0,
                          "databases": [{"name": "x", "size_mb": 1.5}]},
                "redis": {"used_memory_human": "1M", "hit_rate_pct": 50.0, "connected_clients": 2},
                "neo4j": {"node_count": 5, "relationship_count": 7}}
        self.assertEqual(pv.public_database(full), {
            "mysql": {"connections": 1, "max_connections": 10, "slow_queries": 0,
                      "database_count": 1, "total_size_mb": 1.5},
            "redis": {"hit_rate_pct": 50.0, "connected_clients": 2},
            "neo4j": {"node_count": 5, "relationship_count": 7},
        })

    def test_unreachable_stores_are_null(self) -> None:
        self.assertEqual(pv.public_database({"mysql": None}),
                         {"mysql": None, "redis": None, "neo4j": None})


class TestPublicCelery(unittest.TestCase):
    def test_counts(self) -> None:
        full = {"workers": [{"name": "celery@host1", "status": "online", "active_tasks": 3},
                            {"name": "celery@host2", "status": "offline", "active_tasks": 0}],
                "recent_tasks": [{"name": "t"}]}
        self.assertEqual(pv.public_celery(full),
                         {"reachable": True, "workers_total": 2, "workers_online": 1, "active_tasks": 3})

    def test_error_marks_unreachable_without_text(self) -> None:
        data = pv.public_celery({"workers": [], "error": "celery unreachable: redis://10.0.0.5"})
        self.assertFalse(data["reachable"])
        self.assertNotIn("10.0.0.5", str(data))


class TestPublicImageFreshness(unittest.TestCase):
    def test_counts(self) -> None:
        full = {"images": [{"service": "a", "stale": True}, {"service": "b", "stale": False}]}
        self.assertEqual(pv.public_image_freshness(full), {"images_checked": 2, "stale": 1})

    def test_malformed(self) -> None:
        self.assertEqual(pv.public_image_freshness([]), {"images_checked": 0, "stale": 0})


class TestPublicGatewayTraffic(unittest.TestCase):
    def test_allowlist(self) -> None:
        data = pv.public_gateway_traffic({"requests_7d": 5, "requests_by_route": [{"route": "/x"}]})
        self.assertEqual(data["requests_7d"], 5)
        self.assertNotIn("requests_by_route", data)

    def test_malformed(self) -> None:
        self.assertIsNone(pv.public_gateway_traffic(None)["requests_7d"])


class TestPublicGpu(unittest.TestCase):
    def test_drops_message_and_check_errors(self) -> None:
        full = [{"name": "gpu:0", "target": "NVIDIA GB10", "status": "UP", "message": "40°C"},
                {"name": "gpu:check", "target": "-", "status": "WARN", "message": "OSError: /dev/nvidia0"}]
        self.assertEqual(pv.public_gpu(full), [{"name": "gpu:0", "model": "NVIDIA GB10", "status": "UP"}])

    def test_malformed(self) -> None:
        self.assertEqual(pv.public_gpu({"reachable": True}), [])


if __name__ == "__main__":
    unittest.main()
