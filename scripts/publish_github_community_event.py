#!/usr/bin/env python3
"""Queue sanitized GitHub issue/milestone events for central approval.

This consumes the GitHub Actions event file rather than accepting arbitrary
event fields on a command line. It never copies user-written issue text into
Discord. Events are submitted unapproved and require Control Center IAM
approval before publication.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_discord_event import build_envelope, submit

CONFIRMED_BUG_LABEL = "discord-confirmed-bug"
APPROVED_FEATURE_LABEL = "discord-approved-feature"


def _stable_suffix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def resolve_github_event(event_name: str, action: str, payload: dict[str, Any]) -> dict[str, str] | None:
    """Return a sanitized central event description, or None to ignore it."""
    # GitHub supplies this field on repository events. Fail closed so private
    # issue/release metadata can never cross the public Discord boundary.
    repository = payload.get("repository")
    if not isinstance(repository, dict) or repository.get("private") is not False:
        return None

    if event_name == "release" and action == "published":
        release = payload.get("release")
        if (
            not isinstance(release, dict)
            or release.get("draft") is not False
            or release.get("prerelease") is not False
            or not isinstance(release.get("id"), int)
        ):
            return None
        return {
            "event_id": f"github-release-{release['id']}",
            "event_type": "platform.release",
            "title": "OmniBioAI release published",
            "message": "A new stable public release is available in the OmniBioAI release catalog.",
        }

    if event_name == "issues":
        issue = payload.get("issue")
        if (
            not isinstance(issue, dict)
            or not isinstance(issue.get("number"), int)
            or not isinstance(issue.get("id"), int)
            or "pull_request" in issue
        ):
            return None
        number = issue["number"]
        labels = {
            item.get("name") for item in issue.get("labels", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        if action == "labeled":
            label = payload.get("label", {}).get("name") if isinstance(payload.get("label"), dict) else None
            if label == CONFIRMED_BUG_LABEL:
                event_type, slug, title, message = (
                    "github.issue.confirmed", "bug-confirmed",
                    "Confirmed public bug report",
                    f"A maintainer confirmed public issue #{number}. Details are available in the public issue tracker.",
                )
            elif label == APPROVED_FEATURE_LABEL:
                event_type, slug, title, message = (
                    "feature.request.accepted", "feature-accepted",
                    "Feature request accepted",
                    f"A maintainer accepted public feature request #{number}.",
                )
            else:
                return None
            return {
                "event_id": f"github-issue-{slug}-{issue['id']}",
                "event_type": event_type,
                "title": title,
                "message": message,
            }
        if action == "closed" and CONFIRMED_BUG_LABEL in labels:
            closed_at = issue.get("closed_at")
            if not isinstance(closed_at, str) or not closed_at:
                return None
            return {
                "event_id": f"github-issue-resolved-{issue['id']}-{_stable_suffix(closed_at)}",
                "event_type": "github.issue.resolved",
                "title": "Confirmed public bug resolved",
                "message": f"Maintainers resolved confirmed public issue #{number}.",
            }
        return None

    if event_name == "milestone" and action == "closed":
        milestone = payload.get("milestone")
        if not isinstance(milestone, dict) or not isinstance(milestone.get("number"), int):
            return None
        closed_at = milestone.get("closed_at")
        milestone_id = milestone.get("id")
        if not isinstance(closed_at, str) or not closed_at or not isinstance(milestone_id, int):
            return None
        return {
            "event_id": f"github-milestone-{milestone_id}-{_stable_suffix(closed_at)}",
            "event_type": "platform.milestone",
            "title": "OmniBioAI platform milestone completed",
            "message": f"A public platform milestone (#{milestone['number']}) was completed.",
        }
    return None


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    base_url = os.environ.get("DISCORD_EVENT_ROUTER_URL", "").strip()
    secret = os.environ.get("DISCORD_EVENT_SOURCE_SECRET", "")
    if not event_path or not base_url or len(secret) < 43:
        print("GitHub Discord event source is not configured", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("event payload must be an object")
        event = resolve_github_event(event_name, str(payload.get("action", "")), payload)
        if event is None:
            print("github_discord_event=ignored")
            return 0
        from argparse import Namespace

        args = Namespace(
            **event,
            source="github",
            correlation_id=event["event_id"],
            color="info",
            fields_json="{}",
            approved=False,
        )
        envelope = build_envelope(args)
        status, receipt = submit(envelope, base_url=base_url, secret=secret)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"GitHub Discord event submission failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if status not in {200, 202}:
        print(f"GitHub Discord event rejected: HTTP {status}", file=sys.stderr)
        return 1
    print(json.dumps({
        "event_id": receipt.get("event_id", event["event_id"]),
        "event_type": event["event_type"],
        "destination_channel": receipt.get("destination_channel"),
        "delivery_status": receipt.get("delivery_status", "accepted"),
        "approved_publication": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
