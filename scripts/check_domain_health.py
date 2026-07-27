# omnibioai-control-center/scripts/check_domain_health.py

#!/usr/bin/env python3
"""
check_domain_health.py — Domain reachability + SSL cert expiry self-check.

Runs on the host via cron (same pattern as check_cron_health.py and
check_disk_space.py), not inside the control-center container. For each
production domain this ecosystem depends on, does a real TLS handshake
(no external service -- stdlib ssl/socket only) to read the live
certificate's expiry, then a real HTTPS GET to confirm the domain
actually responds (any HTTP status counts as reachable -- a 302 to a
login page is fine; a connection failure or DNS failure is not).
Files/updates/resolves a known_issues.json entry via the same admin API
the other two self-checks use, with the same dedup-on-resolve logic as
check_disk_space.py (an entry auto-resolves once the domain is reachable
again / the cert has been renewed, rather than piling up duplicates).

Domains checked -- confirmed live via real DNS + docker-compose CORS
config, not assumed from memory:
  - webstudio.omnibioai.org  current public web app (nginx-router.conf's
                             own comment: OAuth callback base domain)
  - control.omnibioai.org    public Control Center dashboard
  - app.omnibioai.org        old web domain pre-webstudio migration --
                             CHANGELOG.md claims this was "kept working
                             during the transition period", but it no
                             longer resolves at all (see live-validation
                             notes: this is a REAL unreachable domain,
                             not a hypothetical one)
  - omnibioai.org            apex/marketing domain
  - lims.omnibioai.org       present in every docker-compose*.yml's
                             CORS_ALLOWED_ORIGINS alongside the other 4 --
                             a real dependency even though it wasn't in
                             the original ask
  workbench.omnibioai.org resolves too (Cloudflare zone wildcard) but is
  explicitly marked "planned, not yet live" in README.md's roadmap, so
  it's deliberately excluded -- monitoring a not-yet-shipped domain would
  just be permanent noise.

nginx-router.conf itself has no `listen 443`/`ssl_certificate` blocks
(`server_name _` is a single catch-all on port 80) -- TLS for all 5
domains above is terminated at Cloudflare, in front of this repo, which
is exactly why this check talks to the real public hostnames over the
network rather than reading a certificate file on disk.

Cron (daily at 05:00):
  0 5 * * * python3 /home/manish/Desktop/machine/omnibioai-control-center/scripts/check_domain_health.py >> /home/manish/Desktop/machine/work/backups/omnibioai-domain-health.log 2>&1
"""

from __future__ import annotations

import http.client
import os
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

import jwt
import requests

CONTROL_CENTER_URL = os.environ.get("CONTROL_CENTER_URL", "http://127.0.0.1:7070")

# Same shared secret used by the other two self-checks.
STUDIO_ENV_PATH = Path("/home/manish/Desktop/machine/omnibioai-studio/.env")

# Overridable for live-validation test runs only -- production always
# uses the real 30/7-day defaults below.
WARNING_DAYS = int(os.environ.get("DOMAIN_WARNING_DAYS", "30"))
CRITICAL_DAYS = int(os.environ.get("DOMAIN_CRITICAL_DAYS", "7"))

CONNECT_TIMEOUT = 8

DOMAINS = [
    {"id": "webstudio", "domain": "webstudio.omnibioai.org", "label": "Web Studio (webstudio.omnibioai.org)"},
    {"id": "control", "domain": "control.omnibioai.org", "label": "Control Center dashboard (control.omnibioai.org)"},
    {"id": "app", "domain": "app.omnibioai.org", "label": "Legacy app domain (app.omnibioai.org)"},
    {"id": "apex", "domain": "omnibioai.org", "label": "Apex/marketing domain (omnibioai.org)"},
    {"id": "lims", "domain": "lims.omnibioai.org", "label": "LIMS (lims.omnibioai.org)"},
]


def _log(level: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{level}] {ts} {msg}", flush=True)


