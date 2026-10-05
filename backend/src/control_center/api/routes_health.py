"""
OmniBioAI backend.src.control_center.api.routes_health.

Purpose:
    Defines HTTP route handlers for backend.src.control_center.api.routes_health, including health.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
