"""scripts/check_platform_health.py: NAS mounts (host + inside TES) and compose services, one known issue each."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_platform_health.py"
_spec = importlib.util.spec_from_file_location("check_platform_health", SCRIPT)
check = importlib.util.module_from_spec(_spec)
sys.modules["check_platform_health"] = check
_spec.loader.exec_module(check)

NAS = "192.168.86.24"
SIF = ["/mnt/nas/omnibioai/sif-images", f"{NAS}:/volume3/omnibioai-fast/sif-images", 900]


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(check, "LOCK_PATH", tmp_path / "run.lock")
    monkeypatch.setattr(check, "DEPLOY_LOCK", tmp_path / "deploy.lock")
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret")


def _proc(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# mounts
# ---------------------------------------------------------------------------


def test_mount_sources_ignores_the_autofs_point():
    with patch.object(check, "_run", return_value=_proc(
            f"systemd-1 autofs\n{NAS}:/volume2/omnibioai-main nfs\n")):
        assert check.mount_sources("/mnt/nas/omnibioai") == [f"{NAS}:/volume2/omnibioai-main"]
    with patch.object(check, "_run", return_value=_proc("systemd-1 autofs\n")):
        assert check.mount_sources("/mnt/nas/sif") == []


def test_entry_count_and_errors():
    with patch.object(check, "_run", return_value=_proc("a.sif\nb.sif\n")):
        assert check.entry_count([], "/x") == 2
    with patch.object(check, "_run", return_value=_proc("", 2, "ls: cannot open directory '/x': Permission denied\n")):
        assert check.entry_count([], "/x") == "ls: cannot open directory '/x': Permission denied"
    with patch.object(check, "_run", side_effect=subprocess.TimeoutExpired("ls", 20)):
        assert check.entry_count([], "/x") == "no answer within 20s"


def _fake_fs(mounted: dict[str, str], counts: dict[tuple, int | str]):
    """Patch findmnt/ls: mounted = path -> source; counts = (prefix tuple, path) -> entries."""
    def sources(path):
        return [mounted[path]] if path in mounted else []

    def count(prefix, path):
        return counts.get((tuple(prefix), path), 0)

    return patch.object(check, "mount_sources", side_effect=sources), patch.object(check, "entry_count", side_effect=count)


def test_the_2026_11_24_boot_failure_is_reported():
    """Parent mounted, sub-mount failed (empty mountpoint dir), TES bind empty."""
    parent = ["/mnt/nas/omnibioai", f"{NAS}:/volume2/omnibioai-main", 1]
    tes = ("docker", "exec", check.TES_CONTAINER)
    p1, p2 = _fake_fs({parent[0]: parent[1]}, {((), parent[0]): 30, ((), SIF[0]): 0,
                                              (tes, "/mnt/nas/omnibioai/sif-images"): 0, (tes, "/sif"): 0})
    with p1, p2:
        problems = check.mount_problems([parent, SIF], check.TES_PATHS, tes_running=True)
    assert problems == [
        f"/mnt/nas/omnibioai/sif-images: not mounted from {SIF[1]} (found nothing)",
        ("inside omnibioai-studio-tes-1 /mnt/nas/omnibioai/sif-images: 0 entries (expected >= 900; "
         "a bind made before the mount came back: recreate tes)"),
        ("inside omnibioai-studio-tes-1 /sif: 0 entries (expected >= 900; a bind made before the mount came back: "
         "recreate tes)"),
    ]


def test_healthy_mounts_and_tes():
    tes = ("docker", "exec", check.TES_CONTAINER)
    p1, p2 = _fake_fs({SIF[0]: SIF[1]}, {((), SIF[0]): 1007, (tes, "/mnt/nas/omnibioai/sif-images"): 1007,
                                         (tes, "/sif"): 1007})
    with p1, p2:
        assert check.mount_problems([SIF], check.TES_PATHS, tes_running=True) == []


def test_mounted_but_too_few_or_unreadable():
    p1, p2 = _fake_fs({SIF[0]: SIF[1]}, {((), SIF[0]): 12})
    with p1, p2:
        assert check.mount_problems([SIF], [], tes_running=False) == [
            "/mnt/nas/omnibioai/sif-images: 12 entries (expected >= 900)"]
    p1, p2 = _fake_fs({SIF[0]: SIF[1]}, {((), SIF[0]): "no answer within 20s"})
    with p1, p2:
        assert check.mount_problems([SIF], [], tes_running=False) == [
            "/mnt/nas/omnibioai/sif-images: unreadable (no answer within 20s)"]


def test_wrong_source_is_a_problem():
    p1, p2 = _fake_fs({SIF[0]: f"{NAS}:/volume1/old"}, {((), SIF[0]): 1007})
    with p1, p2:
        assert check.mount_problems([SIF], [], tes_running=False) == [
            f"/mnt/nas/omnibioai/sif-images: not mounted from {SIF[1]} (found {NAS}:/volume1/old)"]


def test_decide_mounts_window():
    assert check.decide_mounts([], {}, 1000) == ("ok", {})
    assert check.decide_mounts(["x"], {}, 1000) == ("waiting", {"bad_since": 1000})
    assert check.decide_mounts(["x"], {"bad_since": 1000}, 1000 + 179) == ("waiting", {"bad_since": 1000})
    assert check.decide_mounts(["x"], {"bad_since": 1000}, 1000 + 180) == ("alert", {"bad_since": 1000})
    assert check.decide_mounts([], {"bad_since": 1000}, 2000) == ("recovered", {})


# ---------------------------------------------------------------------------
# services
# ---------------------------------------------------------------------------


def _c(service, status="running", health=None, code=0, error=""):
    state = {"Status": status, "Running": status == "running", "ExitCode": code, "Error": error}
    if health:
        state["Health"] = {"Status": health}
    return {"Name": f"/omnibioai-studio-{service}-1", "State": state,
            "Config": {"Labels": {"com.docker.compose.service": service}}}


def test_service_problems():
    containers = [
        _c("tes", health="healthy"),
        _c("videos"),                                                  # no healthcheck, running
        _c("workbench", "exited", code=255,
           error="error while creating mount source path '/x/data/PubMed': mkdir: file exists"),
        _c("rag", "exited", code=255),
        _c("neo4j", health="unhealthy"),
        _c("launcher", "restarting"),
        _c("deploy-verify", "exited", code=0),                         # one-shot, done
        _c("redis-acl-init", "exited", code=1),                        # one-shot, failed
        _c("tes2", health="starting"),
    ]
    assert check.service_problems(containers) == {
        "workbench": "exited (code 255): error while creating mount source path '/x/data/PubMed': mkdir: file exists",
        "rag": "exited (code 255)",
        "neo4j": "unhealthy",
        "launcher": "restarting",
        "redis-acl-init": "exited (code 1)",
    }


def test_decide_services_window_per_service():
    assert check.decide_services({}, {}, 1000) == ("ok", {}, [])
    action, state, over = check.decide_services({"rag": "exited"}, {}, 1000)
    assert (action, state, over) == ("waiting", {"rag": 1000}, [])
    action, state, over = check.decide_services({"rag": "exited", "neo4j": "unhealthy"}, {"rag": 1000}, 1300)
    assert (action, state, over) == ("alert", {"rag": 1000, "neo4j": 1300}, ["rag"])
    assert check.decide_services({}, {"rag": 1000}, 1400) == ("recovered", {}, [])


def test_deploy_lock(tmp_path):
    assert check.deploy_lock_held(1000) is False
    check.DEPLOY_LOCK.write_text("session=x\nservice=tes\nexpires_epoch=2000\n")
    assert check.deploy_lock_held(1000) is True
    assert check.deploy_lock_held(2001) is False                       # expired: problems count again
    check.DEPLOY_LOCK.write_text("garbage")
    assert check.deploy_lock_held(1000) is False


def test_compose_containers(monkeypatch):
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd[:3] == ["docker", "ps", "-aq"]:
            return _proc("abc\ndef\n")
        return _proc('[{"Name": "/a"}, {"Name": "/b"}]')

    monkeypatch.setattr(check, "_run", run)
    assert [c["Name"] for c in check.compose_containers()] == ["/a", "/b"]
    assert calls[0] == ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=omnibioai-studio"]
    assert calls[1] == ["docker", "inspect", "abc", "def"]
    monkeypatch.setattr(check, "_run", lambda cmd: _proc(""))
    assert check.compose_containers() == []
    monkeypatch.setattr(check, "_run", lambda cmd: _proc("abc") if "ps" in cmd else _proc("", 1, "boom"))
    with pytest.raises(RuntimeError, match="docker inspect failed: boom"):
        check.compose_containers()
    monkeypatch.setattr(check, "_run", lambda cmd: _proc("", 1, "Cannot connect to the Docker daemon"))
    with pytest.raises(RuntimeError, match="docker ps failed: Cannot connect to the Docker daemon"):
        check.compose_containers()

    def hang(cmd):
        raise subprocess.TimeoutExpired(cmd, 20)

    monkeypatch.setattr(check, "_run", hang)
    with pytest.raises(RuntimeError, match="docker ps: no answer within 20s"):
        check.compose_containers()


def test_docker_down_or_no_containers_is_a_service_problem():
    with patch.object(check, "compose_containers", side_effect=RuntimeError("docker ps failed: no daemon")), \
            patch.object(check, "mount_problems", return_value=[]), patch.object(check.time, "time", return_value=1000):
        check.main()
    assert check.load_state()["services"] == {"docker": 1000}
    with patch.object(check, "compose_containers", return_value=[]), \
            patch.object(check, "mount_problems", return_value=[]), patch.object(check.time, "time", return_value=1060):
        check.main()
    assert check.load_state()["services"] == {"(all)": 1060}


# ---------------------------------------------------------------------------
# main: known issues
# ---------------------------------------------------------------------------


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def _main(now, mounts_problems, containers, open_issues=()):
    with patch.object(check, "mount_problems", return_value=mounts_problems), \
            patch.object(check, "compose_containers", return_value=containers), \
            patch.object(check.time, "time", return_value=now), \
            patch.object(check.requests, "get", return_value=_resp({"issues": list(open_issues)})), \
            patch.object(check.requests, "post", return_value=_resp({"id": "ki-1"})) as post, \
            patch.object(check.requests, "put", return_value=_resp({})) as put:
        assert check.main() == 0
    return post, put


def test_mounts_alert_after_the_window_then_resolve():
    bad = ["/mnt/nas/omnibioai/sif-images: 0 entries (expected >= 900)"]
    post, _ = _main(1000, bad, [])
    post.assert_not_called()                                           # first minute: waiting
    post, _ = _main(1000 + 180, bad, [])
    body = post.call_args.kwargs["json"]
    assert body["severity"] == "high" and body["area"] == "NAS / Infra"
    assert body["title"].startswith("[platform-mounts] 1 NAS mount problem(s): /mnt/nas/omnibioai/sif-images")
    assert "since " in body["description"] and bad[0] in body["description"]

    _, put = _main(1000 + 240, bad, [], open_issues=[{"id": "ki-1", "title": body["title"], "status": "open"}])
    assert put.call_args.args[0].endswith("/known-issues/ki-1")        # updated while it lasts, not re-filed

    _, put = _main(1000 + 300, [], [], open_issues=[{"id": "ki-1", "title": body["title"], "status": "open",
                                                     "description": "d"}])
    assert put.call_args.kwargs["json"]["status"] == "resolved"


def test_services_alert_after_five_minutes_and_lock_suspends():
    down = [_c("rag", "exited", code=255)]
    post, _ = _main(1000, [], down)
    post.assert_not_called()
    check.DEPLOY_LOCK.write_text("expires_epoch=99999\n")
    post, _ = _main(1000 + 400, [], down)
    post.assert_not_called()                                           # deploy in progress
    check.DEPLOY_LOCK.unlink()
    post, _ = _main(1000 + 400, [], down)
    body = post.call_args.kwargs["json"]
    assert body["title"] == "[platform-services] 1 service(s) down > 5 min: rag"
    assert "rag: exited (code 255) since" in body["description"]


def test_a_stuck_previous_run_is_not_stacked(capsys):
    import fcntl

    check.LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(check.LOCK_PATH, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert check.main() == 1
    assert "previous run still running" in capsys.readouterr().out


def test_tes_checked_only_when_running():
    seen = {}

    def problems(mounts, tes_paths, tes_running):
        seen["tes_running"] = tes_running
        return []

    with patch.object(check, "mount_problems", side_effect=problems), \
            patch.object(check, "compose_containers", return_value=[_c("tes", "exited", code=1)]), \
            patch.object(check.requests, "post"):
        check.main()
    assert seen["tes_running"] is False
