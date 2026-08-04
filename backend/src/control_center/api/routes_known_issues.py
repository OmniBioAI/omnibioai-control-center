from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from control_center.checks.known_issues import (
    KNOWN_ISSUES_PATH_DEFAULT,
    KnownIssueError,
    create_known_issue,
    delete_known_issue,
    list_known_issues,
    update_known_issue,
)
from control_center.core.auth import require_permission

router = APIRouter()


def _issues_path() -> Path:
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    return workspace / KNOWN_ISSUES_PATH_DEFAULT


class KnownIssueCreate(BaseModel):
    title: str
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    area: Optional[str] = None
    opened_at: Optional[str] = None


class KnownIssueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    area: Optional[str] = None
    opened_at: Optional[str] = None


@router.get("/known-issues")
def known_issues_list() -> JSONResponse:
    """Read-only, open to everyone."""
    try:
        issues = list_known_issues(_issues_path())
    except KnownIssueError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse({"issues": issues})


@router.post("/known-issues")
def known_issues_create(
    body: KnownIssueCreate, _admin: dict = Depends(require_permission("platform.manage_content")),
) -> JSONResponse:
    # AUDIT_EVENT integration point: PR3D leaves this a comment, not a
    # call -- IAM's persistent audit ledger (PR9) has no client library
    # this repo can import yet. Once one exists, emit here with
    # actor=_admin["sub"], action="known_issue.create".
    try:
        issue = create_known_issue(_issues_path(), body.model_dump())
    except KnownIssueError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(issue, status_code=201)


@router.put("/known-issues/{issue_id}")
def known_issues_update(
    issue_id: str, body: KnownIssueUpdate, _admin: dict = Depends(require_permission("platform.manage_content")),
) -> JSONResponse:
    # AUDIT_EVENT integration point: see known_issues_create above --
    # actor=_admin["sub"], action="known_issue.update", target=issue_id.
    try:
        issue = update_known_issue(_issues_path(), issue_id, body.model_dump())
    except KnownIssueError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(issue)


@router.delete("/known-issues/{issue_id}")
def known_issues_delete(issue_id: str, _admin: dict = Depends(require_permission("platform.manage_content"))):
    # AUDIT_EVENT integration point: see known_issues_create above --
    # actor=_admin["sub"], action="known_issue.delete", target=issue_id.
    try:
        delete_known_issue(_issues_path(), issue_id)
    except KnownIssueError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return Response(status_code=204)
