#!/usr/bin/env python3
"""
OmniBioAI Ecosystem Report — scripts/generate_report.py

Generates an interactive HTML report with five tabs:
  1. Architecture   — SVG lane diagram
  2. Projects       — Chart.js donut + horizontal bar + table
  3. Languages      — Chart.js donut + horizontal bar + table
  4. Code Coverage  — Chart.js bars + KPI cards + progress bars
  5. Health Status  — Live service + disk health from Control Center /summary

Usage
-----
# From the ecosystem root (all repos as siblings):
python omnibioai-control-center/scripts/generate_report.py

# With explicit options:
python omnibioai-control-center/scripts/generate_report.py \
    --root ~/Desktop/machine \
    --control-center-url http://127.0.0.1:7070 \
    --out out/reports/omnibioai_ecosystem_report.html

Output
------
<ecosystem_root>/out/reports/omnibioai_ecosystem_report.html
Also served at http://<control-center>/report after generation.

Dependencies
------------
pip install cloc pandas
pytest + pytest-cov (for coverage collection, best-effort)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd


# ==============================================================================
# Constants
# ==============================================================================

EXCLUDE_DIRS = (
    "obsolete,staticfiles,node_modules,.venv,env,__pycache__,migrations,node_modules"
    "admin,venv,gnn_env,venv_sys,work,input,demo,md"
)
EXCLUDE_EXTS = "svg,json,txt,csv,lock,min.js,map,pyc"
NOT_MATCH_D  = r"(data|uploads|downloads|cache|results|logs)"

DEFAULT_TARGETS = [
    "omnibioai-tes",
    "omnibioai",
    "omnibioai-rag",
    "omnibioai-lims",
    "omnibioai-toolserver",
    "omnibioai-tool-runtime",
    "omnibioai-control-center",
    "omnibioai-dev-docker",
    "omnibioai_sdk",
    "omnibioai-workflow-bundles",
    "omnibioai-model-registry",
    "omnibioai-tool-images",
    "omnibioai-studio",
    "omnibioai-dev-hub",
    "omnibioai-videos",
    "omnibioai-iam-client",
    "omnibioai-policy-engine",
    "omnibioai-security-audit",
    "omnibioai-security-sdk",
    "omnibioai-api-gateway",
    "omnibioai-hpc-policy-engine",
    "omnibioai-docs",
]

DEFAULT_OUT_RELPATH        = "out/reports/omnibioai_ecosystem_report.html"
DEFAULT_TITLE              = "OmniBioAI Ecosystem"
DEFAULT_CONTROL_CENTER_URL = "http://127.0.0.1:7070"

def _cov_source_args(cwd: Path) -> List[str]:
    text = _read_text_if_exists(cwd / "pyproject.toml")
    if text:
        m = re.search(r'\[tool\.coverage\.run\](.*?)(?=\n\[|\Z)', text, re.DOTALL)
        if m:
            sm = re.search(r'^source\s*=\s*\[([^\]]*)\]', m.group(1), re.MULTILINE)
            if sm:
                sources = re.findall(r'["\']([^"\']+)["\']', sm.group(1))
                if sources:
                    return [f"--cov={s}" for s in sources]
    text = _read_text_if_exists(cwd / ".coveragerc")
    if text:
        m = re.search(r'\[run\](.*?)(?=\n\[|\Z)', text, re.DOTALL)
        if m:
            sm = re.search(r'^source\s*=\s*(.+?)$', m.group(1), re.MULTILINE)
            if sm:
                sources = [s.strip() for s in sm.group(1).split(',') if s.strip()]
                if sources:
                    return [f"--cov={s}" for s in sources]
    if (cwd / "src").is_dir():
        return ["--cov=src"]
    return ["--cov=."]


def _coverage_cmd(cov_args: List[str], noconftest: bool = False) -> list:
    cmd = [
        sys.executable, "-m", "pytest",
        *cov_args,
        "--cov-report=term-missing", "--cov-report=json",
        "--tb=no", "-q",
        "-p", "no:cacheprovider",
        "--continue-on-collection-errors",
        "--ignore=node_modules",
    ]
    if noconftest:
        cmd.append("--noconftest")
    return cmd

_CHARTJS = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/'
    'Chart.js/4.4.1/chart.umd.js"></script>'
)
_PALETTE = [
    "#378ADD", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
    "#06B6D4", "#F97316", "#84CC16", "#EC4899", "#6366F1",
    "#14B8A6", "#A78BFA",
]


# ==============================================================================
# Data models
# ==============================================================================

@dataclass
class Totals:
    files:   int = 0
    blank:   int = 0
    comment: int = 0
    code:    int = 0

    def add(self, other: "Totals") -> None:
        self.files   += other.files
        self.blank   += other.blank
        self.comment += other.comment
        self.code    += other.code


@dataclass
class ServiceHealth:
    name:       str
    type:       str
    target:     str
    status:     str
    latency_ms: Optional[int]
    message:    str
    ui_url:     Optional[str] = None


@dataclass
class DiskHealth:
    name:    str
    target:  str
    status:  str
    message: str


@dataclass
class EcosystemHealth:
    overall_status: str
    generated_at:   str
    services: List[ServiceHealth] = field(default_factory=list)
    disk:     List[DiskHealth]    = field(default_factory=list)
    error:    Optional[str]       = None


# ==============================================================================
# Helpers
# ==============================================================================

def fmt_int(n: int) -> str:
    return f"{n:,}"

def safe_div(a: float, b: float) -> float:
    return (a / b) if b else 0.0

def _jsl(items: List[str]) -> str:
    return "[" + ",".join(json.dumps(s) for s in items) + "]"

def _jsn(items: List[Union[int, float]]) -> str:
    return "[" + ",".join(str(round(v, 2)) for v in items) + "]"


# ==============================================================================
# cloc
# ==============================================================================

def ensure_cloc() -> None:
    if shutil.which("cloc") is None:
        raise RuntimeError("cloc not found. Install: sudo apt-get install cloc")

def validate_paths(paths: List[Path]) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print("⚠ Repo paths not found (will show 'missing' in report):")
        for m in missing:
            print(f"  - {m}")


def _resolve_target_paths(root: Path, targets: List[str]) -> List[Path]:
    norm_map: Dict[str, Path] = {}
    if root.is_dir():
        for entry in root.iterdir():
            if entry.is_dir():
                norm_map[entry.name.lower().replace("-", "_")] = entry
    paths: List[Path] = []
    for name in targets:
        exact = root / name
        if exact.is_dir():
            paths.append(exact)
        else:
            norm_key = name.lower().replace("-", "_")
            resolved = norm_map.get(norm_key)
            if resolved is not None:
                print(f"  ↳ resolved '{name}' → '{resolved.name}'")
                paths.append(resolved)
            else:
                paths.append(exact)
    return paths

def run_cloc(path: Path) -> Tuple[Totals, Dict[str, Totals]]:
    cmd = [
        "cloc", str(path),
        "--exclude-dir", EXCLUDE_DIRS,
        "--exclude-ext", EXCLUDE_EXTS,
        "--fullpath", "--not-match-d", NOT_MATCH_D,
        "--force-lang", "Dockerfile,Dockerfile",
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cloc failed for {path}:\n{proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    if "SUM" not in data:
        raise RuntimeError(f"Unexpected cloc JSON for {path}.")
    s = data["SUM"]
    overall = Totals(
        files=int(s.get("nFiles", 0)), blank=int(s.get("blank", 0)),
        comment=int(s.get("comment", 0)), code=int(s.get("code", 0)),
    )
    per_lang: Dict[str, Totals] = {}
    for k, v in data.items():
        if k in ("header", "SUM"):
            continue
        if isinstance(v, dict) and "code" in v:
            per_lang[k] = Totals(
                files=int(v.get("nFiles", 0)), blank=int(v.get("blank", 0)),
                comment=int(v.get("comment", 0)), code=int(v.get("code", 0)),
            )
    return overall, per_lang


# ==============================================================================
# Coverage collection
# ==============================================================================

def _read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def _pytest_available() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def _has_pytest_project(repo: Path) -> bool:
    return (
        (repo / "pyproject.toml").exists()
        or (repo / "pytest.ini").exists()
        or (repo / "tests").exists()
        or (repo / "backend" / "pyproject.toml").exists()
    )


def _pytest_cwd(repo: Path) -> Path:
    if (repo / "backend" / "pyproject.toml").exists():
        return repo / "backend"
    return repo


def _subprocess_env(cwd: Path) -> dict:
    import os
    env = os.environ.copy()
    for cfg_path in [cwd / "pytest.ini", cwd / "setup.cfg",
                     cwd.parent / "pytest.ini", cwd.parent / "setup.cfg"]:
        if not cfg_path.exists():
            continue
        text = _read_text_if_exists(cfg_path)
        m = re.search(r"DJANGO_SETTINGS_MODULE\s*[=:]\s*(\S+)", text)
        if m:
            env.setdefault("DJANGO_SETTINGS_MODULE", m.group(1))
            break
    return env

def _extract_total_line(output: str) -> Optional[str]:
    for line in output.splitlines():
        if re.match(r"^\s*TOTAL\b", line):
            return line.strip()
    return None

def _parse_total_line(total_line: str) -> Dict[str, Any]:
    parts = re.split(r"\s+", total_line.strip())
    if not parts or parts[0] != "TOTAL":
        raise ValueError(f"Not a TOTAL line: {total_line}")
    nums = parts[1:]
    if len(nums) == 3:
        stmts, miss, cover = nums
        return {"statements": int(stmts), "missed": int(miss),
                "branches": None, "partial_branches": None,
                "coverage_pct": float(cover.rstrip("%"))}
    if len(nums) == 5:
        stmts, miss, branches, bpart, cover = nums
        return {"statements": int(stmts), "missed": int(miss),
                "branches": int(branches), "partial_branches": int(bpart),
                "coverage_pct": float(cover.rstrip("%"))}
    raise ValueError(f"Unexpected TOTAL format: {total_line}")

def _extract_fail_under(repo: Path) -> Optional[float]:
    text = (_read_text_if_exists(repo / "pyproject.toml")
            + "\n" + _read_text_if_exists(repo / "pytest.ini"))
    for pat in [r"--cov-fail-under[=\s]+([0-9]+(?:\.[0-9]+)?)",
                r"fail[_-]under\s*=\s*([0-9]+(?:\.[0-9]+)?)"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None

def _parse_coverage_json(cwd: Path) -> Optional[Dict[str, Any]]:
    cov_file = cwd / "coverage.json"
    if not cov_file.exists():
        return None
    try:
        data = json.loads(cov_file.read_text(encoding="utf-8"))
        totals = data.get("totals", {})
        pct    = totals.get("percent_covered")
        stmts  = totals.get("num_statements")
        missed = totals.get("missing_lines")
        if pct is None or stmts is None:
            return None
        return {
            "statements":       int(stmts),
            "missed":           int(missed or 0),
            "branches":         totals.get("num_partial_branches"),
            "partial_branches": None,
            "coverage_pct":     round(float(pct), 2),
        }
    except Exception:
        return None


def _classify_coverage_band(pct: Optional[float]) -> str:
    if pct is None: return "No data"
    if pct >= 95:   return "Excellent (>=95%)"
    if pct >= 85:   return "Good (85-94.99%)"
    return "Needs attention (<85%)"

def _stderr_tail(stderr: str, n: int = 10) -> Optional[str]:
    stderr = stderr.strip()
    return "\n".join(stderr.splitlines()[-n:]) if stderr else None

def _classify_status(rc, total_line, coverage_pct, fail_under, stdout, stderr) -> str:
    if total_line is None:  return "no_total_found"
    if rc == 0:             return "ok"
    combined = f"{stdout}\n{stderr}".lower()
    cov_fail  = ("required test coverage" in combined or "fail-under" in combined
                 or (fail_under is not None and coverage_pct is not None
                     and coverage_pct < fail_under))
    test_fail = (" failed" in combined
                 or "interrupted" in combined
                 or re.search(r"\b\d+ failed\b", combined) is not None)
    if cov_fail and test_fail: return "test_and_coverage_failure"
    if cov_fail:               return "coverage_threshold_failure"
    if test_fail:              return "test_failure"
    return "collection_errors"

def _load_precomputed(repo: Path, precomputed_dir: Path) -> Optional[Dict[str, Any]]:
    f = precomputed_dir / f"{repo.name}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        # Raw coverage.py JSON format (from pytest --cov-report=json) has a
        # "totals" key. Translate it into the pre-processed field names that
        # collect_coverage() expects.
        if "totals" in data and "coverage_pct" not in data:
            t = data["totals"]
            return {
                "coverage_pct":       t.get("percent_covered"),
                "statements":         t.get("num_statements"),
                "missed":             t.get("missing_lines"),
                "branches":           t.get("num_branches"),
                "partial_branches":   t.get("num_partial_branches"),
                "returncode":         0,
                "total_line":         None,
                "stderr_tail":        None,
            }
        return data
    except Exception:
        return None


def collect_coverage(
    target_paths: List[Path],
    precomputed_dir: Optional[Path] = None,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    if precomputed_dir and precomputed_dir.is_dir():
        print(f"  Using pre-computed coverage from {precomputed_dir}")

    pytest_ok = _pytest_available()
    if not pytest_ok and not (precomputed_dir and precomputed_dir.is_dir()):
        print("  ⚠ pytest not found in this Python environment — coverage skipped")

    for repo in target_paths:
        row: Dict[str, Any] = {
            "repo": repo.name, "path": str(repo), "status": "ok",
            "returncode": None, "statements": None, "missed": None,
            "branches": None, "partial_branches": None,
            "coverage_pct": None, "coverage_band": "No data",
            "fail_under": _extract_fail_under(repo),
            "total_line": None, "stderr_tail": None,
        }
        if not repo.exists():
            row["status"] = "missing_path"; rows.append(row); continue

        if precomputed_dir and precomputed_dir.is_dir():
            precomp = _load_precomputed(repo, precomputed_dir)
            if precomp is not None:
                for k in ("returncode", "statements", "missed", "branches",
                          "partial_branches", "coverage_pct", "total_line",
                          "stderr_tail"):
                    if k in precomp:
                        row[k] = precomp[k]
                if row["coverage_pct"] is not None:
                    row["coverage_band"] = _classify_coverage_band(row["coverage_pct"])
                    row["status"] = _classify_status(
                        row.get("returncode"), row.get("total_line"),
                        row["coverage_pct"], row["fail_under"],
                        precomp.get("stdout_tail") or "",
                        precomp.get("stderr_tail") or "",
                    )
                else:
                    row["status"] = precomp.get("status", "no_total_found")
                rows.append(row)
                continue

        if not pytest_ok:
            row["status"] = "skipped_no_pytest"; rows.append(row); continue
        if not _has_pytest_project(repo):
            row["status"] = "skipped_no_pytest_project"; rows.append(row); continue
        try:
            cwd = _pytest_cwd(repo)
            cov_args = _cov_source_args(cwd)
            env = _subprocess_env(cwd)

            def _run_and_parse(noconftest: bool) -> tuple:
                _proc = subprocess.run(
                    _coverage_cmd(cov_args=cov_args, noconftest=noconftest),
                    cwd=str(cwd), env=env,
                    capture_output=True, text=True, timeout=300,
                )
                _total = _extract_total_line(_proc.stdout)
                _cov   = None
                if not _total:
                    _cov = _parse_coverage_json(cwd)
                return _proc, _total, _cov

            proc, total_line, cov_data = _run_and_parse(noconftest=False)

            if total_line is None and cov_data is None:
                conftest_err = ("ImportError while loading conftest" in proc.stderr
                                or "ERROR while loading conftest" in proc.stderr
                                or "while loading conftest" in proc.stderr)
                if conftest_err:
                    proc, total_line, cov_data = _run_and_parse(noconftest=True)
                    if total_line or cov_data:
                        row["stderr_tail"] = ("conftest skipped (import error) — "
                                              + (row["stderr_tail"] or ""))

            row["returncode"] = proc.returncode
            if not row.get("stderr_tail"):
                row["stderr_tail"] = _stderr_tail(proc.stderr)

            if total_line and total_line != "json":
                row["total_line"] = total_line
                row.update(_parse_total_line(total_line))
            elif cov_data:
                row["total_line"] = "json"
                row.update(cov_data)

            if row["coverage_pct"] is not None:
                row["coverage_band"] = _classify_coverage_band(row["coverage_pct"])
                row["status"] = _classify_status(
                    proc.returncode, row["total_line"], row["coverage_pct"],
                    row["fail_under"], proc.stdout, proc.stderr)
            else:
                row["status"] = "no_total_found"
        except Exception as e:
            row["status"] = f"error: {e}"
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["coverage_pct", "repo"], ascending=[False, True],
                            na_position="last").reset_index(drop=True)
    return df


# ==============================================================================
# Health data — fetch from Control Center /summary
# ==============================================================================

def _parse_service(raw: Dict[str, Any]) -> ServiceHealth:
    return ServiceHealth(
        name=str(raw.get("name", "unknown")),
        type=str(raw.get("type", "unknown")),
        target=str(raw.get("target", "-")),
        status=str(raw.get("status", "DOWN")).upper(),
        ui_url=raw.get("ui_url") or None,
        latency_ms=raw.get("latency_ms"),
        message=str(raw.get("message", "")),
    )

def _parse_disk(raw: Dict[str, Any]) -> DiskHealth:
    return DiskHealth(
        name=str(raw.get("name", "disk")),
        target=str(raw.get("target", "-")),
        status=str(raw.get("status", "WARN")).upper(),
        message=str(raw.get("message", "")),
    )

def fetch_health(base_url: str, timeout_s: float = 5.0) -> EcosystemHealth:
    url = base_url.rstrip("/") + "/summary"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "omnibioai-report/0.1"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        services = [_parse_service(s) for s in (payload.get("services") or [])]
        disk_raw = (payload.get("system") or {}).get("disk") or []
        disk     = [_parse_disk(d) for d in disk_raw]
        return EcosystemHealth(
            overall_status=str(payload.get("overall_status", "WARN")).upper(),
            generated_at=str(payload.get("generated_at", "")),
            services=services,
            disk=disk,
        )
    except urllib.error.URLError as e:
        return EcosystemHealth(
            overall_status="UNREACHABLE", generated_at="",
            error=f"Control Center unreachable: {e.reason}")
    except Exception as e:
        return EcosystemHealth(
            overall_status="UNREACHABLE", generated_at="",
            error=f"{type(e).__name__}: {e}")


# ==============================================================================
# Architecture tab — improved wide SVG
# ==============================================================================

def architecture_section_html(
    project_totals: Dict[str, Totals],
    nodes_present: List[str],
) -> str:
    """
    Renders a full-width 1200px SVG architecture diagram with five lanes:
      Dev/Clients | Security Control Plane | Workbench | Services | Execution

    The security control plane lane is visually elevated (taller, red accent)
    to signal the zero-trust enforcement boundary.
    """

    def _loc(name: str) -> str:
        """Return 'X LOC' string for a repo, or empty string if not found."""
        t = project_totals.get(name, Totals())
        return f"{t.code:,} LOC" if t.code else ""

    def _node(nx: int, ny: int, nw: int, nh: int,
              fill: str, stroke: str, title: str, sub: str,
              onclick_query: str) -> str:
        cx = nx + nw // 2
        ty = ny + nh // 2 - 8
        sy = ny + nh // 2 + 10
        return (
            f'<g style="cursor:pointer" onclick="(function(){{var q={json.dumps(onclick_query)};'
            f'if(window.sendPrompt)window.sendPrompt(q);else window.open(\'https://github.com/man4ish/\'+q,\'_blank\')}})()">'
            f'<rect x="{nx}" y="{ny}" width="{nw}" height="{nh}" rx="8" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>'
            f'<text x="{cx}" y="{ty}" text-anchor="middle" '
            f'font-size="13" font-weight="600" font-family="IBM Plex Sans,Arial,sans-serif" '
            f'fill="{stroke}">{title}</text>'
            f'<text x="{cx}" y="{sy}" text-anchor="middle" '
            f'font-size="11" font-family="IBM Plex Sans,Arial,sans-serif" '
            f'fill="{stroke}" opacity="0.75">{sub}</text>'
            f'</g>'
        )

    def _line(x1, y1, x2, y2, color, width=2.0, dash="") -> str:
        dash_attr = f'stroke-dasharray="{dash}"' if dash else ""
        return (
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="{width}" {dash_attr} '
            f'marker-end="url(#arch-arrow)"/>'
        )

    def _path(d: str, color: str, width=0.8, dash="", opacity=1.0) -> str:
        dash_attr = f'stroke-dasharray="{dash}"' if dash else ""
        return (
            f'<path d="{d}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" {dash_attr} opacity="{opacity}" '
            f'marker-end="url(#arch-arrow)"/>'
        )

    # ── Lane geometry ──────────────────────────────────────────────────────────
    # viewBox: 1200 x 620
    # Lane x positions and widths
    L1_X, L1_W = 12,  196   # Dev / Clients
    L2_X, L2_W = 218, 220   # Security Control Plane (elevated)
    L3_X, L3_W = 448, 196   # Workbench
    L4_X, L4_W = 654, 220   # Services
    L5_X, L5_W = 884, 304   # Execution

    LANE_H    = 460
    SEC_H     = 490   # security lane is taller
    LANE_TOP  = 44
    SEC_TOP   = 30

    # Node geometry
    NW1 = L1_W - 24   # node width for dev lane
    NW2 = L2_W - 24   # security lane
    NW3 = L3_W - 24   # workbench
    NW4 = L4_W - 24   # services
    NW5 = L5_W - 24   # execution
    NH  = 52           # node height
    NP  = 16           # padding between nodes
    NY0 = 106          # first node y

    def nx(lx, lw, nw): return lx + (lw - nw) // 2

    # Row y positions
    rows = [NY0 + i * (NH + NP) for i in range(6)]

    # ── Color palette ──────────────────────────────────────────────────────────
    BLUE_FILL   = "#E6F1FB"; BLUE_STR   = "#185FA5"
    RED_FILL    = "#FCEBEB"; RED_STR    = "#A32D2D"
    TEAL_FILL   = "#E1F5EE"; TEAL_STR   = "#0F6E56"
    AMBER_FILL  = "#FAEEDA"; AMBER_STR  = "#854F0B"
    PURPLE_FILL = "#EEEDFE"; PURPLE_STR = "#3C3489"
    GRAY_STR    = "#6B7280"

    svg = f'''<svg width="100%" viewBox="0 0 1200 640"
  xmlns="http://www.w3.org/2000/svg"
  style="display:block;font-family:'IBM Plex Sans',Arial,sans-serif;">
<title>OmniBioAI Ecosystem Architecture</title>
<desc>Five-lane architecture: Dev/Clients, Security Control Plane (zero-trust boundary), Workbench, Services, Execution</desc>
<defs>
  <marker id="arch-arrow" viewBox="0 0 10 10" refX="8" refY="5"
    markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke"
      stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </marker>
</defs>

<!-- ═══════════════════════════════════════════════════════════════
     Lane backgrounds
═══════════════════════════════════════════════════════════════ -->

<!-- Dev / Clients -->
<rect x="{L1_X}" y="{LANE_TOP}" width="{L1_W}" height="{LANE_H}"
  rx="12" fill="{BLUE_FILL}" stroke="{BLUE_STR}" stroke-width="0.5" stroke-opacity="0.4"/>
<rect x="{L1_X}" y="{LANE_TOP}" width="{L1_W}" height="6" rx="3" fill="{BLUE_STR}" opacity="0.7"/>
<text x="{L1_X + L1_W//2}" y="72" text-anchor="middle"
  font-size="14" font-weight="600" fill="{BLUE_STR}">Dev / clients</text>

<!-- Security Control Plane — elevated, red accent, taller -->
<rect x="{L2_X}" y="{SEC_TOP}" width="{L2_W}" height="{SEC_H}"
  rx="12" fill="{RED_FILL}" stroke="{RED_STR}" stroke-width="1.2" stroke-opacity="0.7"/>
<rect x="{L2_X}" y="{SEC_TOP}" width="{L2_W}" height="7" rx="3" fill="{RED_STR}" opacity="0.85"/>
<text x="{L2_X + L2_W//2}" y="56" text-anchor="middle"
  font-size="14" font-weight="600" fill="{RED_STR}">🔐 Security control plane</text>
<text x="{L2_X + L2_W//2}" y="72" text-anchor="middle"
  font-size="11" fill="{RED_STR}" opacity="0.8">zero-trust boundary</text>

<!-- Workbench -->
<rect x="{L3_X}" y="{LANE_TOP}" width="{L3_W}" height="{LANE_H}"
  rx="12" fill="{TEAL_FILL}" stroke="{TEAL_STR}" stroke-width="0.5" stroke-opacity="0.4"/>
<rect x="{L3_X}" y="{LANE_TOP}" width="{L3_W}" height="6" rx="3" fill="{TEAL_STR}" opacity="0.7"/>
<text x="{L3_X + L3_W//2}" y="72" text-anchor="middle"
  font-size="14" font-weight="600" fill="{TEAL_STR}">Workbench</text>

<!-- Services -->
<rect x="{L4_X}" y="{LANE_TOP}" width="{L4_W}" height="{LANE_H}"
  rx="12" fill="{AMBER_FILL}" stroke="{AMBER_STR}" stroke-width="0.5" stroke-opacity="0.4"/>
<rect x="{L4_X}" y="{LANE_TOP}" width="{L4_W}" height="6" rx="3" fill="{AMBER_STR}" opacity="0.7"/>
<text x="{L4_X + L4_W//2}" y="72" text-anchor="middle"
  font-size="14" font-weight="600" fill="{AMBER_STR}">Services</text>

<!-- Execution -->
<rect x="{L5_X}" y="{LANE_TOP}" width="{L5_W}" height="{LANE_H}"
  rx="12" fill="{PURPLE_FILL}" stroke="{PURPLE_STR}" stroke-width="0.5" stroke-opacity="0.4"/>
<rect x="{L5_X}" y="{LANE_TOP}" width="{L5_W}" height="6" rx="3" fill="{PURPLE_STR}" opacity="0.7"/>
<text x="{L5_X + L5_W//2}" y="72" text-anchor="middle"
  font-size="14" font-weight="600" fill="{PURPLE_STR}">Execution</text>

<!-- ═══════════════════════════════════════════════════════════════
     Enforced request path label + arrows
═══════════════════════════════════════════════════════════════ -->
<text x="600" y="90" text-anchor="middle" font-size="11"
  fill="{RED_STR}" font-family="IBM Plex Sans,Arial,sans-serif">enforced request path →</text>
{_line(L1_X+L1_W+2,  96, L2_X-2,  96, RED_STR, 2.5)}
{_line(L2_X+L2_W+2,  96, L3_X-2,  96, RED_STR, 2.5)}
{_line(L3_X+L3_W+2,  96, L4_X-2,  96, RED_STR, 2.5)}
{_line(L4_X+L4_W+2,  96, L5_X-2,  96, RED_STR, 2.5)}

<!-- ═══════════════════════════════════════════════════════════════
     Dev / Clients nodes
═══════════════════════════════════════════════════════════════ -->
{_node(nx(L1_X,L1_W,NW1), rows[0], NW1, NH, BLUE_FILL, BLUE_STR,
       "studio", f"Electron · v0.2.0 · {_loc('omnibioai-studio')}",
       "omnibioai-studio")}
{_node(nx(L1_X,L1_W,NW1), rows[1], NW1, NH, BLUE_FILL, BLUE_STR,
       "dev-hub", f"knowledge graph · {_loc('omnibioai-dev-hub')}",
       "omnibioai-dev-hub")}
{_node(nx(L1_X,L1_W,NW1), rows[2], NW1, NH, BLUE_FILL, BLUE_STR,
       "sdk", f"Python SDK · :5190 · {_loc('omnibioai_sdk')}",
       "omnibioai_sdk")}
{_node(nx(L1_X,L1_W,NW1), rows[3], NW1, NH, BLUE_FILL, BLUE_STR,
       "iam-client", f"auth SDK · Redis cache · {_loc('omnibioai-iam-client')}",
       "omnibioai-iam-client")}
{_node(nx(L1_X,L1_W,NW1), rows[4], NW1, NH, BLUE_FILL, BLUE_STR,
       "security-sdk", f"policy client · decorator · {_loc('omnibioai-security-sdk')}",
       "omnibioai-security-sdk")}

<!-- ═══════════════════════════════════════════════════════════════
     Security Control Plane nodes
═══════════════════════════════════════════════════════════════ -->
{_node(nx(L2_X,L2_W,NW2), rows[0], NW2, NH, RED_FILL, RED_STR,
       "api-gateway", f":8080 · JWT · trace propagation · {_loc('omnibioai-api-gateway')}",
       "omnibioai-api-gateway")}
{_node(nx(L2_X,L2_W,NW2), rows[1], NW2, NH, RED_FILL, RED_STR,
       "auth-service", f":8001 · bcrypt · JWT · pub/sub · {_loc('omnibioai-auth')}",
       "omnibioai-auth")}
{_node(nx(L2_X,L2_W,NW2), rows[2], NW2, NH, RED_FILL, RED_STR,
       "policy-engine", f":8002 · RBAC/ABAC · Redis cache · {_loc('omnibioai-policy-engine')}",
       "omnibioai-policy-engine")}
{_node(nx(L2_X,L2_W,NW2), rows[3], NW2, NH, RED_FILL, RED_STR,
       "hpc-policy-engine", f":8003 · GPU/CPU quota · {_loc('omnibioai-hpc-policy-engine')}",
       "omnibioai-hpc-policy-engine")}
{_node(nx(L2_X,L2_W,NW2), rows[4], NW2, NH, RED_FILL, RED_STR,
       "security-audit", f":8004 · Redis streams · fail open · {_loc('omnibioai-security-audit')}",
       "omnibioai-security-audit")}

<!-- Fail policy note inside security lane -->
<text x="{L2_X + L2_W//2}" y="{rows[4] + NH + 22}" text-anchor="middle"
  font-size="10" fill="{RED_STR}" opacity="0.85"
  font-family="IBM Plex Sans,Arial,sans-serif">
  auth / policy / HPC → fail closed · audit → fail open
</text>

<!-- ═══════════════════════════════════════════════════════════════
     Workbench nodes
═══════════════════════════════════════════════════════════════ -->
{_node(nx(L3_X,L3_W,NW3), rows[0], NW3, NH, TEAL_FILL, TEAL_STR,
       "omnibioai", f"Django · 313k LOC · 80+ plugins",
       "omnibioai")}
{_node(nx(L3_X,L3_W,NW3), rows[1], NW3, NH, TEAL_FILL, TEAL_STR,
       "lims", f"lab data · Django · :7000 · {_loc('omnibioai-lims')}",
       "omnibioai-lims")}
{_node(nx(L3_X,L3_W,NW3), rows[2], NW3, NH, TEAL_FILL, TEAL_STR,
       "rag", f"PubMed · DeepSeek · :8090 · {_loc('omnibioai-rag')}",
       "omnibioai-rag")}
{_node(nx(L3_X,L3_W,NW3), rows[3], NW3, NH, TEAL_FILL, TEAL_STR,
       "workflow-bundles", f"WDL · Nextflow · CWL · {_loc('omnibioai-workflow-bundles')}",
       "omnibioai-workflow-bundles")}
{_node(nx(L3_X,L3_W,NW3), rows[4], NW3, NH, TEAL_FILL, TEAL_STR,
       "control-center", f"health · Docker imgs · :7070 · {_loc('omnibioai-control-center')}",
       "omnibioai-control-center")}

<!-- ═══════════════════════════════════════════════════════════════
     Services nodes
═══════════════════════════════════════════════════════════════ -->
{_node(nx(L4_X,L4_W,NW4), rows[0], NW4, NH, AMBER_FILL, AMBER_STR,
       "toolserver", f"FastAPI · bio tools · :9090 · {_loc('omnibioai-toolserver')}",
       "omnibioai-toolserver")}
{_node(nx(L4_X,L4_W,NW4), rows[1], NW4, NH, AMBER_FILL, AMBER_STR,
       "model-registry", f"ML versioning · MySQL · :8095 · {_loc('omnibioai-model-registry')}",
       "omnibioai-model-registry")}
{_node(nx(L4_X,L4_W,NW4), rows[2], NW4, NH, AMBER_FILL, AMBER_STR,
       "OPA", "Open Policy Agent · :8181",
       "OPA policy rules")}
{_node(nx(L4_X,L4_W,NW4), rows[3], NW4, NH, AMBER_FILL, AMBER_STR,
       "ollama", "local LLM · Llama/DeepSeek · :11434",
       "ollama local inference")}
{_node(nx(L4_X,L4_W,NW4), rows[4], NW4, NH, AMBER_FILL, AMBER_STR,
       "videos · sdk-launcher", "tutorials · :8086 · :5190",
       "omnibioai-videos")}

<!-- ═══════════════════════════════════════════════════════════════
     Execution nodes
═══════════════════════════════════════════════════════════════ -->
{_node(nx(L5_X,L5_W,NW5), rows[0], NW5, NH, PURPLE_FILL, PURPLE_STR,
       "tes", f"Slurm · AWS Batch · Azure · GCP · K8s · {_loc('omnibioai-tes')}",
       "omnibioai-tes")}
{_node(nx(L5_X,L5_W,NW5), rows[1], NW5, NH, PURPLE_FILL, PURPLE_STR,
       "tool-runtime", f"Docker · Singularity · GCS · S3 · {_loc('omnibioai-tool-runtime')}",
       "omnibioai-tool-runtime")}
{_node(nx(L5_X,L5_W,NW5), rows[2], NW5, NH, PURPLE_FILL, PURPLE_STR,
       "tool-images", f"80+ bio tools · ARM64 SIF · GHCR · {_loc('omnibioai-tool-images')}",
       "omnibioai-tool-images")}
{_node(nx(L5_X,L5_W,NW5), rows[3], NW5, NH, PURPLE_FILL, PURPLE_STR,
       "dev-docker", f"DGX · GPU dev environment · {_loc('omnibioai-dev-docker')}",
       "omnibioai-dev-docker")}

<!-- ═══════════════════════════════════════════════════════════════
     Internal connector lines
═══════════════════════════════════════════════════════════════ -->
<!-- iam-client → auth-service (dashed blue) -->
{_path(f"M{L1_X+L1_W} {rows[3]+NH//2} Q{L2_X-10} {rows[3]+NH//2} {L2_X-10} {rows[1]+NH//2} L{L2_X} {rows[1]+NH//2}",
       BLUE_STR, 0.8, "4 3")}
<!-- security-sdk → policy-engine (dashed blue) -->
{_path(f"M{L1_X+L1_W} {rows[4]+NH//2} Q{L2_X-20} {rows[4]+NH//2} {L2_X-20} {rows[2]+NH//2} L{L2_X} {rows[2]+NH//2}",
       BLUE_STR, 0.8, "4 3")}
<!-- policy-engine → OPA (dashed amber) -->
{_path(f"M{L2_X+L2_W} {rows[2]+NH//2} Q{L4_X-10} {rows[2]+NH//2} {L4_X} {rows[2]+NH//2}",
       AMBER_STR, 0.8, "4 3")}
<!-- Async audit arc -->
{_path(f"M{L2_X+L2_W//2} {rows[4]+NH+5} L{L2_X+L2_W//2} {rows[4]+NH+38} L{L3_X+L3_W//2} {rows[4]+NH+38} L{L3_X+L3_W//2} {rows[4]+NH+5}",
       RED_STR, 0.8, "4 3", 0.6)}
<text x="{(L2_X+L2_W//2 + L3_X+L3_W//2)//2}" y="{rows[4]+NH+54}"
  text-anchor="middle" font-size="10" fill="{RED_STR}" opacity="0.8"
  font-family="IBM Plex Sans,Arial,sans-serif">async audit (non-blocking)</text>
<!-- TES → tool-runtime → tool-images vertical -->
{_line(L5_X+L5_W//2, rows[0]+NH, L5_X+L5_W//2, rows[1], GRAY_STR, 0.8)}
{_line(L5_X+L5_W//2, rows[1]+NH, L5_X+L5_W//2, rows[2], GRAY_STR, 0.8)}

<!-- ═══════════════════════════════════════════════════════════════
     Stats strip
═══════════════════════════════════════════════════════════════ -->
<rect x="12" y="528" width="1176" height="58" rx="10"
  fill="white" stroke="#E5E7EB" stroke-width="0.5"/>
'''

    # Stats items: (x, value, label, color)
    stats = [
        (90,   "3,331",   "files",           "#374151"),
        (250,  "776,719", "total lines",     "#374151"),
        (420,  "576,457", "code lines",      "#374151"),
        (590,  "223",     "security tests",  "#374151"),
        (750,  "100%",    "test coverage",   "#3B6D11"),
        (910,  "20 / 20", "services healthy","#374151"),
        (1060, "v0.2.0",  "OmniBioAI Studio","#3C3489"),
        (1160, "zero-trust","JWT · RBAC · HPC","#A32D2D"),
    ]
    for sx, val, lbl, col in stats:
        svg += (
            f'<text x="{sx}" y="553" text-anchor="middle" font-size="14" '
            f'font-weight="600" fill="{col}" '
            f'font-family="IBM Plex Sans,Arial,sans-serif">{val}</text>'
            f'<text x="{sx}" y="574" text-anchor="middle" font-size="11" '
            f'fill="#9CA3AF" font-family="IBM Plex Sans,Arial,sans-serif">{lbl}</text>'
        )

    # Legend
    svg += f'''
<!-- ═══════════════════════════════════════════════════════════════
     Legend
═══════════════════════════════════════════════════════════════ -->
<line x1="20" y1="610" x2="60" y2="610" stroke="{RED_STR}" stroke-width="2.5"
  marker-end="url(#arch-arrow)"/>
<text x="68" y="614" font-size="11" fill="#374151"
  font-family="IBM Plex Sans,Arial,sans-serif">enforced request path</text>

<line x1="260" y1="610" x2="300" y2="610" stroke="{GRAY_STR}"
  stroke-width="0.8" stroke-dasharray="4 3" marker-end="url(#arch-arrow)"/>
<text x="308" y="614" font-size="11" fill="#374151"
  font-family="IBM Plex Sans,Arial,sans-serif">internal / async call</text>

<rect x="530" y="602" width="12" height="12" rx="2"
  fill="{RED_FILL}" stroke="{RED_STR}" stroke-width="1"/>
<text x="548" y="614" font-size="11" fill="#374151"
  font-family="IBM Plex Sans,Arial,sans-serif">zero-trust boundary</text>

<text x="900" y="614" font-size="11" fill="#9CA3AF"
  font-family="IBM Plex Sans,Arial,sans-serif">click any node to explore ↗</text>

</svg>'''

    return (
        f'<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;'
        f'padding:20px;overflow-x:auto;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:16px;flex-wrap:wrap;gap:10px;">'
        f'<div><div style="font-size:13px;font-weight:600;color:#111827;">'
        f'Architecture — OmniBioAI Ecosystem</div>'
        f'<div style="font-size:11px;color:#9CA3AF;margin-top:2px;">'
        f'Hover any node for metrics · click to explore</div></div>'
        f'</div>{svg}</div>'
    )


# ==============================================================================
# Shared table helper
# ==============================================================================

def _stats_table(rows: List[Dict[str, Any]], cols: List[str]) -> str:
    ths = "".join(
        f'<th style="padding:8px 12px;font-size:11px;font-weight:600;color:#9CA3AF;'
        f'background:#F8FAFC;border-bottom:1px solid #E5E7EB;white-space:nowrap;'
        f'text-transform:uppercase;letter-spacing:.04em;'
        f'text-align:{"left" if col in ("Project","Language") else "right"};">{col}</th>'
        for col in cols
    )
    body = ""
    for i, row in enumerate(rows):
        bg = "#F8FAFC" if i % 2 else "white"
        tds = ""
        for col in cols:
            val = row.get(col, "")
            align = "left" if col in ("Project", "Language") else "right"
            fmt = (f"{val:,}" if isinstance(val, int)
                   else f"{val:.2f}%" if col == "Code %" else str(val))
            tds += (f'<td style="padding:7px 12px;font-size:12px;color:#374151;'
                    f'text-align:{align};">{fmt}</td>')
        body += f'<tr style="background:{bg};">{tds}</tr>\n'
    return (f'<div style="overflow-x:auto;">'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div>')


# ==============================================================================
# Projects tab
# ==============================================================================

def projects_section_html(project_totals: Dict[str, Totals], grand: Totals) -> str:
    proj   = sorted(project_totals.items(), key=lambda kv: kv[1].code, reverse=True)
    labels = [k for k, _ in proj]
    values = [v.code for _, v in proj]
    colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(labels))]
    TOP    = 8
    dl = labels[:TOP] + (["Other"] if len(labels) > TOP else [])
    dv = values[:TOP] + ([sum(values[TOP:])] if len(labels) > TOP else [])
    dc = colors[:TOP] + (["#D1D5DB"] if len(labels) > TOP else [])
    bar_h  = max(260, len(labels) * 34 + 60)
    legend = "".join(
        f'<div style="display:flex;align-items:center;gap:6px;font-size:11px;'
        f'color:#374151;margin-bottom:4px;">'
        f'<span style="width:10px;height:10px;border-radius:2px;background:{c};'
        f'flex-shrink:0;display:inline-block;"></span>{l}</div>'
        for l, c in zip(dl, dc)
    )
    table_rows = [
        {"Project": name, "Files": t.files, "Blank": t.blank,
         "Comment": t.comment, "Code": t.code,
         "Code %": round(100.0 * safe_div(t.code, grand.code), 2)}
        for name, t in proj
    ]
    return f"""
