from __future__ import annotations

import json
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from control_center.notifications.discord import notify as _discord_notify

KNOWN_ISSUES_PATH_DEFAULT = "omnibioai-work/known_issues.json"

_VALID_SEVERITIES = {"high", "medium", "low"}
_VALID_STATUSES = {"open", "acknowledged", "resolved"}

# Separate from DISCORD_WEBHOOK_URL (used by checks/gpu.py for temperature
# alerts) -- a different channel/server for known-issue alerts. Same
# graceful-absence behavior: notify() itself no-ops on an empty URL, so
# nothing here needs its own "is this configured" branch.
_ALERT_WEBHOOK_URL = os.environ.get("DISCORD_ALERT_WEBHOOK_URL", "")
_DESCRIPTION_ALERT_LIMIT = 500


class KnownIssueError(Exception):
    """Raised by the functions below; routes_known_issues.py maps
    status_code straight onto the HTTP response."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _load_issues(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise KnownIssueError(f"Cannot read known_issues.json: {e}", 500)
    if not isinstance(data, list):
        raise KnownIssueError("known_issues.json does not contain a JSON list", 500)
    return data


def _save_issues(path: Path, issues: list[dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(issues, indent=2), encoding="utf-8")
    except OSError as e:
        raise KnownIssueError(f"Cannot write known_issues.json: {e}", 500)


def _backfill_ids(issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Assigns a UUID id to any entry missing one. Purely additive -- every
    other field (title, description, severity, opened_at, status, area) is
    preserved exactly as-is; only entries that already lack an "id" gain one."""
    changed = False
    backfilled = []
    for issue in issues:
        if "id" not in issue:
            issue = {"id": str(uuid.uuid4()), **issue}
            changed = True
        backfilled.append(issue)
    return backfilled, changed


def list_known_issues(path: Path) -> list[dict[str, Any]]:
    issues = _load_issues(path)
    issues, changed = _backfill_ids(issues)
    if changed:
        _save_issues(path, issues)
    return issues


def _validate_severity(value: str) -> None:
    if value not in _VALID_SEVERITIES:
        raise KnownIssueError(f"Invalid severity: {value!r} (must be one of {sorted(_VALID_SEVERITIES)})")


def _validate_status(value: str) -> None:
    if value not in _VALID_STATUSES:
        raise KnownIssueError(f"Invalid status: {value!r} (must be one of {sorted(_VALID_STATUSES)})")


def _alert_high_severity(issue: dict[str, Any]) -> None:
    """Fires on genuinely new high-severity issues only -- not medium/low
    (avoids alert fatigue) and not on updates to existing entries (only
    create_known_issue calls this, never update_known_issue). Same code
    path regardless of whether the entry was created by a human via the
    Admin tab or a cron self-check script, since both go through this
    one function. notify() itself is already failure-tolerant (no-ops on
    an empty webhook URL, swallows request errors) -- a Discord outage
    must never block a known-issue from being recorded."""
    description = issue["description"] or ""
    if len(description) > _DESCRIPTION_ALERT_LIMIT:
        description = description[:_DESCRIPTION_ALERT_LIMIT].rstrip() + "…"
    _discord_notify(
        _ALERT_WEBHOOK_URL,
        f"🔴 High-severity issue: {issue['title']}",
        description or "(no description)",
        color="error",
        fields={"Area": issue["area"] or "—", "Opened": issue["opened_at"]},
    )


def create_known_issue(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    title = (data.get("title") or "").strip()
    if not title:
        raise KnownIssueError("title is required")

    severity = data.get("severity") or "medium"
    status = data.get("status") or "open"
    _validate_severity(severity)
    _validate_status(status)

    issue = {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": data.get("description") or "",
        "severity": severity,
        "opened_at": data.get("opened_at") or date.today().isoformat(),
        "status": status,
        "area": data.get("area") or "",
    }

    issues, _ = _backfill_ids(_load_issues(path))
    issues.append(issue)
    _save_issues(path, issues)

    if severity == "high":
        try:
            _alert_high_severity(issue)
        except Exception:
            # notify() already swallows its own request errors -- this is
            # belt-and-suspenders against anything else going wrong in the
            # alert path itself. A failed/misconfigured alert must never
            # fail the actual known-issue creation.
            pass

    return issue


def update_known_issue(path: Path, issue_id: str, data: dict[str, Any]) -> dict[str, Any]:
    issues, _ = _backfill_ids(_load_issues(path))
    idx = next((i for i, issue in enumerate(issues) if issue.get("id") == issue_id), None)
    if idx is None:
        raise KnownIssueError(f"No known issue with id {issue_id!r}", 404)

    if "severity" in data and data["severity"] is not None:
        _validate_severity(data["severity"])
    if "status" in data and data["status"] is not None:
        _validate_status(data["status"])

    updated = dict(issues[idx])
    for field in ("title", "description", "severity", "opened_at", "status", "area"):
        if field in data and data[field] is not None:
            updated[field] = data[field]

    issues[idx] = updated
    _save_issues(path, issues)
    return updated


def delete_known_issue(path: Path, issue_id: str) -> None:
    issues, _ = _backfill_ids(_load_issues(path))
    remaining = [issue for issue in issues if issue.get("id") != issue_id]
    if len(remaining) == len(issues):
        raise KnownIssueError(f"No known issue with id {issue_id!r}", 404)
    _save_issues(path, remaining)
