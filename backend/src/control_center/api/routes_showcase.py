"""Public showcase routes for control.omnibioai.org.

GET /showcase -- curated, schema-validated content (core/showcase.py):
    releases, benchmarks, example runs, tool versions, publications, test
    evidence, per-repo coverage, CI repos, security controls, data
    handling, limitations, plus the regression certification summary.
GET /uptime   -- 90-day per-service availability (core/uptime.py). Anonymous
    callers see only the services allowlisted in the showcase file's
    `uptime_services`, under their public labels; a platform.manage_infra
    caller sees every recorded service under its internal name.

Both routes are deliberately unauthenticated: their public responses carry
no hostnames, paths, credentials or per-user data.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from control_center.core import public_cache, uptime
from control_center.core.auth import infra_viewer
from control_center.core.showcase import load_showcase, public_showcase

router = APIRouter()


@router.get("/showcase")
def get_showcase() -> JSONResponse:
    return JSONResponse(public_cache.cached("showcase", public_showcase))


@router.get("/uptime")
def get_uptime(full: bool = Depends(infra_viewer)) -> JSONResponse:
    if full:
        return JSONResponse(uptime.summarize(None))
    return JSONResponse(public_cache.cached(
        "uptime", lambda: uptime.summarize(load_showcase()[0].uptime_services)))
