"""
OmniBioAI backend.src.control_center.api.routes_services.

Purpose:
    Defines HTTP route handlers for backend.src.control_center.api.routes_services, including services.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from control_center.core.settings import load_settings
from control_center.core.runner import run_all_checks
from control_center.api.routes_summary import _inject_ui_urls

router = APIRouter()


@router.get("/services")
def services() -> JSONResponse:
    try:
        settings = load_settings()
        results = run_all_checks(settings)
        results = _inject_ui_urls(results, settings.services)
        return JSONResponse({"services": results})
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=500)