<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.7fr);gap:14px;margin-bottom:14px;">
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;display:flex;flex-direction:column;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Share by project</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:14px;">Code lines</div>
    <div style="position:relative;width:180px;height:180px;margin:0 auto 16px;"><canvas id="proj-donut"></canvas></div>
    <div>{legend}</div>
  </div>
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Lines of code by project</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:14px;">Sorted by size</div>
    <div style="position:relative;width:100%;height:{bar_h}px;"><canvas id="proj-hbar"></canvas></div>
  </div>
</div>
<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;">
  <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Per-project totals</div>
  <div style="font-size:11px;color:#9CA3AF;margin-bottom:10px;">All repositories</div>
  {_stats_table(table_rows, ["Project","Files","Blank","Comment","Code","Code %"])}
</div>
<script data-tab="tab-proj">
registerChartInit('tab-proj', function(){{
  new Chart(document.getElementById('proj-donut'),{{type:'doughnut',
    data:{{labels:{_jsl(dl)},datasets:[{{data:{_jsn(dv)},backgroundColor:{_jsl(dc)},borderWidth:0,hoverOffset:4}}]}},
    options:{{responsive:true,maintainAspectRatio:false,cutout:'65%',
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(ctx){{
        var t=ctx.dataset.data.reduce(function(a,b){{return a+b;}},0);
        return ctx.label+': '+ctx.raw.toLocaleString()+' LOC ('+(ctx.raw/t*100).toFixed(1)+'%)';
      }}}}}}}}
    }}
  }});
  new Chart(document.getElementById('proj-hbar'),{{type:'bar',
    data:{{labels:{_jsl(labels)},datasets:[{{data:{_jsn(values)},backgroundColor:{_jsl(colors)},borderWidth:0,borderRadius:4}}]}},
    options:{{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(ctx){{return ctx.parsed.x.toLocaleString()+' LOC';}}}}}}}},
      scales:{{
        x:{{ticks:{{callback:function(v){{return v>=1000?(v/1000).toFixed(0)+'k':v;}},font:{{size:10}},color:'#9CA3AF'}},grid:{{color:'rgba(0,0,0,0.05)'}},border:{{display:false}}}},
        y:{{ticks:{{font:{{size:11}},color:'#374151'}},grid:{{display:false}},border:{{display:false}}}}
      }}
    }}
  }});
}});
</script>
"""


# ==============================================================================
# Languages tab
# ==============================================================================

def languages_section_html(language_totals: Dict[str, Totals], grand: Totals) -> str:
    langs  = sorted(language_totals.items(), key=lambda kv: kv[1].code, reverse=True)
    labels = [k for k, _ in langs]
    values = [v.code for _, v in langs]
    colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(labels))]
    TOP    = 8
    dl = labels[:TOP] + (["Other"] if len(labels) > TOP else [])
    dv = values[:TOP] + ([sum(values[TOP:])] if len(labels) > TOP else [])
    dc = colors[:TOP] + (["#D1D5DB"] if len(labels) > TOP else [])
    bl, bv, bc = labels[:20], values[:20], colors[:20]
    bar_h  = max(260, len(bl) * 30 + 60)
    legend = "".join(
        f'<div style="display:flex;align-items:center;gap:6px;font-size:11px;'
        f'color:#374151;margin-bottom:4px;">'
        f'<span style="width:10px;height:10px;border-radius:2px;background:{c};'
        f'flex-shrink:0;display:inline-block;"></span>{l}</div>'
        for l, c in zip(dl, dc)
    )
    table_rows = [
        {"Language": name, "Files": t.files, "Blank": t.blank,
         "Comment": t.comment, "Code": t.code,
         "Code %": round(100.0 * safe_div(t.code, grand.code), 2)}
        for name, t in langs
    ]
    return f"""
