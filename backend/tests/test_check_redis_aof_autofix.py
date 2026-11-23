"""scripts/check_redis_aof_autofix.py: one high-severity known issue per Redis AOF auto-repair."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_redis_aof_autofix.py"
_spec = importlib.util.spec_from_file_location("check_redis_aof_autofix", SCRIPT)
check = importlib.util.module_from_spec(_spec)
sys.modules["check_redis_aof_autofix"] = check
_spec.loader.exec_module(check)

# the exact line scripts/redis-start-guarded.sh (omnibioai-studio) logs
REPAIR = ("redis-start-guarded: REDIS-AOF-AUTOFIX: repaired appendonly.aof.11.incr.aof (discarded 75 bytes after "
          "a format error); backup /data/aof-autofix/backup-20261122T042517Z-1; see "
          "/data/aof-autofix/ALERT-20261122T042517Z-1.txt")


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret")


def test_parses_the_wrapper_line():
    assert check.repairs_in_log(f"noise\n{REPAIR}\n1:M * Ready to accept connections\n") == [
        {"file": "appendonly.aof.11.incr.aof", "bytes": "75", "backup": "/data/aof-autofix/backup-20261122T042517Z-1"}]
    assert check.repairs_in_log("redis-start-guarded: AOF not valid, but not the repairable case") == []


def _run(log_text):
    resp = MagicMock()
    resp.json.return_value = {"id": "ki-7"}
    resp.raise_for_status.return_value = None
    with patch.object(check, "container_log", return_value=log_text), \
            patch.object(check.requests, "post", return_value=resp) as post:
        assert check.main() == 0
    return post


def test_files_one_issue_per_repair_and_never_twice():
    post = _run(REPAIR)
    body = post.call_args.kwargs["json"]
    assert body["severity"] == "high" and body["title"].startswith("[redis-aof-autofix] Redis repaired its AOF")
    assert "/data/aof-autofix/backup-20261122T042517Z-1" in body["description"]
    assert _run(REPAIR).call_count == 0                       # same repair: already reported
    second = REPAIR.replace("20261122T042517Z-1", "20261201T000000Z-1")
    assert _run(f"{REPAIR}\n{second}").call_count == 1        # a new repair: one more issue


def test_no_repair_no_issue():
    assert _run("1:M * Ready to accept connections tcp").call_count == 0