def _load_jwt_secret() -> str:
    env_override = os.environ.get("AUTH_SECRET_KEY") or os.environ.get("JWT_SECRET")
    if env_override:
        return env_override
    for line in STUDIO_ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("AUTH_SECRET_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"AUTH_SECRET_KEY not found in {STUDIO_ENV_PATH}")


def _admin_headers() -> dict:
    secret = _load_jwt_secret()
    token = jwt.encode({"sub": "domain-health-check", "roles": ["admin"]}, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _existing_open_issue(marker: str) -> dict | None:
    resp = requests.get(f"{CONTROL_CENTER_URL}/known-issues", timeout=10)
    resp.raise_for_status()
    for issue in resp.json().get("issues", []):
        if issue.get("title", "").startswith(marker) and issue.get("status") != "resolved":
            return issue
    return None


def _create_known_issue(title: str, description: str, severity: str) -> dict:
    resp = requests.post(
        f"{CONTROL_CENTER_URL}/known-issues",
        json={"title": title, "description": description, "severity": severity, "area": "Domains / SSL"},
        headers=_admin_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _update_known_issue(issue_id: str, **fields) -> dict:
    resp = requests.put(
        f"{CONTROL_CENTER_URL}/known-issues/{issue_id}",
        json=fields,
        headers=_admin_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _check_domain(domain: str) -> dict:
    """Real TLS handshake + real HTTPS GET, no external service. Returns
    reachable/http_status/days_until_expiry/not_after/error."""
    result: dict = {
        "reachable": False, "http_status": None,
        "days_until_expiry": None, "not_after": None, "error": None,
    }

    try:
        socket.getaddrinfo(domain, 443)
    except socket.gaierror as e:
        result["error"] = f"DNS resolution failed: {e}"
        return result

    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=CONNECT_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                result["not_after"] = not_after.isoformat()
                result["days_until_expiry"] = (not_after - datetime.now(timezone.utc)).days
    except (OSError, ssl.SSLError) as e:
        result["error"] = f"TLS connection failed: {e}"
        return result

    try:
        conn = http.client.HTTPSConnection(domain, 443, timeout=CONNECT_TIMEOUT, context=ssl.create_default_context())
        conn.request("GET", "/", headers={"User-Agent": "omnibioai-domain-health-check/1.0"})
        resp = conn.getresponse()
        result["http_status"] = resp.status
        result["reachable"] = True
        conn.close()
    except OSError as e:
        result["error"] = f"HTTPS request failed: {e}"

    return result


def _tier(check: dict) -> tuple[str, str] | None:
    """Returns (level, severity) or None if healthy. Unreachable always
    wins over cert expiry -- a domain that's down has no meaningful cert
    status to report on top of that."""
    if not check["reachable"]:
        return "UNREACHABLE", "high"
    days = check["days_until_expiry"]
    if days is None:
        return None
    if days <= CRITICAL_DAYS:
        return "CRITICAL", "high"
    if days <= WARNING_DAYS:
        return "WARNING", "medium"
    return None


def main() -> int:
    problems_found = 0

    for entry in DOMAINS:
        domain_id, domain, label = entry["id"], entry["domain"], entry["label"]
        check = _check_domain(domain)
        marker = f"[domain-health:{domain_id}]"
        existing = _existing_open_issue(marker)
        tier = _tier(check)

        if tier is None:
            if existing:
                _update_known_issue(
                    existing["id"],
                    status="resolved",
                    description=(
                        f"{existing.get('description', '')}\n\n"
                        f"Auto-resolved by domain-health-check: {domain} is reachable "
                        f"(HTTP {check['http_status']}) with {check['days_until_expiry']} days "
                        f"left on its cert (above the {WARNING_DAYS}-day warning threshold) as of "
                        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}."
                    ),
                )
                _log("ISSUE", f"{domain_id}: healthy again, resolved known-issue {existing['id']}")
            else:
                _log("INFO", f"{domain_id}: ok (HTTP {check['http_status']}, {check['days_until_expiry']}d until cert expiry)")
            continue

        level, severity = tier
        problems_found += 1
        # "ISSUE", never "ERROR" -- see check_cron_health.py's fix: this
        # job's own GET /cron/jobs last_status is a generic
        # case-insensitive substring("error") scan of this log's tail,
        # and correctly reporting a down domain is this job succeeding,
        # not failing. "ERROR" is reserved for this script's own crash.
        if level == "UNREACHABLE":
            detail = f"unreachable -- {check['error']}"
        else:
            detail = f"cert expires {check['not_after']} ({check['days_until_expiry']}d from now)"
        _log("ISSUE", f"{domain_id}: {level} -- {detail}")

        if level == "UNREACHABLE":
            title = f"{marker} {label} is unreachable"
            description = (
                f"Detected by the domain-health-check self-check. {label} ({domain}) failed a real "
                f"HTTPS connection attempt: {check['error']}. This is a live reachability failure, "
                f"not a certificate issue -- treated as high severity regardless of any prior cert status."
            )
        else:
            threshold = CRITICAL_DAYS if level == "CRITICAL" else WARNING_DAYS
            title = f"{marker} {label} cert expires in {check['days_until_expiry']}d ({level})"
            description = (
                f"Detected by the domain-health-check self-check. {label} ({domain})'s TLS certificate "
                f"expires {check['not_after']} ({check['days_until_expiry']} days from now), crossing the "
                f"{level.lower()} threshold ({threshold} days). Domain is still reachable (HTTP {check['http_status']})."
            )

        if existing:
            _update_known_issue(existing["id"], title=title, description=description, severity=severity)
            _log("ISSUE", f"{domain_id}: updated existing known-issue {existing['id']} (severity={severity})")
        else:
            issue = _create_known_issue(title, description, severity)
            _log("ISSUE", f"{domain_id}: filed known-issue {issue['id']} (severity={severity})")

    if problems_found:
        _log("ISSUE", f"domain-health-check: {problems_found} domain(s) unhealthy")
    else:
        _log("INFO", "domain-health-check: all domains healthy")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 -- cron captures stderr; any failure must be visible in the log, not silent
        _log("ERROR", f"domain-health-check crashed: {e}")
        sys.exit(1)