<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.7fr);gap:14px;margin-bottom:14px;">
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;display:flex;flex-direction:column;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Share by language</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:14px;">Top {TOP} + other</div>
    <div style="position:relative;width:180px;height:180px;margin:0 auto 16px;"><canvas id="lang-donut"></canvas></div>
    <div>{legend}</div>
  </div>
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Lines of code by language</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:14px;">Top 20 languages</div>
    <div style="position:relative;width:100%;height:{bar_h}px;"><canvas id="lang-hbar"></canvas></div>
  </div>
</div>
<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;">
  <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Language totals</div>
  <div style="font-size:11px;color:#9CA3AF;margin-bottom:10px;">All detected languages</div>
  {_stats_table(table_rows, ["Language","Files","Blank","Comment","Code","Code %"])}
</div>
<script>
registerChartInit('tab-lang', function(){{
  new Chart(document.getElementById('lang-donut'),{{type:'doughnut',
    data:{{labels:{_jsl(dl)},datasets:[{{data:{_jsn(dv)},backgroundColor:{_jsl(dc)},borderWidth:0,hoverOffset:4}}]}},
    options:{{responsive:true,maintainAspectRatio:false,cutout:'65%',
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(ctx){{
        var t=ctx.dataset.data.reduce(function(a,b){{return a+b;}},0);
        return ctx.label+': '+ctx.raw.toLocaleString()+' LOC ('+(ctx.raw/t*100).toFixed(1)+'%)';
      }}}}}}}}
    }}
  }});
  new Chart(document.getElementById('lang-hbar'),{{type:'bar',
    data:{{labels:{_jsl(bl)},datasets:[{{data:{_jsn(bv)},backgroundColor:{_jsl(bc)},borderWidth:0,borderRadius:4}}]}},
    options:{{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(ctx){{return ctx.parsed.x.toLocaleString()+' LOC';}}}}}}}},
      scales:{{
        x:{{ticks:{{callback:function(v){{return v>=1000?(v/1000).toFixed(0)+'k':v;}},font:{{size:10}},color:'#9CA3AF'}},grid:{{color:'rgba(0,0,0,0.05)'}},border:{{display:false}}}},
        y:{{ticks:{{font:{{size:11}},color:'#374151'}},grid:{{display:false}},border:{{display:false}}}}
      }}
    }}
  }});
}});
</script>
"""


# ==============================================================================
# Coverage tab
# ==============================================================================

def _cov_color(pct: Optional[float]) -> str:
    if pct is None: return "#B4B2A9"
    return "#639922" if pct >= 95 else ("#BA7517" if pct >= 85 else "#E24B4A")

def _badge(status: str) -> Tuple[str, str]:
    if status == "ok":
        return "badge-green", "ok"
    _gray_map = {
        "skipped_no_pytest_project": "no tests",
        "skipped_no_pytest":         "no pytest",
        "missing_path":              "missing",
        "no_total_found":            "no total",
    }
    if status in _gray_map or any(x in status for x in ("skipped", "missing", "no_total")):
        return "badge-gray", _gray_map.get(status, status)
    if status.startswith("error:"):
        return "badge-amber", "error"
    _amber_map = {
        "test_failure":                "test failure",
        "coverage_threshold_failure":  "cov threshold",
        "test_and_coverage_failure":   "test + cov",
        "collection_errors":           "partial (import errs)",
    }
    return "badge-amber", _amber_map.get(status, status)

def coverage_section_html(df: pd.DataFrame, timestamp: str) -> str:
    valid       = df[df["coverage_pct"].notna()].copy()
    total_repos = len(df)
    covered     = len(valid)
    skipped     = int(df["status"].str.contains("skipped", na=False).sum())
    avg_cov     = float(valid["coverage_pct"].mean()) if covered else 0.0
    excellent   = int((valid["coverage_pct"] >= 95).sum()) if covered else 0
    below_85    = int((valid["coverage_pct"] < 85).sum())  if covered else 0
    good_count  = int(valid["coverage_pct"].between(85, 95, inclusive="left").sum())
    no_data_cnt = total_repos - covered

    wd  = valid.sort_values("coverage_pct", ascending=False)
    bl  = [r.replace("omnibioai-","…-").replace("omnibioai_","…_") for r in wd["repo"].tolist()]
    bp  = [round(float(v),2) for v in wd["coverage_pct"].tolist()]
    bfg = [_cov_color(v)+"CC" for v in wd["coverage_pct"].tolist()]
    bbr = [_cov_color(v) for v in wd["coverage_pct"].tolist()]
    bst = [int(v) if v==v and v is not None else "null" for v in wd["statements"].tolist()]
    bmi = [int(v) if v==v and v is not None else "null" for v in wd["missed"].tolist()]
    ms  = valid.sort_values("missed", ascending=False, na_position="last")
    ml  = [r.replace("omnibioai-","…-").replace("omnibioai_","…_") for r in ms["repo"].tolist()]
    mv  = [int(v) if v==v else 0 for v in ms["missed"].fillna(0).tolist()]
    mfg = [_cov_color(v)+"BB" for v in ms["coverage_pct"].tolist()]
    mbr = [_cov_color(v) for v in ms["coverage_pct"].tolist()]
    mpt = [round(float(v),2) for v in ms["coverage_pct"].tolist()]

    def _f(v: Any) -> str:
        if v is None or (isinstance(v, float) and v != v): return "—"
        try: return f"{int(v):,}"
        except Exception: return str(v)

    table_rows = ""
    for i, (_, row) in enumerate(df.iterrows()):
        pct    = row.get("coverage_pct")
        status = str(row.get("status",""))
        bg     = "#F8FAFC" if i % 2 else "white"
        bc, bl2 = _badge(status)
        pct_html = "—"
        if pct is not None and pct == pct:
            c = _cov_color(pct)
            pct_html = (
                f'<div style="font-size:12px;font-weight:500;color:{c};">{float(pct):.2f}%</div>'
                f'<div style="height:4px;background:#E5E7EB;border-radius:99px;margin-top:3px;overflow:hidden;">'
                f'<div style="height:100%;width:{float(pct):.1f}%;background:{c};border-radius:99px;"></div></div>'
            )
        table_rows += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:7px 12px;font-size:12px;font-weight:500;color:#111827;white-space:nowrap;">{row.get("repo","")}</td>'
            f'<td style="padding:7px 12px;"><span class="cov-badge {bc}">{bl2}</span></td>'
            f'<td style="padding:7px 12px;min-width:120px;">{pct_html}</td>'
            f'<td style="padding:7px 12px;font-size:12px;color:#6B7280;text-align:right;">{_f(row.get("statements"))}</td>'
            f'<td style="padding:7px 12px;font-size:12px;color:#6B7280;text-align:right;">{_f(row.get("missed"))}</td>'
            f'<td style="padding:7px 12px;font-size:12px;color:#6B7280;text-align:right;">{_f(row.get("branches"))}</td>'
            f'<td style="padding:7px 12px;font-size:12px;color:#6B7280;text-align:right;">{_f(row.get("fail_under"))}</td>'
            f'</tr>'
        )

    def _kpi(accent, label, value, sub):
        return (
            f'<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;'
            f'padding:16px 18px 14px;position:relative;overflow:hidden;">'
            f'<div style="position:absolute;top:0;left:0;right:0;height:3px;background:{accent};'
            f'border-radius:12px 12px 0 0;"></div>'
            f'<div style="font-size:11px;color:#9CA3AF;text-transform:uppercase;letter-spacing:.06em;'
            f'margin-bottom:8px;">{label}</div>'
            f'<div style="font-size:26px;font-weight:700;color:#0F172A;line-height:1;margin-bottom:4px;">{value}</div>'
            f'<div style="font-size:11px;color:#9CA3AF;">{sub}</div></div>'
        )

    return f"""
