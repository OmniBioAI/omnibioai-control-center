from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).parents[2] / "scripts" / "publish_github_community_event.py"
SPEC = importlib.util.spec_from_file_location("publish_github_community_event", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_confirmed_bug_label_queues_generic_unapproved_bug_event():
    event = MODULE.resolve_github_event("issues", "labeled", {
        "repository": {"private": False},
        "issue": {"id": 101, "number": 7, "labels": [{"name": "discord-confirmed-bug"}],
                  "title": "Contains private text", "body": "Do not publish this"},
        "label": {"name": "discord-confirmed-bug"},
    })
    assert event == {
        "event_id": "github-issue-bug-confirmed-101",
        "event_type": "github.issue.confirmed",
        "title": "Confirmed public bug report",
        "message": "A maintainer confirmed public issue #7. Details are available in the public issue tracker.",
    }
    assert "private" not in str(event).lower()


def test_approved_feature_label_maps_to_feature_channel_event():
    event = MODULE.resolve_github_event("issues", "labeled", {
        "repository": {"private": False},
        "issue": {"id": 102, "number": 8, "labels": [{"name": "discord-approved-feature"}]},
        "label": {"name": "discord-approved-feature"},
    })
    assert event["event_type"] == "feature.request.accepted"
    assert event["event_id"] == "github-issue-feature-accepted-102"


def test_unreviewed_issues_and_other_actions_are_ignored():
    payload = {"repository": {"private": False}, "issue": {"id": 103, "number": 9, "labels": [], "title": "untrusted"},
               "label": {"name": "bug"}}
    assert MODULE.resolve_github_event("issues", "opened", payload) is None
    assert MODULE.resolve_github_event("issues", "labeled", payload) is None
    assert MODULE.resolve_github_event("pull_request", "opened", payload) is None


def test_confirmed_bug_close_uses_stable_resolution_id_and_no_issue_text():
    payload = {"repository": {"private": False}, "issue": {"id": 104, "number": 10, "closed_at": "2026-10-24T12:00:00Z",
                          "labels": [{"name": "discord-confirmed-bug"}],
                          "title": "private", "body": "sensitive"}}
    first = MODULE.resolve_github_event("issues", "closed", payload)
    second = MODULE.resolve_github_event("issues", "closed", payload)
    assert first == second
    assert first["event_type"] == "github.issue.resolved"
    assert "private" not in str(first).lower() and "sensitive" not in str(first).lower()
    assert MODULE.resolve_github_event(
        "issues", "closed", {"repository": {"private": False}, "issue": {**payload["issue"], "labels": []}}
    ) is None


def test_completed_milestone_has_stable_event_id():
    payload = {"repository": {"private": False}, "milestone": {"id": 105, "number": 3, "closed_at": "2026-10-24T12:00:00Z",
                              "title": "untrusted title"}}
    event = MODULE.resolve_github_event("milestone", "closed", payload)
    assert event["event_type"] == "platform.milestone"
    assert event["event_id"] == MODULE.resolve_github_event("milestone", "closed", payload)["event_id"]
    assert "untrusted" not in str(event)


def test_built_github_envelope_never_asserts_publication_approval():
    event = MODULE.resolve_github_event("issues", "labeled", {
        "repository": {"private": False},
        "issue": {"id": 106, "number": 11, "labels": [{"name": "discord-approved-feature"}]},
        "label": {"name": "discord-approved-feature"},
    })
    args = SimpleNamespace(
        **event, source="github", correlation_id=event["event_id"], color="info",
        fields_json="{}", approved=False,
    )
    envelope = MODULE.build_envelope(args)
    assert envelope["approved_publication"] is False
    assert envelope["destination_channel"] == "feature-requests"
    assert envelope["source_service"] == "github"


def test_only_stable_public_releases_are_queued():
    payload = {
        "repository": {"private": False},
        "release": {"id": 9001, "draft": False, "prerelease": False,
                    "name": "untrusted text", "body": "never copied"},
    }
    event = MODULE.resolve_github_event("release", "published", payload)
    assert event == {
        "event_id": "github-release-9001",
        "event_type": "platform.release",
        "title": "OmniBioAI release published",
        "message": "A new stable public release is available in the OmniBioAI release catalog.",
    }
    assert "untrusted" not in str(event)
    assert MODULE.resolve_github_event(
        "release", "published", {**payload, "repository": {"private": True}}
    ) is None
    assert MODULE.resolve_github_event(
        "release", "published", {**payload, "release": {**payload["release"], "prerelease": True}}
    ) is None


def test_private_repository_and_pull_request_issues_fail_closed():
    payload = {
        "repository": {"private": True},
        "issue": {"id": 901, "number": 12, "labels": [{"name": "discord-confirmed-bug"}]},
        "label": {"name": "discord-confirmed-bug"},
    }
    assert MODULE.resolve_github_event("issues", "labeled", payload) is None
    payload["repository"] = {"private": False}
    payload["issue"]["pull_request"] = {"url": "https://example.invalid"}
    assert MODULE.resolve_github_event("issues", "labeled", payload) is None
