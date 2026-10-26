"""Shared pytest setup.

The public-response cache (core/public_cache.py) is disabled for every
test by default -- most route tests call the same endpoint several times
with different patched data within one test. test_public_cache.py turns it
back on explicitly to test the caching itself.
"""
from __future__ import annotations

import asyncio
import sys

import pytest

from control_center.core import public_cache

# Uvicorn's ``standard`` extra includes uvloop on Linux, and the deployed
# Control Center uses it when available. In this restricted test host,
# Python's default selector loop can queue call_soon_threadsafe() callbacks
# from AnyIO worker threads without waking the selector; Starlette TestClient
# then hangs even for a one-route FastAPI app. Select the same supported loop
# backend before pytest/AnyIO creates a loop. This keeps TestClient lifespan,
# sync dependencies, and thread offloading fully enabled in the suite.
if sys.platform != "win32":
    try:
        import uvloop
    except ImportError:  # pragma: no cover - uvicorn[standard] installs uvloop on Linux
        pass
    else:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


@pytest.fixture(autouse=True)
def _no_public_cache(monkeypatch):
    monkeypatch.setenv("PUBLIC_CACHE_SECONDS", "0")
    # No real background knowledge-base scan from on_startup() in tests.
    monkeypatch.setenv("KNOWLEDGE_BASE_SCAN_ON_STARTUP", "0")
    public_cache.clear()
    yield
    public_cache.clear()