<style>
  .cov-badge {{display:inline-flex;align-items:center;padding:2px 8px;border-radius:99px;font-size:10px;font-weight:600;white-space:nowrap;}}
  .badge-green {{background:#EAF3DE;color:#3B6D11;}}
  .badge-amber {{background:#FAEEDA;color:#854F0B;}}
  .badge-gray  {{background:#F1F5F9;color:#64748B;}}
</style>
<div style="font-size:12px;color:#9CA3AF;margin-bottom:20px;">Best-effort pytest collection · {timestamp}</div>
<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-bottom:24px;">
  {_kpi("#D1D5DB","Repos scanned",str(total_repos),"full ecosystem")}
  {_kpi("#378ADD","With data",str(covered),f"{skipped} skipped")}
  {_kpi("#639922","Average coverage",f"{avg_cov:.2f}%",f"across {covered} repos")}
  {_kpi("#639922","Repos &ge; 95%",str(excellent),"excellent band")}
  {_kpi("#E24B4A","Repos &lt; 85%",str(below_85),"needs attention")}
</div>
<div style="display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:14px;margin-bottom:14px;">
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Coverage by repository</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:14px;">Y-axis from 80%</div>
    <div style="position:relative;width:100%;height:260px;"><canvas id="cov-bar"></canvas></div>
  </div>
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Missed lines</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:14px;">Lower is better</div>
    <div style="position:relative;width:100%;height:260px;"><canvas id="cov-missed"></canvas></div>
  </div>
</div>
<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,0.42fr);gap:14px;">
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Coverage summary</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:10px;">All repos · status · thresholds</div>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr>
          {"".join(f'<th style="padding:8px 12px;font-size:11px;font-weight:600;color:#9CA3AF;background:#F8FAFC;border-bottom:1px solid #E5E7EB;text-transform:uppercase;letter-spacing:.04em;text-align:{a};">{h}</th>' for h,a in [("Repo","left"),("Status","left"),("Coverage","left"),("Statements","right"),("Missed","right"),("Branches","right"),("Fail under","right")])}
        </tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
  </div>
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;display:flex;flex-direction:column;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:3px;">Band distribution</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:12px;">Repos per band</div>
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;">
      <div style="position:relative;width:150px;height:150px;margin-bottom:20px;">
        <canvas id="cov-donut"></canvas>
        <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;pointer-events:none;">
          <div style="font-size:22px;font-weight:700;color:#0F172A;line-height:1;">{covered}</div>
          <div style="font-size:10px;color:#9CA3AF;margin-top:2px;">repos</div>
        </div>
      </div>
      <div style="width:100%;">
        {"".join(f'<div style="display:flex;align-items:center;gap:8px;font-size:12px;color:#6B7280;margin-bottom:8px;"><span style="width:10px;height:10px;border-radius:2px;background:{c};flex-shrink:0;display:inline-block;"></span><span>{lbl}</span><span style="margin-left:auto;font-weight:700;color:#0F172A;">{cnt}</span></div>' for c,lbl,cnt in [("#639922","Excellent &ge;95%",excellent),("#BA7517","Good 85–94.99%",good_count),("#E24B4A","Needs attention",below_85),("#B4B2A9","No data",no_data_cnt)])}
      </div>
    </div>
  </div>
</div>
<script>
(function(){{
  new Chart(document.getElementById('cov-bar'),{{type:'bar',
    data:{{labels:{json.dumps(bl)},datasets:[{{data:{json.dumps(bp)},backgroundColor:{json.dumps(bfg)},borderColor:{json.dumps(bbr)},borderWidth:1,borderRadius:4,borderSkipped:false}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(ctx){{var i=ctx.dataIndex;return[ctx.parsed.y.toFixed(2)+'%','Stmts: '+({json.dumps(bst)}[i]!==null?{json.dumps(bst)}[i].toLocaleString():'—'),'Missed: '+({json.dumps(bmi)}[i]!==null?{json.dumps(bmi)}[i].toLocaleString():'—')];}}}}}}}},
      scales:{{y:{{min:80,max:102,ticks:{{callback:function(v){{return v+'%';}},font:{{size:11}},color:'#9CA3AF'}},grid:{{color:'rgba(0,0,0,0.05)'}},border:{{display:false}}}},x:{{ticks:{{font:{{size:10}},color:'#9CA3AF',maxRotation:35,autoSkip:false}},grid:{{display:false}},border:{{display:false}}}}}}
    }}
  }});
  new Chart(document.getElementById('cov-missed'),{{type:'bar',
    data:{{labels:{json.dumps(ml)},datasets:[{{data:{json.dumps(mv)},backgroundColor:{json.dumps(mfg)},borderColor:{json.dumps(mbr)},borderWidth:1,borderRadius:4,borderSkipped:false}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(ctx){{var i=ctx.dataIndex;return['Missed: '+ctx.parsed.y.toLocaleString(),'Coverage: '+{json.dumps(mpt)}[i].toFixed(2)+'%'];}}}}}}}},
      scales:{{y:{{ticks:{{callback:function(v){{return v>=1000?(v/1000).toFixed(1)+'k':v;}},font:{{size:11}},color:'#9CA3AF'}},grid:{{color:'rgba(0,0,0,0.05)'}},border:{{display:false}}}},x:{{ticks:{{font:{{size:10}},color:'#9CA3AF',maxRotation:35,autoSkip:false}},grid:{{display:false}},border:{{display:false}}}}}}
    }}
  }});
  new Chart(document.getElementById('cov-donut'),{{type:'doughnut',
    data:{{labels:['Excellent \u226595%','Good 85\u201394.99%','Needs attention','No data'],datasets:[{{data:[{excellent},{good_count},{below_85},{no_data_cnt}],backgroundColor:['#639922','#BA7517','#E24B4A','#B4B2A9'],borderWidth:0,hoverOffset:4}}]}},
    options:{{responsive:true,maintainAspectRatio:false,cutout:'68%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(ctx){{return ctx.label+': '+ctx.raw+' repos';}}}}}}}}}}
  }});
}})();
</script>
"""


# ==============================================================================
# Health Status tab
# ==============================================================================

def _status_pill(status: str) -> str:
    cfg = {
        "UP":          ("background:#EAF3DE;color:#3B6D11;", "UP"),
        "DOWN":        ("background:#FCEBEB;color:#A32D2D;", "DOWN"),
        "WARN":        ("background:#FAEEDA;color:#854F0B;", "WARN"),
        "UNREACHABLE": ("background:#F1F5F9;color:#64748B;", "UNREACHABLE"),
    }
    style, label = cfg.get(status.upper(), ("background:#F1F5F9;color:#64748B;", status))
    return (f'<span style="display:inline-flex;align-items:center;padding:3px 10px;'
            f'border-radius:99px;font-size:11px;font-weight:600;{style}">{label}</span>')

def _overall_banner(status: str) -> str:
    cfg = {
        "UP":          ("#ECFDF5", "#10B981", "#065F46", "All systems operational"),
        "DOWN":        ("#FEF2F2", "#EF4444", "#7F1D1D", "One or more services are down"),
        "WARN":        ("#FFFBEB", "#F59E0B", "#78350F", "One or more services need attention"),
        "UNREACHABLE": ("#F8FAFC", "#94A3B8", "#1E293B", "Control Center unreachable"),
    }
    bg, accent, text, msg = cfg.get(status.upper(),
        ("#F8FAFC", "#94A3B8", "#1E293B", status))
    return (
        f'<div style="background:{bg};border:1px solid {accent}33;border-radius:12px;'
        f'padding:16px 20px;margin-bottom:20px;display:flex;align-items:center;gap:14px;">'
        f'<div style="width:10px;height:10px;border-radius:50%;background:{accent};flex-shrink:0;"></div>'
        f'<div>'
        f'<div style="font-size:14px;font-weight:600;color:{text};">{msg}</div>'
        f'<div style="font-size:11px;color:{accent};margin-top:2px;">Overall status: {status}</div>'
        f'</div></div>'
    )

def health_section_html(health: EcosystemHealth) -> str:
    if health.overall_status == "UNREACHABLE" or health.error:
        return f"""
{_overall_banner("UNREACHABLE")}
<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:24px;text-align:center;">
  <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px;">
    Control Center API is not reachable</div>
  <div style="font-size:12px;color:#9CA3AF;margin-bottom:16px;">
    Start the Control Center and regenerate the report to see live health data.
  </div>
  <code style="display:block;background:#F8FAFC;border:1px solid #E5E7EB;border-radius:8px;
               padding:12px 16px;font-size:12px;color:#374151;text-align:left;">
    {health.error or "Connection refused"}
  </code>
