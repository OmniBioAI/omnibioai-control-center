from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from control_center.notifications.discord_events import (
    DiscordEventStore,
    DiscordEventValidationError,
    parse_event_payload,
)

SCRIPTS = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "publish_github_workflow_failure", SCRIPTS / "publish_github_workflow_failure.py",
)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(adapter)
sys.path.remove(str(SCRIPTS))


def workflow_payload(conclusion: str = "failure") -> dict:
    return {
        "repository": {"full_name": "OmniBioAI/control-center"},
        "workflow_run": {
            "id": 987654,
            "run_attempt": 2,
            "conclusion": conclusion,
            "name": "Backend tests",
            "head_branch": "main",
            "html_url": "https://github.com/OmniBioAI/control-center/actions/runs/987654",
            "head_sha": "0123456789abcdef0123456789abcdef01234567",
        },
    }


@pytest.mark.parametrize("conclusion", ["failure", "timed_out"])
def test_failure_queues_only_sanitized_metadata_for_human_approval(monkeypatch, tmp_path, conclusion):
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(workflow_payload(conclusion)), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    monkeypatch.setenv("DISCORD_EVENT_ROUTER_URL", "https://control.example.org")
    monkeypatch.setenv("DISCORD_EVENT_SOURCE_SECRET", "s" * 43)
    with patch.object(adapter, "submit", return_value=(202, {})) as submit:
        assert adapter.main() == 0
    envelope = submit.call_args.args[0]
    assert envelope["event_id"] == "OmniBioAI:control-center:987654:2"
    assert envelope["event_type"] == "github.workflow.failed"
    assert envelope["destination_channel"] == "omnibioai-alerts"
    assert envelope["approved_publication"] is False
    assert set(envelope["safe_message_payload"]["fields"]) == {
        "Repository", "Workflow", "Branch", "Run URL", "Short SHA",
    }
    assert "logs" not in json.dumps(envelope).lower()


@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", "neutral", "success"])
def test_non_failure_conclusions_are_dropped_before_submit(monkeypatch, tmp_path, conclusion):
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(workflow_payload(conclusion)), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    with patch.object(adapter, "submit") as submit:
        assert adapter.main() == 0
    submit.assert_not_called()


def test_duplicate_repo_run_and_attempt_deduplicates_in_event_store(tmp_path):
    resolved = adapter.resolve_workflow_run(workflow_payload())
    envelope = adapter.build_envelope(argparse.Namespace(**resolved))
    event, raw = parse_event_payload(json.dumps(envelope).encode(), authenticated_source="github")
    store = DiscordEventStore(tmp_path)
    first, first_duplicate = store.ingest(event, raw)
    second, second_duplicate = store.ingest(event, raw)
    assert first["event_id"] == second["event_id"]
    assert first_duplicate is False
    assert second_duplicate is True


def test_workflow_failure_is_rejected_from_unknown_source():
    resolved = adapter.resolve_workflow_run(workflow_payload())
    envelope = adapter.build_envelope(argparse.Namespace(**resolved))
    envelope["source_service"] = "support"
    with pytest.raises(DiscordEventValidationError):
        parse_event_payload(json.dumps(envelope).encode(), authenticated_source="support")
