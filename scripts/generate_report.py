# omnibioai-control-center/scripts/generate_report.py

#!/usr/bin/env python3
"""
OmniBioAI Ecosystem Report — scripts/generate_report.py  (redesigned)

Five tabs, consistent color palette across all tabs:
  teal   = core workbench / backend
  blue   = sdk / clients / frontend
  red    = security plane
  amber  = infrastructure / services
  purple = execution
  green  = healthy status
  gray   = neutral / unknown

Usage
-----
python omnibioai-control-center/scripts/generate_report.py

Options
-------
--root PATH              ecosystem root (default: auto-detect)
--health-url URL         default http://127.0.0.1:7070 (alias: --control-center-url)
--out PATH               default ${WORK_DIR}/out/reports/omnibioai_ecosystem_report.html
--skip-health            skip live health fetch
--skip-coverage          skip pytest coverage collection
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

# ── constants ──────────────────────────────────────────────────────────────────

EXCLUDE_DIRS = (
    "obsolete,staticfiles,node_modules,.venv,env,__pycache__,migrations,"
    "admin,venv,gnn_env,venv_sys,work,input,demo,md"
)
EXCLUDE_EXTS  = "svg,json,txt,csv,lock,min.js,map,pyc"
NOT_MATCH_D   = r"(data|uploads|downloads|cache|results|logs)"

DEFAULT_TARGETS = [
    "omnibioai-tes", "omnibioai", "omnibioai-rag", "omnibioai-lims",
    "omnibioai-toolserver", "omnibioai-tool-runtime",
    "omnibioai-control-center", "omnibioai-dev-docker", "omnibioai-sdk",
    "omnibioai-workflow-bundles", "omnibioai-model-registry",
    "omnibioai-tool-images", "omnibioai-studio", "omnibioai-dev-hub",
    "omnibioai-videos", "omnibioai-iam-client", "omnibioai-policy-engine",
    "omnibioai-security-audit", "omnibioai-security-sdk",
    "omnibioai-api-gateway", "omnibioai-hpc-policy-engine", "omnibioai-docs", "omnibioai-auth", "omnibioai-landing", "omnibioai-design-tokens", "omnibioai-ui",
    "omnibioai-utils",
    "omnibioai-launcher",
]

# Use WORK_DIR env var if set, otherwise fall back to omnibioai-work/
_work_dir = Path(os.environ.get(
    "WORK_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "omnibioai-work")
))
DEFAULT_OUT_PATH = _work_dir / "out" / "reports" / "omnibioai_ecosystem_report.html"
DEFAULT_TITLE              = "OmniBioAI Ecosystem"
DEFAULT_CONTROL_CENTER_URL = "http://127.0.0.1:7070"

# shared color palette (matches all 5 tabs)
COLORS = {
    "teal":   {"fill": "#E1F5EE", "stroke": "#1D9E75", "text": "#0F6E56"},
    "blue":   {"fill": "#E6F1FB", "stroke": "#378ADD", "text": "#185FA5"},
    "red":    {"fill": "#FCEBEB", "stroke": "#E24B4A", "text": "#A32D2D"},
    "amber":  {"fill": "#FAEEDA", "stroke": "#BA7517", "text": "#854F0B"},
    "purple": {"fill": "#EEEDFE", "stroke": "#7F77DD", "text": "#3C3489"},
    "gray":   {"fill": "#F1EFE8", "stroke": "#888780", "text": "#444441"},
    "green":  {"fill": "#EAF3DE", "stroke": "#97C459", "text": "#3B6D11"},
}

_CHARTJS = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/'
    'Chart.js/4.4.1/chart.umd.js"></script>'
)

# ── data models ────────────────────────────────────────────────────────────────

@dataclass
class Totals:
    files: int = 0; blank: int = 0; comment: int = 0; code: int = 0
    def add(self, o: "Totals") -> None:
        self.files += o.files; self.blank += o.blank
        self.comment += o.comment; self.code += o.code

@dataclass
class ServiceHealth:
    name: str; type: str; target: str; status: str
    latency_ms: Optional[int]; message: str; ui_url: Optional[str] = None

@dataclass
class DiskHealth:
    name: str; target: str; status: str; message: str

@dataclass
class EcosystemHealth:
    overall_status: str; generated_at: str
    services: List[ServiceHealth] = field(default_factory=list)
    disk: List[DiskHealth]        = field(default_factory=list)
    error: Optional[str]          = None

# ── helpers ────────────────────────────────────────────────────────────────────

def fmt_int(n: int) -> str: return f"{n:,}"
def safe_div(a: float, b: float) -> float: return (a / b) if b else 0.0
def _jsl(items): return "[" + ",".join(json.dumps(s) for s in items) + "]"
def _jsn(items): return "[" + ",".join(str(round(v, 2)) for v in items) + "]"

def _read_text_if_exists(path: Path) -> str:
    try: return path.read_text(encoding="utf-8")
    except Exception: return ""

# ── cloc ───────────────────────────────────────────────────────────────────────

def ensure_cloc() -> None:
    if shutil.which("cloc") is None:
        raise RuntimeError("cloc not found. Install: sudo apt-get install cloc")

def validate_paths(paths: List[Path]) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print("⚠ Repo paths not found:")
        for m in missing: print(f"  - {m}")

def _resolve_target_paths(root: Path, targets: List[str]) -> List[Path]:
    norm_map: Dict[str, Path] = {}
    if root.is_dir():
        for e in root.iterdir():
            if e.is_dir():
                norm_map[e.name.lower().replace("-", "_")] = e
    paths: List[Path] = []
    for name in targets:
        exact = root / name
        if exact.is_dir():
            paths.append(exact)
        else:
            nk = name.lower().replace("-", "_")
            resolved = norm_map.get(nk)
            if resolved:
                print(f"  ↳ resolved '{name}' → '{resolved.name}'")
                paths.append(resolved)
            else:
                paths.append(exact)
    return paths

def run_cloc(path: Path) -> Tuple[Totals, Dict[str, Totals]]:
    cmd = ["cloc", str(path),
           "--exclude-dir", EXCLUDE_DIRS,
           "--exclude-ext", EXCLUDE_EXTS,
           "--fullpath", "--not-match-d", NOT_MATCH_D,
           "--force-lang", "Dockerfile,Dockerfile", "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cloc failed for {path}:\n{proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    if "SUM" not in data:
        raise RuntimeError(f"Unexpected cloc JSON for {path}.")
    s = data["SUM"]
    overall = Totals(files=int(s.get("nFiles", 0)), blank=int(s.get("blank", 0)),
                     comment=int(s.get("comment", 0)), code=int(s.get("code", 0)))
    per_lang: Dict[str, Totals] = {}
    for k, v in data.items():
        if k in ("header", "SUM"): continue
        if isinstance(v, dict) and "code" in v:
            per_lang[k] = Totals(files=int(v.get("nFiles", 0)),
                                  blank=int(v.get("blank", 0)),
                                  comment=int(v.get("comment", 0)),
                                  code=int(v.get("code", 0)))
    return overall, per_lang

# ── coverage ───────────────────────────────────────────────────────────────────

def _cov_source_args(cwd: Path) -> List[str]:
    text = _read_text_if_exists(cwd / "pyproject.toml")
    if text:
        m = re.search(r'\[tool\.coverage\.run\](.*?)(?=\n\[|\Z)', text, re.DOTALL)
        if m:
            sm = re.search(r'^source\s*=\s*\[([^\]]*)\]', m.group(1), re.MULTILINE)
            if sm:
                sources = re.findall(r'["\']([^"\']+)["\']', sm.group(1))
                if sources: return [f"--cov={s}" for s in sources]
    text = _read_text_if_exists(cwd / ".coveragerc")
    if text:
        m = re.search(r'\[run\](.*?)(?=\n\[|\Z)', text, re.DOTALL)
        if m:
            sm = re.search(r'^source\s*=\s*(.+?)$', m.group(1), re.MULTILINE)
            if sm:
                sources = [s.strip() for s in sm.group(1).split(',') if s.strip()]
                if sources: return [f"--cov={s}" for s in sources]
    if (cwd / "src").is_dir(): return ["--cov=src"]
    return ["--cov=."]

def _coverage_cmd(cov_args, noconftest=False):
    cmd = [sys.executable, "-m", "pytest", *cov_args,
           "--cov-report=term-missing", "--cov-report=json",
           "--tb=no", "-q", "-p", "no:cacheprovider",
           "--continue-on-collection-errors", "--ignore=node_modules"]
    if noconftest: cmd.append("--noconftest")
    return cmd

def _pytest_available() -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception: return False

def _has_pytest_project(repo: Path) -> bool:
    return any((repo / p).exists() for p in
               ["pyproject.toml", "pytest.ini", "tests",
                "backend/pyproject.toml"])

def _pytest_cwd(repo: Path) -> Path:
    return repo / "backend" if (repo / "backend" / "pyproject.toml").exists() else repo

def _subprocess_env(cwd: Path) -> dict:
    import os; env = os.environ.copy()
    for cfg in [cwd / "pytest.ini", cwd / "setup.cfg",
                cwd.parent / "pytest.ini", cwd.parent / "setup.cfg"]:
        if not cfg.exists(): continue
        text = _read_text_if_exists(cfg)
        m = re.search(r"DJANGO_SETTINGS_MODULE\s*[=:]\s*(\S+)", text)
        if m: env.setdefault("DJANGO_SETTINGS_MODULE", m.group(1)); break
    return env

def _extract_total_line(output: str) -> Optional[str]:
    for line in output.splitlines():
        if re.match(r"^\s*TOTAL\b", line): return line.strip()
    return None

def _parse_total_line(total_line: str) -> Dict[str, Any]:
    parts = re.split(r"\s+", total_line.strip())
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

def _classify_coverage_band(pct: Optional[float]) -> str:
    if pct is None: return "No data"
    if pct >= 95:   return "Excellent (>=95%)"
    if pct >= 85:   return "Good (85-94.99%)"
    return "Needs attention (<85%)"

def _stderr_tail(stderr: str, n: int = 10) -> Optional[str]:
    stderr = stderr.strip()
    return "\n".join(stderr.splitlines()[-n:]) if stderr else None

def _classify_status(rc, total_line, coverage_pct, fail_under, stdout, stderr) -> str:
    if total_line is None: return "no_total_found"
    if rc == 0: return "ok"
    combined = f"{stdout}\n{stderr}".lower()
    cov_fail  = ("required test coverage" in combined or "fail-under" in combined
                 or (fail_under is not None and coverage_pct is not None
                     and coverage_pct < fail_under))
    test_fail = (" failed" in combined or "interrupted" in combined
                 or re.search(r"\b\d+ failed\b", combined) is not None)
    if cov_fail and test_fail: return "test_and_coverage_failure"
    if cov_fail:               return "coverage_threshold_failure"
    if test_fail:              return "test_failure"
    return "collection_errors"

def _extract_fail_under(repo: Path) -> Optional[float]:
    text = (_read_text_if_exists(repo / "pyproject.toml")
            + "\n" + _read_text_if_exists(repo / "pytest.ini"))
    for pat in [r"--cov-fail-under[=\s]+([0-9]+(?:\.[0-9]+)?)",
                r"fail[_-]under\s*=\s*([0-9]+(?:\.[0-9]+)?)"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m: return float(m.group(1))
    return None

def _parse_coverage_json(cwd: Path) -> Optional[Dict[str, Any]]:
    cov_file = cwd / "coverage.json"
    if not cov_file.exists(): return None
    try:
        data = json.loads(cov_file.read_text(encoding="utf-8"))
        totals = data.get("totals", {})
        pct    = totals.get("percent_covered")
        stmts  = totals.get("num_statements")
        missed = totals.get("missing_lines")
        if pct is None or stmts is None: return None
        return {"statements": int(stmts), "missed": int(missed or 0),
                "branches": totals.get("num_partial_branches"),
                "partial_branches": None,
                "coverage_pct": round(float(pct), 2)}
    except Exception: return None

def _load_precomputed(repo: Path, precomputed_dir: Path) -> Optional[Dict[str, Any]]:
    f = precomputed_dir / f"{repo.name}.json"
    if not f.exists(): return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict): return None
        if "totals" in data and "coverage_pct" not in data:
            t = data["totals"]
            return {"coverage_pct": t.get("percent_covered"),
                    "statements": t.get("num_statements"),
                    "missed": t.get("missing_lines"),
                    "branches": t.get("num_branches"),
                    "partial_branches": t.get("num_partial_branches"),
                    "returncode": 0, "total_line": None, "stderr_tail": None}
        return data
    except Exception: return None

def collect_coverage(target_paths: List[Path],
                     precomputed_dir: Optional[Path] = None) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    pytest_ok = _pytest_available()
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
                    if k in precomp: row[k] = precomp[k]
                if row["coverage_pct"] is not None:
                    row["coverage_band"] = _classify_coverage_band(row["coverage_pct"])
                    row["status"] = _classify_status(
                        row.get("returncode"), row.get("total_line"),
                        row["coverage_pct"], row["fail_under"],
                        precomp.get("stdout_tail") or "",
                        precomp.get("stderr_tail") or "")
                else:
                    row["status"] = precomp.get("status", "no_total_found")
                rows.append(row); continue
        if not pytest_ok:
            row["status"] = "skipped_no_pytest"; rows.append(row); continue
        if not _has_pytest_project(repo):
            row["status"] = "skipped_no_pytest_project"; rows.append(row); continue
        try:
            cwd = _pytest_cwd(repo)
            cov_args = _cov_source_args(cwd)
            env = _subprocess_env(cwd)
            def _run(noconftest):
                p = subprocess.run(
                    _coverage_cmd(cov_args, noconftest),
                    cwd=str(cwd), env=env,
                    capture_output=True, text=True, timeout=300)
                t = _extract_total_line(p.stdout)
                c = None if t else _parse_coverage_json(cwd)
                return p, t, c
            proc, total_line, cov_data = _run(False)
            if total_line is None and cov_data is None:
                ce = ("ImportError while loading conftest" in proc.stderr
                      or "ERROR while loading conftest" in proc.stderr)
                if ce:
                    proc, total_line, cov_data = _run(True)
            row["returncode"] = proc.returncode
            if not row.get("stderr_tail"): row["stderr_tail"] = _stderr_tail(proc.stderr)
            if total_line and total_line != "json":
                row["total_line"] = total_line; row.update(_parse_total_line(total_line))
            elif cov_data:
                row["total_line"] = "json"; row.update(cov_data)
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

# ── health fetch ───────────────────────────────────────────────────────────────

def _parse_service(raw: Dict[str, Any]) -> ServiceHealth:
    return ServiceHealth(
        name=str(raw.get("name", "unknown")), type=str(raw.get("type", "unknown")),
        target=str(raw.get("target", "-")),
        status=str(raw.get("status", "DOWN")).upper(),
        ui_url=raw.get("ui_url") or None,
        latency_ms=raw.get("latency_ms"),
        message=str(raw.get("message", "")))

def _parse_disk(raw: Dict[str, Any]) -> DiskHealth:
    return DiskHealth(name=str(raw.get("name", "disk")),
                      target=str(raw.get("target", "-")),
                      status=str(raw.get("status", "WARN")).upper(),
                      message=str(raw.get("message", "")))

def fetch_health(base_url: str, timeout_s: float = 5.0) -> EcosystemHealth:
    url = base_url.rstrip("/") + "/summary"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omnibioai-report/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        services = [_parse_service(s) for s in (payload.get("services") or [])]
        disk_raw = (payload.get("system") or {}).get("disk") or []
        disk     = [_parse_disk(d) for d in disk_raw]
        return EcosystemHealth(
            overall_status=str(payload.get("overall_status", "WARN")).upper(),
            generated_at=str(payload.get("generated_at", "")),
            services=services, disk=disk)
    except urllib.error.URLError as e:
        return EcosystemHealth(overall_status="UNREACHABLE", generated_at="",
                               error=f"Control Center unreachable: {e.reason}")
    except Exception as e:
        return EcosystemHealth(overall_status="UNREACHABLE", generated_at="",
                               error=f"{type(e).__name__}: {e}")

# ── SHARED CSS ─────────────────────────────────────────────────────────────────

SHARED_CSS = """
<style id="shared">
:root {
  --color-bg:              #0d1117;
  --color-bg-surface:      #161b27;
  --color-bg-surface2:     #1e2435;
  --color-border:          #2a2d3e;
  --color-text:            #e2e8f0;
  --color-text-secondary:  #9ca3af;
  --color-text-muted:      #6b7280;
  --color-accent:          #00e5a0;
  --color-accent-dim:      rgba(0,229,160,0.10);
  --color-success:         #22c55e;
  --color-success-dim:     rgba(34,197,94,0.12);
  --color-success-border:  rgba(34,197,94,0.30);
  --color-danger:          #ef4444;
  --color-danger-dim:      rgba(239,68,68,0.12);
  --color-danger-border:   rgba(239,68,68,0.30);
  --color-warning:         #f59e0b;
  --color-warning-dim:     rgba(245,158,11,0.12);
  --color-warning-border:  rgba(245,158,11,0.30);
  --color-info:            #0094ff;
  --color-info-dim:        rgba(0,148,255,0.10);
  --radius-sm:             6px;
  --radius-lg:             12px;
  --radius-pill:           9999px;
  --font-sans:             'IBM Plex Sans', system-ui, sans-serif;
  --font-size-xs:          11px;
  --font-size-sm:          12px;
  --font-size-base:        13px;

  /* Architecture lane colors — kept unchanged, encode domain meaning */
  --c-teal:   #00e5a0; --c-teal-bg:   rgba(0,229,160,0.08); --c-teal-bd:   rgba(0,229,160,0.25);
  --c-blue:   #0094ff; --c-blue-bg:   rgba(0,148,255,0.08); --c-blue-bd:   rgba(0,148,255,0.25);
  --c-red:    #ef4444; --c-red-bg:    rgba(239,68,68,0.08);  --c-red-bd:    rgba(239,68,68,0.25);
  --c-amber:  #f59e0b; --c-amber-bg:  rgba(245,158,11,0.08); --c-amber-bd:  rgba(245,158,11,0.25);
  --c-purple: #a855f7; --c-purple-bg: rgba(168,85,247,0.08); --c-purple-bd: rgba(168,85,247,0.25);
  --c-gray:   #9ca3af; --c-gray-bg:   rgba(107,114,128,0.08);--c-gray-bd:   rgba(107,114,128,0.25);
  --c-green:  #22c55e; --c-green-bg:  rgba(34,197,94,0.08);  --c-green-bd:  rgba(34,197,94,0.25);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font-sans);background:transparent}
.tab-section{padding:20px 0}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:16px}
.kpi{background:var(--color-bg-surface);border-radius:8px;padding:12px 14px}
.kpi-label{font-size:11px;color:var(--color-text-muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.04em}
.kpi-val{font-size:20px;font-weight:600;color:var(--color-text)}
.kpi-sub{font-size:11px;color:var(--color-text-muted);margin-top:2px}
.section{background:var(--color-bg-surface);border:0.5px solid var(--color-border);border-radius:12px;padding:16px;margin-bottom:12px}
.sec-title{font-size:13px;font-weight:600;color:var(--color-text);margin-bottom:2px}
.sec-sub{font-size:11px;color:var(--color-text-muted);margin-bottom:14px}
.badge{font-size:10px;padding:2px 7px;border-radius:99px;font-weight:600;white-space:nowrap}
.tbl-wrap{border:0.5px solid var(--color-border);border-radius:12px;overflow:hidden;margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{padding:8px 12px;font-size:11px;font-weight:600;color:var(--color-text-muted);background:var(--color-bg-surface);
   border-bottom:0.5px solid var(--color-border);text-align:left;white-space:nowrap;
   cursor:pointer;user-select:none;text-transform:uppercase;letter-spacing:.04em}
th:hover{color:var(--color-text)}
th.r,td.r{text-align:right}
td{padding:7px 12px;border-bottom:0.5px solid var(--color-border);color:var(--color-text) !important;vertical-align:middle;background:var(--color-bg-surface) !important}
td.mono{font-family:monospace;font-size:11px;color:var(--color-text) !important;
        max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--color-bg-surface) !important}
.filter-row{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.search-inp{flex:1;min-width:140px;padding:6px 10px;font-size:12px;
            border:0.5px solid var(--color-border);border-radius:8px;background:var(--color-bg-surface);color:var(--color-text)}
.filter-sel{padding:6px 10px;font-size:12px;border:0.5px solid var(--color-border);
            border-radius:8px;background:var(--color-bg-surface);color:var(--color-text);cursor:pointer}
.result-count{font-size:11px;color:var(--color-text-muted);white-space:nowrap}
.pg-wrap{display:flex;align-items:center;gap:6px;justify-content:center;padding:4px 0}
.pg-btn{padding:5px 10px;font-size:12px;border:0.5px solid var(--color-border);border-radius:8px;
        background:var(--color-bg-surface);color:var(--color-text-muted);cursor:pointer;min-width:32px;text-align:center}
.pg-btn:hover:not(:disabled){background:var(--color-bg-surface);color:var(--color-text)}
.pg-btn:disabled{opacity:.4;cursor:not-allowed}
.pg-btn.active{background:var(--color-accent);color:#000;border-color:var(--color-accent)}
.pg-info{font-size:11px;color:var(--color-text-muted);margin:0 4px}
.per-pg{font-size:11px;color:var(--color-text-muted);display:flex;align-items:center;gap:6px;margin-left:auto}
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.bar-label{font-size:11px;color:var(--color-text-muted);text-align:right;flex-shrink:0;
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{flex:1;border-radius:3px;overflow:hidden;position:relative;background:var(--color-border)}
.bar-fill{height:100%;border-radius:3px;min-width:2px}
.bar-val{font-size:10px;font-weight:600;white-space:nowrap;
         position:absolute;right:6px;top:50%;transform:translateY(-50%)}
.share-bar{width:50px;height:4px;background:var(--color-border);border-radius:2px;
           overflow:hidden;display:inline-block;vertical-align:middle;margin-left:6px}
.share-fill{height:100%;border-radius:2px}
.donut-center{position:absolute;inset:0;display:flex;flex-direction:column;
              align-items:center;justify-content:center;pointer-events:none}
.donut-center-val{font-size:18px;font-weight:700;color:var(--color-text)}
.donut-center-lbl{font-size:10px;color:var(--color-text-muted)}
.legend-item{display:flex;align-items:center;gap:6px;padding:3px 0;
             font-size:11px;color:var(--color-text-muted)}
.legend-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0}
.legend-pct{margin-left:auto;font-size:11px;font-weight:600;color:var(--color-text)}
.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0}
.dot-up{background:var(--color-success)}.dot-down{background:var(--color-danger)}
.dot-warn{background:var(--color-warning)}.dot-loading{background:var(--color-text-muted)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.dot-loading{animation:pulse 1s ease-in-out infinite}
</style>
"""

# ── TAB 1: ARCHITECTURE ────────────────────────────────────────────────────────

def architecture_section_html(project_totals: Dict[str, Totals],
                               grand: Totals,
                               control_center_url: str) -> str:
    cc_url = control_center_url.rstrip("/")
    return f"""
<div class="tab-section">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px">
  <div>
    <div style="font-size:15px;font-weight:600;color:var(--color-text)">OmniBioAI ecosystem</div>
    <div style="font-size:12px;color:var(--color-text-muted);margin-top:2px">Click any node to see live health, latency and metrics</div>
  </div>
  <div style="display:flex;align-items:center;gap:8px">
    <div style="display:flex;align-items:center;gap:5px;font-size:11px;padding:3px 8px;border-radius:99px;background:var(--color-bg-surface);border:0.5px solid var(--color-border);color:var(--color-text-muted)">
      <span class="status-dot dot-loading" id="g-dot"></span>
      <span id="g-status">fetching...</span>
    </div>
    <button onclick="fetchH()" style="display:flex;align-items:center;gap:5px;padding:6px 12px;border:0.5px solid var(--color-border);border-radius:8px;background:var(--color-bg-surface);font-size:12px;color:var(--color-text-muted);cursor:pointer">
      ↻ refresh
    </button>
  </div>
</div>

<div style="display:flex;align-items:center;gap:0;margin-bottom:8px">
  <div style="flex:1;height:1px;background:var(--c-red-bd);opacity:.4"></div>
  <span style="font-size:11px;color:var(--c-red);font-weight:600;padding:0 10px">enforced request path →</span>
  <div style="flex:1;height:1px;background:var(--c-red-bd);opacity:.4"></div>
</div>

<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px">

  <!-- DEV / CLIENTS -->
  <div style="border-radius:12px;border:0.5px solid var(--c-blue-bd);background:var(--c-blue-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-blue);margin-bottom:8px">dev / clients</div>
    {"".join(_arch_node(n,d,p,u,'blue') for n,d,p,u in [
      ('studio','Electron · v0.2.0',None,None),
      ('dev-hub','knowledge graph','5173',None),
      ('sdk','Python SDK','5190',None),
      ('iam-client','auth SDK',None,None),
      ('security-sdk','policy client',None,None),
    ])}
  </div>

  <!-- SECURITY -->
  <div style="border-radius:12px;border:1px solid var(--c-red-bd);background:var(--c-red-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-red);margin-bottom:2px">🔐 security plane</div>
    <div style="font-size:10px;text-align:center;color:var(--c-red);opacity:.8;margin-bottom:6px">zero-trust boundary</div>
    {"".join(_arch_node(n,d,p,u,'red') for n,d,p,u in [
      ('api-gateway','JWT · trace prop','8080',None),
      ('auth-service','bcrypt · JWT','8001',None),
      ('policy-engine','RBAC/ABAC','8002',None),
      ('hpc-policy-engine','GPU quota','8003',None),
      ('security-audit','Redis streams','8004',None),
    ])}
  </div>

  <!-- WORKBENCH -->
  <div style="border-radius:12px;border:0.5px solid var(--c-teal-bd);background:var(--c-teal-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-teal);margin-bottom:8px">workbench</div>
    {"".join(_arch_node(n,d,p,u,'teal') for n,d,p,u in [
      ('workbench','Django · 80+ plugins','8000','https://app.omnibioai.org'),
      ('lims','lab data','7000','https://lims.omnibioai.org'),
      ('rag','PubMed · DeepSeek','8090','https://rag.omnibioai.org'),
      ('workflow-bundles','WDL/Nextflow/CWL','8098','https://bundles.omnibioai.org'),
      ('control-center','health · images','7070','https://control.omnibioai.org'),
    ])}
  </div>

  <!-- SERVICES -->
  <div style="border-radius:12px;border:0.5px solid var(--c-amber-bd);background:var(--c-amber-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-amber);margin-bottom:8px">services</div>
    {"".join(_arch_node(n,d,p,u,'amber') for n,d,p,u in [
      ('toolserver','FastAPI bio tools','9090','https://tools.omnibioai.org'),
      ('model-registry','ML versioning','8095','https://models.omnibioai.org'),
      ('opa','Open Policy Agent','8181',None),
      ('ollama','Llama/DeepSeek','11434',None),
      ('videos','tutorials · SDK','8086',None),
    ])}
  </div>

  <!-- EXECUTION -->
  <div style="border-radius:12px;border:0.5px solid var(--c-purple-bd);background:var(--c-purple-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-purple);margin-bottom:8px">execution</div>
    {"".join(_arch_node(n,d,p,u,'purple') for n,d,p,u in [
      ('tes','Slurm/AWS/Azure/GCP','8081','https://app.omnibioai.org/_svc/tes'),
      ('tool-runtime','Docker/Singularity',None,None),
      ('tool-images','80+ bio tools','8097',None),
      ('dev-docker','DGX · GPU env','8082','https://dev.omnibioai.org'),
    ])}
  </div>

</div>

<!-- DETAIL PANEL -->
<div id="det-panel" style="display:none;border:0.5px solid var(--color-border);border-radius:12px;background:var(--color-bg-surface);overflow:hidden;margin-bottom:12px">
  <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:0.5px solid var(--color-border)">
    <div>
      <div style="font-size:14px;font-weight:600;color:var(--color-text)" id="det-name">—</div>
      <div style="font-size:11px;color:var(--color-text-muted);margin-top:2px" id="det-lane">—</div>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <a id="det-open" style="display:none;font-size:11px;padding:3px 8px;border:0.5px solid var(--color-border);border-radius:6px;background:var(--color-info-dim);color:var(--color-info);text-decoration:none" target="_blank">open UI ↗</a>
      <button onclick="document.getElementById('det-panel').style.display='none'" style="padding:4px 10px;border:0.5px solid var(--color-border);border-radius:6px;background:transparent;font-size:11px;color:var(--color-text-muted);cursor:pointer">close</button>
    </div>
  </div>
  <div style="padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:3px">health status</div><div style="font-size:13px;font-weight:600" id="det-status">—</div></div>
    <div><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:3px">latency</div><div style="font-size:13px" id="det-lat">—</div></div>
    <div><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:3px">port</div><div style="font-size:13px;font-weight:600" id="det-port">—</div></div>
    <div><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:3px">message</div><div style="font-size:12px;color:var(--color-text-muted)" id="det-msg">—</div></div>
    <div style="grid-column:1/-1">
      <div style="font-size:11px;color:var(--color-text-muted);margin-bottom:4px">description</div>
      <div style="font-size:12px;color:var(--color-text-muted)" id="det-desc">—</div>
    </div>
  </div>
</div>

<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:8px 0;border-top:0.5px solid var(--color-border)">
  <div class="legend-item"><span class="legend-dot" style="background:#3B6D11;border-radius:50%"></span>healthy</div>
  <div class="legend-item"><span class="legend-dot" style="background:#A32D2D;border-radius:50%"></span>down</div>
  <div class="legend-item"><span class="legend-dot" style="background:#888780;border-radius:50%"></span>not monitored</div>
  <div style="margin-left:auto;font-size:11px;color:var(--color-text-muted)">live from <code style="font-size:10px">/summary</code> · auto-refreshes every 30s</div>
</div>
</div>

<script>
var _hd={{}};var _cc='';
function fetchH(){{
  fetch(_cc+'/summary').then(function(r){{return r.json();}}).then(function(d){{
    var svcs=d.services||[];
    _hd={{}};svcs.forEach(function(s){{_hd[s.name]=s;}});
    var ov=(d.overall_status||'').toUpperCase();
    var gd=document.getElementById('g-dot');
    var gs=document.getElementById('g-status');
    gd.className='status-dot '+(ov==='UP'?'dot-up':'dot-down');
    gs.textContent=ov==='UP'?'all systems up':ov.toLowerCase();
    Object.keys(_hd).forEach(function(k){{
      var el=document.getElementById('nd-'+k);
      if(el){{var s=(_hd[k].status||'').toUpperCase();el.className='status-dot '+(s==='UP'?'dot-up':'dot-down');}}
    }});
  }}).catch(function(){{
    document.getElementById('g-dot').className='status-dot dot-down';
    document.getElementById('g-status').textContent='unreachable';
  }});
}}
function showDet(name,lane,desc,port,ui){{
  var p=document.getElementById('det-panel');
  p.style.display='block';
  document.getElementById('det-name').textContent=name;
  document.getElementById('det-lane').textContent=lane;
  document.getElementById('det-desc').textContent=desc;
  document.getElementById('det-port').textContent=port?':'+port:'—';
  var oa=document.getElementById('det-open');
  if(ui){{oa.style.display='inline';oa.href=ui;}}else{{oa.style.display='none';}}
  var s=_hd[name];
  if(s){{
    var st=(s.status||'UNKNOWN').toUpperCase();
    var sel=document.getElementById('det-status');
    sel.textContent=st;sel.style.color=st==='UP'?'#3B6D11':'#A32D2D';
    var lat=s.latency_ms;
    document.getElementById('det-lat').innerHTML=lat!=null?'<span style="color:'+(lat<5?'#3B6D11':lat<20?'#854F0B':'#A32D2D')+';font-weight:600">'+lat+' ms</span>':'—';
    document.getElementById('det-msg').textContent=s.message||'—';
  }}else{{
    document.getElementById('det-status').textContent='not monitored';
    document.getElementById('det-status').style.color='#888780';
    document.getElementById('det-lat').textContent='—';
    document.getElementById('det-msg').textContent='—';
  }}
  p.scrollIntoView({{behavior:'smooth',block:'nearest'}});
}}
fetchH();setInterval(fetchH,30000);
</script>
"""

def _arch_node(name: str, desc: str, port: Optional[str],
               ui: Optional[str], color: str) -> str:
    c = COLORS[color]
    ui_js = f"'{ui}'" if ui else "null"
    port_js = f"'{port}'" if port else "null"
    short = name.replace("omnibioai-", "").replace("omnibioai", "omnibioai")
    return f"""<div onclick="showDet('{name}','{color} lane','{desc}',{port_js},{ui_js})"
  style="border-radius:8px;border:0.5px solid {c['stroke']};background:var(--color-bg-surface);
         padding:8px 10px;margin-bottom:6px;cursor:pointer;
         transition:transform .15s;position:relative"
  onmouseover="this.style.transform='translateY(-1px)'"
  onmouseout="this.style.transform=''"
>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:2px">
    <span style="font-size:11px;font-weight:600;color:{c['text']}">{short}</span>
    <span class="status-dot dot-loading" id="nd-{name}"></span>
  </div>
  <div style="font-size:10px;color:var(--color-text-muted);line-height:1.3">{desc}{(' · :'+port) if port else ''}</div>
</div>"""

# ── TAB 2: PROJECTS ────────────────────────────────────────────────────────────

CAT_MAP = {
    "omnibioai":                    "core",
    "omnibioai-lims":               "core",
    "omnibioai-rag":                "core",
    "omnibioai-workflow-bundles":   "core",
    "omnibioai-studio":             "sdk",
    "omnibioai-sdk":                "sdk",
    "omnibioai-dev-hub":            "sdk",
    "omnibioai-videos":             "sdk",
    "omnibioai-tes":                "exec",
    "omnibioai-tool-runtime":       "exec",
    "omnibioai-tool-images":        "exec",
    "omnibioai-dev-docker":         "exec",
    "omnibioai-toolserver":         "infra",
    "omnibioai-model-registry":     "infra",
    "omnibioai-control-center":     "infra",
    "omnibioai-api-gateway":        "sec",
    "omnibioai-auth":               "sec",
    "omnibioai-policy-engine":      "sec",
    "omnibioai-hpc-policy-engine":  "sec",
    "omnibioai-security-audit":     "sec",
    "omnibioai-security-sdk":       "sec",
    "omnibioai-iam-client":         "sec",
}
CAT_META = {
    "core":  {"label": "core workbench", "color": "#0F6E56", "bg": "#E1F5EE"},
    "sec":   {"label": "security",       "color": "#A32D2D", "bg": "#FCEBEB"},
    "exec":  {"label": "execution",      "color": "#3C3489", "bg": "#EEEDFE"},
    "infra": {"label": "infrastructure", "color": "#854F0B", "bg": "#FAEEDA"},
    "sdk":   {"label": "sdk / clients",  "color": "#185FA5", "bg": "#E6F1FB"},
}

def projects_section_html(project_totals: Dict[str, Totals], grand: Totals) -> str:
    proj = sorted(project_totals.items(), key=lambda kv: kv[1].code, reverse=True)
    total_code = grand.code or 1
    cat_totals: Dict[str, int] = {k: 0 for k in CAT_META}
    for name, t in proj:
        cat = CAT_MAP.get(name, "infra")
        cat_totals[cat] = cat_totals.get(cat, 0) + t.code
    cat_order = sorted(cat_totals, key=lambda k: cat_totals[k], reverse=True)

    donut_data   = json.dumps([cat_totals[k] for k in cat_order])
    donut_colors = json.dumps([CAT_META[k]["color"] for k in cat_order])
    donut_labels = json.dumps([CAT_META[k]["label"] for k in cat_order])

    rows_js = []
    for name, t in proj:
        cat = CAT_MAP.get(name, "infra")
        m = CAT_META[cat]
        pct = round(100 * t.code / total_code, 2)
        short = name.replace("omnibioai-", "").replace("omnibioai_", "").replace("omnibioai", "omnibioai")
        rows_js.append(json.dumps({
            "name": short, "full": name, "cat": cat,
            "catLabel": m["label"], "color": m["color"], "bg": m["bg"],
            "files": t.files, "code": t.code,
            "comment": t.comment, "blank": t.blank, "pct": pct
        }))
    rows_js_str = "[" + ",".join(rows_js) + "]"
    max_code = proj[0][1].code if proj else 1

    legend_html = "".join(
        f'<div class="legend-item"><span class="legend-dot" style="background:{CAT_META[k]["color"]}"></span>'
        f'<span>{CAT_META[k]["label"]}</span>'
        f'<span class="legend-pct">{round(100*cat_totals[k]/total_code,1)}%</span></div>'
        for k in cat_order
    )

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">repositories</div><div class="kpi-val">{len(proj)}</div><div class="kpi-sub">tracked by cloc</div></div>
  <div class="kpi"><div class="kpi-label">code lines</div><div class="kpi-val">{fmt_int(grand.code)}</div><div class="kpi-sub">excl. vendored</div></div>
  <div class="kpi"><div class="kpi-label">largest repo</div><div class="kpi-val">{proj[0][0].replace('omnibioai','omni') if proj else '—'}</div><div class="kpi-sub">{fmt_int(proj[0][1].code)+' LOC' if proj else ''}</div></div>
  <div class="kpi"><div class="kpi-label">categories</div><div class="kpi-val">5</div><div class="kpi-sub">core · sec · exec · infra · sdk</div></div>
</div>

<div class="section">
  <div class="sec-title">share by project</div>
  <div class="sec-sub">code lines · categorized by function</div>
  <div style="display:grid;grid-template-columns:180px 1fr;gap:16px">
    <div style="display:flex;flex-direction:column;align-items:center">
      <div style="position:relative;width:140px;height:140px;margin:0 auto 12px">
        <canvas id="proj-donut" width="140" height="140"></canvas>
        <div class="donut-center">
          <div class="donut-center-val">{fmt_int(grand.code)}</div>
          <div class="donut-center-lbl">total LOC</div>
        </div>
      </div>
      {legend_html}
    </div>
    <div id="proj-bars" style="display:flex;flex-direction:column;justify-content:center"></div>
  </div>
</div>

<div class="section">
  <div class="sec-title">per-project breakdown</div>
  <div class="sec-sub">all repositories · sorted by code lines · click headers to sort</div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search..." oninput="projFilter(this.value)" id="proj-search">
    <select class="filter-sel" onchange="projCatFilter(this.value)">
      <option value="">all categories</option>
      {"".join(f'<option value="{k}">{CAT_META[k]["label"]}</option>' for k in CAT_META)}
    </select>
    <span class="result-count" id="proj-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="projPerPage(this.value)"><option value="10" selected>10</option><option value="20">20</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="projSort('name')">repository</th>
        <th>category</th>
        <th class="r" onclick="projSort('files')">files</th>
        <th class="r" onclick="projSort('code')">code</th>
        <th class="r" onclick="projSort('comment')">comment</th>
        <th class="r" onclick="projSort('blank')">blank</th>
        <th class="r" onclick="projSort('pct')">share</th>
      </tr></thead>
      <tbody id="proj-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="proj-pg"></div>
</div>
</div>

<script>
var _pd={rows_js_str},_ps={{data:[],filtered:[],page:1,pp:10,sort:'code',dir:-1,search:'',cat:''}};
var _pm={max_code};
(function(){{
  _ps.data=_pd.slice();
  new Chart(document.getElementById('proj-donut'),{{
    type:'doughnut',
    data:{{labels:{donut_labels},datasets:[{{data:{donut_data},backgroundColor:{donut_colors},borderWidth:2,borderColor:'#1a1d2e',hoverOffset:4}}]}},
    options:{{responsive:false,cutout:'68%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+(c.raw/1000).toFixed(0)+'k LOC ('+(c.raw/{total_code}*100).toFixed(1)+'%)';}}}}}}}}}}
  }});
  var bEl=document.getElementById('proj-bars');
  _pd.slice(0,16).forEach(function(r){{
    var pct=Math.round(r.code/_pm*100);
    var loc=r.code>=1000?(r.code/1000).toFixed(0)+'k':r.code;
    var d=document.createElement('div');d.className='bar-row';
    d.innerHTML='<span class="bar-label" style="width:110px" title="'+r.full+'">'+r.name+'</span>'+
      '<div class="bar-track" style="height:16px"><div class="bar-fill" style="width:'+pct+'%;background:'+r.color+'22"></div>'+
      '<span class="bar-val" style="color:'+r.color+'">'+loc+'</span></div>'+
      '<span class="badge" style="background:'+r.bg+';color:'+r.color+';width:64px;text-align:center">'+r.catLabel.split(' ')[0]+'</span>';
    bEl.appendChild(d);
  }});
  projApply();
}})();
function projFilter(v){{_ps.search=v.toLowerCase();_ps.page=1;projApply();}}
function projCatFilter(v){{_ps.cat=v;_ps.page=1;projApply();}}
function projPerPage(v){{_ps.pp=parseInt(v);_ps.page=1;projApply();}}
function projSort(col){{if(_ps.sort===col){{_ps.dir*=-1;}}else{{_ps.sort=col;_ps.dir=col==='name'?1:-1;}} _ps.page=1;projApply();}}
function projApply(){{
  var d=_ps.data.slice();
  if(_ps.search)d=d.filter(function(r){{return (r.name+r.catLabel).toLowerCase().includes(_ps.search);}});
  if(_ps.cat)d=d.filter(function(r){{return r.cat===_ps.cat;}});
  var col=_ps.sort;
  d.sort(function(a,b){{
    var av=typeof a[col]==='number'?a[col]:(a[col]||'').toLowerCase();
    var bv=typeof b[col]==='number'?b[col]:(b[col]||'').toLowerCase();
    return av<bv?_ps.dir:av>bv?-_ps.dir:0;
  }});
  _ps.filtered=d;
  document.getElementById('proj-count').textContent=d.length+' items';
  var start=(_ps.page-1)*_ps.pp,page=d.slice(start,start+_ps.pp);
  var tb=document.getElementById('proj-tbody');tb.innerHTML='';
  page.forEach(function(r){{
    var tr=document.createElement('tr');
    tr.innerHTML='<td style="font-weight:600;font-size:12px">'+r.name+'</td>'+
      '<td><span class="badge" style="background:'+r.bg+';color:'+r.color+'">'+r.catLabel+'</span></td>'+
      '<td class="r">'+r.files.toLocaleString()+'</td>'+
      '<td class="r" style="font-weight:600">'+r.code.toLocaleString()+'</td>'+
      '<td class="r">'+r.comment.toLocaleString()+'</td>'+
      '<td class="r">'+r.blank.toLocaleString()+'</td>'+
      '<td class="r">'+r.pct.toFixed(1)+'%<span class="share-bar"><span class="share-fill" style="width:'+Math.min(100,r.pct*2).toFixed(1)+'%;background:'+r.color+'"></span></span></td>';
    tb.appendChild(tr);
  }});
  renderPg('proj',_ps,projApply);
}}
</script>
"""

# ── TAB 3: LANGUAGES ───────────────────────────────────────────────────────────

LANG_TYPE = {
    "Python":"backend","Jupyter Notebook":"backend","SQL":"backend",
    "Mojo":"backend","Metal":"backend","C++":"backend","C/C++ Header":"backend",
    "HTML":"frontend","TypeScript":"frontend","JavaScript":"frontend","CSS":"frontend",
    "Markdown":"docs","reStructuredText":"docs",
    "YAML":"config","TOML":"config","INI":"config","Properties":"config","JSON":"config",
    "Dockerfile":"infra","Bourne Shell":"infra","Bourne Again Shell":"infra",
    "Source Shell":"infra","Source Again Shell":"infra","make":"infra",
    "Windows Module Definition":"infra",
}
LANG_TYPE_META = {
    "backend":  {"label":"backend",  "color":"#0F6E56","bg":"#E1F5EE","icon":"🐍"},
    "frontend": {"label":"frontend", "color":"#185FA5","bg":"#E6F1FB","icon":"🌐"},
    "docs":     {"label":"docs",     "color":"#444441","bg":"#F1EFE8","icon":"📄"},
    "config":   {"label":"config",   "color":"#854F0B","bg":"#FAEEDA","icon":"⚙️"},
    "infra":    {"label":"infra",    "color":"#3C3489","bg":"#EEEDFE","icon":"🔧"},
}

def languages_section_html(language_totals: Dict[str, Totals], grand: Totals) -> str:
    langs = sorted(language_totals.items(), key=lambda kv: kv[1].code, reverse=True)
    total_code = grand.code or 1
    type_totals: Dict[str, int] = {k: 0 for k in LANG_TYPE_META}
    for name, t in langs:
        lt = LANG_TYPE.get(name, "infra")
        type_totals[lt] = type_totals.get(lt, 0) + t.code
    type_order = sorted(type_totals, key=lambda k: type_totals[k], reverse=True)

    donut_data   = json.dumps([type_totals[k] for k in type_order])
    donut_colors = json.dumps([LANG_TYPE_META[k]["color"] for k in type_order])
    donut_labels = json.dumps([LANG_TYPE_META[k]["label"] for k in type_order])

    rows_js = []
    for name, t in langs:
        lt = LANG_TYPE.get(name, "infra")
        m  = LANG_TYPE_META[lt]
        pct = round(100 * t.code / total_code, 2)
        rows_js.append(json.dumps({
            "name": name, "type": lt, "typeLabel": m["label"],
            "color": m["color"], "bg": m["bg"],
            "files": t.files, "code": t.code,
            "comment": t.comment, "blank": t.blank, "pct": pct
        }))
    rows_js_str = "[" + ",".join(rows_js) + "]"
    max_code = langs[0][1].code if langs else 1

    type_cards = "".join(
        f'<div style="background:var(--color-bg-surface);border-radius:8px;padding:10px 12px;display:flex;align-items:center;gap:10px">'
        f'<div style="width:32px;height:32px;border-radius:8px;background:{LANG_TYPE_META[k]["bg"]};display:flex;align-items:center;justify-content:center;font-size:16px">{LANG_TYPE_META[k]["icon"]}</div>'
        f'<div style="flex:1"><div style="font-size:12px;font-weight:600;color:var(--color-text)">{LANG_TYPE_META[k]["label"]}</div>'
        f'<div style="font-size:11px;color:var(--color-text-muted)">{fmt_int(type_totals[k])} LOC</div></div>'
        f'<div style="font-size:14px;font-weight:700;color:{LANG_TYPE_META[k]["color"]}">{round(100*type_totals[k]/total_code,1)}%</div>'
        f'</div>'
        for k in type_order
    )

    legend_html = "".join(
        f'<div class="legend-item"><span class="legend-dot" style="background:{LANG_TYPE_META[k]["color"]}"></span>'
        f'<span>{LANG_TYPE_META[k]["label"]}</span>'
        f'<span class="legend-pct">{round(100*type_totals[k]/total_code,1)}%</span></div>'
        for k in type_order
    )

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">languages</div><div class="kpi-val">{len(langs)}</div><div class="kpi-sub">detected by cloc</div></div>
  <div class="kpi"><div class="kpi-label">dominant</div><div class="kpi-val">{langs[0][0] if langs else '—'}</div><div class="kpi-sub">{round(100*langs[0][1].code/total_code,1) if langs else 0}% of codebase</div></div>
  <div class="kpi"><div class="kpi-label">backend</div><div class="kpi-val">{round(100*type_totals.get('backend',0)/total_code,1)}%</div><div class="kpi-sub">Python + SQL + notebooks</div></div>
  <div class="kpi"><div class="kpi-label">frontend</div><div class="kpi-val">{round(100*type_totals.get('frontend',0)/total_code,1)}%</div><div class="kpi-sub">HTML + CSS + TS + JS</div></div>
</div>

<div class="section">
  <div class="sec-title">language type distribution</div>
  <div class="sec-sub">grouped by role in the stack</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:4px">{type_cards}</div>
</div>

<div class="section">
  <div class="sec-title">lines of code by language</div>
  <div class="sec-sub">top languages · color = type</div>
  <div style="display:grid;grid-template-columns:180px 1fr;gap:16px">
    <div style="display:flex;flex-direction:column;align-items:center">
      <div style="position:relative;width:140px;height:140px;margin:0 auto 12px">
        <canvas id="lang-donut" width="140" height="140"></canvas>
        <div class="donut-center">
          <div class="donut-center-val">{len(langs)}</div>
          <div class="donut-center-lbl">languages</div>
        </div>
      </div>
      {legend_html}
    </div>
    <div id="lang-bars" style="display:flex;flex-direction:column;justify-content:center"></div>
  </div>
</div>

<div class="section">
  <div class="sec-title">all languages</div>
  <div class="sec-sub">complete breakdown · click headers to sort</div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search language..." oninput="langFilter(this.value)">
    <select class="filter-sel" onchange="langTypeFilter(this.value)">
      <option value="">all types</option>
      {"".join(f'<option value="{k}">{LANG_TYPE_META[k]["label"]}</option>' for k in LANG_TYPE_META)}
    </select>
    <span class="result-count" id="lang-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="langPerPage(this.value)"><option value="10" selected>10</option><option value="20">20</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="langSort('name')">language</th>
        <th>type</th>
        <th class="r" onclick="langSort('files')">files</th>
        <th class="r" onclick="langSort('code')">code</th>
        <th class="r" onclick="langSort('comment')">comment</th>
        <th class="r" onclick="langSort('blank')">blank</th>
        <th class="r" onclick="langSort('pct')">share</th>
      </tr></thead>
      <tbody id="lang-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="lang-pg"></div>
</div>
</div>

<script>
var _ld={rows_js_str},_ls={{data:[],filtered:[],page:1,pp:10,sort:'code',dir:-1,search:'',type:''}};
var _lm={max_code};
(function(){{
  _ls.data=_ld.slice();
  new Chart(document.getElementById('lang-donut'),{{
    type:'doughnut',
    data:{{labels:{donut_labels},datasets:[{{data:{donut_data},backgroundColor:{donut_colors},borderWidth:2,borderColor:'#1a1d2e',hoverOffset:4}}]}},
    options:{{responsive:false,cutout:'68%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+(c.raw/1000).toFixed(0)+'k LOC ('+(c.raw/{total_code}*100).toFixed(1)+'%)';}}}}}}}}}}
  }});
  var bEl=document.getElementById('lang-bars');
  _ld.slice(0,18).forEach(function(r){{
    var pct=Math.round(r.code/_lm*100);
    var loc=r.code>=1000?(r.code/1000).toFixed(0)+'k':r.code;
    var d=document.createElement('div');d.className='bar-row';
    d.innerHTML='<span class="bar-label" style="width:110px">'+r.name+'</span>'+
      '<div class="bar-track" style="height:14px"><div class="bar-fill" style="width:'+pct+'%;background:'+r.color+'22"></div>'+
      '<span class="bar-val" style="color:'+r.color+'">'+loc+'</span></div>'+
      '<span class="badge" style="background:'+r.bg+';color:'+r.color+';width:60px;text-align:center">'+r.typeLabel+'</span>';
    bEl.appendChild(d);
  }});
  langApply();
}})();
function langFilter(v){{_ls.search=v.toLowerCase();_ls.page=1;langApply();}}
function langTypeFilter(v){{_ls.type=v;_ls.page=1;langApply();}}
function langPerPage(v){{_ls.pp=parseInt(v);_ls.page=1;langApply();}}
function langSort(col){{if(_ls.sort===col)_ls.dir*=-1;else{{_ls.sort=col;_ls.dir=col==='name'?1:-1;}} _ls.page=1;langApply();}}
function langApply(){{
  var d=_ls.data.slice();
  if(_ls.search)d=d.filter(function(r){{return r.name.toLowerCase().includes(_ls.search);}});
  if(_ls.type)d=d.filter(function(r){{return r.type===_ls.type;}});
  var col=_ls.sort;
  d.sort(function(a,b){{var av=typeof a[col]==='number'?a[col]:(a[col]||'').toLowerCase();var bv=typeof b[col]==='number'?b[col]:(b[col]||'').toLowerCase();return av<bv?_ls.dir:av>bv?-_ls.dir:0;}});
  _ls.filtered=d;
  document.getElementById('lang-count').textContent=d.length+' items';
  var start=(_ls.page-1)*_ls.pp,page=d.slice(start,start+_ls.pp);
  var tb=document.getElementById('lang-tbody');tb.innerHTML='';
  page.forEach(function(r){{
    var tr=document.createElement('tr');
    tr.innerHTML='<td style="font-weight:600;font-size:12px">'+r.name+'</td>'+
      '<td><span class="badge" style="background:'+r.bg+';color:'+r.color+'">'+r.typeLabel+'</span></td>'+
      '<td class="r">'+r.files.toLocaleString()+'</td>'+
      '<td class="r" style="font-weight:600">'+r.code.toLocaleString()+'</td>'+
      '<td class="r">'+r.comment.toLocaleString()+'</td>'+
      '<td class="r">'+r.blank.toLocaleString()+'</td>'+
      '<td class="r">'+r.pct.toFixed(1)+'%<span class="share-bar"><span class="share-fill" style="width:'+Math.min(100,r.pct*3).toFixed(1)+'%;background:'+r.color+'"></span></span></td>';
    tb.appendChild(tr);
  }});
  renderPg('lang',_ls,langApply);
}}
</script>
"""

# ── TAB 4: CODE COVERAGE ───────────────────────────────────────────────────────

def _cov_color(pct: Optional[float]) -> str:
    if pct is None: return "#888780"
    return "#3B6D11" if pct >= 95 else ("#854F0B" if pct >= 85 else "#A32D2D")

def _cov_bg(pct: Optional[float]) -> str:
    if pct is None: return "#F1EFE8"
    return "#EAF3DE" if pct >= 95 else ("#FAEEDA" if pct >= 85 else "#FCEBEB")

def coverage_section_html(df: pd.DataFrame, timestamp: str) -> str:
    valid   = df[df["coverage_pct"].notna()].copy()
    covered = len(valid)
    avg_cov = float(valid["coverage_pct"].mean()) if covered else 0.0
    excellent = int((valid["coverage_pct"] >= 95).sum()) if covered else 0
    good_cnt  = int(valid["coverage_pct"].between(85, 95, inclusive="left").sum()) if covered else 0
    below_85  = int((valid["coverage_pct"] < 85).sum()) if covered else 0
    no_data   = len(df) - covered

    rows_js = []
    for _, row in df.iterrows():
        pct = row.get("coverage_pct")
        rows_js.append(json.dumps({
            "repo":      str(row.get("repo", "")),
            "status":    str(row.get("status", "")),
            "pct":       round(float(pct), 2) if pct is not None and pct == pct else None,
            "stmts":     int(row["statements"]) if row.get("statements") == row.get("statements") and row.get("statements") is not None else None,
            "missed":    int(row["missed"])     if row.get("missed")     == row.get("missed")     and row.get("missed")     is not None else None,
            "branches":  int(row["branches"])   if row.get("branches")   == row.get("branches")   and row.get("branches")   is not None else None,
            "failUnder": float(row["fail_under"]) if row.get("fail_under") == row.get("fail_under") and row.get("fail_under") is not None else None,
            "color":     _cov_color(pct if pct == pct else None),
            "bg":        _cov_bg(pct if pct == pct else None),
        }))
    rows_js_str = "[" + ",".join(rows_js) + "]"

    return f"""
<div class="tab-section">
<div style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px">best-effort pytest collection · {timestamp}</div>
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">repos scanned</div><div class="kpi-val">{len(df)}</div><div class="kpi-sub">full ecosystem</div></div>
  <div class="kpi"><div class="kpi-label">with data</div><div class="kpi-val">{covered}</div><div class="kpi-sub">coverage collected</div></div>
  <div class="kpi"><div class="kpi-label">average</div><div class="kpi-val" style="color:#3B6D11">{avg_cov:.1f}%</div><div class="kpi-sub">across {covered} repos</div></div>
  <div class="kpi"><div class="kpi-label">excellent ≥95%</div><div class="kpi-val" style="color:#3B6D11">{excellent}</div><div class="kpi-sub">repos</div></div>
  <div class="kpi"><div class="kpi-label">needs attention</div><div class="kpi-val" style="color:#A32D2D">{below_85}</div><div class="kpi-sub">below 85%</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 200px;gap:12px;margin-bottom:12px">
  <div class="section">
    <div class="sec-title">coverage by repository</div>
    <div class="sec-sub">sorted high to low</div>
    <div style="position:relative;height:260px"><canvas id="cov-bar"></canvas></div>
  </div>
  <div class="section" style="display:flex;flex-direction:column">
    <div class="sec-title">band distribution</div>
    <div class="sec-sub">repos per band</div>
    <div style="position:relative;width:120px;height:120px;margin:0 auto 12px">
      <canvas id="cov-donut" width="120" height="120"></canvas>
      <div class="donut-center">
        <div class="donut-center-val">{covered}</div>
        <div class="donut-center-lbl">repos</div>
      </div>
    </div>
    <div>
      {"".join(f'<div class="legend-item"><span class="legend-dot" style="background:{c}"></span><span>{lbl}</span><span class="legend-pct">{cnt}</span></div>' for c,lbl,cnt in [('#3B6D11','≥95%',excellent),('#854F0B','85–94%',good_cnt),('#A32D2D','<85%',below_85),('#888780','no data',no_data)])}
    </div>
  </div>
</div>

<div class="section">
  <div class="sec-title">coverage summary</div>
  <div class="sec-sub">all repos · status · thresholds · click headers to sort</div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search repo..." oninput="covFilter(this.value)">
    <select class="filter-sel" onchange="covBandFilter(this.value)">
      <option value="">all bands</option>
      <option value="excellent">excellent ≥95%</option>
      <option value="good">good 85–94%</option>
      <option value="low">needs attention</option>
      <option value="none">no data</option>
    </select>
    <span class="result-count" id="cov-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="covPerPage(this.value)"><option value="10" selected>10</option><option value="20">20</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="covSort('repo')">repository</th>
        <th onclick="covSort('status')">status</th>
        <th onclick="covSort('pct')">coverage</th>
        <th class="r" onclick="covSort('stmts')">statements</th>
        <th class="r" onclick="covSort('missed')">missed</th>
        <th class="r" onclick="covSort('branches')">branches</th>
        <th class="r" onclick="covSort('failUnder')">fail under</th>
      </tr></thead>
      <tbody id="cov-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="cov-pg"></div>
</div>
</div>

<script>
var _cvd={rows_js_str},_cvs={{data:[],filtered:[],page:1,pp:10,sort:'pct',dir:-1,search:'',band:''}};
(function(){{
  _cvs.data=_cvd.slice();
  var wd=_cvd.filter(function(r){{return r.pct!==null;}}).sort(function(a,b){{return b.pct-a.pct;}});
  new Chart(document.getElementById('cov-bar'),{{
    type:'bar',
    data:{{labels:wd.map(function(r){{return r.repo.replace('omnibioai-','').replace('omnibioai_','');}}),
           datasets:[{{data:wd.map(function(r){{return r.pct;}}),
                       backgroundColor:wd.map(function(r){{return r.color+'44';}}),
                       borderColor:wd.map(function(r){{return r.color;}}),
                       borderWidth:1,borderRadius:4}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.parsed.y.toFixed(2)+'%';}}}}}}}},
      scales:{{y:{{min:0,max:102,ticks:{{callback:function(v){{return v+'%';}},font:{{size:10}},color:'#9CA3AF'}},grid:{{color:'rgba(0,0,0,0.04)'}},border:{{display:false}}}},
               x:{{ticks:{{font:{{size:9}},color:'#9CA3AF',maxRotation:45,autoSkip:false}},grid:{{display:false}},border:{{display:false}}}}}}}}
  }});
  new Chart(document.getElementById('cov-donut'),{{
    type:'doughnut',
    data:{{labels:['≥95%','85–94%','<85%','no data'],
           datasets:[{{data:[{excellent},{good_cnt},{below_85},{no_data}],
                       backgroundColor:['#3B6D11','#854F0B','#A32D2D','#888780'],
                       borderWidth:2,borderColor:'#1a1d2e',hoverOffset:3}}]}},
    options:{{responsive:false,cutout:'68%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+c.raw+' repos';}}}}}}}}}}
  }});
  covApply();
}})();
function covFilter(v){{_cvs.search=v.toLowerCase();_cvs.page=1;covApply();}}
function covBandFilter(v){{_cvs.band=v;_cvs.page=1;covApply();}}
function covPerPage(v){{_cvs.pp=parseInt(v);_cvs.page=1;covApply();}}
function covSort(col){{if(_cvs.sort===col)_cvs.dir*=-1;else{{_cvs.sort=col;_cvs.dir=col==='repo'||col==='status'?1:-1;}} _cvs.page=1;covApply();}}
function covApply(){{
  var d=_cvs.data.slice();
  if(_cvs.search)d=d.filter(function(r){{return r.repo.toLowerCase().includes(_cvs.search);}});
  if(_cvs.band){{
    d=d.filter(function(r){{
      if(_cvs.band==='excellent')return r.pct!==null&&r.pct>=95;
      if(_cvs.band==='good')return r.pct!==null&&r.pct>=85&&r.pct<95;
      if(_cvs.band==='low')return r.pct!==null&&r.pct<85;
      if(_cvs.band==='none')return r.pct===null;
      return true;
    }});
  }}
  var col=_cvs.sort;
  d.sort(function(a,b){{
    var av=a[col]===null?-999:typeof a[col]==='number'?a[col]:(a[col]||'').toLowerCase();
    var bv=b[col]===null?-999:typeof b[col]==='number'?b[col]:(b[col]||'').toLowerCase();
    return av<bv?_cvs.dir:av>bv?-_cvs.dir:0;
  }});
  _cvs.filtered=d;
  document.getElementById('cov-count').textContent=d.length+' items';
  var start=(_cvs.page-1)*_cvs.pp,page=d.slice(start,start+_cvs.pp);
  var tb=document.getElementById('cov-tbody');tb.innerHTML='';
  page.forEach(function(r){{
    var pctHtml=r.pct!==null
      ?'<div style="font-size:12px;font-weight:600;color:'+r.color+'">'+r.pct.toFixed(2)+'%</div>'+
        '<div style="height:4px;background:#2a2d3e;border-radius:2px;margin-top:3px;overflow:hidden">'+
        '<div style="height:100%;width:'+r.pct.toFixed(1)+'%;background:'+r.color+';border-radius:2px"></div></div>'
      :'<span style="color:#6b7280;font-size:12px">—</span>';
    var stBg=r.status==='ok'?'#EAF3DE':r.status.includes('skip')||r.status.includes('missing')?'#F1EFE8':'#FAEEDA';
    var stCol=r.status==='ok'?'#3B6D11':r.status.includes('skip')||r.status.includes('missing')?'#444441':'#854F0B';
    var stLbl=r.status==='ok'?'ok':r.status.includes('skip')?'skipped':r.status.includes('miss')?'missing':r.status.startsWith('error')?'error':'partial';
    var tr=document.createElement('tr');
    var short=r.repo.replace('omnibioai-','').replace('omnibioai_','').replace('omnibioai','omnibioai');
    tr.innerHTML='<td style="font-weight:600;font-size:12px">'+short+'</td>'+
      '<td><span class="badge" style="background:'+stBg+';color:'+stCol+'">'+stLbl+'</span></td>'+
      '<td style="min-width:120px">'+pctHtml+'</td>'+
      '<td class="r">'+(r.stmts!==null?r.stmts.toLocaleString():'—')+'</td>'+
      '<td class="r">'+(r.missed!==null?r.missed.toLocaleString():'—')+'</td>'+
      '<td class="r">'+(r.branches!==null?r.branches.toLocaleString():'—')+'</td>'+
      '<td class="r">'+(r.failUnder!==null?r.failUnder:'—')+'</td>';
    tb.appendChild(tr);
  }});
  renderPg('cov',_cvs,covApply);
}}
</script>
"""

# ── TAB 5: HEALTH STATUS ───────────────────────────────────────────────────────

def health_section_html(health: EcosystemHealth, control_center_url: str) -> str:
    cc_url = control_center_url.rstrip("/")
    return f"""
<div class="tab-section">
<div id="hlth-banner" style="border-radius:12px;padding:12px 16px;display:flex;align-items:center;gap:10px;margin-bottom:16px;border:0.5px solid var(--color-border);background:var(--color-bg-surface)">
  <span class="status-dot dot-loading" id="hlth-dot"></span>
  <div style="flex:1">
    <div style="font-size:13px;font-weight:600;color:var(--color-text)" id="hlth-title">fetching health data...</div>
    <div style="font-size:11px;color:var(--color-text-muted);margin-top:2px" id="hlth-sub">connecting to control center</div>
  </div>
  <span style="font-size:11px;color:var(--color-text-muted)" id="hlth-countdown">next refresh in 30s</span>
  <button onclick="hlthFetch()" style="display:flex;align-items:center;gap:5px;padding:6px 12px;border:0.5px solid var(--color-border);border-radius:8px;background:var(--color-bg-surface);font-size:12px;color:var(--color-text-muted);cursor:pointer">↻ refresh</button>
</div>

<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">monitored</div><div class="kpi-val" id="hk-total">—</div><div class="kpi-sub">services</div></div>
  <div class="kpi"><div class="kpi-label">healthy</div><div class="kpi-val" id="hk-up" style="color:#3B6D11">—</div><div class="kpi-sub">UP</div></div>
  <div class="kpi"><div class="kpi-label">down</div><div class="kpi-val" id="hk-down" style="color:#A32D2D">—</div><div class="kpi-sub">need attention</div></div>
  <div class="kpi"><div class="kpi-label">degraded</div><div class="kpi-val" id="hk-warn" style="color:#854F0B">—</div><div class="kpi-sub">WARN</div></div>
  <div class="kpi"><div class="kpi-label">disk warnings</div><div class="kpi-val" id="hk-disk">—</div><div class="kpi-sub">paths checked</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
  <div class="section">
    <div class="sec-title">status distribution</div>
    <div class="sec-sub">across all monitored services</div>
    <div style="display:flex;align-items:center;gap:16px">
      <div style="position:relative;width:100px;height:100px;flex-shrink:0">
        <canvas id="hlth-donut" width="100" height="100"></canvas>
        <div class="donut-center"><div class="donut-center-val" id="hlth-up-val">—</div><div class="donut-center-lbl" id="hlth-of-lbl">of — UP</div></div>
      </div>
      <div>
        <div class="legend-item"><span class="legend-dot" style="background:#3B6D11;border-radius:50%"></span><span>healthy</span><span class="legend-pct" id="hl-up">—</span></div>
        <div class="legend-item"><span class="legend-dot" style="background:#A32D2D;border-radius:50%"></span><span>down</span><span class="legend-pct" id="hl-down">—</span></div>
        <div class="legend-item"><span class="legend-dot" style="background:#854F0B;border-radius:50%"></span><span>degraded</span><span class="legend-pct" id="hl-warn">—</span></div>
      </div>
    </div>
  </div>
  <div class="section">
    <div class="sec-title">response latency</div>
    <div class="sec-sub">per service · proportional bars · color = health</div>
    <div id="hlth-lat-bars"><div style="font-size:12px;color:#6b7280">loading...</div></div>
  </div>
</div>

<div style="font-size:11px;font-weight:600;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">services</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px;margin-bottom:12px" id="hlth-svc-grid">
  <div style="font-size:12px;color:var(--color-text-muted);grid-column:1/-1">loading service cards...</div>
</div>

<div class="section">
  <div class="sec-title">disk checks</div>
  <div class="sec-sub">storage paths monitored by control center</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px" id="hlth-disk-grid">
    <div style="font-size:12px;color:var(--color-text-muted)">loading...</div>
  </div>
</div>
</div>

<script>
var _hChart=null,_hTimer=null,_hCd=30,_hUrl='';
var _hIcons={{mysql:'🗄️',redis:'⚡',http:'🌐',tcp:'🔌'}};
function _hLatCol(ms){{return ms<5?'#3B6D11':ms<20?'#854F0B':'#A32D2D';}}
function hlthFetch(){{
  clearInterval(_hTimer);_hCd=30;
  fetch(_hUrl+'/summary').then(function(r){{return r.json();}}).then(function(d){{
    _hlthRender(d);_hStartCd();
  }}).catch(function(){{_hlthError();_hStartCd();}});
}}
function _hStartCd(){{
  _hTimer=setInterval(function(){{
    _hCd--;
    document.getElementById('hlth-countdown').textContent='next refresh in '+_hCd+'s';
    if(_hCd<=0){{clearInterval(_hTimer);hlthFetch();}}
  }},1000);
}}
function _hlthRender(data){{
  var svcs=data.services||[];var disk=(data.system||{{}}).disk||[];
  var ov=(data.overall_status||'UNKNOWN').toUpperCase();
  var ts=data.generated_at||'';
  var up=svcs.filter(function(s){{return s.status==='UP';}}).length;
  var dn=svcs.filter(function(s){{return s.status==='DOWN';}}).length;
  var wn=svcs.filter(function(s){{return s.status==='WARN';}}).length;
  var dw=disk.filter(function(d){{return d.status!=='UP';}}).length;
  var bn=document.getElementById('hlth-banner');
  var bgMap={{UP:'#EAF3DE',DOWN:'#FCEBEB',WARN:'#FAEEDA'}};
  var bdMap={{UP:'#97C459',DOWN:'#E24B4A',WARN:'#EF9F27'}};
  bn.style.background=bgMap[ov]||'#1a1d2e';bn.style.borderColor=bdMap[ov]||'#2a2d3e';
  document.getElementById('hlth-dot').className='status-dot dot-'+(ov==='UP'?'up':ov==='DOWN'?'down':'warn');
  document.getElementById('hlth-title').textContent=ov==='UP'?'All systems operational':ov==='DOWN'?'One or more services are down':'One or more services degraded';
  document.getElementById('hlth-sub').textContent='Checked: '+(ts?new Date(ts).toLocaleTimeString():'')+' · Source: Control Center /summary';
  document.getElementById('hk-total').textContent=svcs.length;
  document.getElementById('hk-up').textContent=up;
  document.getElementById('hk-down').textContent=dn;
  document.getElementById('hk-warn').textContent=wn;
  document.getElementById('hk-disk').textContent=dw;
  document.getElementById('hl-up').textContent=up;
  document.getElementById('hl-down').textContent=dn;
  document.getElementById('hl-warn').textContent=wn;
  document.getElementById('hlth-up-val').textContent=up;
  document.getElementById('hlth-of-lbl').textContent='of '+svcs.length+' UP';
  if(_hChart)_hChart.destroy();
  _hChart=new Chart(document.getElementById('hlth-donut'),{{
    type:'doughnut',
    data:{{labels:['healthy','down','degraded'],
           datasets:[{{data:[up,dn,wn],backgroundColor:['#22c55e','#ef4444','#f59e0b'],borderWidth:2,borderColor:'#1a1d2e',hoverOffset:3}}]}},
    options:{{responsive:false,cutout:'70%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+c.raw;}}}}}}}}}}
  }});
  var latEl=document.getElementById('hlth-lat-bars');latEl.innerHTML='';
  var wl=svcs.filter(function(s){{return s.latency_ms!==null&&s.latency_ms!==undefined;}});
  var ml=Math.max.apply(null,wl.map(function(s){{return s.latency_ms;}}));if(!ml)ml=1;
  if(wl.length===0){{latEl.innerHTML='<div style="font-size:12px;color:#6b7280">no latency data</div>';}}
  wl.forEach(function(s){{
    var pct=Math.round(s.latency_ms/ml*100);var c=_hLatCol(s.latency_ms);
    var d=document.createElement('div');d.className='bar-row';
    d.innerHTML='<span class="bar-label" style="width:100px" title="'+s.name+'">'+s.name+'</span>'+
      '<div class="bar-track" style="height:14px"><div class="bar-fill" style="width:'+pct+'%;background:'+c+'33"></div>'+
      '<span class="bar-val" style="color:'+c+'">'+s.latency_ms+' ms</span></div>';
    latEl.appendChild(d);
  }});
  var grid=document.getElementById('hlth-svc-grid');grid.innerHTML='';
  svcs.forEach(function(s){{
    var sc=s.status==='UP'?'up':s.status==='DOWN'?'down':'warn';
    var bgC={{up:'#F0FDF4',down:'#FEF2F2',warn:'#FFFBEB'}};
    var bdC={{up:'#97C459',down:'#E24B4A',warn:'#EF9F27'}};
    var stC={{up:'#3B6D11',down:'#A32D2D',warn:'#854F0B'}};
    var icon=_hIcons[s.type]||'⚙️';
    var latH=s.latency_ms!=null?'<span style="color:'+_hLatCol(s.latency_ms)+';font-weight:600">'+s.latency_ms+' ms</span>':'—';
    var openH=s.ui_url?'<a href="'+s.ui_url+'" style="font-size:11px;color:#0094ff;display:inline-flex;align-items:center;gap:3px;margin-top:8px;text-decoration:none" target="_blank">open UI ↗</a>':'';
    var card=document.createElement('div');
    card.style.cssText='background:'+bgC[sc]+';border:1px solid '+bdC[sc]+'33;border-left:4px solid '+bdC[sc]+';border-radius:12px;padding:14px';
    card.innerHTML='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">'+
      '<div style="display:flex;align-items:center;gap:7px"><span style="font-size:18px">'+icon+'</span>'+
      '<span style="font-size:13px;font-weight:600;color:#ffffff">'+s.name+'</span></div>'+
      '<span class="badge" style="background:'+stC[sc]+'22;color:'+stC[sc]+'">'+s.status+'</span></div>'+
      '<div style="display:grid;grid-template-columns:60px 1fr;gap:3px 8px;font-size:11px">'+
      '<span style="color:#6b7280">target</span><span style="color:#6b7280;font-family:monospace;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+s.target+'</span>'+
      '<span style="color:#6b7280">latency</span><span>'+latH+'</span>'+
      '<span style="color:#6b7280">message</span><span style="color:#6b7280">'+(s.message||'—')+'</span>'+
      '</div>'+openH;
    grid.appendChild(card);
  }});
  var dg=document.getElementById('hlth-disk-grid');dg.innerHTML='';
  if(disk.length===0){{dg.innerHTML='<div style="font-size:12px;color:#6b7280">no disk checks configured</div>';return;}}
  disk.forEach(function(d){{
    var m=(d.message||'').match(/([0-9.]+)%/);var pct=m?parseFloat(m[1]):0;
    var c=d.status==='UP'?'#3B6D11':d.status==='WARN'?'#854F0B':'#A32D2D';
    var card=document.createElement('div');
    card.style.cssText='background:#1a1d2e;border-radius:8px;padding:10px 12px';
    card.innerHTML='<div style="display:flex;justify-content:space-between;margin-bottom:4px">'+
      '<span style="font-size:12px;font-weight:600;color:#ffffff">'+d.name.replace('disk:','')+'</span>'+
      '<span style="font-size:11px;font-weight:600;color:'+c+'">'+d.message+'</span></div>'+
      '<div style="font-size:10px;color:#6b7280;margin-bottom:6px">'+d.target+'</div>'+
      '<div style="background:#2a2d3e;border-radius:3px;height:5px;overflow:hidden">'+
      '<div style="width:'+Math.min(100,pct).toFixed(1)+'%;height:100%;background:'+c+';border-radius:3px"></div></div>';
    dg.appendChild(card);
  }});
}}
function _hlthError(){{
  document.getElementById('hlth-dot').className='status-dot dot-down';
  document.getElementById('hlth-title').textContent='Control center unreachable';
  document.getElementById('hlth-sub').textContent='Check that the control center is running on the configured URL';
  ['hk-total','hk-up','hk-down','hk-warn','hk-disk'].forEach(function(id){{document.getElementById(id).textContent='—';}});
  document.getElementById('hlth-svc-grid').innerHTML='<div style="font-size:12px;color:#6b7280;grid-column:1/-1">unable to reach '+_hUrl+'/summary</div>';
  document.getElementById('hlth-disk-grid').innerHTML='<div style="font-size:12px;color:#6b7280">no data</div>';
  document.getElementById('hlth-lat-bars').innerHTML='<div style="font-size:12px;color:#6b7280">no data</div>';
}}
hlthFetch();
</script>
"""

def llm_section_html(control_center_url: str) -> str:
    """Fetch Ollama models and API key status from control center."""
    import urllib.request, json

    models = []
    api_keys = {}
    ollama_status = "unreachable"

    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/llms", timeout=5
        ) as r:
            data = json.loads(r.read())
            models = data.get("ollama", {}).get("models", [])
            ollama_status = data.get("ollama", {}).get("status", "unknown")
            api_keys = data.get("api_keys", {})
    except Exception:
        pass

    model_rows = ""
    for m in models:
        size = m.get("size_gb", 0)
        name = m.get("name", "")
        modified = m.get("modified", "")
        model_rows += f"""
          <tr>
            <td style="padding:10px 16px;font-family:monospace;color:#a855f7">{name}</td>
            <td style="padding:10px 16px;color:var(--color-text-soft)">{size} GB</td>
            <td style="padding:10px 16px;color:var(--color-text-muted)">{modified}</td>
          </tr>"""

    if not model_rows:
        model_rows = '<tr><td colspan="3" style="padding:20px 16px;color:var(--color-text-muted)">No models installed or Ollama unreachable</td></tr>'

    key_rows = ""
    for key, info in api_keys.items():
        configured = info.get("configured", False)
        label = info.get("label", key)
        badge_color = "#00e5a0" if configured else "#6b7280"
        badge_bg = "rgba(0,229,160,0.15)" if configured else "rgba(107,114,128,0.15)"
        badge_text = "CONFIGURED" if configured else "NOT SET"
        key_rows += f"""
          <tr>
            <td style="padding:10px 16px;color:var(--color-text)">{label}</td>
            <td style="padding:10px 16px">
              <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;
                background:{badge_bg};color:{badge_color};
                border:1px solid {badge_color}33">{badge_text}</span>
            </td>
          </tr>"""

    if not key_rows:
        key_rows = '<tr><td colspan="2" style="padding:20px 16px;color:var(--color-text-muted)">No API key data available</td></tr>'

    ollama_badge = "🟢 running" if ollama_status == "running" else "🔴 unreachable"

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Local LLMs</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    Ollama models installed on this machine · API key configuration status
  </p>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden;margin-bottom:20px">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border);
      display:flex;align-items:center;justify-content:space-between">
      <span style="font-weight:700;font-size:13px">Ollama — Local LLMs</span>
      <span style="font-size:12px;color:var(--color-text-muted)">{ollama_badge}</span>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="border-bottom:1px solid var(--color-border);
          background:rgba(255,255,255,0.02)">
          <th style="padding:8px 16px;text-align:left;font-size:10px;
            font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
            color:var(--color-text-muted)">Model</th>
          <th style="padding:8px 16px;text-align:left;font-size:10px;
            font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
            color:var(--color-text-muted)">Size</th>
          <th style="padding:8px 16px;text-align:left;font-size:10px;
            font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
            color:var(--color-text-muted)">Modified</th>
        </tr>
      </thead>
      <tbody>{model_rows}</tbody>
    </table>
  </div>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
      <span style="font-weight:700;font-size:13px">Cloud API Keys</span>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <tbody>{key_rows}</tbody>
    </table>
  </div>
</div>"""


def cloud_section_html(control_center_url: str) -> str:
    """Fetch cloud/HPC execution backend config from control center."""
    import urllib.request, json

    backends = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/cloud", timeout=5
        ) as r:
            backends = json.loads(r.read())
    except Exception:
        pass

    ICONS = {
        "local": "🖥", "slurm": "⚡", "aws": "☁️",
        "azure": "🔷", "gcp": "🟡", "kubernetes": "⎈"
    }

    cards = ""
    for key, info in backends.items():
        configured = info.get("configured", False)
        label = info.get("label", key)
        icon = ICONS.get(key, "🔧")
        border = "rgba(0,229,160,0.25)" if configured else "var(--color-border)"
        badge_color = "#00e5a0" if configured else "#6b7280"
        badge_bg = "rgba(0,229,160,0.15)" if configured else "rgba(107,114,128,0.15)"
        badge_text = "✓ CONFIGURED" if configured else "NOT CONFIGURED"

        details = ""
        for field in ["region", "project", "account", "queue", "host", "context", "note"]:
            val = info.get(field, "")
            if val:
                details += f"""<div style="display:flex;gap:8px;font-size:11px;margin-top:4px">
                  <span style="color:var(--color-text-muted);min-width:60px">{field}</span>
                  <span style="font-family:monospace;color:var(--color-text-soft)">{val}</span>
                </div>"""

        cards += f"""
          <div style="background:var(--color-bg-surface);
            border:1px solid {border};border-radius:10px;
            padding:16px 18px">
            <div style="display:flex;align-items:center;
              justify-content:space-between;margin-bottom:8px">
              <div style="display:flex;align-items:center;gap:8px">
                <span style="font-size:20px">{icon}</span>
                <span style="font-weight:700;font-size:14px">{label}</span>
              </div>
              <span style="font-size:10px;font-weight:700;padding:2px 8px;
                border-radius:99px;background:{badge_bg};color:{badge_color};
                border:1px solid {badge_color}33">{badge_text}</span>
            </div>
            {details}
          </div>"""

    if not cards:
        cards = '<p style="color:var(--color-text-muted)">Could not reach control center</p>'

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Execution Backends</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    Cloud and HPC execution backend configuration status
  </p>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px">
    {cards}
  </div>
</div>"""


def reference_section_html(control_center_url: str) -> str:
    """Fetch reference genome data status from control center."""
    import urllib.request, json

    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/reference", timeout=5
        ) as r:
            data = json.loads(r.read())
    except Exception:
        pass

    if not data.get("available"):
        ref_root = data.get("ref_root", "omnibioai-data/reference/")
        return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Reference Data</h2>
  <p style="color:var(--color-text-muted);font-size:13px">
    Reference data directory not found. Expected at:
    <code style="font-family:monospace;color:#a855f7">{ref_root}</code>
  </p>
</div>"""

    organisms = data.get("organisms", [])
    databases = data.get("databases", {})

    ORGANISM_ICONS = {
        "human": "🧬", "mouse": "🐭", "rat": "🐀",
        "zebrafish": "🐟", "drosophila": "🪰", "yeast": "🧫",
        "chimpanzee": "🐒", "macaque": "🐵",
        "celegans": "🪱", "arabidopsis": "🌿", "pig": "🐷", "chicken": "🐔",
    }
    ORGANISM_LABELS = {
        "human": "Human", "mouse": "Mouse", "rat": "Rat",
        "zebrafish": "Zebrafish", "drosophila": "Drosophila", "yeast": "Yeast",
        "chimpanzee": "Chimpanzee", "macaque": "Macaque",
        "celegans": "C. elegans", "arabidopsis": "Arabidopsis",
        "pig": "Pig", "chicken": "Chicken",
    }

    def check(ok: bool) -> str:
        color = "#00e5a0" if ok else "#374151"
        mark = "✓" if ok else "·"
        return f'<span style="color:{color};font-size:14px">{mark}</span>'

    org_rows = ""
    for org in organisms:
        name = org["organism"]
        assembly = org["assembly"]
        icon = ORGANISM_ICONS.get(name, "🧬")
        label = ORGANISM_LABELS.get(name, name.title())
        indexes = org.get("indexes", {})
        variants = org.get("variants", {})

        idx_cells = "".join(
            f'<td style="padding:8px 12px;text-align:center">{check(indexes.get(idx, False))}</td>'
            for idx in ["star", "bwa", "bowtie2", "salmon", "cellranger"]
        )
        var_cells = "".join(
            f'<td style="padding:8px 12px;text-align:center">{check(variants.get(vdb, False))}</td>'
            for vdb in ["clinvar", "dbsnp", "gnomad", "cosmic"]
        )

        org_rows += f"""
        <tr style="border-bottom:1px solid var(--color-border)">
          <td style="padding:8px 16px;font-weight:600;color:var(--color-text)">{icon} {label}</td>
          <td style="padding:8px 12px;font-family:monospace;font-size:11px;color:#a855f7">{assembly}</td>
          {idx_cells}
          {var_cells}
        </tr>"""

    if not org_rows:
        org_rows = '<tr><td colspan="11" style="padding:20px 16px;color:var(--color-text-muted)">No reference organisms found</td></tr>'

    DB_LABELS = {
        "clinvar": "ClinVar", "cosmic": "COSMIC", "dbsnp": "dbSNP",
        "gnomad": "gnomAD", "go": "Gene Ontology", "interpro": "InterPro",
        "pfam": "Pfam", "uniprot": "UniProt"
    }
    db_cards = ""
    for db, present in databases.items():
        color = "#00e5a0" if present else "#6b7280"
        bg = "rgba(0,229,160,0.1)" if present else "rgba(107,114,128,0.1)"
        label = DB_LABELS.get(db, db.upper())
        status = "✓ Available" if present else "Not downloaded"
        db_cards += f"""
        <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
          border-radius:8px;padding:12px 14px;display:flex;
          align-items:center;justify-content:space-between">
          <span style="font-size:13px;font-weight:600;color:var(--color-text)">{label}</span>
          <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;
            background:{bg};color:{color}">{status}</span>
        </div>"""

    if not db_cards:
        db_cards = '<p style="color:var(--color-text-muted);padding:16px">No database info available</p>'

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Reference Data</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    Reference genomes, indexes, and databases available on this machine
  </p>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden;margin-bottom:20px">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
      <span style="font-weight:700;font-size:13px">Reference Genomes &amp; Indexes</span>
    </div>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead>
          <tr style="border-bottom:1px solid var(--color-border);background:rgba(255,255,255,0.02)">
            <th style="padding:8px 16px;text-align:left;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">Organism</th>
            <th style="padding:8px 12px;text-align:left;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">Assembly</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">STAR</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">BWA</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">Bowtie2</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">Salmon</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">CellRanger</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">ClinVar</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">dbSNP</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">gnomAD</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">COSMIC</th>
          </tr>
        </thead>
        <tbody>{org_rows}</tbody>
      </table>
    </div>
    <p style="font-size:11px;color:var(--color-text-muted);margin-top:8px;padding:0 4px">
      * Zebrafish (GRCz11) STAR index requires 141GB RAM —
      exceeds DGX Spark capacity (128GB).
      Salmon and Bowtie2 indexes available.
      STAR index will be added post-launch.
    </p>
  </div>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
      <span style="font-weight:700;font-size:13px">Annotation Databases</span>
    </div>
    <div style="padding:16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px">
      {db_cards}
    </div>
  </div>
</div>"""


def knowledge_base_section_html(control_center_url: str) -> str:
    """Fetch AI knowledge base stats from control center."""
    import urllib.request, json

    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/knowledge-base", timeout=120
        ) as r:
            data = json.loads(r.read())
    except Exception:
        pass

    if not data:
        return """
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">AI Knowledge Base</h2>
  <p style="color:var(--color-text-muted);font-size:13px">
    Could not reach control center for knowledge base stats.
  </p>
</div>"""

    abstracts = data.get("abstracts", {})
    faiss = data.get("faiss_index", {})
    rag_status = data.get("rag_status", "unknown")

    total_abstracts = abstracts.get("total", 0)
    domains_with_abstracts = abstracts.get("domains_with_abstracts", 0)
    domains_indexed = faiss.get("domains_indexed", 0)
    index_size_gb = faiss.get("size_gb", 0)
    domain_list = faiss.get("domain_list", [])

    rag_color = "#00e5a0" if rag_status == "running" else "#ef4444"
    rag_bg = "rgba(0,229,160,0.15)" if rag_status == "running" else "rgba(239,68,68,0.15)"

    def stat_card(value, label, color="#00e5a0"):
        return f"""
        <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
          border-radius:10px;padding:20px 24px;text-align:center">
          <div style="font-size:32px;font-weight:800;color:{color};
            font-family:var(--font-mono);margin-bottom:4px">{value}</div>
          <div style="font-size:11px;font-weight:600;color:var(--color-text-muted);
            text-transform:uppercase;letter-spacing:0.06em">{label}</div>
        </div>"""

    if total_abstracts >= 1_000_000:
        abs_display = f"{total_abstracts/1_000_000:.1f}M"
    elif total_abstracts >= 1_000:
        abs_display = f"{total_abstracts/1_000:.0f}K"
    else:
        abs_display = str(total_abstracts)

    domain_tags = ""
    for domain in domain_list:
        domain_tags += f"""
        <span style="display:inline-block;font-size:10px;padding:3px 8px;
          border-radius:99px;background:rgba(168,85,247,0.15);
          color:#a855f7;border:1px solid rgba(168,85,247,0.3);
          margin:2px;font-family:var(--font-mono)">{domain}</span>"""

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">AI Knowledge Base</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    PubMed literature indexed locally · FAISS vector search · RAG pipeline
  </p>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;padding:12px 16px;margin-bottom:16px;
    display:flex;align-items:center;justify-content:space-between">
    <span style="font-weight:700;font-size:13px">RAG Service</span>
    <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;
      background:{rag_bg};color:{rag_color}">{rag_status.upper()}</span>
  </div>

  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px">
    {stat_card(abs_display, "PubMed Abstracts")}
    {stat_card(domains_with_abstracts, "Domains Ingested", "#a855f7")}
    {stat_card(domains_indexed, "FAISS Indexes", "#f59e0b")}
    {stat_card(f"{index_size_gb} GB", "Index Size", "#06b6d4")}
  </div>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border);
      display:flex;align-items:center;justify-content:space-between">
      <span style="font-weight:700;font-size:13px">Indexed Domains (showing first 20)</span>
      <span style="font-size:11px;color:var(--color-text-muted)">{domains_indexed} total</span>
    </div>
    <div style="padding:14px 16px">
      {domain_tags if domain_tags else
        '<p style="color:var(--color-text-muted);font-size:12px">No domains indexed yet</p>'}
    </div>
  </div>
</div>"""


def storage_section_html(control_center_url: str) -> str:
    """Fetch disk/storage usage from control center."""
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/storage", timeout=120
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] storage_section_html failed: {type(e).__name__}: {e}", flush=True)

    if not data:
        return '<div class="tab-section"><h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Storage</h2><p style="color:var(--color-text-muted);font-size:13px">Unavailable</p></div>'

    disk = data.get("disk", {})
    total_gb = round(disk.get("total", 0) / 1e9, 1)
    used_gb  = round(disk.get("used",  0) / 1e9, 1)
    free_gb  = round(disk.get("free",  0) / 1e9, 1)
    pct_used = disk.get("pct_used", 0)
    pct_free = round(100 - pct_used, 1)

    categories = data.get("categories", {})
    ref_indexes = data.get("reference_indexes", {})

    def fmt_gb(b):
        gb = b / 1e9
        if gb >= 1:
            return f"{gb:.1f} GB"
        return f"{b/1e6:.0f} MB"

    bar_color = "#00e5a0" if pct_used < 80 else "#f59e0b" if pct_used < 90 else "#ef4444"

    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)

    CAT_COLORS = [
        "#00e5a0", "#a855f7", "#f59e0b", "#06b6d4",
        "#ef4444", "#8b5cf6", "#10b981", "#f97316"
    ]

    cat_cards = ""
    for i, (name, size) in enumerate(sorted_cats):
        color = CAT_COLORS[i % len(CAT_COLORS)]
        pct = round(size / disk.get("used", 1) * 100, 1)
        cat_cards += f"""
        <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
          border-radius:8px;padding:12px 16px;display:flex;align-items:center;
          justify-content:space-between;gap:12px">
          <div style="display:flex;align-items:center;gap:10px">
            <div style="width:10px;height:10px;border-radius:50%;
              background:{color};flex-shrink:0"></div>
            <span style="font-size:12px;font-weight:600;
              color:var(--color-text)">{name}</span>
          </div>
          <div style="text-align:right">
            <div style="font-size:13px;font-weight:700;
              color:{color}">{fmt_gb(size)}</div>
            <div style="font-size:10px;color:var(--color-text-muted)">{pct}%</div>
          </div>
        </div>"""

    sorted_orgs = sorted(ref_indexes.items(), key=lambda x: x[1], reverse=True)
    max_org_size = sorted_orgs[0][1] if sorted_orgs else 1

    ORG_ICONS = {
        "human": "🧬", "mouse": "🐭", "rat": "🐀",
        "zebrafish": "🐟", "drosophila": "🪰", "yeast": "🧫",
        "chimpanzee": "🐒", "macaque": "🐵", "celegans": "🪱",
        "arabidopsis": "🌿", "pig": "🐷", "chicken": "🐔",
    }
    org_bars = ""
    for org_key, size in sorted_orgs[:15]:
        org_name = org_key.split("_")[0]
        icon = ORG_ICONS.get(org_name, "🧬")
        pct_bar = round(size / max_org_size * 100)
        org_bars += f"""
        <div style="display:grid;grid-template-columns:140px 1fr 80px;
          gap:8px;align-items:center;margin-bottom:6px">
          <span style="font-size:11px;color:var(--color-text);
            font-family:var(--font-mono);overflow:hidden;
            text-overflow:ellipsis;white-space:nowrap">
            {icon} {org_key}
          </span>
          <div style="background:var(--color-border);border-radius:4px;height:8px">
            <div style="width:{pct_bar}%;height:100%;border-radius:4px;
              background:#a855f7"></div>
          </div>
          <span style="font-size:11px;color:var(--color-text-muted);
            text-align:right">{fmt_gb(size)}</span>
        </div>"""

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Storage</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    Disk usage · Reference data · Workflow outputs
  </p>

  <!-- Disk usage bar -->
  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;padding:20px;margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;
      align-items:baseline;margin-bottom:10px">
      <span style="font-weight:700;font-size:14px">NVMe Storage</span>
      <span style="font-size:12px;color:var(--color-text-muted)">
        {used_gb} GB used of {total_gb} GB
      </span>
    </div>
    <div style="background:var(--color-border);border-radius:6px;
      height:16px;overflow:hidden;margin-bottom:8px">
      <div style="width:{pct_used}%;height:100%;
        background:{bar_color};border-radius:6px;
        transition:width 0.3s ease"></div>
    </div>
    <div style="display:flex;justify-content:space-between">
      <span style="font-size:11px;color:{bar_color};font-weight:700">
        {pct_used}% used
      </span>
      <span style="font-size:11px;color:#00e5a0;font-weight:700">
        {free_gb} GB free ({pct_free}%)
      </span>
    </div>
  </div>

  <!-- Two column layout -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">

    <!-- Category breakdown -->
    <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
      border-radius:10px;overflow:hidden">
      <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
        <span style="font-weight:700;font-size:13px">Data Categories</span>
      </div>
      <div style="padding:12px;display:flex;flex-direction:column;gap:8px">
        {cat_cards if cat_cards else
          '<p style="color:var(--color-text-muted);font-size:12px;padding:8px">No data found</p>'}
      </div>
    </div>

    <!-- Reference index breakdown -->
    <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
      border-radius:10px;overflow:hidden">
      <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
        <span style="font-weight:700;font-size:13px">Reference Indexes by Organism</span>
      </div>
      <div style="padding:16px">
        {org_bars if org_bars else
          '<p style="color:var(--color-text-muted);font-size:12px">No indexes found</p>'}
      </div>
    </div>
  </div>
</div>"""


def docker_section_html_UNUSED(control_center_url: str) -> str:  # kept for reference; not included in report (duplicate of React DockerPage)
    cc_url = control_center_url.rstrip("/")
    return f"""
<div class="tab-section">

<!-- KPI strip -->
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">running / total</div><div class="kpi-val" id="dk-k-run">—</div><div class="kpi-sub">containers</div></div>
  <div class="kpi"><div class="kpi-label">SIF built</div><div class="kpi-val" id="dk-k-sif-ok" style="color:#22c55e">—</div><div class="kpi-sub">images</div></div>
  <div class="kpi"><div class="kpi-label">SIF missing</div><div class="kpi-val" id="dk-k-sif-miss" style="color:#ef4444">—</div><div class="kpi-sub">not built</div></div>
  <div class="kpi"><div class="kpi-label">SIF storage</div><div class="kpi-val" id="dk-k-gb">—</div><div class="kpi-sub">GB total</div></div>
  <div class="kpi"><div class="kpi-label">plugin images</div><div class="kpi-val" id="dk-k-plug">—</div><div class="kpi-sub">tracked</div></div>
  <div class="kpi"><div class="kpi-label">plugins present</div><div class="kpi-val" id="dk-k-plug-ok" style="color:#22c55e">—</div><div class="kpi-sub">local images</div></div>
</div>

<!-- Sub-tabs -->
<div style="display:flex;border-bottom:1px solid #2a2d3e;margin-bottom:16px">
  <button class="dk-sub" data-sub="containers" onclick="dkSub('containers')" style="padding:10px 16px;font-size:13px;color:#00e5a0;font-weight:600;background:none;border:none;border-bottom:2px solid #00e5a0;cursor:pointer;white-space:nowrap;margin-bottom:-1px;font-family:inherit">Platform Containers</button>
  <button class="dk-sub" data-sub="sif"        onclick="dkSub('sif')"        style="padding:10px 16px;font-size:13px;color:#6b7280;font-weight:400;background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap;margin-bottom:-1px;font-family:inherit">Tool SIF Images</button>
  <button class="dk-sub" data-sub="plugins"    onclick="dkSub('plugins')"    style="padding:10px 16px;font-size:13px;color:#6b7280;font-weight:400;background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap;margin-bottom:-1px;font-family:inherit">Plugin Docker Images</button>
</div>

<!-- Platform Containers -->
<div id="dk-containers">
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search containers…" oninput="dkCS(this.value)">
    <span class="result-count" id="dk-cont-count">—</span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>Container</th><th>Image</th><th>Status</th><th>Uptime</th><th>Ports</th></tr></thead>
      <tbody id="dk-cont-tbody"><tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="dk-cont-pg"></div>
</div>

<!-- Tool SIF Images -->
<div id="dk-sif" style="display:none">
  <div style="display:flex;gap:16px;align-items:flex-start">
    <div id="dk-sif-sidebar" style="width:154px;flex-shrink:0">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>
    </div>
    <div style="flex:1;min-width:0">
      <div class="filter-row">
        <input class="search-inp" type="text" placeholder="search tools…" oninput="dkSS(this.value)">
        <span class="result-count" id="dk-sif-count">—</span>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Tool</th><th>Category</th><th>Status</th><th>Size</th></tr></thead>
          <tbody id="dk-sif-tbody"><tr><td colspan="4" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
        </table>
      </div>
      <div class="pg-wrap" id="dk-sif-pg"></div>
    </div>
  </div>
</div>

<!-- Plugin Docker Images -->
<div id="dk-plugins" style="display:none">
  <div style="display:flex;gap:16px;align-items:flex-start">
    <div id="dk-plug-sidebar" style="width:154px;flex-shrink:0">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>
    </div>
    <div style="flex:1;min-width:0">
      <div class="filter-row">
        <input class="search-inp" type="text" placeholder="search plugins…" oninput="dkPS(this.value)">
        <label style="font-size:12px;color:#6b7280;display:flex;align-items:center;gap:5px;cursor:pointer">
          <input type="checkbox" id="dk-plug-miss-cb" onchange="dkPM(this.checked)"> Missing only
        </label>
        <span class="result-count" id="dk-plug-count">—</span>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Plugin</th><th>Category</th><th>Image</th><th>Local Status</th><th>Size</th></tr></thead>
          <tbody id="dk-plug-tbody"><tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
        </table>
      </div>
      <div class="pg-wrap" id="dk-plug-pg"></div>
    </div>
  </div>
</div>
</div>

<script>
var _DKU='';
var _DC={{pp:15,page:1,all:[],filtered:[],q:''}};
var _DS={{pp:15,page:1,all:[],filtered:[],q:'',cat:null}};
var _DP={{pp:15,page:1,all:[],filtered:[],q:'',cat:null,miss:false}};

function dkSub(id){{
  ['containers','sif','plugins'].forEach(function(s){{document.getElementById('dk-'+s).style.display=s===id?'':'none';}});
  document.querySelectorAll('.dk-sub').forEach(function(b){{
    var a=b.dataset.sub===id;
    b.style.color=a?'#00e5a0':'#6b7280';b.style.fontWeight=a?'600':'400';b.style.borderBottomColor=a?'#00e5a0':'transparent';
  }});
}}

function _dkBadge(r,re){{
  var bg=r?'rgba(34,197,94,.12)':re?'rgba(245,158,11,.12)':'rgba(239,68,68,.12)';
  var c=r?'#22c55e':re?'#f59e0b':'#ef4444';
  return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+bg+';color:'+c+';white-space:nowrap">'+(r?'running':re?'restarting':'stopped')+'</span>';
}}

function _dkChip(cat){{
  var M={{alignment:'#0094ff',assembly:'#22c55e','variant-calling':'#a855f7','rna-seq':'#f59e0b',genomics:'#0094ff',metagenomics:'#0094ff',proteomics:'#ef4444','single-cell':'#0094ff',epigenomics:'#f59e0b','protein-structure':'#a855f7','population-genetics':'#22c55e',annotation:'#f59e0b',qc:'#9ca3af',imaging:'#ef4444'}};
  var c=M[cat]||'#9ca3af';
  return '<span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:99px;background:'+c+'22;color:'+c+';white-space:nowrap">'+cat+'</span>';
}}

function _dkBuildSidebar(sid,all,curCat,onCat){{
  var cats={{}};all.forEach(function(x){{cats[x.category]=(cats[x.category]||0)+1;}});
  var el=document.getElementById(sid);
  el.innerHTML='<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>';
  var entries=[['All',null,all.length]].concat(Object.entries(cats).sort(function(a,b){{return b[1]-a[1];}}).map(function(e){{return[e[0],e[0],e[1]];}}));
  entries.forEach(function(e){{
    var active=e[1]===curCat;
    var btn=document.createElement('button');
    btn.style.cssText='width:100%;text-align:left;padding:5px 8px;border-radius:6px;font-size:11px;background:'+(active?'rgba(0,229,160,.1)':'transparent')+';color:'+(active?'#00e5a0':'#6b7280')+';border:1px solid '+(active?'rgba(0,229,160,.25)':'transparent')+';font-weight:'+(active?'600':'400')+';cursor:pointer;display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;font-family:inherit';
    var lbl=document.createElement('span');lbl.style.cssText='overflow:hidden;text-overflow:ellipsis;white-space:nowrap';lbl.textContent=e[0];
    var cnt=document.createElement('span');cnt.style.cssText='background:rgba(255,255,255,.08);color:#6b7280;border-radius:99px;font-size:10px;font-weight:700;padding:1px 5px;flex-shrink:0;margin-left:4px';cnt.textContent=e[2];
    btn.appendChild(lbl);btn.appendChild(cnt);
    btn.onclick=(function(cat){{return function(){{onCat(cat);}};}})(e[1]);
    el.appendChild(btn);
  }});
}}

/* ── Containers ── */
function dkCS(v){{_DC.q=v.toLowerCase();_DC.page=1;dkCA();}}
function dkCA(){{
  var d=_DC.all.filter(function(c){{return!_DC.q||((c.Names||'')+' '+(c.Image||'')).toLowerCase().includes(_DC.q);}});
  _DC.filtered=d;document.getElementById('dk-cont-count').textContent=d.length+' containers';
  var pg=d.slice((_DC.page-1)*_DC.pp,_DC.page*_DC.pp);
  document.getElementById('dk-cont-tbody').innerHTML=pg.length?pg.map(function(c){{
    var name=(c.Names||'').replace(/^[/]/,'')||'—';var s=(c.State||'').toLowerCase();
    var r=s==='running'||(c.Status||'').startsWith('Up');var re=s==='restarting'||(c.Status||'').toLowerCase().includes('restart');
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important;white-space:nowrap">'+name+'</td>'+
      '<td class="mono">'+(c.Image||'—')+'</td><td>'+_dkBadge(r,re)+'</td>'+
      '<td style="font-size:12px;color:#e2e8f0 !important;white-space:nowrap">'+(c.RunningFor||'—')+'</td>'+
      '<td class="mono">'+(c.Ports||'—')+'</td></tr>';
  }}).join(''):'<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">No containers found</td></tr>';
  renderPg('dk-cont',_DC,dkCA);
}}

/* ── SIF Images ── */
function dkSS(v){{_DS.q=v.toLowerCase();_DS.page=1;dkSA();}}
function dkSC(cat){{_DS.cat=cat;_DS.page=1;dkSA();_dkBuildSidebar('dk-sif-sidebar',_DS.all,_DS.cat,dkSC);}}
function dkSA(){{
  var d=_DS.all.filter(function(i){{return(!_DS.q||i.tool.toLowerCase().includes(_DS.q))&&(!_DS.cat||i.category===_DS.cat);}});
  _DS.filtered=d;document.getElementById('dk-sif-count').textContent=d.length+' images';
  var pg=d.slice((_DS.page-1)*_DS.pp,_DS.page*_DS.pp);
  document.getElementById('dk-sif-tbody').innerHTML=pg.length?pg.map(function(i){{
    var sb=i.exists?'rgba(34,197,94,.12)':'rgba(239,68,68,.12)';var sc=i.exists?'#22c55e':'#ef4444';
    var sz='—';if(i.exists){{var mb=i.size_mb,w=Math.min(100,(mb/5120)*100).toFixed(1),lbl=mb>=1024?(mb/1024).toFixed(1)+' GB':mb+' MB';sz='<div style="display:flex;align-items:center;gap:6px"><div style="width:50px;height:4px;background:#2a2d3e;border-radius:99px;overflow:hidden;flex-shrink:0"><div style="height:100%;width:'+w+'%;background:#0094ff;border-radius:99px"></div></div><span style="font-size:12px;font-family:monospace;color:#e2e8f0 !important;white-space:nowrap">'+lbl+'</span></div>';}}
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important">'+i.tool+'</td>'+
      '<td>'+_dkChip(i.category)+'</td>'+
      '<td><span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+sb+';color:'+sc+'">'+(i.exists?'built':'missing')+'</span></td>'+
      '<td>'+sz+'</td></tr>';
  }}).join(''):'<tr><td colspan="4" style="text-align:center;color:#6b7280;padding:24px 12px">No SIF images found</td></tr>';
  renderPg('dk-sif',_DS,dkSA);
}}

/* ── Plugin Images ── */
function dkPS(v){{_DP.q=v.toLowerCase();_DP.page=1;dkPA();}}
function dkPM(v){{_DP.miss=v;_DP.page=1;dkPA();}}
function dkPC(cat){{_DP.cat=cat;_DP.page=1;dkPA();_dkBuildSidebar('dk-plug-sidebar',_DP.all,_DP.cat,dkPC);}}
function dkPA(){{
  var d=_DP.all.filter(function(p){{return(!_DP.q||(p.name+' '+p.plugin).toLowerCase().includes(_DP.q))&&(!_DP.cat||p.category===_DP.cat)&&(!_DP.miss||p.local_status==='missing');}});
  _DP.filtered=d;document.getElementById('dk-plug-count').textContent=d.length+' plugins';
  var pg=d.slice((_DP.page-1)*_DP.pp,_DP.page*_DP.pp);
  document.getElementById('dk-plug-tbody').innerHTML=pg.length?pg.map(function(p){{
    var sb=p.local_status==='present'?'rgba(34,197,94,.12)':'rgba(239,68,68,.12)';var sc=p.local_status==='present'?'#22c55e':'#ef4444';
    var sz='—';if(p.local_status==='present'&&p.size_mb>0)sz=p.size_mb>=1024?(p.size_mb/1024).toFixed(1)+' GB':p.size_mb+' MB';
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important;white-space:nowrap">'+p.name+'</td>'+
      '<td>'+_dkChip(p.category)+'</td>'+
      '<td class="mono" style="max-width:260px">'+p.image+'</td>'+
      '<td><span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+sb+';color:'+sc+'">'+p.local_status+'</span></td>'+
      '<td style="font-size:12px;font-family:monospace;color:#e2e8f0 !important;white-space:nowrap">'+sz+'</td></tr>';
  }}).join(''):'<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">No plugins match filters</td></tr>';
  renderPg('dk-plug',_DP,dkPA);
}}

/* ── Fetch all three endpoints on load ── */
(function(){{
  fetch(_DKU+'/docker/containers').then(function(r){{return r.json();}}).then(function(d){{
    _DC.all=d.containers||[];
    document.getElementById('dk-k-run').textContent=(d.running||0)+'/'+_DC.all.length;
    dkCA();
  }}).catch(function(){{document.getElementById('dk-cont-tbody').innerHTML='<tr><td colspan="5" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';}});

  fetch(_DKU+'/docker/sif-images').then(function(r){{return r.json();}}).then(function(d){{
    _DS.all=d.images||[];
    document.getElementById('dk-k-sif-ok').textContent=d.built||0;
    document.getElementById('dk-k-sif-miss').textContent=d.missing||0;
    document.getElementById('dk-k-gb').textContent=(d.total_gb||0)+' GB';
    _dkBuildSidebar('dk-sif-sidebar',_DS.all,_DS.cat,dkSC);
    dkSA();
  }}).catch(function(){{document.getElementById('dk-sif-tbody').innerHTML='<tr><td colspan="4" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';}});

  fetch(_DKU+'/docker/plugin-images').then(function(r){{return r.json();}}).then(function(d){{
    _DP.all=d.plugins||[];
    document.getElementById('dk-k-plug').textContent=_DP.all.length;
    document.getElementById('dk-k-plug-ok').textContent=d.present||0;
    _dkBuildSidebar('dk-plug-sidebar',_DP.all,_DP.cat,dkPC);
    dkPA();
  }}).catch(function(){{document.getElementById('dk-plug-tbody').innerHTML='<tr><td colspan="5" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';}});
}})();
</script>
"""

# ── SHARED PAGINATION JS ───────────────────────────────────────────────────────

PAGINATION_JS = """
<script id="pg-shared">
function renderPg(prefix, state, applyFn) {
  var total = state.filtered.length;
  var pages = Math.ceil(total / state.pp);
  var pg = document.getElementById(prefix + '-pg');
  if (!pg) return;
  pg.innerHTML = '';
  if (pages <= 1) return;
  var start = (state.page - 1) * state.pp + 1;
  var end = Math.min(state.page * state.pp, total);
  var info = document.createElement('span');
  info.className = 'pg-info';
  info.textContent = start + '–' + end + ' of ' + total;
  pg.appendChild(info);
  var prev = document.createElement('button');
  prev.className = 'pg-btn';
  prev.textContent = '←';
  prev.disabled = state.page === 1;
  prev.onclick = function() { if (state.page > 1) { state.page--; applyFn(); } };
  pg.appendChild(prev);
  var maxB = 5, sP = Math.max(1, state.page - 2), eP = Math.min(pages, sP + maxB - 1);
  if (eP - sP < maxB - 1) sP = Math.max(1, eP - maxB + 1);
  for (var i = sP; i <= eP; i++) {
    (function(p) {
      var btn = document.createElement('button');
      btn.className = 'pg-btn' + (state.page === p ? ' active' : '');
      btn.textContent = p;
      btn.onclick = function() { state.page = p; applyFn(); };
      pg.appendChild(btn);
    })(i);
  }
  var next = document.createElement('button');
  next.className = 'pg-btn';
  next.textContent = '→';
  next.disabled = state.page === pages;
  next.onclick = function() { if (state.page < pages) { state.page++; applyFn(); } };
  pg.appendChild(next);
}
</script>
"""

# ── REPORT COMPOSER ────────────────────────────────────────────────────────────

def build_report(out_html: Path, title: str, timestamp: str,
                 grand: Totals, project_totals: Dict[str, Totals],
                 language_totals: Dict[str, Totals],
                 coverage_df: pd.DataFrame, health: EcosystemHealth,
                 control_center_url: str) -> None:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    cc_url = control_center_url.rstrip("/")
    total_all = grand.blank + grand.comment + grand.code
    doc_lines = language_totals.get("Markdown", Totals()).code

    arch_html     = architecture_section_html(project_totals, grand, control_center_url)
    proj_html     = projects_section_html(project_totals, grand)
    lang_html     = languages_section_html(language_totals, grand)
    cov_html      = coverage_section_html(coverage_df, timestamp)
    hlth_html     = health_section_html(health, control_center_url)
    llms_html     = llm_section_html(control_center_url)
    cloud_html    = cloud_section_html(control_center_url)
    ref_html      = reference_section_html(control_center_url)
    kb_html       = knowledge_base_section_html(control_center_url)
    storage_html  = storage_section_html(control_center_url)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet">
  {_CHARTJS}
  {SHARED_CSS}
  <style>
    body {{font-family:var(--font-sans);background:var(--color-bg);color:var(--color-text);min-height:100vh}}
    .page {{max-width:1400px;margin:0 auto;padding:24px 24px 48px}}
    .hero {{background:var(--color-bg-surface);border:0.5px solid var(--color-border);border-radius:16px;padding:20px 24px;margin-bottom:20px;display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:12px}}
    .hero-title {{font-size:22px;font-weight:500;color:var(--color-text);margin-bottom:4px}}
    .hero-sub {{font-size:13px;color:var(--color-text)}}
    .hero-ts {{font-size:11px;color:var(--color-text-muted);margin-top:4px}}
    .hero-right {{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
    .regen-btn {{display:flex;align-items:center;gap:5px;padding:8px 16px;border-radius:8px;background:var(--color-accent);color:#000;font-size:13px;font-weight:600;border:none;cursor:pointer;text-decoration:none}}
    .regen-btn:hover {{background:var(--color-bg-surface2)}}
    .status-badge {{display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:99px;font-size:12px;font-weight:600}}
    .sb-up {{background:#EAF3DE;color:#3B6D11}}
    .sb-down {{background:#FCEBEB;color:#A32D2D}}
    .sb-warn {{background:#FAEEDA;color:#854F0B}}
    .sb-unknown {{background:#F1EFE8;color:#444441}}
    .global-kpi {{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}}
    .gk {{background:var(--color-bg-surface);border:0.5px solid var(--color-border);border-radius:10px;padding:12px 18px;flex:1;min-width:100px}}
    .gk-lbl {{font-size:11px;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}}
    .gk-val {{font-size:24px;font-weight:500;color:var(--color-text)}}
    .tab-nav {{display:flex;gap:0;border-bottom:1px solid var(--color-border);margin-bottom:0;background:var(--color-bg-surface);border-radius:12px 12px 0 0;padding:0 4px}}
    .tab-btn {{padding:12px 20px;font-size:13px;font-weight:600;color:var(--color-text-muted);background:transparent;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap;margin-bottom:-1px;font-family:inherit}}
    .tab-btn:hover {{color:var(--color-text)}}
    .tab-btn.active {{color:var(--color-text);border-bottom-color:var(--color-accent)}}
    .tab-panel {{display:none;background:var(--color-bg-surface);border:1px solid var(--color-border);border-top:none;border-radius:0 0 12px 12px;padding:0 20px}}
    .tab-panel.active {{display:block}}
    .footer {{margin-top:24px;padding-top:16px;border-top:0.5px solid var(--color-border);font-size:11px;color:var(--color-text-muted);line-height:1.8}}
  </style>
</head>
<body>
<div class="page">

  <div class="hero">
    <div>
      <div class="hero-title">{title}</div>
      <div class="hero-sub">Architecture · Codebase · Coverage · Health</div>
      <div class="hero-ts">Generated: {timestamp}</div>
    </div>
    <div class="hero-right">
      <div class="status-badge sb-unknown" id="global-health-badge">
        <span class="status-dot dot-loading" id="global-health-dot"></span>
        <span id="global-health-text">checking...</span>
      </div>
      <span style="font-size:12px;color:var(--color-text-muted)" id="global-health-ts"></span>
    </div>
  </div>

  <div class="global-kpi">
    <div class="gk"><div class="gk-lbl">files</div><div class="gk-val">{fmt_int(grand.files)}</div></div>
    <div class="gk"><div class="gk-lbl">documentation</div><div class="gk-val">{fmt_int(doc_lines)}</div></div>
    <div class="gk"><div class="gk-lbl">code lines</div><div class="gk-val">{fmt_int(grand.code)}</div></div>
    <div class="gk"><div class="gk-lbl">comment lines</div><div class="gk-val">{fmt_int(grand.comment)}</div></div>
    <div class="gk"><div class="gk-lbl">blank lines</div><div class="gk-val">{fmt_int(grand.blank)}</div></div>
    <div class="gk"><div class="gk-lbl">total lines</div><div class="gk-val">{fmt_int(total_all)}</div></div>
  </div>

  <div class="tab-nav">
    <button class="tab-btn active" onclick="openTab('tab-arch',this)">Architecture</button>
    <button class="tab-btn" onclick="openTab('tab-proj',this)">Projects</button>
    <button class="tab-btn" onclick="openTab('tab-lang',this)">Languages</button>
    <button class="tab-btn" onclick="openTab('tab-cov',this)">Code Coverage</button>
    <button class="tab-btn" onclick="openTab('tab-health',this)">Health Status</button>
    <button class="tab-btn" onclick="openTab('tab-llms',this)">LLMs</button>
    <button class="tab-btn" onclick="openTab('tab-cloud',this)">Cloud</button>
    <button class="tab-btn" onclick="openTab('tab-ref',this)">Reference Data</button>
    <button class="tab-btn" onclick="openTab('tab-kb',this)">AI Knowledge Base</button>
    <button class="tab-btn" onclick="openTab('tab-storage',this)">Storage</button>
  </div>

  {PAGINATION_JS}

  <div id="tab-arch"   class="tab-panel active">{arch_html}</div>
  <div id="tab-proj"   class="tab-panel">{proj_html}</div>
  <div id="tab-lang"   class="tab-panel">{lang_html}</div>
  <div id="tab-cov"    class="tab-panel">{cov_html}</div>
  <div id="tab-health" class="tab-panel">{hlth_html}</div>
  <div id="tab-llms"   class="tab-panel">{llms_html}</div>
  <div id="tab-cloud"  class="tab-panel">{cloud_html}</div>
  <div id="tab-ref"    class="tab-panel">{ref_html}</div>
  <div id="tab-kb"      class="tab-panel">{kb_html}</div>
  <div id="tab-storage" class="tab-panel">{storage_html}</div>

  <div class="footer">
    cloc counts exclude vendored/runtime directories and selected extensions per cloc policy.<br>
    Coverage is best-effort and does not fail the report when a repository has test or configuration issues.<br>
    Health data is live — fetched from the Control Center /summary endpoint with 30-second auto-refresh.
  </div>
</div>

<script>
function openTab(id, btn) {{
  document.querySelectorAll('.tab-panel').forEach(function(t){{t.classList.remove('active');}});
  document.querySelectorAll('.tab-btn').forEach(function(b){{b.classList.remove('active');}});
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}

(function globalHealthBadge(){{
  fetch('/summary').then(function(r){{return r.json();}}).then(function(d){{
    var ov=(d.overall_status||'UNKNOWN').toUpperCase();
    var badge=document.getElementById('global-health-badge');
    var dot=document.getElementById('global-health-dot');
    var txt=document.getElementById('global-health-text');
    var ts=document.getElementById('global-health-ts');
    var cls={{UP:'sb-up',DOWN:'sb-down',WARN:'sb-warn'}};
    badge.className='status-badge '+(cls[ov]||'sb-unknown');
    dot.className='status-dot '+(ov==='UP'?'dot-up':ov==='DOWN'?'dot-down':'dot-warn');
    var svcs=d.services||[];
    var up=svcs.filter(function(s){{return s.status==='UP';}}).length;
    txt.textContent=up+'/'+svcs.length+' UP';
    if(d.generated_at)ts.textContent=new Date(d.generated_at).toLocaleTimeString();
  }}).catch(function(){{
    document.getElementById('global-health-dot').className='status-dot dot-down';
    document.getElementById('global-health-text').textContent='unreachable';
  }});
}})();
</script>
</body>
</html>
"""
    out_html.write_text(html, encoding="utf-8")

    # ── Save structured JSON for React frontend ──────────────────────────────
    total_code = grand.code or 1
    proj_sorted = sorted(project_totals.items(), key=lambda kv: kv[1].code, reverse=True)
    lang_sorted  = sorted(language_totals.items(), key=lambda kv: kv[1].code, reverse=True)

    projects_json = []
    for name, t in proj_sorted:
        cat = CAT_MAP.get(name, "infra")
        m   = CAT_META[cat]
        projects_json.append({
            "name": name.replace("omnibioai-", "").replace("omnibioai_", ""),
            "full": name, "cat": cat, "catLabel": m["label"],
            "files": t.files, "code": t.code,
            "comment": t.comment, "blank": t.blank,
            "pct": round(100 * t.code / total_code, 2),
        })

    languages_json = []
    for name, t in lang_sorted:
        lt = LANG_TYPE.get(name, "infra")
        m  = LANG_TYPE_META[lt]
        languages_json.append({
            "name": name, "type": lt, "typeLabel": m["label"],
            "files": t.files, "code": t.code,
            "comment": t.comment, "blank": t.blank,
            "pct": round(100 * t.code / total_code, 2),
        })

    coverage_json = []
    for _, row in coverage_df.iterrows():
        pct = row.get("coverage_pct")
        pct_val = round(float(pct), 2) if (pct is not None and pct == pct) else None
        stmts    = row.get("statements")
        missed   = row.get("missed")
        branches = row.get("branches")
        fail_u   = row.get("fail_under")
        coverage_json.append({
            "repo":      str(row.get("repo", "")),
            "status":    str(row.get("status", "")),
            "pct":       pct_val,
            "stmts":     int(stmts)    if (stmts    is not None and stmts    == stmts)    else None,
            "missed":    int(missed)   if (missed    is not None and missed   == missed)   else None,
            "branches":  int(branches) if (branches  is not None and branches == branches) else None,
            "failUnder": float(fail_u) if (fail_u    is not None and fail_u   == fail_u)   else None,
        })

    json_out = out_html.with_name("report_data.json")
    json_out.write_text(json.dumps({
        "generated_at": timestamp,
        "grand":     {"files": grand.files, "code": grand.code, "comment": grand.comment, "blank": grand.blank},
        "projects":  projects_json,
        "languages": languages_json,
        "coverage":  coverage_json,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate OmniBioAI ecosystem report")
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--targets", nargs="+", default=None)
    p.add_argument("--out", default=str(DEFAULT_OUT_PATH))
    p.add_argument("--title", default=DEFAULT_TITLE)
    p.add_argument("--health-url", "--control-center-url",
                   default=DEFAULT_CONTROL_CENTER_URL,
                   dest="control_center_url")
    p.add_argument("--skip-health",    action="store_true")
    p.add_argument("--skip-coverage",  action="store_true")
    return p.parse_args()

def generate_report(ecosystem_root: Path,
                    targets: Optional[List[str]] = None,
                    out_relpath: str = str(DEFAULT_OUT_PATH),
                    title: str = DEFAULT_TITLE,
                    control_center_url: str = DEFAULT_CONTROL_CENTER_URL,
                    skip_health: bool = False,
                    skip_coverage: bool = False) -> Path:
    ensure_cloc()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not targets:
        targets = DEFAULT_TARGETS

    target_paths = _resolve_target_paths(ecosystem_root, targets)
    validate_paths(target_paths)

    print("→ Running cloc…")
    project_totals:  Dict[str, Totals] = {}
    language_totals: Dict[str, Totals] = {}
    grand = Totals()
    for tp in target_paths:
        if not tp.exists(): continue
        overall, per_lang = run_cloc(tp)
        project_totals[tp.name] = overall
        grand.add(overall)
        for lang, tot in per_lang.items():
            language_totals.setdefault(lang, Totals()).add(tot)

    if skip_coverage:
        print("→ Skipping coverage (--skip-coverage)")
        coverage_df = pd.DataFrame(columns=[
            "repo","path","status","returncode","statements","missed",
            "branches","partial_branches","coverage_pct","coverage_band",
            "fail_under","total_line","stderr_tail"])
    else:
        work_dir = Path(os.environ.get("WORK_DIR", str(ecosystem_root / "omnibioai-work")))
        precomputed_dir = work_dir / "out" / "coverage"
        if precomputed_dir.is_dir():
            print(f"→ Loading pre-computed coverage from {precomputed_dir}…")
        else:
            print("→ Collecting pytest coverage (live)…")
        coverage_df = collect_coverage(
            target_paths,
            precomputed_dir=precomputed_dir if precomputed_dir.is_dir() else None)

    if skip_health:
        health = EcosystemHealth(overall_status="UNREACHABLE", generated_at="",
                                  error="Health check skipped")
    else:
        print(f"→ Fetching health from {control_center_url}…")
        health = fetch_health(control_center_url)
        print(f"  {'✓' if health.overall_status=='UP' else '⚠'} Overall: {health.overall_status}")

    out_html = ecosystem_root / out_relpath
    print("→ Building report…")
    build_report(out_html=out_html, title=title, timestamp=ts,
                 grand=grand, project_totals=project_totals,
                 language_totals=language_totals, coverage_df=coverage_df,
                 health=health, control_center_url=control_center_url)
    return out_html

def main() -> int:
    args = parse_args()
    if args.root:
        ecosystem_root = args.root
    else:
        # Derive root from script location: <root>/omnibioai-control-center/scripts/generate_report.py
        script_candidate = Path(__file__).resolve().parent.parent.parent  # /workspace
        if any((script_candidate / t).is_dir() for t in DEFAULT_TARGETS[:6]):
            ecosystem_root = script_candidate
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
            skip_coverage=args.skip_coverage)
        print(f"\n✓ Report written: {out}")
        return 0
    except Exception as e:
        print(f"\n✗ {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())