</div>
"""

    total_svc  = len(health.services)
    up_count   = sum(1 for s in health.services if s.status == "UP")
    down_count = sum(1 for s in health.services if s.status == "DOWN")
    warn_count = sum(1 for s in health.services if s.status == "WARN")
    disk_warn  = sum(1 for d in health.disk if d.status != "UP")
    checked_at = health.generated_at or "unknown"

    def _kpi(accent, label, value, sub):
        return (
            f'<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;'
            f'padding:16px 18px 14px;position:relative;overflow:hidden;">'
            f'<div style="position:absolute;top:0;left:0;right:0;height:3px;background:{accent};'
            f'border-radius:12px 12px 0 0;"></div>'
            f'<div style="font-size:11px;color:#9CA3AF;text-transform:uppercase;letter-spacing:.06em;'
            f'margin-bottom:8px;">{label}</div>'
            f'<div style="font-size:26px;font-weight:700;color:#0F172A;line-height:1;margin-bottom:4px;">{value}</div>'
            f'<div style="font-size:11px;color:#9CA3AF;">{sub}</div></div>'
        )

    kpis = (
        _kpi("#D1D5DB", "Services",   str(total_svc),  "monitored")
        + _kpi("#10B981", "Healthy",  str(up_count),   "UP")
        + _kpi("#EF4444", "Down",     str(down_count), "need attention")
        + _kpi("#F59E0B", "Degraded", str(warn_count), "WARN")
        + _kpi("#F59E0B" if disk_warn else "#10B981",
               "Disk warnings", str(disk_warn), "paths checked")
    )

    donut_data   = [up_count, down_count, warn_count]
    donut_colors = '["#10B981","#EF4444","#F59E0B"]'
    donut_labels = '["UP","DOWN","WARN"]'
    lat_labels   = ",".join(f'"{s.name}"' for s in health.services if s.latency_ms is not None)
    lat_data     = ",".join(str(s.latency_ms) for s in health.services if s.latency_ms is not None)

    SERVICE_ICONS = {
        "mysql": ("🗄️", "#3B82F6"),
        "redis": ("⚡", "#EF4444"),
        "http":  ("🌐", "#10B981"),
        "tcp":   ("🔌", "#8B5CF6"),
    }

    def _svc_card(s: ServiceHealth) -> str:
        latency = f"{s.latency_ms} ms" if s.latency_ms is not None else "—"
        icon, _ = SERVICE_ICONS.get(s.type.lower(), ("⚙️", "#6B7280"))
        border  = {"UP": "#10B981", "DOWN": "#EF4444", "WARN": "#F59E0B"}.get(s.status, "#E5E7EB")
        bg      = {"UP": "#F0FDF4", "DOWN": "#FEF2F2", "WARN": "#FFFBEB"}.get(s.status, "white")
        lat_col = "#10B981" if s.latency_ms is not None and s.latency_ms < 10 else "#6B7280"
        ui_btn  = (
            f'<a href="{s.ui_url}" target="_blank" style="'
            f'display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;'
            f'color:#2563EB;background:#EFF6FF;border:1px solid #BFDBFE;'
            f'border-radius:6px;padding:4px 10px;text-decoration:none;margin-top:10px;">'
            f'Open UI &#8599;</a>'
        ) if s.ui_url else ""
        return (
            f'<div style="background:{bg};border:1.5px solid {border}33;'
            f'border-left:4px solid {border};border-radius:12px;padding:16px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<span style="font-size:20px;">{icon}</span>'
            f'<span style="font-size:14px;font-weight:700;color:#111827;">{s.name}</span>'
            f'</div>{_status_pill(s.status)}</div>'
            f'<div style="font-size:11px;color:#6B7280;display:grid;'
            f'grid-template-columns:80px 1fr;gap:4px 8px;">'
            f'<span style="color:#9CA3AF;">Target</span>'
            f'<span style="word-break:break-all;font-family:monospace;font-size:10px;">{s.target}</span>'
            f'<span style="color:#9CA3AF;">Latency</span>'
            f'<span style="color:{lat_col};font-weight:600;">{latency}</span>'
            f'<span style="color:#9CA3AF;">Message</span>'
            f'<span>{s.message or "—"}</span>'
            f'</div>{ui_btn}</div>'
        )

    svc_cards = "".join(_svc_card(s) for s in health.services)

    def _disk_bar(d: DiskHealth) -> str:
        import re as _re
        m = _re.search(r"([0-9.]+)%", d.message or "")
        pct       = float(m.group(1)) if m else 0
        bar_color = {"UP": "#10B981", "WARN": "#F59E0B", "DOWN": "#EF4444"}.get(d.status, "#9CA3AF")
        border    = {"UP": "#D1FAE5", "WARN": "#FEF3C7", "DOWN": "#FEE2E2"}.get(d.status, "#E5E7EB")
        return (
            f'<div style="background:white;border:1px solid {border};border-radius:12px;padding:16px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
            f'<div style="font-size:13px;font-weight:600;color:#111827;">'
            f'{d.name.replace("disk:","")}</div>'
            f'<div style="font-size:13px;font-weight:700;color:{bar_color};">{d.message}</div>'
            f'</div>'
            f'<div style="font-size:10px;color:#9CA3AF;margin-bottom:8px;">{d.target}</div>'
            f'<div style="background:#F3F4F6;border-radius:99px;height:6px;overflow:hidden;">'
            f'<div style="width:{pct:.1f}%;height:100%;background:{bar_color};border-radius:99px;"></div>'
            f'</div></div>'
        )

    disk_section = ""
    if health.disk:
        disk_bars = "".join(_disk_bar(d) for d in health.disk)
        disk_section = f"""
