"""
OmniBioAI backend.src.control_center.api.routes_summary.

Purpose:
    Defines HTTP route handlers for backend.src.control_center.api.routes_summary, including summary.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from control_center.core.settings import load_settings
from control_center.core.runner import run_all_checks
from control_center.checks.disk import run_disk_checks

router = APIRouter()


def _inject_ui_urls(
    service_results: list[dict],
    services_cfg: dict,
) -> list[dict]:
    """
    Enrich each service result with ui_url from config (if present).
    ui_url is optional — services without it (mysql, redis) get None.
    """
    for result in service_results:
        cfg = services_cfg.get(result["name"], {})
        result["ui_url"] = cfg.get("ui_url") or None
    return service_results


@router.get("/summary")
def summary() -> JSONResponse:
    try:
        settings = load_settings()
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    service_results = run_all_checks(settings)
    service_results = _inject_ui_urls(service_results, settings.services)
    disk_results = run_disk_checks(settings)

    overall = "UP"
    for r in service_results + disk_results:
        if r["status"] == "DOWN":
            overall = "DOWN"
            break
        if r["status"] == "WARN" and overall != "DOWN":
            overall = "WARN"

    return JSONResponse({
        "overall_status": overall,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "services": service_results,
        "system": {
            "disk": disk_results,
        },
    })