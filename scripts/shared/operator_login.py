"""Ephemeral operator login for the report CLI; no credential cache or cookies."""

from __future__ import annotations

import getpass
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import warnings
from contextlib import contextmanager
from pathlib import Path

import yaml

from shared.health_fetch import ReportAuthenticationError, _admin_header, operator_access_token


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _trusted_url(url: str, *, internal: bool = False) -> str:
    """Require TLS except for loopback and the configured Compose IAM service."""
    parsed = urllib.parse.urlsplit(url)
    try:
        loopback = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        loopback = False
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.hostname or parsed.scheme not in ("https", "http")
            or (parsed.scheme == "http" and not loopback
                and not (internal and parsed.hostname == "auth-service" and Path("/.dockerenv").exists()))):
        raise ReportAuthenticationError(
            "IAM/report authentication requires a trusted HTTPS URL or a local loopback endpoint. "
            "Configure IAM_URL for this environment."
        )
    return url.rstrip("/")


def iam_url() -> str:
    """Reuse IAM_URL or Control Center's configured Auth service address."""
    configured = os.environ.get("IAM_URL", "").strip()
    if not configured:
        config_path = Path(os.environ.get(
            "CONTROL_CENTER_CONFIG",
            str(Path(__file__).resolve().parents[2] / "config" / "control_center.yaml"),
        ))
        try:
            config = yaml.safe_load(config_path.read_text())
            health_url = config["services"]["auth-service"]["url"]
            parts = urllib.parse.urlsplit(health_url)
            if parts.path.rstrip("/") != "/health":
                raise ValueError
            configured = urllib.parse.urlunsplit(parts._replace(path=""))
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
            raise ReportAuthenticationError("IAM URL unavailable. Configure IAM_URL or CONTROL_CENTER_CONFIG.") from None
    parts = urllib.parse.urlsplit(configured)
    # Compose publishes this service's port to the host. Do not use a LAN HTTP URL.
    if parts.hostname == "auth-service" and not Path("/.dockerenv").exists():
        configured = urllib.parse.urlunsplit(parts._replace(netloc=parts.netloc.replace("auth-service", "127.0.0.1", 1)))
    return _trusted_url(configured, internal=True)


def _request_json(url: str, payload: dict | None = None, *, headers: dict | None = None) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", "User-Agent": "omnibioai-report/1.0", **(headers or {})},
    )
    # No cookies, credential-bearing redirects, or ambient HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=10) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError
    return data


def _post_auth(url: str, payload: dict, *, mfa: bool = False) -> dict:
    try:
        return _request_json(url, payload)
    except urllib.error.HTTPError as error:
        if error.code == 401 or (mfa and error.code == 400):
            message = "MFA verification failed." if mfa else "Invalid IAM operator credentials (HTTP 401)."
        elif error.code == 403:
            message = "IAM login denied (HTTP 403). Complete required SSO or MFA enrollment through IAM."
        elif error.code == 429:
            message = "IAM authentication rate limited. Try again later."
        else:
            message = "IAM unavailable or authentication endpoint failed."
        raise ReportAuthenticationError(message) from None
    except (urllib.error.URLError, OSError):
        raise ReportAuthenticationError("IAM unavailable. Check IAM_URL and service connectivity.") from None
    except (ValueError, TypeError):
        raise ReportAuthenticationError("IAM returned an invalid authentication response.") from None


def _secret(prompt: str) -> str:
    # getpass's fallback echoes on some non-terminal streams; fail instead.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def login_operator() -> str:
    base = iam_url()
    print("→ Authentication required for protected report sections", flush=True)
    try:
        email = input("Email: ").strip()
        password = _secret("Password: ")
        data = _post_auth(f"{base}/auth/login", {"email": email, "password": password})
        del password
        if data.get("mfa_required") is True:
            challenge = data.get("challenge_token")
            if not isinstance(challenge, str) or not challenge:
                raise ReportAuthenticationError("IAM returned an invalid MFA challenge.")
            print("→ MFA required", flush=True)
            code = _secret("MFA code: ")
            data = _post_auth(f"{base}/users/me/mfa/challenge", {
                "challenge_token": challenge, "code": code,
            }, mfa=True)
            del code, challenge
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ReportAuthenticationError("IAM returned no user access token.")
        return access_token
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        raise ReportAuthenticationError("Operator login cancelled or secure terminal input unavailable.") from None


def _verify_infra_access(control_center_url: str) -> None:
    # The protected endpoint verifies signature, user sub, expiry, revocation and
    # platform.manage_infra. No local JWT decode or claim-based authorization.
    base = _trusted_url(control_center_url)
    try:
        _request_json(f"{base}/license", headers=_admin_header())
    except urllib.error.HTTPError as error:
        if error.code == 401:
            message = "/license: HTTP 401 authentication failure. IAM user access token rejected."
        elif error.code == 403:
            message = "/license: HTTP 403 insufficient permission. Authenticated user lacks platform.manage_infra."
        else:
            message = "/license endpoint unavailable or not implemented; operator authorization could not be verified."
        raise ReportAuthenticationError(message) from None
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        raise ReportAuthenticationError("/license unavailable; operator authorization could not be verified.") from None


@contextmanager
def operator_session(control_center_url: str):
    if os.environ.get("CONTROL_CENTER_ACCESS_TOKEN", "").strip():
        yield  # Existing environment-token path: no login or new preflight.
        return
    if not sys.stdin.isatty():
        raise ReportAuthenticationError(
            "CONTROL_CENTER_ACCESS_TOKEN is required for non-interactive report generation. "
            "Run in a terminal for IAM operator login, or supply a short-lived IAM-issued "
            "operator access token authorized for platform.manage_infra through the environment."
        )
    # Validate destination before prompting or sending credentials.
    _trusted_url(control_center_url)
    marker = operator_access_token.set(login_operator())
    try:
        _verify_infra_access(control_center_url)
        print("✓ Authenticated", flush=True)
        yield
    finally:
        operator_access_token.reset(marker)