<div style="margin-top:24px;">
  <div style="font-size:12px;font-weight:600;color:#9CA3AF;text-transform:uppercase;
              letter-spacing:.06em;margin-bottom:12px;">Disk Checks</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;">
    {disk_bars}
  </div>
</div>"""

    return f"""
{_overall_banner(health.overall_status)}
<div style="font-size:12px;color:#9CA3AF;margin-bottom:20px;">
  Checked: <strong style="color:#374151;">{checked_at}</strong>
  &nbsp;&middot;&nbsp; Source: Control Center
  <code style="font-size:11px;background:#F8FAFC;padding:1px 5px;border-radius:4px;">/summary</code>
</div>
<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-bottom:24px;">
  {kpis}
</div>
<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;margin-bottom:24px;">
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:20px;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:4px;">Service Health</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:16px;">Status distribution</div>
    <div style="display:flex;align-items:center;gap:24px;">
      <div style="position:relative;width:120px;height:120px;flex-shrink:0;">
        <canvas id="health-donut" width="120" height="120"></canvas>
        <div style="position:absolute;inset:0;display:flex;flex-direction:column;
             align-items:center;justify-content:center;pointer-events:none;">
          <div style="font-size:24px;font-weight:700;color:#111827;">{up_count}</div>
          <div style="font-size:10px;color:#9CA3AF;">of {total_svc} UP</div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="width:10px;height:10px;border-radius:2px;background:#10B981;display:inline-block;"></span>
          <span style="font-size:12px;color:#374151;">Healthy <strong>{up_count}</strong></span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="width:10px;height:10px;border-radius:2px;background:#EF4444;display:inline-block;"></span>
          <span style="font-size:12px;color:#374151;">Down <strong>{down_count}</strong></span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="width:10px;height:10px;border-radius:2px;background:#F59E0B;display:inline-block;"></span>
          <span style="font-size:12px;color:#374151;">Degraded <strong>{warn_count}</strong></span>
        </div>
      </div>
    </div>
  </div>
  <div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:20px;">
    <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:4px;">Response Latency</div>
    <div style="font-size:11px;color:#9CA3AF;margin-bottom:16px;">Per service (ms)</div>
    <div style="position:relative;height:120px;"><canvas id="health-latency"></canvas></div>
  </div>
