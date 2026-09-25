"""Shared pytest setup.

The public-response cache (core/public_cache.py) is disabled for every
test by default -- most route tests call the same endpoint several times
with different patched data within one test. test_public_cache.py turns it
back on explicitly to test the caching itself.
"""
from __future__ import annotations

import pytest

from control_center.core import public_cache


@pytest.fixture(autouse=True)
def _no_public_cache(monkeypatch):
    monkeypatch.setenv("PUBLIC_CACHE_SECONDS", "0")
    # No real background knowledge-base scan from on_startup() in tests.
    monkeypatch.setenv("KNOWLEDGE_BASE_SCAN_ON_STARTUP", "0")
    public_cache.clear()
    yield
    public_cache.clear()
