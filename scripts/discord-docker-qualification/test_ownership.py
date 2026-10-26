"""Docker-free failure-path tests for manifest-scoped cleanup."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import yaml

from ownership import verified_cleanup
import run_qualification as runner
from subnet import assert_subnet_free, select_free_subnet

WS = "OMNIBIOAI_DISCORD_DOCKER_QUALIFICATION_INFRASTRUCTURE_V1"
RUN = "unit-run-001"
PROJECT = "obai-discord-qual-unit-run-001"


def owned(kind: str, rid: str, **extra: str) -> dict:
    labels = {"io.omnibioai.workstream": WS, "io.omnibioai.run-id": RUN,
              "io.omnibioai.disposable": "true"}
    row = {"id": rid, "labels": labels, **extra}
    if kind == "container":
        row.update(project=PROJECT, service=extra.get("service", "router"))
    elif kind == "network":
        row.update(name=f"{PROJECT}_isolated", driver="bridge",
                   ipam_config=[{"Subnet": "10.240.0.0/24", "Gateway": "10.240.0.1"}], driver_options={})
    elif kind == "volume":
        row.update(name=f"{PROJECT}_router-state")
    return row


class FakeDocker:
    def __init__(self, rows: dict[str, list[dict]] | None = None, fail_remove: int = 0):
        self.rows = rows or {"container": [], "network": [], "volume": [], "image": []}
        self.removed: list[tuple[str, str]] = []
        self.fail_remove = fail_remove
        self.mutate_on_inspect: dict[str, dict] = {}
        self.states: dict[str, dict] = {}
        self.streams: dict[str, dict] = {}
        self.log_error: Exception | None = None

    def resources(self, kind: str, run_id: str) -> list[dict]:
        return [row.copy() for row in self.rows.get(kind, [])
                if row.get("labels", {}).get("io.omnibioai.run-id") == run_id]

    def resource_by_id(self, kind: str, rid: str) -> dict | None:
        row = next((row.copy() for row in self.rows.get(kind, []) if row["id"] == rid), None)
        if row and rid in self.mutate_on_inspect:
            for key, value in self.mutate_on_inspect[rid].items():
                row[key] = value
        return row

    def remove(self, kind: str, rid: str) -> None:
        self.removed.append((kind, rid))
        if self.fail_remove:
            self.fail_remove -= 1
            raise TimeoutError("simulated interrupted Docker cleanup")
        self.rows[kind] = [row for row in self.rows.get(kind, []) if row["id"] != rid]

    def container_state(self, rid: str) -> dict:
        return self.states[rid]

    def container_log_streams(self, rid: str, *, max_bytes: int) -> dict:
        if self.log_error:
            raise self.log_error
        return self.streams[rid]


def manifest() -> dict:
    return {"workstream": WS, "run_id": RUN, "project": PROJECT,
            "expected_network": f"{PROJECT}_isolated", "expected_volume": f"{PROJECT}_router-state",
            "network_subnet": "10.240.0.0/24", "network_gateway": "10.240.0.1",
            "owned_resources": {}}


class OwnershipFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ownership.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def exercise(self, scenario: str, rows: dict[str, list[dict]], *, fail_remove: int = 0) -> FakeDocker:
        protected = owned("container", "protected-container", project="production", service="api")
        protected["labels"] = {"com.docker.compose.project": "production"}
        docker = FakeDocker(rows, fail_remove=fail_remove)
        m = manifest()
        errors = verified_cleanup(docker, self.path, m)
        # Protected host resources never appear in exact run-id discovery and
        # are never passed to a destructive method, under any simulated fault.
        self.assertNotIn(("container", "protected-container"), docker.removed, scenario)
        if scenario in {"cleanup_failure", "timeout", "sigint", "sigterm", "interrupted_cleanup"}:
            self.assertTrue(errors, scenario)
            self.assertTrue(self.path.exists(), scenario)
        return docker

    def test_partial_startup(self):
        self.exercise("partial_startup", {"container": [owned("container", "redis", service="redis")],
                                           "network": [], "volume": [], "image": []})

    def test_stranded_one_off_runner(self):
        self.exercise("stranded_runner", {"container": [owned("container", "runner", service="test-runner")],
                                           "network": [], "volume": [], "image": []})

    def test_signal_timeout_and_runner_failure_all_cleanup(self):
        for event in ("sigint", "sigterm", "timeout", "runner_failure"):
            with self.subTest(event=event):
                self.exercise(event, {"container": [owned("container", "router", service="router")],
                                      "network": [], "volume": [], "image": []},
                              fail_remove=1 if event != "runner_failure" else 0)

    def test_cleanup_failure_and_interruption_preserve_manifest(self):
        self.exercise("cleanup_failure", {"container": [owned("container", "router", service="router")]}, fail_remove=1)
        self.exercise("interrupted_cleanup", {"container": [owned("container", "router", service="router")]}, fail_remove=1)

    def test_ownership_mismatch_aborts_before_any_removal(self):
        bad = owned("container", "mismatch", service="router")
        docker = FakeDocker({"container": [bad]})
        docker.mutate_on_inspect["mismatch"] = {"labels": {"io.omnibioai.run-id": "different-run"}}
        with self.assertRaises(RuntimeError):
            verified_cleanup(docker, self.path, manifest())
        self.assertEqual(docker.removed, [])

    def test_prevalidates_all_manifest_targets_before_first_removal(self):
        first = owned("container", "first", service="router")
        later = owned("container", "later", service="router")
        docker = FakeDocker({"container": [first, later]})
        docker.mutate_on_inspect["later"] = {"project": "production", "service": "api"}
        m = manifest()
        m["owned_resources"] = {"container": ["first", "later"]}
        with self.assertRaises(RuntimeError):
            verified_cleanup(docker, self.path, m)
        self.assertEqual(docker.removed, [])

    def test_container_requires_exact_compose_project(self):
        row = owned("container", "no-project", service="router")
        row["project"] = None
        docker = FakeDocker({"container": [row]})
        with self.assertRaises(RuntimeError):
            verified_cleanup(docker, self.path, manifest())
        self.assertEqual(docker.removed, [])

    def test_unrelated_concurrent_creation_is_not_a_target(self):
        protected = owned("container", "concurrent-prod", service="api")
        protected["labels"] = {"com.docker.compose.project": "production"}
        docker = FakeDocker({"container": [owned("container", "router", service="router"), protected]})
        verified_cleanup(docker, self.path, manifest())
        self.assertEqual(docker.removed, [("container", "router")])
        self.assertIn("concurrent-prod", [row["id"] for row in docker.rows["container"]])

    def test_repeated_cleanup_and_missing_resources_are_idempotent(self):
        docker = FakeDocker({"container": [owned("container", "router", service="router")]})
        m = manifest()
        verified_cleanup(docker, self.path, m)
        self.assertEqual(verified_cleanup(docker, self.path, m), [])
        self.assertEqual(docker.removed, [("container", "router")])

    def test_network_volume_image_and_exact_ids(self):
        docker = FakeDocker({"container": [owned("container", "r", service="router")],
                             "network": [owned("network", "net-id")],
                             "volume": [owned("volume", f"{PROJECT}_router-state")], "image": []})
        verified_cleanup(docker, self.path, manifest())
        self.assertEqual(set(docker.removed), {("container", "r"), ("network", "net-id"),
                                                ("volume", f"{PROJECT}_router-state")})
        saved = json.loads(self.path.read_text())
        self.assertIn("net-id", saved["owned_resources"]["network"])

    def test_network_cleanup_rejects_additional_ipam_config(self):
        network = owned("network", "net-id")
        network["ipam_config"].append({"Subnet": "10.241.0.0/24", "Gateway": "10.241.0.1"})
        docker = FakeDocker({"network": [network]})
        with self.assertRaises(RuntimeError):
            verified_cleanup(docker, self.path, manifest())
        self.assertEqual(docker.removed, [])

    def test_subnet_allocator_subtracts_docker_and_host_networks(self):
        subnet, gateway = select_free_subnet(["10.240.0.0/23", "10.240.2.0/24"])
        self.assertEqual((subnet, gateway), ("10.240.3.0/24", "10.240.3.1"))

    def test_subnet_allocator_exhaustion_and_fresh_overlap(self):
        with self.assertRaises(RuntimeError):
            select_free_subnet(["10.240.0.0/23"], pool="10.240.0.0/23")
        with self.assertRaises(RuntimeError):
            assert_subnet_free("10.240.3.0/24", ["10.240.0.0/20"])

    def test_cleanup_failure_does_not_suppress_after_inventory(self):
        out = Path(self.temp.name) / "evidence"
        out.mkdir()
        run_dir = Path(self.temp.name) / "run"
        run_dir.mkdir()
        (run_dir / "ownership-manifest.json").write_text("{}")
        before = {"containers": [], "networks": [], "volumes": []}
        after = {"containers": [], "networks": [], "volumes": []}
        with patch.object(runner, "EVIDENCE", out), patch.object(runner, "verified_cleanup", side_effect=RuntimeError("fake cleanup")), \
                patch.object(runner, "inventory", return_value=after):
            with self.assertRaises(RuntimeError):
                runner.finalize_run(before, run_dir,
                    {"run_id": RUN, "project": PROJECT, "workstream": WS, "owned_resources": {}}, report_run_id=RUN)
        self.assertTrue((out / "docker-inventory-after.json").exists())
        report = json.loads((out / "ownership-verification.json").read_text())
        self.assertEqual(report["cleanup_errors"], ["RuntimeError:fake cleanup"])

    def test_inventory_failure_is_recorded_independently(self):
        out = Path(self.temp.name) / "evidence"
        out.mkdir()
        run_dir = Path(self.temp.name) / "run"
        run_dir.mkdir()
        (run_dir / "ownership-manifest.json").write_text("{}")
        before = {"containers": [], "networks": [], "volumes": []}
        with patch.object(runner, "EVIDENCE", out), patch.object(runner, "verified_cleanup", return_value=[]), \
                patch.object(runner, "inventory", side_effect=RuntimeError("fake inventory")):
            with self.assertRaises(RuntimeError):
                runner.finalize_run(before, run_dir,
                    {"run_id": RUN, "project": PROJECT, "workstream": WS, "owned_resources": {}}, report_run_id=RUN)
        self.assertEqual(json.loads((out / "docker-inventory-after.json").read_text())["status"], "FAIL")
        report = json.loads((out / "ownership-verification.json").read_text())
        self.assertIn("fake inventory", report["inventory_error"])

    def test_inventory_comparison_distinguishes_concurrent_activity(self):
        base = {"id": "protected", "labels": {"role": "prod"}, "mounts": [], "networks": ["prod-net"]}
        concurrent = {"id": "new-unrelated", "labels": {"role": "other"}}
        before = {"containers": [base], "networks": ["prod-net|id1|bridge|local|"], "volumes": ["prod-vol|local|"]}
        after = {"containers": [base, concurrent], "networks": ["prod-net|id1|bridge|local|", "new-net|id2|bridge|local|"],
                 "volumes": ["prod-vol|local|"]}
        result = runner.compare_inventories(before, after, RUN)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["unrelated_concurrent_container_ids"], ["new-unrelated"])
        after["containers"].append({"id": "leftover", "labels": {"io.omnibioai.run-id": RUN}})
        self.assertEqual(runner.compare_inventories(before, after, RUN)["status"], "FAIL")


class RedisDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        (self.run_dir / "compose.env").write_text(
            'SOURCE_SECRETS_JSON={"github":"synthetic-signing-secret"}\n'
            'MOCK_WEBHOOKS_JSON={"alerts":"https://discord.com/api/webhooks/12345/synthetic-webhook-token"}\n',
            encoding="utf-8")
        self.run_dir.joinpath("compose.env").chmod(0o600)
        self.path = self.root / "redis-diagnostics.json"
        self.container_id = "a" * 64
        self.manifest = {"workstream": WS, "run_id": RUN, "project": PROJECT,
                         "expected_service_names": [f"{PROJECT}-{service}-1"
                                                    for service in ("redis", "mock-discord", "state-init")],
                         "owned_resources": {}}
        row = owned("container", self.container_id, service="redis")
        row["name"] = f"{PROJECT}-redis-1"
        self.docker = FakeDocker({"container": [row], "network": [], "volume": [], "image": []})
        self.docker.states[self.container_id] = {"status": "exited", "exit_code": 1,
                                                   "error": "", "oom_killed": False, "health": "unhealthy",
                                                   "created_at": "t0", "started_at": "t1", "finished_at": "t2"}
        self.docker.streams[self.container_id] = {
            "stdout": "startup synthetic-signing-secret https://discord.com/api/webhooks/12345/synthetic-webhook-token\n",
            "stderr": "Redis failed\n", "truncated": False}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_service(self, service: str, container_id: str) -> None:
        row = owned("container", container_id, service=service)
        row["name"] = f"{PROJECT}-{service}-1"
        self.docker.rows["container"].append(row)
        self.docker.states[container_id] = {"status": "exited", "exit_code": 0,
                                            "error": "", "oom_killed": False, "health": None}
        self.docker.streams[container_id] = {"stdout": f"{service} output", "stderr": "", "truncated": False}

    def test_run_error_evidence_redacts_synthetic_secret(self):
        summary = runner.safe_exception_summary(
            RuntimeError("Docker stderr exposed synthetic-signing-secret"), self.run_dir)
        self.assertNotIn("synthetic-signing-secret", summary)
        self.assertIn("[REDACTED]", summary)

    def test_successful_capture_is_owned_bounded_and_redacted(self):
        errors = runner.collect_redis_diagnostics(self.docker, self.manifest, self.run_dir, self.path)
        self.assertEqual(errors, [])
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["status"], "PASS")
        self.assertEqual(saved["container_id"], self.container_id)
        self.assertEqual(saved["state"]["exit_code"], 1)
        self.assertFalse(saved["state"]["oom_killed"])
        self.assertNotIn("synthetic-signing-secret", self.path.read_text())
        self.assertNotIn("synthetic-webhook-token", self.path.read_text())
        self.assertNotIn("https://discord.com/api/webhooks", self.path.read_text())
        self.assertEqual(self.manifest["owned_resources"]["container"], [self.container_id])
        self.docker.streams[self.container_id]["stdout"] = "x" * (runner.DIAGNOSTIC_BYTES_PER_STREAM + 10)
        runner.collect_redis_diagnostics(self.docker, self.manifest, self.run_dir, self.path)
        self.assertLessEqual(len(json.loads(self.path.read_text())["stdout"].encode()), runner.DIAGNOSTIC_BYTES_PER_STREAM)

    def test_missing_redis_container_is_recorded(self):
        self.docker.rows["container"] = []
        errors = runner.collect_redis_diagnostics(self.docker, self.manifest, self.run_dir, self.path)
        self.assertTrue(errors)
        self.assertEqual(json.loads(self.path.read_text())["status"], "NOT_FOUND")

    def test_ownership_mismatch_rejects_diagnostic_target(self):
        self.docker.rows["container"][0]["labels"]["io.omnibioai.workstream"] = "foreign-workstream"
        errors = runner.collect_redis_diagnostics(self.docker, self.manifest, self.run_dir, self.path)
        self.assertTrue(errors)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["status"], "FAIL")
        self.assertNotIn("container_id", saved)

    def test_immutable_id_reinspection_mismatch_rejects_target(self):
        self.docker.mutate_on_inspect[self.container_id] = {"project": "production"}
        errors = runner.collect_redis_diagnostics(self.docker, self.manifest, self.run_dir, self.path)
        self.assertTrue(errors)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["status"], "FAIL")
        self.assertNotIn("container_id", saved)

    def test_log_retrieval_failure_preserves_state_diagnostic(self):
        self.docker.log_error = OSError("synthetic log read failure")
        errors = runner.collect_redis_diagnostics(self.docker, self.manifest, self.run_dir, self.path)
        self.assertEqual(len(errors), 1)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["status"], "PARTIAL")
        self.assertEqual(saved["state"]["exit_code"], 1)
        self.assertIn("synthetic log read failure", saved["logs_error"])

    def test_cleanup_and_after_inventory_run_after_diagnostic_failure(self):
        evidence_dir = self.root / "evidence"
        evidence_dir.mkdir()
        (self.run_dir / "ownership-manifest.json").write_text("{}", encoding="utf-8")
        before = {"containers": [], "networks": [], "volumes": []}
        after = {"containers": [], "networks": [], "volumes": []}
        with patch.object(runner, "EVIDENCE", evidence_dir), \
                patch.object(runner, "verified_cleanup", return_value=[]) as cleanup, \
                patch.object(runner, "inventory", return_value=after):
            runner.finalize_run(before, self.run_dir, self.manifest, report_run_id=RUN,
                                diagnostic_errors=["logs:OSError:synthetic-signing-secret"])
        cleanup.assert_called_once()
        self.assertTrue((evidence_dir / "docker-inventory-after.json").exists())
        report = json.loads((evidence_dir / "ownership-verification.json").read_text())
        self.assertNotIn("synthetic-signing-secret", json.dumps(report))
        self.assertIn("[REDACTED]", report["diagnostic_errors"][0])

    def test_ambiguous_redis_resources_are_rejected(self):
        second_id = "b" * 64
        second = owned("container", second_id, service="redis")
        second["name"] = f"{PROJECT}-redis-1"
        self.docker.rows["container"].append(second)
        errors = runner.collect_redis_diagnostics(self.docker, self.manifest, self.run_dir, self.path)
        self.assertTrue(errors)
        self.assertEqual(json.loads(self.path.read_text())["status"], "FAIL")
        self.assertNotIn("container_id", json.loads(self.path.read_text()))

    def test_unknown_run_labeled_container_rejects_all_diagnostics(self):
        unknown = owned("container", "e" * 64, service="mystery")
        self.docker.rows["container"].append(unknown)
        errors = runner.collect_service_diagnostics(self.docker, self.manifest, self.run_dir, "redis", self.path)
        self.assertTrue(errors)
        self.assertEqual(json.loads(self.path.read_text())["status"], "FAIL")
        self.assertNotIn("container_id", json.loads(self.path.read_text()))

    def test_mock_discord_and_state_init_capture(self):
        for service, container_id in (("mock-discord", "c" * 64), ("state-init", "d" * 64)):
            with self.subTest(service=service):
                self.add_service(service, container_id)
                path = self.root / f"{service}-diagnostics.json"
                errors = runner.collect_service_diagnostics(self.docker, self.manifest, self.run_dir, service, path)
                saved = json.loads(path.read_text())
                self.assertEqual(errors, [])
                self.assertEqual(saved["status"], "PASS")
                self.assertEqual(saved["container_id"], container_id)

    def test_docker_logs_uses_exact_id_and_bounds_both_outputs(self):
        result = runner.subprocess.CompletedProcess(
            args=[], returncode=0, stdout="x" * (runner.DIAGNOSTIC_LOG_TAIL_BYTES + 100),
            stderr="y" * (runner.DIAGNOSTIC_LOG_TAIL_BYTES + 100))
        with patch.object(runner, "run", return_value=result) as run_mock:
            streams = runner.DockerCLI().container_log_streams(
                self.container_id, max_bytes=runner.DIAGNOSTIC_LOG_TAIL_BYTES)
        self.assertEqual(run_mock.call_args.args[0],
                         ["docker", "logs", "--timestamps", "--tail", "200", self.container_id])
        self.assertEqual(len(streams["stdout"].encode()), runner.DIAGNOSTIC_LOG_TAIL_BYTES)
        self.assertEqual(len(streams["stderr"].encode()), runner.DIAGNOSTIC_LOG_TAIL_BYTES)
        self.assertTrue(streams["truncated"])

    def test_redis_user_workdir_tmpfs_and_compose_isolation_policy(self):
        compose = yaml.safe_load(runner.COMPOSE.read_text(encoding="utf-8"))
        redis = compose["services"]["redis"]
        self.assertEqual(redis["image"],
                         "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499")
        self.assertEqual(redis["user"], "999:1000")
        self.assertEqual(redis["working_dir"], "/data")
        self.assertTrue(redis["read_only"])
        data_tmpfs = next(mount for mount in redis["tmpfs"] if mount.startswith("/data:"))
        for option in ("size=16m", "noexec", "nosuid", "uid=999", "gid=1000", "mode=0700"):
            self.assertIn(option, data_tmpfs)
        self.assertEqual(redis["mem_limit"], "128m")
        self.assertEqual(redis["cpus"], 0.5)
        self.assertEqual(redis["cap_drop"], ["ALL"])
        self.assertNotIn("cap_add", redis)
        self.assertNotIn("ports", redis)
        self.assertEqual(redis["healthcheck"]["test"], ["CMD", "redis-cli", "ping"])
        self.assertEqual(redis["healthcheck"]["timeout"], "1s")
        self.assertEqual(redis["healthcheck"]["start_period"], "2s")
        isolated = compose["networks"]["isolated"]
        self.assertTrue(isolated["internal"])
        self.assertNotIn("ports", compose["services"]["router"])
        self.assertNotIn("ports", compose["services"]["mock-discord"])

    def test_container_ownership_inspect_does_not_request_environment(self):
        result = runner.subprocess.CompletedProcess(args=[], returncode=0,
            stdout=json.dumps({"id": self.container_id, "name": f"/{PROJECT}-redis-1",
                               "labels": {"com.docker.compose.project": PROJECT,
                                          "com.docker.compose.service": "redis"}}), stderr="")
        with patch.object(runner, "run", return_value=result) as run_mock:
            row = runner.DockerCLI().resource_by_id("container", self.container_id)
        command = run_mock.call_args.args[0]
        self.assertIn("--format", command)
        self.assertNotIn(".Config.Env", " ".join(command))
        self.assertEqual(row["id"], self.container_id)
        self.assertEqual(row["service"], "redis")


class MockTLSStartupTests(unittest.TestCase):
    @staticmethod
    def _mode_allows_read(mode: int, *, file_uid: int, file_gid: int,
                          process_uid: int, process_gid: int) -> bool:
        if process_uid == file_uid:
            return bool(mode & 0o400)
        if process_gid == file_gid:
            return bool(mode & 0o040)
        return bool(mode & 0o004)

    def test_generated_tls_permissions_and_certificate_loading(self):
        if not shutil.which("openssl"):
            self.skipTest("OpenSSL is required by the existing qualification harness")
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir(mode=0o700)
            run_dir.chmod(0o700)
            runner.make_certificates(run_dir)
            tls_dir = run_dir / "tls"
            key = tls_dir / "server-key.pem"
            self.assertEqual(os.stat(run_dir).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(tls_dir).st_mode & 0o777, 0o711)
            self.assertEqual(os.stat(key).st_mode & 0o777, 0o400)
            self.assertEqual(os.stat(tls_dir / "server.pem").st_mode & 0o777, 0o444)
            self.assertEqual(os.stat(tls_dir / "ca.pem").st_mode & 0o777, 0o444)
            self.assertEqual({p.name for p in tls_dir.iterdir()},
                             {"server-key.pem", "server.pem", "ca.pem"})
            self.assertFalse((tls_dir / "ca-key.pem").exists())
            server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server.load_cert_chain(str(tls_dir / "server.pem"), str(key))
            client = ssl.create_default_context(cafile=str(tls_dir / "ca.pem"))
            self.assertIsNotNone(client)
            san = subprocess.run(
                ["openssl", "x509", "-in", str(tls_dir / "server.pem"),
                 "-noout", "-ext", "subjectAltName"],
                capture_output=True, text=True, check=True).stdout
            self.assertIn("DNS:discord.com", san)
            self.assertIn("IP Address:127.0.0.1", san)

    def test_tls_generation_rejects_preexisting_symlink_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            outside = root / "outside"
            run_dir.mkdir(mode=0o700)
            outside.mkdir()
            (run_dir / "tls").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(FileExistsError):
                runner.make_certificates(run_dir)
            self.assertEqual(list(outside.iterdir()), [])

    def test_ca_key_is_removed_when_openssl_fails_after_creating_it(self):
        secret_key_material = "SYNTHETIC-CA-PRIVATE-KEY-MATERIAL-MUST-NOT-ESCAPE"
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir(mode=0o700)
            injected_error = RuntimeError(f"injected OpenSSL failure {secret_key_material}")

            def create_ca_key_then_fail(argv, **kwargs):
                key_path = Path(argv[argv.index("-keyout") + 1])
                key_path.write_text(secret_key_material, encoding="utf-8")
                raise injected_error

            with patch.object(runner, "run", side_effect=create_ca_key_then_fail):
                with self.assertRaises(RuntimeError) as raised:
                    runner.make_certificates(run_dir)

            self.assertFalse((run_dir / "tls/ca-key.pem").exists())
            self.assertIs(raised.exception, injected_error)
            self.assertEqual(str(raised.exception), "disposable TLS certificate generation failed (RuntimeError)")
            self.assertNotIn(secret_key_material, str(raised.exception))
            self.assertNotIn(secret_key_material, " ".join(getattr(raised.exception, "__notes__", [])))
            self.assertNotIn(secret_key_material, runner.safe_exception_summary(raised.exception, run_dir))

    def test_ca_key_is_removed_after_intermediate_and_signing_failures(self):
        secret_key_material = "SYNTHETIC-CA-KEY-NEVER-LOG-THIS"
        for failure_call in (2, 3):
            with self.subTest(failure_call=failure_call), tempfile.TemporaryDirectory() as temp_dir:
                run_dir = Path(temp_dir) / "run"
                run_dir.mkdir(mode=0o700)
                calls = 0
                injected_error = RuntimeError(f"openssl output contains {secret_key_material}")

                def fail_at_stage(argv, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        Path(argv[argv.index("-keyout") + 1]).write_text(secret_key_material, encoding="utf-8")
                        return subprocess.CompletedProcess(argv, 0, "", "")
                    if calls == 2 and failure_call == 3:
                        Path(argv[argv.index("-keyout") + 1]).write_text("synthetic server private key", encoding="utf-8")
                        Path(argv[argv.index("-out") + 1]).write_text("synthetic CSR", encoding="utf-8")
                        return subprocess.CompletedProcess(argv, 0, "", "")
                    raise injected_error

                with patch.object(runner, "run", side_effect=fail_at_stage):
                    with self.assertRaises(RuntimeError) as raised:
                        runner.make_certificates(run_dir)
                self.assertIs(raised.exception, injected_error)
                self.assertEqual(calls, failure_call)
                self.assertFalse((run_dir / "tls/ca-key.pem").exists())
                self.assertNotIn(secret_key_material, str(raised.exception))
                self.assertNotIn(secret_key_material, runner.safe_exception_summary(raised.exception, run_dir))

    def test_ca_key_is_removed_when_intermediate_extension_write_fails(self):
        secret_key_material = "SYNTHETIC-CA-KEY-NEVER-LOG-THIS"
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir(mode=0o700)
            calls = 0

            def generate_keys(argv, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    Path(argv[argv.index("-keyout") + 1]).write_text(secret_key_material, encoding="utf-8")
                else:
                    Path(argv[argv.index("-keyout") + 1]).write_text("synthetic server private key", encoding="utf-8")
                    Path(argv[argv.index("-out") + 1]).write_text("synthetic CSR", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "", "")

            original_write_text = Path.write_text

            def fail_extension_write(path, data, *args, **kwargs):
                if path.name == "server.ext":
                    raise OSError("injected extension write failure")
                return original_write_text(path, data, *args, **kwargs)

            with patch.object(runner, "run", side_effect=generate_keys), \
                    patch.object(Path, "write_text", fail_extension_write):
                with self.assertRaises(OSError):
                    runner.make_certificates(run_dir)
            self.assertEqual(calls, 2)
            self.assertFalse((run_dir / "tls/ca-key.pem").exists())

    def test_ca_key_is_removed_when_generation_is_interrupted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir(mode=0o700)

            def create_ca_key_then_interrupt(argv, **kwargs):
                key_path = Path(argv[argv.index("-keyout") + 1])
                key_path.write_text("synthetic interrupted CA key", encoding="utf-8")
                raise KeyboardInterrupt("simulated OpenSSL interruption")

            with patch.object(runner, "run", side_effect=create_ca_key_then_interrupt):
                with self.assertRaisesRegex(KeyboardInterrupt, "simulated OpenSSL interruption"):
                    runner.make_certificates(run_dir)

            self.assertFalse((run_dir / "tls/ca-key.pem").exists())

    def test_late_interrupt_during_final_directory_hardening_removes_server_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir(mode=0o700)

            def create_generated_outputs(argv, **kwargs):
                for flag, value in (("-keyout", "synthetic private key"),
                                    ("-out", "synthetic certificate")):
                    if flag in argv:
                        Path(argv[argv.index(flag) + 1]).write_text(value, encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "", "")

            tls = run_dir / "tls"
            original_chmod = Path.chmod

            def interrupt_after_final_permissions(path, mode, *args, **kwargs):
                result = original_chmod(path, mode, *args, **kwargs)
                if path == tls and mode == 0o711:
                    raise KeyboardInterrupt("simulated late generation interruption")
                return result

            with patch.object(runner, "run", side_effect=create_generated_outputs), \
                    patch.object(Path, "chmod", interrupt_after_final_permissions):
                with self.assertRaisesRegex(KeyboardInterrupt, "simulated late generation interruption"):
                    runner.make_certificates(run_dir)

            self.assertFalse((tls / "ca-key.pem").exists())
            self.assertFalse((tls / "server-key.pem").exists())
            self.assertFalse((tls / "server.pem").exists())
            self.assertFalse((tls / "ca.pem").exists())

    def test_partial_server_key_and_certificates_are_removed_on_generation_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir(mode=0o700)
            calls = 0

            def fail_after_server_key(argv, **kwargs):
                nonlocal calls
                calls += 1
                output_path = Path(argv[argv.index("-keyout") + 1])
                output_path.write_text("synthetic private key", encoding="utf-8")
                if calls == 1:
                    Path(argv[argv.index("-out") + 1]).write_text("synthetic CA certificate", encoding="utf-8")
                    return subprocess.CompletedProcess(argv, 0, "", "")
                raise RuntimeError("injected server-key generation failure")

            with patch.object(runner, "run", side_effect=fail_after_server_key):
                with self.assertRaisesRegex(RuntimeError, "disposable TLS certificate generation failed"):
                    runner.make_certificates(run_dir)

            tls = run_dir / "tls"
            self.assertFalse((tls / "ca-key.pem").exists())
            self.assertFalse((tls / "ca.pem").exists())
            self.assertFalse((tls / "server-key.pem").exists())
            self.assertFalse((tls / "server.pem").exists())

    def test_generated_artifacts_are_removed_when_key_permission_hardening_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir(mode=0o700)

            def create_generated_outputs(argv, **kwargs):
                for flag, value in (("-keyout", "synthetic private key"),
                                    ("-out", "synthetic certificate")):
                    if flag in argv:
                        Path(argv[argv.index(flag) + 1]).write_text(value, encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "", "")

            key_path = run_dir / "tls/server-key.pem"
            original_chmod = Path.chmod

            def fail_key_hardening(path, mode, *args, **kwargs):
                if path == key_path:
                    raise PermissionError("injected chmod failure")
                return original_chmod(path, mode, *args, **kwargs)

            with patch.object(runner, "run", side_effect=create_generated_outputs), \
                    patch.object(Path, "chmod", fail_key_hardening):
                with self.assertRaises(PermissionError) as raised:
                    runner.make_certificates(run_dir)
                self.assertEqual(str(raised.exception), "disposable TLS certificate generation failed (PermissionError)")

            tls = run_dir / "tls"
            self.assertFalse((tls / "ca-key.pem").exists())
            self.assertFalse((tls / "server-key.pem").exists())
            self.assertFalse((tls / "server.pem").exists())
            self.assertFalse((tls / "ca.pem").exists())

    def test_cleanup_error_is_recorded_without_masking_generation_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir(mode=0o700)
            key_path = run_dir / "tls/ca-key.pem"
            original_unlink = Path.unlink
            primary_error = ValueError("primary injected failure")

            def create_ca_key_then_fail(argv, **kwargs):
                Path(argv[argv.index("-keyout") + 1]).write_text("synthetic key", encoding="utf-8")
                raise primary_error

            def fail_ca_key_cleanup(path, *args, **kwargs):
                if path == key_path:
                    raise PermissionError("injected cleanup failure")
                return original_unlink(path, *args, **kwargs)

            with patch.object(runner, "run", side_effect=create_ca_key_then_fail), \
                    patch.object(Path, "unlink", fail_ca_key_cleanup):
                with self.assertRaises(ValueError) as raised:
                    runner.make_certificates(run_dir)
                self.assertIs(raised.exception, primary_error)
                self.assertEqual(str(raised.exception), "disposable TLS certificate generation failed (ValueError)")
                self.assertEqual(len(getattr(raised.exception, "__notes__", [])), 1)
                self.assertIn("ca-key.pem:PermissionError", raised.exception.__notes__[0])
                self.assertNotIn("injected cleanup failure", str(raised.exception))
            original_unlink(key_path)

    def test_receiver_identity_mount_and_state_init_are_nonroot_safe_and_idempotent(self):
        compose = yaml.safe_load(runner.COMPOSE.read_text(encoding="utf-8"))
        services = compose["services"]
        dockerfile = (runner.COMPOSE.parent / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^USER 10001:10001\s*$")
        mock = services["mock-discord"]
        self.assertNotIn("user", mock)  # image's explicit final USER applies
        self.assertEqual(mock["depends_on"]["state-init"]["condition"], "service_completed_successfully")
        self.assertTrue(mock["read_only"])
        self.assertEqual(mock["cap_drop"], ["ALL"])
        self.assertEqual(mock["cap_add"], ["NET_BIND_SERVICE"])
        probe = " ".join(mock["healthcheck"]["test"])
        self.assertIn("https://127.0.0.1/__test__/health", probe)
        self.assertIn("r.status == 200", probe)
        self.assertIn("r.read()", probe)
        init = services["state-init"]
        self.assertEqual(init["user"], "0:0")
        self.assertEqual(init["cap_drop"], ["ALL"])
        self.assertEqual(init["cap_add"], ["CHOWN"])
        self.assertTrue(init["read_only"])
        mounts = {(mount.get("source"), mount.get("target"), bool(mount.get("read_only")))
                  for mount in init["volumes"] if isinstance(mount, dict) and mount.get("type") == "bind"}
        self.assertEqual(mounts, {("${RUN_DIR:?run directory required}/tls/server-key.pem",
                                  "/run/server-key.pem", False)})
        command = init["command"][2]
        # Verify the complete privileged command contract and resulting POSIX
        # access policy without relying on privileged chown in the test process.
        runner.validate_state_init_owner(init)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tls = root / "tls"
            tls.mkdir(mode=0o711)
            tls.chmod(0o711)
            key = tls / "server-key.pem"
            key.write_text("synthetic key fixture", encoding="utf-8")
            key.chmod(0o400)
            key_mode = stat.S_IMODE(os.stat(key).st_mode)
            tls_mode = stat.S_IMODE(os.stat(tls).st_mode)
            owner_match = re.search(r"\bchown\s+(\d+):(\d+)\s+/run/discord-state\s+/run/server-key\.pem\b", command)
            self.assertIsNotNone(owner_match)
            target_uid, target_gid = map(int, owner_match.groups())
            self.assertEqual((target_uid, target_gid), (10001, 10001))
            self.assertEqual(key_mode, 0o400)
            self.assertTrue(self._mode_allows_read(key_mode, file_uid=target_uid, file_gid=target_gid,
                                                   process_uid=10001, process_gid=10001))
            self.assertFalse(self._mode_allows_read(key_mode, file_uid=target_uid, file_gid=target_gid,
                                                    process_uid=10002, process_gid=10002))
            self.assertEqual(tls_mode, 0o711)
            self.assertTrue(tls_mode & 0o001)  # unrelated identity can traverse, not list or write
            self.assertFalse(tls_mode & 0o004)
            self.assertFalse(tls_mode & 0o002)

    def test_rendered_compose_policy_rejects_wrong_tls_uid_and_gid_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir).resolve()
            project, run_id = "obai-discord-policy-test", "policy-test-001"
            subnet, gateway = "10.241.17.0/24", "10.241.17.1"

            def rendered_config():
                config = yaml.safe_load(runner.COMPOSE.read_text(encoding="utf-8"))
                for service in config["services"].values():
                    service["labels"]["io.omnibioai.run-id"] = run_id
                    normalized_mounts = []
                    for mount in service.get("volumes", []):
                        if isinstance(mount, str):
                            pieces = mount.split(":")
                            mount = {"type": "volume", "source": pieces[0], "target": pieces[1],
                                     "read_only": len(pieces) == 3 and pieces[2] == "ro"}
                        source = mount.get("source", "")
                        if source.startswith("${RUN_DIR"):
                            suffix = source.split("}", 1)[1].lstrip("/")
                            mount["source"] = str(run_dir / suffix)
                        normalized_mounts.append(mount)
                    service["volumes"] = normalized_mounts
                network = config["networks"]["isolated"]
                network["name"] = f"{project}_isolated"
                network["ipam"]["config"] = [{"subnet": subnet, "gateway": gateway}]
                network["labels"]["io.omnibioai.run-id"] = run_id
                volume = config["volumes"]["router-state"]
                volume["name"] = f"{project}_router-state"
                volume["labels"]["io.omnibioai.run-id"] = run_id
                return config

            config = rendered_config()
            runner.validate_rendered_config(config, project, run_id, run_dir, subnet, gateway)
            for owner in ("10002:10001", "10001:10002"):
                with self.subTest(owner=owner):
                    invalid = rendered_config()
                    command = invalid["services"]["state-init"]["command"][2]
                    invalid["services"]["state-init"]["command"][2] = command.replace(
                        "chown 10001:10001", f"chown {owner}")
                    with self.assertRaisesRegex(RuntimeError, "state-init identity or command"):
                        runner.validate_rendered_config(invalid, project, run_id, run_dir, subnet, gateway)

            injected = rendered_config()
            injected["services"]["state-init"]["command"][2] += "; echo injected"
            with self.assertRaisesRegex(RuntimeError, "state-init identity or command"):
                runner.validate_rendered_config(injected, project, run_id, run_dir, subnet, gateway)


if __name__ == "__main__":
    unittest.main()