</div>
<script>
registerChartInit('tab-health', function(){{
  new Chart(document.getElementById('health-donut'), {{
    type: 'doughnut',
    data: {{
      labels: {donut_labels},
      datasets: [{{ data: {donut_data}, backgroundColor: {donut_colors}, borderWidth: 0, hoverOffset: 4 }}]
    }},
    options: {{
      responsive: false, cutout: '68%',
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
        label: function(ctx) {{ return ctx.label + ': ' + ctx.raw; }}
      }} }} }}
    }}
  }});
  new Chart(document.getElementById('health-latency'), {{
    type: 'bar',
    data: {{
      labels: [{lat_labels}],
      datasets: [{{
        data: [{lat_data}],
        backgroundColor: [{lat_data}].map(function(v) {{
          return v < 5 ? '#10B981' : v < 20 ? '#F59E0B' : '#EF4444';
        }}),
        borderRadius: 4, borderWidth: 0
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
        label: function(ctx) {{ return ctx.parsed.y + ' ms'; }}
      }} }} }},
      scales: {{
        x: {{ ticks: {{ font: {{ size: 10 }}, color: '#9CA3AF' }}, grid: {{ display: false }}, border: {{ display: false }} }},
        y: {{ ticks: {{ font: {{ size: 10 }}, color: '#9CA3AF',
              callback: function(v) {{ return v + ' ms'; }} }},
              grid: {{ color: 'rgba(0,0,0,0.05)' }}, border: {{ display: false }} }}
      }}
    }}
  }});
}});
</script>
<div style="font-size:12px;font-weight:600;color:#9CA3AF;text-transform:uppercase;
            letter-spacing:.06em;margin-bottom:12px;">Services</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;">
  {svc_cards}
