#!/usr/bin/env python3
"""Queue a sanitized failed GitHub Actions run in the central router."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from publish_discord_event import build_envelope, submit

SEND_CONCLUSIONS = {"failure", "timed_out"}
_SAFE_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")
_SAFE_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
_RUN_URL = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+$")


def resolve_workflow_run(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        raise ValueError("GitHub workflow payload must be an object")
    run = payload.get("workflow_run")
    repository = payload.get("repository")
    if not isinstance(run, dict) or not isinstance(repository, dict):
        raise ValueError("GitHub workflow payload is incomplete")
    conclusion = run.get("conclusion")
    if conclusion not in SEND_CONCLUSIONS:
        return None
    repo = repository.get("full_name")
    run_id = run.get("id")
    attempt = run.get("run_attempt")
    workflow = run.get("name")
    branch = run.get("head_branch")
    run_url = run.get("html_url")
    sha = run.get("head_sha")
    if (
        not isinstance(repo, str) or not _SAFE_REPOSITORY.fullmatch(repo)
        or not isinstance(run_id, int) or run_id < 1
        or not isinstance(attempt, int) or attempt < 1
        or not isinstance(workflow, str) or not 1 <= len(workflow) <= 120
        or not isinstance(branch, str) or not _SAFE_REF.fullmatch(branch)
        or not isinstance(run_url, str) or not _RUN_URL.fullmatch(run_url)
        or not isinstance(sha, str) or not _SAFE_SHA.fullmatch(sha)
    ):
        raise ValueError("GitHub workflow payload contains invalid metadata")
    event_id = f"{repo.replace('/', ':')}:{run_id}:{attempt}"
    return {
        "event_id": event_id,
        "event_type": "github.workflow.failed",
        "source": "github",
        "title": "GitHub workflow failed",
        "message": "A GitHub Actions workflow requires operator attention.",
        "correlation_id": event_id,
        "color": "error",
        "fields_json": json.dumps({
            "Repository": repo,
            "Workflow": workflow,
            "Branch": branch,
            "Run URL": run_url,
            "Short SHA": sha[:12],
        }, separators=(",", ":")),
        "approved": False,
    }


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    base_url = os.environ.get("DISCORD_EVENT_ROUTER_URL", "").strip()
    secret = os.environ.get("DISCORD_EVENT_SOURCE_SECRET", "")
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        resolved = resolve_workflow_run(payload)
        if resolved is None:
            return 0
        args = argparse.Namespace(**resolved)
        status, _receipt = submit(build_envelope(args), base_url=base_url, secret=secret)
    except (OSError, ValueError, json.JSONDecodeError):
        print("GitHub workflow event submission failed", file=sys.stderr)
        return 1
    return 0 if status in {200, 202} else 1


if __name__ == "__main__":
    raise SystemExit(main())
