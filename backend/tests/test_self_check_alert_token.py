"""Every host self-check script mints a token the known-issues write routes accept.

Since 7887ea6 (2026-08-03) those routes check the `permissions` claim; the scripts kept minting
`roles: ["admin"]`, which got 403, so no self-check could file an issue (and alert) after that.
Found by the end-to-end platform-health alert test on 2026-11-25.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import jwt
import pytest
from fastapi import HTTPException

from control_center.core.auth import require_permission
from control_center.core.jwt_verify import JWT_SECRET

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
CHECKS = ["check_cron_health", "check_disk_space", "check_domain_health", "check_platform_health",
          "check_redis_aof_autofix", "check_tes_runnable"]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_selfcheck_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", CHECKS)
def test_token_passes_the_known_issues_write_permission(name, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", JWT_SECRET)
    header = _load(name)._admin_headers()["Authorization"]
    payload = require_permission("platform.manage_content")(authorization=header)
    assert payload["permissions"] == ["platform.manage_content"]        # least privilege, nothing else
    assert payload["type"] == "access"
    assert 0 < payload["exp"] - time.time() <= 300                       # short-lived


def test_the_old_roles_only_token_is_what_got_403():
    old = jwt.encode({"sub": "x-check", "roles": ["admin"]}, JWT_SECRET, algorithm="HS256")
    with pytest.raises(HTTPException) as e:
        require_permission("platform.manage_content")(authorization=f"Bearer {old}")
    assert e.value.status_code == 403


def test_every_check_script_is_covered():
    minting = sorted(p.stem for p in SCRIPTS.glob("check_*.py") if "jwt.encode(" in p.read_text())
    assert minting == sorted(CHECKS)


LOOKUPS = ["check_cron_health", "check_disk_space", "check_domain_health", "check_platform_health",
           "check_tes_runnable"]


@pytest.mark.parametrize("name", LOOKUPS)
def test_open_issue_lookup_is_authenticated(name, monkeypatch):
    """Anonymous GET /known-issues returns only public issues, so an unauthenticated lookup never
    finds the open issue: a new issue (and alert) every run and no auto-resolve (2026-11-25)."""
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("AUTH_SECRET_KEY", JWT_SECRET)
    module = _load(name)
    resp = MagicMock()
    resp.json.return_value = {"issues": []}
    with patch.object(module.requests, "get", return_value=resp) as get:
        if name == "check_tes_runnable":
            module._existing_open_issue()
        else:
            module._existing_open_issue("[marker]")
    header = get.call_args.kwargs["headers"]["Authorization"]
    assert require_permission("platform.manage_content")(authorization=header)["sub"]
