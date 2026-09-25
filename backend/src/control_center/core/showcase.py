"""Curated public showcase content for control.omnibioai.org.

Some of what makes a public dashboard credible cannot be measured by the
Control Center itself: benchmark results, example analyses, tool versions,
publications, the security controls summary. Those live in one reviewed
JSON file (SHOWCASE_PATH, default: showcase.json next to the Control Center
config) that the team edits by pull request; config/showcase.json in this
repository is the reviewed source.

The file is validated against a strict schema (unknown keys are rejected,
links must be https) before anything is served. An invalid or missing
file never breaks the page: every section simply comes back empty, and
the public response says only that the content is unavailable -- the
validation detail is logged for operators, not returned to anonymous
callers.

Two sections are filled from live sources when the file asks for them:
  - releases: the GitHub Releases of `releases_repo` (public API, cached
    for an hour) when the file lists no releases itself.
  - regression: a counts-and-date summary of the promoted regression
    certification artifact (regression_health.py) -- phase and capability
    statuses only, never findings text or evidence.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from control_center.regression_health import (
    RegressionHealthUnavailable,
    load_regression_health,
)

log = logging.getLogger("control_center.showcase")

_REPO_RE = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _https(value: str | None) -> str | None:
    if value is not None and not value.startswith("https://"):
        raise ValueError("links must be https:// URLs")
    return value


class Release(_Strict):
    version: str
    date: str | None = None
    url: str | None = None
    _check_url = field_validator("url")(_https)


class Benchmark(_Strict):
    pipeline: str
    dataset: str
    metrics: dict[str, float | str]
    date: str
    url: str | None = None
    _check_url = field_validator("url")(_https)


class ExampleRun(_Strict):
    title: str
    dataset: str
    description: str
    report_url: str | None = None
    inputs_url: str | None = None
    _check_urls = field_validator("report_url", "inputs_url")(_https)


class ToolVersion(_Strict):
    name: str
    version: str
    category: str | None = None


class Publication(_Strict):
    year: int
    title: str
    venue: str
    url: str | None = None
    _check_url = field_validator("url")(_https)


class TestEvidence(_Strict):
    suite: str
    date: str
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(default=0, ge=0)
    blocked: int = Field(default=0, ge=0)
    url: str | None = None
    _check_url = field_validator("url")(_https)


class RepoCoverage(_Strict):
    repo: str
    coverage_pct: float = Field(ge=0, le=100)
    date: str


class CiRepo(_Strict):
    repo: str = Field(pattern=_REPO_RE)
    workflow: str = Field(default="ci.yml", pattern=r"^[A-Za-z0-9_.-]+\.ya?ml$")
    label: str | None = None


class SecurityControl(_Strict):
    area: str
    status: Literal["implemented", "partial", "planned"]
    summary: str


class Limitation(_Strict):
    title: str
    detail: str
    url: str | None = None
    _check_url = field_validator("url")(_https)


class Showcase(_Strict):
    as_of: str | None = None
    releases_repo: str | None = Field(default=None, pattern=_REPO_RE)
    releases: list[Release] = []
    benchmarks: list[Benchmark] = []
    example_runs: list[ExampleRun] = []
    tool_versions: list[ToolVersion] = []
    publications: list[Publication] = []
    test_evidence: list[TestEvidence] = []
    repo_coverage: list[RepoCoverage] = []
    ci_repos: list[CiRepo] = []
    security_controls: list[SecurityControl] = []
    data_handling: list[str] = []
    limitations: list[Limitation] = []
    # {internal service name: public label} -- which services appear on the
    # public uptime bars, and under what name. Not returned by /showcase.
    uptime_services: dict[str, str] = {}


def showcase_path() -> Path:
    """SHOWCASE_PATH, else showcase.json next to the Control Center config
    (CONTROL_CENTER_CONFIG, mounted at /config in deployment)."""
    configured = os.environ.get("SHOWCASE_PATH")
    if configured:
        return Path(configured)
    config = os.environ.get("CONTROL_CENTER_CONFIG", "/config/control_center.yaml")
    return Path(config).parent / "showcase.json"


def load_showcase() -> tuple[Showcase, str | None]:
    """Return (content, error). On a missing/invalid file the content is
    empty and error names the problem for operators."""
    try:
        raw = json.loads(showcase_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Showcase(), "showcase file not found"
    except (OSError, ValueError) as exc:
        return Showcase(), f"showcase file unreadable: {type(exc).__name__}"
    try:
        return Showcase.model_validate(raw), None
    except ValidationError as exc:
        return Showcase(), f"showcase file invalid: {exc.error_count()} error(s): {exc.errors()[0]['loc']}"


# ── Live sources ─────────────────────────────────────────────────────────

_RELEASES_TTL_SECONDS = 3600
_releases_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def github_releases(repo: str, now: float | None = None) -> list[dict[str, Any]]:
    """Up to 10 published releases of a public repo, newest first. Cached
    for an hour; any failure returns the last cached value or []."""
    now = time.time() if now is None else now
    cached = _releases_cache.get(repo)
    if cached and now - cached[0] < _RELEASES_TTL_SECONDS:
        return cached[1]
    try:
        r = httpx.get(f"https://api.github.com/repos/{repo}/releases", params={"per_page": 10},
                      headers={"Accept": "application/vnd.github+json"}, timeout=5.0)
        r.raise_for_status()
        releases = [
            {"version": rel.get("name") or rel.get("tag_name"), "date": (rel.get("published_at") or "")[:10] or None,
             "url": rel.get("html_url")}
            for rel in r.json()
            if isinstance(rel, dict) and not rel.get("draft") and (rel.get("name") or rel.get("tag_name"))
        ]
    except (httpx.HTTPError, ValueError, TypeError):
        return cached[1] if cached else []
    _releases_cache[repo] = (now, releases)
    return releases


def regression_summary() -> dict[str, Any] | None:
    """Counts-and-date view of the promoted regression artifact, or None."""
    try:
        data = load_regression_health()
    except RegressionHealthUnavailable:
        return None
    capabilities = data.get("capabilities") or []
    counts: dict[str, int] = {}
    for cap in capabilities:
        status = str(cap.get("certification_status"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "generated_at": data.get("generated_at"),
        "freshness": (data.get("freshness") or {}).get("status"),
        "phases": {
            key: {"status": phase.get("status"), "certification_status": phase.get("certification_status")}
            for key, phase in sorted((data.get("phases") or {}).items())
        },
        "capabilities_total": len(capabilities),
        "capabilities_by_certification": counts,
    }


def public_showcase() -> dict[str, Any]:
    content, error = load_showcase()
    body = content.model_dump(exclude={"uptime_services", "releases_repo"})
    if not body["releases"] and content.releases_repo:
        body["releases"] = github_releases(content.releases_repo)
    body["regression"] = regression_summary()
    body["available"] = error is None
    if error:
        log.warning("showcase_unavailable", extra={"extra_fields": {"error": error}})
    return body
