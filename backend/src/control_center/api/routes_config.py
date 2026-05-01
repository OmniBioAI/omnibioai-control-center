from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter()

_DEFAULT_CONFIG = os.environ.get("CONTROL_CENTER_CONFIG", "/config/control_center.yaml")


@router.get("/config")
def get_config() -> PlainTextResponse:
    if not os.path.exists(_DEFAULT_CONFIG):
        raise HTTPException(status_code=404, detail=f"Config not found: {_DEFAULT_CONFIG}")
    with open(_DEFAULT_CONFIG, "r", encoding="utf-8") as f:
        content = f.read()
    return PlainTextResponse(content, media_type="text/plain")


@router.post("/config/service")
async def add_service(payload: dict) -> JSONResponse:
    name = (payload.get("name") or "").strip()
    svc_type = (payload.get("type") or "http").strip()
    url = (payload.get("url") or "").strip()

    if not name or not url:
        raise HTTPException(status_code=422, detail="name and url are required")

    if not os.path.exists(_DEFAULT_CONFIG):
        raise HTTPException(status_code=404, detail=f"Config not found: {_DEFAULT_CONFIG}")

    import yaml
    with open(_DEFAULT_CONFIG, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    raw.setdefault("services", {})[name] = {"type": svc_type, "url": url, "timeout_s": 2}

    with open(_DEFAULT_CONFIG, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)

    return JSONResponse({"ok": True, "name": name})