</div>
{disk_section}
"""


# ==============================================================================
# Report composer
# ==============================================================================

def build_report(
    out_html: Path,
    title: str,
    timestamp: str,
    grand: Totals,
    project_totals: Dict[str, Totals],
    language_totals: Dict[str, Totals],
    coverage_df: pd.DataFrame,
    health: EcosystemHealth,
) -> None:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    total_all = grand.blank + grand.comment + grand.code
    doc_lines = language_totals.get("Markdown", Totals()).code

    nodes_present = list(project_totals.keys())
    arch_html  = architecture_section_html(project_totals, nodes_present)
    proj_html  = projects_section_html(project_totals, grand)
    lang_html  = languages_section_html(language_totals, grand)
    cov_html   = coverage_section_html(coverage_df, timestamp)
    hlth_html  = health_section_html(health)

    full_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  {_CHARTJS}
  <script id="chart-registry">
  var _chartInits = {{}};
  function registerChartInit(tabId, fn) {{ _chartInits[tabId] = fn; }}
  </script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&display=swap');
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'IBM Plex Sans', Arial, sans-serif; background: #F1F5F9; color: #111827; }}
    .page-wrap {{ max-width: 1400px; margin: 0 auto; padding: 32px 28px 48px; }}
    .global-kpi {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 22px; }}
    .global-kpi-card {{
      background: white; border: 1px solid #E5E7EB; border-radius: 12px;
      padding: 14px 20px 12px; min-width: 120px; flex: 1;
    }}
    .global-kpi-card .lbl {{
      font-size: 11px; color: #9CA3AF; text-transform: uppercase;
      letter-spacing: .06em; margin-bottom: 6px;
    }}
    .global-kpi-card .val {{ font-size: 22px; font-weight: 700; color: #0F172A; }}
    .tab-nav {{
      display: inline-flex; gap: 4px; background: white;
      border: 1px solid #E5E7EB; border-radius: 12px;
      padding: 5px; margin-bottom: 20px;
    }}
    .tab-btn {{
      background: transparent; border: none; border-radius: 8px;
      padding: 8px 20px; cursor: pointer; font-family: inherit;
      font-size: 13px; font-weight: 600; color: #6B7280;
    }}
    .tab-btn:hover  {{ background: #F1F5F9; color: #374151; }}
    .tab-btn.active {{ background: #0F172A; color: white; }}
    .tab-panel        {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .page-footer {{
      margin-top: 32px; padding-top: 16px;
      border-top: 1px solid #E5E7EB;
      font-size: 11px; color: #9CA3AF; line-height: 1.8;
    }}
  </style>
</head>
<body>
<div class="page-wrap">
  <div style="
    display:flex;align-items:flex-start;justify-content:space-between;
    gap:16px;flex-wrap:wrap;margin-bottom:22px;
    padding:20px 24px;border-radius:16px;
    background:
      radial-gradient(1100px 240px at 10% 0%, rgba(37,99,235,.16), transparent 60%),
      radial-gradient(900px 220px at 95% 15%, rgba(37,99,235,.10), transparent 55%),
      linear-gradient(180deg, rgba(37,99,235,.10), rgba(37,99,235,.03));
    border:1px solid rgba(37,99,235,.18);
    box-shadow:0 10px 26px rgba(2,6,23,.06);
  ">
    <div>
      <h2 style="font-size:22px;font-weight:700;letter-spacing:-.02em;color:#0F172A;margin:0 0 6px 0;">{title}</h2>
      <div style="font-size:13px;color:#374151;margin-bottom:6px;">Architecture &middot; Codebase &middot; Coverage &middot; Health</div>
      <div style="font-size:11px;color:#6B7280;">Generated: {timestamp}</div>
    </div>
  </div>

  <div class="global-kpi">
    <div class="global-kpi-card"><div class="lbl">Files</div><div class="val">{fmt_int(grand.files)}</div></div>
    <div class="global-kpi-card"><div class="lbl">Documentation</div><div class="val">{fmt_int(doc_lines)}</div></div>
    <div class="global-kpi-card"><div class="lbl">Code lines</div><div class="val">{fmt_int(grand.code)}</div></div>
    <div class="global-kpi-card"><div class="lbl">Comment lines</div><div class="val">{fmt_int(grand.comment)}</div></div>
    <div class="global-kpi-card"><div class="lbl">Blank lines</div><div class="val">{fmt_int(grand.blank)}</div></div>
    <div class="global-kpi-card"><div class="lbl">Total lines</div><div class="val">{fmt_int(total_all)}</div></div>
  </div>

  <div class="tab-nav">
    <button class="tab-btn active" onclick="openTab('tab-arch',this)">Architecture</button>
    <button class="tab-btn" onclick="openTab('tab-proj',this)">Projects</button>
    <button class="tab-btn" onclick="openTab('tab-lang',this)">Languages</button>
    <button class="tab-btn" onclick="openTab('tab-cov',this)">Code Coverage</button>
    <button class="tab-btn" onclick="openTab('tab-health',this)">Health Status</button>
  </div>

  <div id="tab-arch"   class="tab-panel active">{arch_html}</div>
  <div id="tab-proj"   class="tab-panel">{proj_html}</div>
  <div id="tab-lang"   class="tab-panel">{lang_html}</div>
  <div id="tab-cov"    class="tab-panel">{cov_html}</div>
  <div id="tab-health" class="tab-panel">{hlth_html}</div>

  <div class="page-footer">
    cloc counts exclude vendored/runtime directories and selected file extensions per your cloc policy.<br>
    Coverage is best-effort and does not fail the report when a repository has test or configuration issues.<br>
    Health data is a snapshot taken at report generation time from the Control Center /summary endpoint.
  </div>
</div>
<script>
function openTab(id, btn) {{
  document.querySelectorAll('.tab-panel').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  if (_chartInits[id]) {{
    _chartInits[id]();
    delete _chartInits[id];
  }}
}}
</script>
</body>
</html>
"""
    out_html.write_text(full_html, encoding="utf-8")


# ==============================================================================
# CLI entry point
# ==============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate OmniBioAI ecosystem report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--targets", nargs="+", default=None)
    p.add_argument("--out", default=DEFAULT_OUT_RELPATH)
    p.add_argument("--title", default=DEFAULT_TITLE)
    p.add_argument("--control-center-url", default=DEFAULT_CONTROL_CENTER_URL,
                   dest="control_center_url")
    p.add_argument("--skip-health", action="store_true")
    p.add_argument("--skip-coverage", action="store_true")
    return p.parse_args()


def generate_report(
    ecosystem_root: Path,
    targets: Optional[List[str]] = None,
    out_relpath: str = DEFAULT_OUT_RELPATH,
    title: str = DEFAULT_TITLE,
    control_center_url: str = DEFAULT_CONTROL_CENTER_URL,
    skip_health: bool = False,
    skip_coverage: bool = False,
) -> Path:
    ensure_cloc()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not targets:
        targets = DEFAULT_TARGETS

    target_paths = _resolve_target_paths(ecosystem_root, targets)
    validate_paths(target_paths)

    print("→ Running cloc across repos…")
    project_totals:  Dict[str, Totals] = {}
    language_totals: Dict[str, Totals] = {}
    grand = Totals()
    for tp in target_paths:
        overall, per_lang = run_cloc(tp)
        project_totals[tp.name] = overall
        grand.add(overall)
        for lang, tot in per_lang.items():
            language_totals.setdefault(lang, Totals()).add(tot)

    if skip_coverage:
        print("→ Skipping coverage collection (--skip-coverage)")
        coverage_df = pd.DataFrame(columns=[
            "repo","path","status","returncode","statements",
            "missed","branches","partial_branches","coverage_pct",
            "coverage_band","fail_under","total_line","stderr_tail"])
    else:
        precomputed_dir = ecosystem_root / "out" / "coverage"
        if precomputed_dir.is_dir():
            print(f"→ Loading pre-computed coverage from {precomputed_dir} …")
        else:
            print("→ Collecting pytest coverage (live) …")
        coverage_df = collect_coverage(
            target_paths,
            precomputed_dir=precomputed_dir if precomputed_dir.is_dir() else None,
        )

    if skip_health:
        print("→ Skipping health check (--skip-health)")
        health = EcosystemHealth(
            overall_status="UNREACHABLE", generated_at="",
            error="Health check skipped (--skip-health flag)")
    else:
        print(f"→ Fetching health data from {control_center_url} …")
        health = fetch_health(control_center_url)
        status_icon = "✓" if health.overall_status == "UP" else "⚠"
        print(f"  {status_icon} Overall: {health.overall_status}")

    out_html = ecosystem_root / out_relpath
    print("→ Building report…")
    build_report(
        out_html=out_html, title=title, timestamp=ts,
        grand=grand, project_totals=project_totals,
        language_totals=language_totals, coverage_df=coverage_df,
        health=health,
    )
    return out_html


def main() -> int:
    args = parse_args()
    if args.root:
        ecosystem_root = args.root
    else:
        cwd = Path.cwd()
        ecosystem_root = cwd.parent if (cwd / "manage.py").exists() else cwd

    try:
        out = generate_report(
            ecosystem_root=ecosystem_root,
            targets=args.targets,
            out_relpath=args.out,
            title=args.title,
            control_center_url=args.control_center_url,
            skip_health=args.skip_health,
            skip_coverage=args.skip_coverage,
        )
        print(f"\n✓ Report written: {out}")
        return 0
    except Exception as e:
        print(f"\n✗ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())