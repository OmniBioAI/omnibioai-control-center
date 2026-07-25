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
--compose-path PATH      docker-compose.yml used by the Secrets Audit / Exposed Ports tabs
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
try:
    import yaml
except ImportError:
    yaml = None  # Catalog tab tools-count degrades gracefully if pyyaml missing

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
def _default_compose_path() -> Path:
    env_path = os.environ.get("OMNIBIOAI_COMPOSE_PATH")
    if env_path:
        return Path(env_path)
    # Two fallbacks because this script runs in two different contexts:
    # inside the control-center container, ${MACHINE_DIR} on the host is
    # mounted to /workspace (see docker-compose.yml), so the compose file
    # lives under /workspace there; run directly on the host instead, it's
    # still at its normal Desktop/machine location.
    container_path = Path("/workspace/omnibioai-studio/docker-compose.yml")
    if container_path.exists():
        return container_path
    return Path("/home/manish/Desktop/machine/omnibioai-studio/docker-compose.yml")

DEFAULT_COMPOSE_PATH = _default_compose_path()


def _load_env_file(path: Path) -> None:
    """Best-effort .env loader (KEY=VALUE lines, optional 'export ' prefix,
    '#' comments and blank lines skipped). Never overrides a variable
    already present in the process environment, so an explicit shell
    export still wins over the file. Silently no-ops if the file doesn't
    exist or can't be read -- mirrors docker-compose's own env_file
    handling for the same file, without adding a python-dotenv dependency.
    """
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


_load_env_file(DEFAULT_COMPOSE_PATH.parent / ".env")

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

_SENTRY_LEVEL_COLOR = {
    "error":   ("#FCEBEB", "#A32D2D"),
    "fatal":   ("#FCEBEB", "#A32D2D"),
    "warning": ("#FAEEDA", "#854F0B"),
    "info":    ("#E6F1FB", "#185FA5"),
}


def error_aggregation_section_html(sentry_org: str, sentry_project_slugs: List[str]) -> str:
    """One-shot fetch of recent Sentry issues per project -- intentionally NOT
    live/polling like the rest of the Health Status tab, since Sentry's API has
    its own rate limits; this runs once at report-generation time."""
    token = os.environ.get("SENTRY_API_TOKEN")
    if not token or not sentry_org or not sentry_project_slugs:
        return """
<div class="section" style="margin-top:12px">
  <div class="sec-title">errors (Sentry)</div>
  <div style="font-size:12px;color:var(--color-text-muted)">SENTRY_API_TOKEN not configured -- skipping error aggregation. Set SENTRY_API_TOKEN, SENTRY_ORG and SENTRY_PROJECT_SLUGS to enable this section.</div>
</div>"""

    import urllib.request

    per_project: List[Dict[str, Any]] = []
    for slug in sentry_project_slugs:
        issues = None
        try:
            req = urllib.request.Request(
                f"https://sentry.io/api/0/projects/{sentry_org}/{slug}/issues/?statsPeriod=24h",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                issues = json.loads(r.read())
        except Exception as e:
            print(f"[report] error_aggregation_section_html failed for {slug}: {type(e).__name__}: {e}", flush=True)

        if issues is None:
            per_project.append({"project": slug, "unresolved": None, "events_24h": None, "issues": [], "error": True})
            continue

        unresolved = [i for i in issues if i.get("status") == "unresolved"]
        events_24h = sum(int(i.get("count", 0) or 0) for i in issues)
        top5 = sorted(issues, key=lambda i: int(i.get("count", 0) or 0), reverse=True)[:5]
        per_project.append({
            "project": slug, "unresolved": len(unresolved),
            "events_24h": events_24h, "issues": top5, "error": False,
        })

    total_unresolved = sum(p["unresolved"] for p in per_project if not p["error"])
    total_events = sum(p["events_24h"] for p in per_project if not p["error"])

    def _proj_row(p):
        if p["error"]:
            return f"""<tr>
              <td style="font-weight:600;font-size:12px">{p['project']}</td>
              <td colspan="2" style="color:var(--color-text-muted)">unreachable</td>
            </tr>"""
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{p['project']}</td>
          <td class="r">{p['unresolved']}</td>
          <td class="r">{fmt_int(p['events_24h'])}</td>
        </tr>"""

    proj_rows = "".join(_proj_row(p) for p in per_project) or \
        '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px">no projects configured</td></tr>'

    all_issues = []
    for p in per_project:
        for issue in p.get("issues", []):
            all_issues.append({
                "project": p["project"], "title": issue.get("title", ""),
                "level": issue.get("level", ""),
                "count": int(issue.get("count", 0) or 0),
                "last_seen": issue.get("lastSeen", ""),
            })
    all_issues.sort(key=lambda i: i["count"], reverse=True)

    def _issue_row(i):
        bg, color = _SENTRY_LEVEL_COLOR.get(i["level"], ("#F1EFE8", "#444441"))
        return f"""<tr>
          <td style="font-size:12px">{i['project']}</td>
          <td style="font-size:12px">{i['title']}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{i['level']}</span></td>
          <td class="r">{fmt_int(i['count'])}</td>
          <td style="font-size:11px;color:var(--color-text-muted)">{i['last_seen']}</td>
        </tr>"""

    top_issues_rows = "".join(_issue_row(i) for i in all_issues) or \
        '<tr><td colspan="5" style="text-align:center;color:var(--color-text-muted);padding:20px">no issues found</td></tr>'

    return f"""
<div class="section" style="margin-top:12px">
  <div class="sec-title">errors (Sentry)</div>
  <div class="sec-sub">fetched once at report-generation time, not live · last 24h · org: {sentry_org}</div>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-label">unresolved</div><div class="kpi-val" style="color:{'#A32D2D' if total_unresolved else '#3B6D11'}">{total_unresolved}</div></div>
    <div class="kpi"><div class="kpi-label">events (24h)</div><div class="kpi-val">{fmt_int(total_events)}</div></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>project</th><th class="r">unresolved</th><th class="r">events (24h)</th></tr></thead>
      <tbody>{proj_rows}</tbody>
    </table>
  </div>
  <div class="sec-title" style="margin-top:12px">top issues across all services</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>project</th><th>issue</th><th>level</th><th class="r">events</th><th>last seen</th></tr></thead>
      <tbody>{top_issues_rows}</tbody>
    </table>
  </div>
</div>"""


def _health_overview_section_html() -> str:
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
</div>
"""


def _health_services_section_html() -> str:
    return f"""
<div class="tab-section">
<div style="font-size:11px;font-weight:600;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">services</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px;margin-bottom:12px" id="hlth-svc-grid">
  <div style="font-size:12px;color:var(--color-text-muted);grid-column:1/-1">loading service cards...</div>
</div>
</div>
"""


def _health_storage_section_html() -> str:
    return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">disk checks</div>
  <div class="sec-sub">storage paths monitored by control center</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px" id="hlth-disk-grid">
    <div style="font-size:12px;color:var(--color-text-muted)">loading...</div>
  </div>
</div>

<div class="section" style="margin-top:12px">
  <div class="sec-title">symlink &amp; mount integrity</div>
  <div class="sec-sub">known-important paths, checked live</div>
  <div id="integrity-panel-body">
    <div style="font-size:12px;color:var(--color-text-muted)">loading...</div>
  </div>
</div>
</div>
"""


def _health_gpu_section_html() -> str:
    return f"""
<div class="tab-section">
<div class="section" style="margin-top:12px">
  <div class="sec-title">GPU health</div>
  <div class="sec-sub">nvidia-smi · live, refreshes with the rest of this tab</div>
  <div id="gpu-panel-body">
    <div style="font-size:12px;color:var(--color-text-muted)">loading...</div>
  </div>
</div>
</div>
"""


def _health_activity_section_html() -> str:
    return f"""
<div class="tab-section">
<div class="section" style="margin-top:12px">
  <div class="sec-title">activity monitor</div>
  <div class="sec-sub">live CPU / memory / network via Prometheus + cAdvisor, host stats via node_exporter</div>
  <div id="am-host-summary" style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">
    <div style="font-size:12px;color:var(--color-text-muted);grid-column:1/-1">loading host summary...</div>
  </div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search containers..." oninput="amFilter(this.value)">
    <span class="result-count" id="am-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="amPerPage(this.value)"><option value="15" selected>15</option><option value="30">30</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="amSort('name')">container</th>
        <th class="r" onclick="amSort('cpu_pct')">% cpu</th>
        <th class="r" onclick="amSort('memory_used_mb')">memory</th>
        <th class="r" onclick="amSort('memory_pct')">mem %</th>
        <th class="r" onclick="amSort('net_rx_mb')">net rx</th>
        <th class="r" onclick="amSort('net_tx_mb')">net tx</th>
        <th class="r" onclick="amSort('pids')">pids</th>
      </tr></thead>
      <tbody id="am-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="am-pg"></div>
</div>
</div>
"""


_HEALTH_SCRIPT = f"""
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
    if(_hCd<=0){{clearInterval(_hTimer);hlthFetch();gpuFetch();integrityFetch();activityFetch();}}
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
function _gpuMemColor(usedMb, totalMb, memoryUnsupported){{
  if(memoryUnsupported) return 'var(--color-text-muted)';
  if(usedMb===null||usedMb===undefined) return '#A32D2D';
  var pct=usedMb/totalMb*100;
  return pct<70?'#3B6D11':pct<90?'#854F0B':'#A32D2D';
}}
function gpuFetch(){{
  fetch(_hUrl+'/gpu').then(function(r){{return r.json();}}).then(function(d){{
    var el=document.getElementById('gpu-panel-body');
    if(!d.reachable){{
      el.innerHTML='<div style="font-size:12px;color:#A32D2D">GPU unreachable: '+(d.error||'unknown error')+'</div>';
      return;
    }}
    var memNull = d.memory_used_mb===null||d.memory_used_mb===undefined;
    var memColor=_gpuMemColor(d.memory_used_mb,d.memory_total_mb,d.memory_unsupported);
    var memText = d.memory_unsupported
      ? '<span style="color:var(--color-text-muted)">memory reporting not supported on this GPU</span>'
      : memNull
      ? '<span style="color:#A32D2D;font-weight:600">N/A — driver may be in a bad state</span>'
      : (d.memory_used_mb/1024).toFixed(1)+' / '+(d.memory_total_mb/1024).toFixed(1)+' GB';
    var procRows = (d.processes||[]).map(function(p){{
      return '<div style="font-size:11px;color:var(--color-text-muted)">'+p.name+' (pid '+p.pid+') — '+p.memory_mb+' MB</div>';
    }}).join('') || '<div style="font-size:11px;color:var(--color-text-muted)">no processes</div>';
    var modelRows = (d.ollama_loaded_models||[]).map(function(m){{
      return '<div style="font-size:11px;color:var(--color-text)">'+m.name+' — '+m.size_gb+' GB (until '+(m.until?new Date(m.until).toLocaleTimeString():'?')+')</div>';
    }}).join('') || '<div style="font-size:11px;color:var(--color-text-muted)">no models currently loaded</div>';
    el.innerHTML =
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'+
      '<div><div style="font-size:11px;color:var(--color-text-muted)">GPU</div>'+
      '<div style="font-size:13px;font-weight:600">'+d.gpu_name+'</div></div>'+
      '<div><div style="font-size:11px;color:var(--color-text-muted)">memory</div>'+
      '<div style="font-size:13px;font-weight:600;color:'+memColor+'">'+memText+'</div></div>'+
      '<div><div style="font-size:11px;color:var(--color-text-muted)">utilization</div>'+
      '<div style="font-size:13px">'+d.utilization_pct+'%</div></div>'+
      '<div><div style="font-size:11px;color:var(--color-text-muted)">temp / power</div>'+
      '<div style="font-size:13px">'+d.temperature_c+'°C · '+d.power_draw_w+'W</div></div>'+
      '<div style="grid-column:1/-1"><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:4px">GPU processes</div>'+procRows+'</div>'+
      '<div style="grid-column:1/-1"><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:4px">ollama loaded models</div>'+modelRows+'</div>'+
      '</div>'+
      (d.error?'<div style="margin-top:8px;font-size:11px;color:#854F0B">⚠ '+d.error+'</div>':'');
  }}).catch(function(){{
    document.getElementById('gpu-panel-body').innerHTML='<div style="font-size:12px;color:#A32D2D">could not reach /gpu endpoint</div>';
  }});
}}
var _AM={{pp:15,page:1,sort:'cpu_pct',dir:-1,search:'',all:[],filtered:[]}};
function amFilter(v){{_AM.search=v.toLowerCase();_AM.page=1;amApply();}}
function amPerPage(v){{_AM.pp=parseInt(v);_AM.page=1;amApply();}}
function amSort(col){{if(_AM.sort===col){{_AM.dir*=-1;}}else{{_AM.sort=col;_AM.dir=col==='name'?1:-1;}} _AM.page=1;amApply();}}
function _amNum(v,digits){{return (v===null||v===undefined)?'—':v.toFixed(digits);}}
function amApply(){{
  var d=_AM.all.filter(function(c){{return !_AM.search||c.name.toLowerCase().includes(_AM.search);}});
  var col=_AM.sort;
  d.sort(function(a,b){{
    var av=a[col],bv=b[col];
    if(av===null||av===undefined)av=-Infinity;
    if(bv===null||bv===undefined)bv=-Infinity;
    if(typeof av==='string')av=av.toLowerCase();
    if(typeof bv==='string')bv=bv.toLowerCase();
    return av<bv?_AM.dir:av>bv?-_AM.dir:0;
  }});
  _AM.filtered=d;
  document.getElementById('am-count').textContent=d.length+' containers';
  var start=(_AM.page-1)*_AM.pp,page=d.slice(start,start+_AM.pp);
  var tb=document.getElementById('am-tbody');tb.innerHTML='';
  page.forEach(function(c){{
    var cpuColor=c.cpu_pct>50?'#A32D2D':c.cpu_pct>15?'#854F0B':'#3B6D11';
    var memColor=c.memory_pct===null?'inherit':(c.memory_pct>80?'#A32D2D':c.memory_pct>50?'#854F0B':'#3B6D11');
    var tr=document.createElement('tr');
    tr.innerHTML='<td style="font-size:12px;font-weight:600">'+c.name+'</td>'+
      '<td class="r" style="color:'+cpuColor+';font-weight:600">'+_amNum(c.cpu_pct,2)+'%</td>'+
      '<td class="r">'+_amNum(c.memory_used_mb,1)+' MB</td>'+
      '<td class="r" style="color:'+memColor+'">'+(c.memory_pct===null?'—':_amNum(c.memory_pct,2)+'%')+'</td>'+
      '<td class="r">'+_amNum(c.net_rx_mb,1)+' MB</td>'+
      '<td class="r">'+_amNum(c.net_tx_mb,1)+' MB</td>'+
      '<td class="r">'+(c.pids===null||c.pids===undefined?'—':c.pids)+'</td>';
    tb.appendChild(tr);
  }});
  renderPg('am',_AM,amApply);
}}
function amHostRender(h){{
  var el=document.getElementById('am-host-summary');
  if(!h){{el.innerHTML='<div style="font-size:12px;color:#854F0B;grid-column:1/-1">node_exporter not configured — host-level stats unavailable (container-level stats below still work)</div>';return;}}
  function card(label,val,color){{return '<div class="kpi"><div class="kpi-label">'+label+'</div><div class="kpi-val" style="color:'+(color||'inherit')+'">'+val+'</div></div>';}}
  var memPct = (h.memory_available_gb!==null&&h.memory_total_gb) ? h.memory_available_gb/h.memory_total_gb : null;
  el.innerHTML =
    card('cpu load (1m)', _amNum(h.load_1m,2)) +
    card('memory available', _amNum(h.memory_available_gb,1)+' / '+(h.memory_total_gb===null?'—':h.memory_total_gb)+' GB',
         memPct!==null&&memPct<0.15?'#A32D2D':'inherit') +
    card('swap used', _amNum(h.swap_used_gb,1)+' / '+_amNum(h.swap_total_gb,1)+' GB',
         h.swap_used_gb>2?'#854F0B':'inherit') +
    card('processes', h.processes_total===null?'—':h.processes_total) +
    card('threads', h.threads_total===null?'—':h.threads_total) +
    card('cpu idle', _amNum(h.cpu_idle_pct,1)+'%');
}}
function activityFetch(){{
  fetch(_hUrl+'/activity').then(function(r){{return r.json();}}).then(function(d){{
    if(!d.reachable){{document.getElementById('am-host-summary').innerHTML='<div style="font-size:12px;color:#A32D2D;grid-column:1/-1">activity data unreachable: '+(d.error||'unknown')+'</div>';return;}}
    amHostRender(d.host);
    _AM.all=d.containers||[];
    amApply();
  }}).catch(function(){{
    document.getElementById('am-host-summary').innerHTML='<div style="font-size:12px;color:#A32D2D;grid-column:1/-1">could not reach /activity endpoint</div>';
  }});
}}
function integrityFetch(){{
  fetch(_hUrl+'/integrity').then(function(r){{return r.json();}}).then(function(d){{
    var el=document.getElementById('integrity-panel-body');
    var checks=d.checks||[];
    if(checks.length===0){{el.innerHTML='<div style="font-size:12px;color:var(--color-text-muted)">no paths configured for checking</div>';return;}}
    var statusColor={{ok:'#3B6D11',broken:'#A32D2D',missing:'#A32D2D',empty:'#854F0B'}};
    var statusBg={{ok:'#EAF3DE',broken:'#FCEBEB',missing:'#FCEBEB',empty:'#FAEEDA'}};
    el.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px">' +
      checks.map(function(c){{
        var c1=statusColor[c.status]||'#444441', bg=statusBg[c.status]||'#F1EFE8';
        return '<div style="background:var(--color-bg-surface2);border-left:3px solid '+c1+';border-radius:8px;padding:10px 12px">'+
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'+
          '<span style="font-size:12px;font-weight:600">'+c.name+'</span>'+
          '<span class="badge" style="background:'+bg+';color:'+c1+'">'+c.status+'</span></div>'+
          '<div style="font-size:10px;color:var(--color-text-muted);font-family:monospace;word-break:break-all">'+c.path+'</div>'+
          (c.is_symlink?'<div style="font-size:10px;color:var(--color-text-muted);font-family:monospace;word-break:break-all">→ '+c.resolves_to+'</div>':'')+
          '</div>';
      }}).join('') + '</div>';
  }}).catch(function(){{
    document.getElementById('integrity-panel-body').innerHTML='<div style="font-size:12px;color:#A32D2D">could not reach /integrity endpoint</div>';
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
hlthFetch();gpuFetch();integrityFetch();activityFetch();
</script>
"""


def health_section_html(health: EcosystemHealth, control_center_url: str,
                        sentry_org: str = "", sentry_project_slugs: Optional[List[str]] = None) -> str:
    sub_tabs = [
        ("overview", "Overview",      _health_overview_section_html()),
        ("services", "Services",      _health_services_section_html()),
        ("storage",  "Disk & Mounts", _health_storage_section_html()),
        ("gpu",      "GPU",           _health_gpu_section_html()),
        ("activity", "Activity",      _health_activity_section_html()),
        ("errors",   "Errors",        error_aggregation_section_html(sentry_org, sentry_project_slugs or [])),
    ]
    return misc_section_html(sub_tabs, group_id="health", render_nav=False) + _HEALTH_SCRIPT

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


def cost_tracking_placeholder_section_html() -> str:
    """"Coming soon" placeholder for the sidebar's Cost Tracking leaf.

    Cost tracking needs real AWS/GCP/Azure billing-API credentials tied to
    an active paying account -- separate IAM permissions from whatever's
    already used for compute/storage -- and this deployment doesn't have
    those yet (it runs primarily on local/Slurm backends today). Not wired
    to any endpoint; no JSON contract to document since none is planned
    until real billing access exists.
    """
    return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">cost tracking</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    Coming soon. Cost tracking requires real AWS/GCP/Azure billing API credentials tied to an
    active paying account, which aren't in place for this deployment yet -- it currently runs
    primarily on local/Slurm backends. This view will be built once real cloud billing access
    is available.
  </div>
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
            f"{control_center_url.rstrip('/')}/knowledge-base", timeout=250
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
            f"{control_center_url.rstrip('/')}/storage", timeout=200
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


# ── SIDEBAR GROUP: DOCKER IMAGES (active) ───────────────────────────────────────
# Adapted from docker_section_html_UNUSED above into three separate sub-tab
# panels (matching how misc_section_html groups work) instead of one section
# with its own internal dk-sub switcher -- the sidebar now drives that switch.
# Same backend endpoints (/docker/containers, /docker/sif-images,
# /docker/plugin-images), same client-side rendering/filtering logic.

def docker_kpi_header_html() -> str:
    """Shared KPI strip -- rendered once via misc_section_html's header_html,
    so it stays visible across all three Docker Images sub-tabs rather than
    being tied to (and duplicated across) each one."""
    return """
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">running / total</div><div class="kpi-val" id="dk-k-run">—</div><div class="kpi-sub">containers</div></div>
  <div class="kpi"><div class="kpi-label">SIF built</div><div class="kpi-val" id="dk-k-sif-ok" style="color:#22c55e">—</div><div class="kpi-sub">images</div></div>
  <div class="kpi"><div class="kpi-label">SIF missing</div><div class="kpi-val" id="dk-k-sif-miss" style="color:#ef4444">—</div><div class="kpi-sub">not built</div></div>
  <div class="kpi"><div class="kpi-label">SIF storage</div><div class="kpi-val" id="dk-k-gb">—</div><div class="kpi-sub">GB total</div></div>
  <div class="kpi"><div class="kpi-label">plugin images</div><div class="kpi-val" id="dk-k-plug">—</div><div class="kpi-sub">tracked</div></div>
  <div class="kpi"><div class="kpi-label">plugins present</div><div class="kpi-val" id="dk-k-plug-ok" style="color:#22c55e">—</div><div class="kpi-sub">local images</div></div>
</div>
"""


def docker_containers_section_html() -> str:
    return """
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
"""


def docker_sif_section_html() -> str:
    return """
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
"""


def docker_plugins_section_html() -> str:
    return """
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
"""


_DOCKER_IMAGES_SCRIPT = """
<script>
var _DKU='';
var _DC={pp:15,page:1,all:[],filtered:[],q:''};
var _DS={pp:15,page:1,all:[],filtered:[],q:'',cat:null};
var _DP={pp:15,page:1,all:[],filtered:[],q:'',cat:null,miss:false};

function _dkBadge(r,re){
  var bg=r?'rgba(34,197,94,.12)':re?'rgba(245,158,11,.12)':'rgba(239,68,68,.12)';
  var c=r?'#22c55e':re?'#f59e0b':'#ef4444';
  return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+bg+';color:'+c+';white-space:nowrap">'+(r?'running':re?'restarting':'stopped')+'</span>';
}

function _dkChip(cat){
  var M={alignment:'#0094ff',assembly:'#22c55e','variant-calling':'#a855f7','rna-seq':'#f59e0b',genomics:'#0094ff',metagenomics:'#0094ff',proteomics:'#ef4444','single-cell':'#0094ff',epigenomics:'#f59e0b','protein-structure':'#a855f7','population-genetics':'#22c55e',annotation:'#f59e0b',qc:'#9ca3af',imaging:'#ef4444'};
  var c=M[cat]||'#9ca3af';
  return '<span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:99px;background:'+c+'22;color:'+c+';white-space:nowrap">'+cat+'</span>';
}

function _dkBuildSidebar(sid,all,curCat,onCat){
  var cats={};all.forEach(function(x){cats[x.category]=(cats[x.category]||0)+1;});
  var el=document.getElementById(sid);
  el.innerHTML='<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>';
  var entries=[['All',null,all.length]].concat(Object.entries(cats).sort(function(a,b){return b[1]-a[1];}).map(function(e){return[e[0],e[0],e[1]];}));
  entries.forEach(function(e){
    var active=e[1]===curCat;
    var btn=document.createElement('button');
    btn.style.cssText='width:100%;text-align:left;padding:5px 8px;border-radius:6px;font-size:11px;background:'+(active?'rgba(0,229,160,.1)':'transparent')+';color:'+(active?'#00e5a0':'#6b7280')+';border:1px solid '+(active?'rgba(0,229,160,.25)':'transparent')+';font-weight:'+(active?'600':'400')+';cursor:pointer;display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;font-family:inherit';
    var lbl=document.createElement('span');lbl.style.cssText='overflow:hidden;text-overflow:ellipsis;white-space:nowrap';lbl.textContent=e[0];
    var cnt=document.createElement('span');cnt.style.cssText='background:rgba(255,255,255,.08);color:#6b7280;border-radius:99px;font-size:10px;font-weight:700;padding:1px 5px;flex-shrink:0;margin-left:4px';cnt.textContent=e[2];
    btn.appendChild(lbl);btn.appendChild(cnt);
    btn.onclick=(function(cat){return function(){onCat(cat);};})(e[1]);
    el.appendChild(btn);
  });
}

/* ── Containers ── */
function dkCS(v){_DC.q=v.toLowerCase();_DC.page=1;dkCA();}
function dkCA(){
  var d=_DC.all.filter(function(c){return!_DC.q||((c.Names||'')+' '+(c.Image||'')).toLowerCase().includes(_DC.q);});
  _DC.filtered=d;document.getElementById('dk-cont-count').textContent=d.length+' containers';
  var pg=d.slice((_DC.page-1)*_DC.pp,_DC.page*_DC.pp);
  document.getElementById('dk-cont-tbody').innerHTML=pg.length?pg.map(function(c){
    var name=(c.Names||'').replace(/^[/]/,'')||'—';var s=(c.State||'').toLowerCase();
    var r=s==='running'||(c.Status||'').startsWith('Up');var re=s==='restarting'||(c.Status||'').toLowerCase().includes('restart');
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important;white-space:nowrap">'+name+'</td>'+
      '<td class="mono">'+(c.Image||'—')+'</td><td>'+_dkBadge(r,re)+'</td>'+
      '<td style="font-size:12px;color:#e2e8f0 !important;white-space:nowrap">'+(c.RunningFor||'—')+'</td>'+
      '<td class="mono">'+(c.Ports||'—')+'</td></tr>';
  }).join(''):'<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">No containers found</td></tr>';
  renderPg('dk-cont',_DC,dkCA);
}

/* ── SIF Images ── */
function dkSS(v){_DS.q=v.toLowerCase();_DS.page=1;dkSA();}
function dkSC(cat){_DS.cat=cat;_DS.page=1;dkSA();_dkBuildSidebar('dk-sif-sidebar',_DS.all,_DS.cat,dkSC);}
function dkSA(){
  var d=_DS.all.filter(function(i){return(!_DS.q||i.tool.toLowerCase().includes(_DS.q))&&(!_DS.cat||i.category===_DS.cat);});
  _DS.filtered=d;document.getElementById('dk-sif-count').textContent=d.length+' images';
  var pg=d.slice((_DS.page-1)*_DS.pp,_DS.page*_DS.pp);
  document.getElementById('dk-sif-tbody').innerHTML=pg.length?pg.map(function(i){
    var sb=i.exists?'rgba(34,197,94,.12)':'rgba(239,68,68,.12)';var sc=i.exists?'#22c55e':'#ef4444';
    var sz='—';if(i.exists){var mb=i.size_mb,w=Math.min(100,(mb/5120)*100).toFixed(1),lbl=mb>=1024?(mb/1024).toFixed(1)+' GB':mb+' MB';sz='<div style="display:flex;align-items:center;gap:6px"><div style="width:50px;height:4px;background:#2a2d3e;border-radius:99px;overflow:hidden;flex-shrink:0"><div style="height:100%;width:'+w+'%;background:#0094ff;border-radius:99px"></div></div><span style="font-size:12px;font-family:monospace;color:#e2e8f0 !important;white-space:nowrap">'+lbl+'</span></div>';}
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important">'+i.tool+'</td>'+
      '<td>'+_dkChip(i.category)+'</td>'+
      '<td><span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+sb+';color:'+sc+'">'+(i.exists?'built':'missing')+'</span></td>'+
      '<td>'+sz+'</td></tr>';
  }).join(''):'<tr><td colspan="4" style="text-align:center;color:#6b7280;padding:24px 12px">No SIF images found</td></tr>';
  renderPg('dk-sif',_DS,dkSA);
}

/* ── Plugin Images ── */
function dkPS(v){_DP.q=v.toLowerCase();_DP.page=1;dkPA();}
function dkPM(v){_DP.miss=v;_DP.page=1;dkPA();}
function dkPC(cat){_DP.cat=cat;_DP.page=1;dkPA();_dkBuildSidebar('dk-plug-sidebar',_DP.all,_DP.cat,dkPC);}
function dkPA(){
  var d=_DP.all.filter(function(p){return(!_DP.q||(p.name+' '+p.plugin).toLowerCase().includes(_DP.q))&&(!_DP.cat||p.category===_DP.cat)&&(!_DP.miss||p.local_status==='missing');});
  _DP.filtered=d;document.getElementById('dk-plug-count').textContent=d.length+' plugins';
  var pg=d.slice((_DP.page-1)*_DP.pp,_DP.page*_DP.pp);
  document.getElementById('dk-plug-tbody').innerHTML=pg.length?pg.map(function(p){
    var sb=p.local_status==='present'?'rgba(34,197,94,.12)':'rgba(239,68,68,.12)';var sc=p.local_status==='present'?'#22c55e':'#ef4444';
    var sz='—';if(p.local_status==='present'&&p.size_mb>0)sz=p.size_mb>=1024?(p.size_mb/1024).toFixed(1)+' GB':p.size_mb+' MB';
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important;white-space:nowrap">'+p.name+'</td>'+
      '<td>'+_dkChip(p.category)+'</td>'+
      '<td class="mono" style="max-width:260px">'+p.image+'</td>'+
      '<td><span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+sb+';color:'+sc+'">'+p.local_status+'</span></td>'+
      '<td style="font-size:12px;font-family:monospace;color:#e2e8f0 !important;white-space:nowrap">'+sz+'</td></tr>';
  }).join(''):'<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">No plugins match filters</td></tr>';
  renderPg('dk-plug',_DP,dkPA);
}

/* ── Fetch all three endpoints on load ── */
(function(){
  fetch(_DKU+'/docker/containers').then(function(r){return r.json();}).then(function(d){
    _DC.all=d.containers||[];
    document.getElementById('dk-k-run').textContent=(d.running||0)+'/'+_DC.all.length;
    dkCA();
  }).catch(function(){document.getElementById('dk-cont-tbody').innerHTML='<tr><td colspan="5" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';});

  fetch(_DKU+'/docker/sif-images').then(function(r){return r.json();}).then(function(d){
    _DS.all=d.images||[];
    document.getElementById('dk-k-sif-ok').textContent=d.built||0;
    document.getElementById('dk-k-sif-miss').textContent=d.missing||0;
    document.getElementById('dk-k-gb').textContent=(d.total_gb||0)+' GB';
    _dkBuildSidebar('dk-sif-sidebar',_DS.all,_DS.cat,dkSC);
    dkSA();
  }).catch(function(){document.getElementById('dk-sif-tbody').innerHTML='<tr><td colspan="4" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';});

  fetch(_DKU+'/docker/plugin-images').then(function(r){return r.json();}).then(function(d){
    _DP.all=d.plugins||[];
    document.getElementById('dk-k-plug').textContent=_DP.all.length;
    document.getElementById('dk-k-plug-ok').textContent=d.present||0;
    _dkBuildSidebar('dk-plug-sidebar',_DP.all,_DP.cat,dkPC);
    dkPA();
  }).catch(function(){document.getElementById('dk-plug-tbody').innerHTML='<tr><td colspan="5" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';});
})();
</script>
"""


# ── TAB: CATALOG ───────────────────────────────────────────────────────────────

CATALOG_BACKEND_COLORS = {
    "slurm": "#3C3489", "http": "#0F6E56", "aws_batch": "#854F0B",
    "gcp_batch": "#185FA5", "azure_batch": "#A32D2D", "kubernetes": "#7F77DD",
    "unknown": "#444441",
}

WORKFLOW_EXTS = {
    ".nf": "Nextflow", ".wdl": "WDL", ".cwl": "CWL", ".smk": "Snakemake",
}
WORKFLOW_SPECIAL_NAMES = {
    "Snakefile": "Snakemake", "main.nf": "Nextflow",
}


def _count_plugins(ecosystem_root: Path) -> Tuple[int, Dict[str, int]]:
    """Counts plugin directories under omnibioai/plugins/ that contain a plugin.json."""
    plugins_dir = ecosystem_root / "omnibioai" / "plugins"
    if not plugins_dir.is_dir():
        return 0, {}
    by_category: Dict[str, int] = {}
    count = 0
    for entry in plugins_dir.iterdir():
        if not entry.is_dir():
            continue
        pj = entry / "plugin.json"
        if not pj.exists():
            continue
        count += 1
        try:
            meta = json.loads(pj.read_text(encoding="utf-8"))
            cat = str(meta.get("category", "uncategorized"))
        except Exception:
            cat = "uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1
    return count, by_category


def _infer_tool_backend(tool: Dict[str, Any]) -> str:
    for key, backend in (
        ("slurm", "slurm"), ("http", "http"),
        ("aws_batch", "aws_batch"), ("aws", "aws_batch"),
        ("gcp_batch", "gcp_batch"), ("gcp", "gcp_batch"),
        ("azure_batch", "azure_batch"), ("azure", "azure_batch"),
        ("kubernetes", "kubernetes"), ("k8s", "kubernetes"),
    ):
        if key in tool:
            return backend
    return "unknown"


def _count_tes_tools(ecosystem_root: Path) -> Tuple[int, Dict[str, int]]:
    """
    Counts tools from the live TES API if reachable (ground truth), else falls
    back to reading omnibioai-tes/configs/tools/*.yaml + x86_64/*.yaml directly
    (NOT tools.example.yaml, which is generated and can drift).

    Each category YAML file's root is a plain list of tool dicts (verified
    against configs/tools/01_qc_preprocessing.yaml etc.), not {"tools": [...]}.
    """
    try:
        req = urllib.request.Request(
            "http://tes:8081/api/tools",
            headers={"User-Agent": "omnibioai-report/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            tools = json.loads(resp.read().decode("utf-8"))
        by_backend: Dict[str, int] = {}
        for t in tools:
            tags = set(t.get("tags") or [])
            backend = next(
                (b for b in ("slurm", "http", "aws_batch", "gcp_batch",
                              "azure_batch", "kubernetes", "k8s") if b in tags),
                "unknown")
            by_backend[backend] = by_backend.get(backend, 0) + 1
        return len(tools), by_backend
    except Exception:
        pass  # fall through to static file counting

    if yaml is None:
        return 0, {}
    tools_dir = ecosystem_root / "omnibioai-tes" / "configs" / "tools"
    if not tools_dir.is_dir():
        return 0, {}
    yaml_files = list(tools_dir.glob("*.yaml")) + list(tools_dir.glob("x86_64/*.yaml"))
    total = 0
    by_backend: Dict[str, int] = {}
    for yf in yaml_files:
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8")) or []
        except Exception:
            continue
        tools = data.get("tools", []) if isinstance(data, dict) else data
        for t in (tools or []):
            total += 1
            backend = _infer_tool_backend(t)
            by_backend[backend] = by_backend.get(backend, 0) + 1
    return total, by_backend


def _count_workflow_bundles(ecosystem_root: Path) -> Tuple[int, Dict[str, int]]:
    """
    Counts workflow bundles under omnibioai-workflow-bundles/ by locating
    workflow definition files (Nextflow .nf, WDL .wdl, CWL .cwl, Snakemake
    Snakefile/.smk) and deduplicating by parent directory -- one bundle
    directory may contain a main workflow file plus supporting files, so
    counting files directly would overcount.
    """
    bundles_dir = ecosystem_root / "omnibioai-workflow-bundles"
    if not bundles_dir.is_dir():
        return 0, {}
    exclude_names = set(EXCLUDE_DIRS.split(","))
    bundle_dirs: Dict[Path, str] = {}
    for ext, label in WORKFLOW_EXTS.items():
        for f in bundles_dir.rglob(f"*{ext}"):
            if any(part in exclude_names or part.startswith(".") for part in f.parts):
                continue
            bundle_dirs.setdefault(f.parent, label)
    for name, label in WORKFLOW_SPECIAL_NAMES.items():
        for f in bundles_dir.rglob(name):
            if any(part in exclude_names or part.startswith(".") for part in f.parts):
                continue
            bundle_dirs.setdefault(f.parent, label)
    by_type: Dict[str, int] = {}
    for _, label in bundle_dirs.items():
        by_type[label] = by_type.get(label, 0) + 1
    return len(bundle_dirs), by_type


def catalog_section_html(ecosystem_root: Path) -> str:
    plugin_count, plugin_cats = _count_plugins(ecosystem_root)
    tool_count, tool_backends = _count_tes_tools(ecosystem_root)
    workflow_count, workflow_types = _count_workflow_bundles(ecosystem_root)

    def _breakdown_rows(d: Dict[str, int], color_map: Optional[Dict[str, str]] = None) -> str:
        if not d:
            return '<div style="font-size:12px;color:var(--color-text-muted);padding:8px">no breakdown available</div>'
        total = sum(d.values()) or 1
        rows = ""
        for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True):
            color = (color_map or {}).get(k, "#0094ff")
            pct = round(100 * v / total, 1)
            rows += f"""
            <div class="bar-row">
              <span class="bar-label" style="width:120px">{k}</span>
              <div class="bar-track" style="height:14px">
                <div class="bar-fill" style="width:{pct}%;background:{color}22"></div>
                <span class="bar-val" style="color:{color}">{fmt_int(v)}</span>
              </div>
            </div>"""
        return rows

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">plugins</div><div class="kpi-val">{fmt_int(plugin_count)}</div><div class="kpi-sub">omnibioai/plugins</div></div>
  <div class="kpi"><div class="kpi-label">tools</div><div class="kpi-val">{fmt_int(tool_count)}</div><div class="kpi-sub">omnibioai-tes</div></div>
  <div class="kpi"><div class="kpi-label">workflow bundles</div><div class="kpi-val">{fmt_int(workflow_count)}</div><div class="kpi-sub">omnibioai-workflow-bundles</div></div>
  <div class="kpi"><div class="kpi-label">total catalog</div><div class="kpi-val">{fmt_int(plugin_count + tool_count + workflow_count)}</div><div class="kpi-sub">plugins + tools + workflows</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
  <div class="section">
    <div class="sec-title">plugins by category</div>
    <div class="sec-sub">omnibioai/plugins/*/plugin.json</div>
    {_breakdown_rows(plugin_cats)}
  </div>
  <div class="section">
    <div class="sec-title">tools by backend</div>
    <div class="sec-sub">live TES API if reachable, else configs/tools/*.yaml</div>
    {_breakdown_rows(tool_backends, CATALOG_BACKEND_COLORS)}
  </div>
  <div class="section">
    <div class="sec-title">workflow bundles by type</div>
    <div class="sec-sub">Nextflow / WDL / CWL / Snakemake</div>
    {_breakdown_rows(workflow_types)}
  </div>
</div>

<div style="font-size:11px;color:var(--color-text-muted);margin-top:12px;padding:8px 0;border-top:0.5px solid var(--color-border)">
  Tool count prefers the live TES API (ground truth) when reachable at http://tes:8081;
  falls back to static YAML file counting otherwise. Plugin/workflow counts are
  filesystem-based and reflect what's on disk at report-generation time.
</div>
</div>
"""


# ── TAB: MODEL REGISTRY ─────────────────────────────────────────────────────────

def _classify_data_source(version_name: str, meta: Dict[str, Any],
                          metrics: Dict[str, Any]) -> Tuple[str, str]:
    """
    Returns (classification, confidence) where classification is one of
    "real" / "synthetic" / "unknown", and confidence is "explicit"
    (meta.json has a real data_source field -- trust this) or "inferred"
    (guessed from naming patterns -- show as heuristic, not fact).
    """
    explicit = meta.get("data_source")
    if explicit in ("real", "synthetic"):
        return explicit, "explicit"

    vname = (version_name or "").lower()
    if "real" in vname:
        return "real", "inferred"
    if vname.endswith("_test") or "_test_" in vname or vname == "test":
        return "synthetic", "inferred"

    if metrics.get("seed") == 42 or metrics.get("random_state") == 42:
        return "synthetic", "inferred"
    n_train = metrics.get("n_train") or metrics.get("n_train_cells")
    if isinstance(n_train, (int, float)) and n_train < 100:
        return "synthetic", "inferred"
    if meta.get("git_commit") == "abc123":
        return "synthetic", "inferred"

    return "unknown", "inferred"


def _scan_model_registry(registry_root: Path) -> List[Dict[str, Any]]:
    """
    Walks registry_root/tasks/<task>/models/<model_name>/versions/<version>/
    reading metrics.json and model_meta.json for each.

    Some version directories (verified: real-data training runs under
    admet_properties/admet_mlp) are written mode 700 owned by the
    container's training process -- reading them succeeds when this script
    runs as root inside the control-center container (confirmed: that's
    the only context it actually runs in, per _run_report_job), but would
    PermissionError on a bare-host run as an unprivileged user. Each
    version is scanned independently so one unreadable directory doesn't
    take down the whole registry scan.
    """
    rows: List[Dict[str, Any]] = []
    tasks_dir = registry_root / "tasks"
    if not tasks_dir.is_dir():
        return rows
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        models_dir = task_dir / "models"
        if not models_dir.is_dir():
            continue
        for model_dir in sorted(models_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            versions_dir = model_dir / "versions"
            if not versions_dir.is_dir():
                continue
            for version_dir in sorted(versions_dir.iterdir()):
                if not version_dir.is_dir():
                    continue
                metrics: Dict[str, Any] = {}
                meta: Dict[str, Any] = {}
                mtime = 0.0
                try:
                    mtime = version_dir.stat().st_mtime
                    mf = version_dir / "metrics.json"
                    mmf = version_dir / "model_meta.json"
                    if mf.exists():
                        metrics = json.loads(mf.read_text(encoding="utf-8"))
                    if mmf.exists():
                        meta = json.loads(mmf.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                cls, confidence = _classify_data_source(version_dir.name, meta, metrics)
                metric_display = None
                for k in ("test_accuracy", "val_accuracy", "accuracy",
                          "test_mae", "val_mae", "val_mae_pki", "mae",
                          "auroc", "test_auroc"):
                    if k in metrics:
                        metric_display = f"{k}={metrics[k]}"
                        break
                rows.append({
                    "task": task_dir.name,
                    "model": model_dir.name,
                    "version": version_dir.name,
                    "data_source": cls,
                    "confidence": confidence,
                    "metric": metric_display or "—",
                    "mtime": mtime,
                })
    return rows


def model_registry_section_html(registry_root: Path) -> str:
    rows = _scan_model_registry(registry_root)

    total_versions = len(rows)
    real_rows = [r for r in rows if r["data_source"] == "real"]
    synth_rows = [r for r in rows if r["data_source"] == "synthetic"]
    unknown_rows = [r for r in rows if r["data_source"] == "unknown"]

    tasks_with_real = len(set(r["task"] for r in real_rows))
    total_tasks = len(set(r["task"] for r in rows))

    inferred_count = sum(1 for r in rows if r["confidence"] == "inferred")

    rows_js = [json.dumps(r) for r in sorted(rows, key=lambda r: r["mtime"], reverse=True)]
    rows_js_str = "[" + ",".join(rows_js) + "]"

    return f"""
<div class="tab-section">
<div style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px">
  data_source classification: explicit field if present in model_meta.json, otherwise
  <span style="color:#854F0B;font-weight:600">inferred</span> from naming/metric patterns —
  {inferred_count}/{total_versions} versions are inferred, not confirmed.
</div>

<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">tasks</div><div class="kpi-val">{total_tasks}</div><div class="kpi-sub">{tasks_with_real} with ≥1 real version</div></div>
  <div class="kpi"><div class="kpi-label">total versions</div><div class="kpi-val">{fmt_int(total_versions)}</div><div class="kpi-sub">all registered</div></div>
  <div class="kpi"><div class="kpi-label">real</div><div class="kpi-val" style="color:#3B6D11">{fmt_int(len(real_rows))}</div><div class="kpi-sub">confirmed/inferred real data</div></div>
  <div class="kpi"><div class="kpi-label">synthetic</div><div class="kpi-val" style="color:#A32D2D">{fmt_int(len(synth_rows))}</div><div class="kpi-sub">dummy/placeholder data</div></div>
  <div class="kpi"><div class="kpi-label">unknown</div><div class="kpi-val" style="color:#854F0B">{fmt_int(len(unknown_rows))}</div><div class="kpi-sub">unclassified</div></div>
</div>

<div class="section">
  <div class="sec-title">all model versions</div>
  <div class="sec-sub">sorted by most recent · click headers to sort</div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search task/model/version..." oninput="mrFilter(this.value)">
    <select class="filter-sel" onchange="mrSourceFilter(this.value)">
      <option value="">all data sources</option>
      <option value="real">real</option>
      <option value="synthetic">synthetic</option>
      <option value="unknown">unknown</option>
    </select>
    <span class="result-count" id="mr-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="mrPerPage(this.value)"><option value="15" selected>15</option><option value="30">30</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="mrSort('task')">task</th>
        <th onclick="mrSort('model')">model</th>
        <th onclick="mrSort('version')">version</th>
        <th onclick="mrSort('data_source')">data source</th>
        <th onclick="mrSort('metric')">metric</th>
      </tr></thead>
      <tbody id="mr-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="mr-pg"></div>
</div>
</div>

<script>
var _mrd={rows_js_str},_mrs={{data:[],filtered:[],page:1,pp:15,sort:'mtime',dir:-1,search:'',source:''}};
var _mrColors={{real:'#3B6D11',synthetic:'#A32D2D',unknown:'#854F0B'}};
var _mrBg={{real:'#EAF3DE',synthetic:'#FCEBEB',unknown:'#FAEEDA'}};
(function(){{_mrs.data=_mrd.slice();mrApply();}})();
function mrFilter(v){{_mrs.search=v.toLowerCase();_mrs.page=1;mrApply();}}
function mrSourceFilter(v){{_mrs.source=v;_mrs.page=1;mrApply();}}
function mrPerPage(v){{_mrs.pp=parseInt(v);_mrs.page=1;mrApply();}}
function mrSort(col){{if(_mrs.sort===col)_mrs.dir*=-1;else{{_mrs.sort=col;_mrs.dir=1;}} _mrs.page=1;mrApply();}}
function mrApply(){{
  var d=_mrs.data.slice();
  if(_mrs.search)d=d.filter(function(r){{return (r.task+r.model+r.version).toLowerCase().includes(_mrs.search);}});
  if(_mrs.source)d=d.filter(function(r){{return r.data_source===_mrs.source;}});
  var col=_mrs.sort;
  d.sort(function(a,b){{var av=(a[col]||'').toString().toLowerCase();var bv=(b[col]||'').toString().toLowerCase();return av<bv?_mrs.dir:av>bv?-_mrs.dir:0;}});
  _mrs.filtered=d;
  document.getElementById('mr-count').textContent=d.length+' items';
  var start=(_mrs.page-1)*_mrs.pp,page=d.slice(start,start+_mrs.pp);
  var tb=document.getElementById('mr-tbody');tb.innerHTML='';
  page.forEach(function(r){{
    var tr=document.createElement('tr');
    var confBadge=r.confidence==='inferred'?' <span style="font-size:9px;color:#854F0B;opacity:.8">(inferred)</span>':'';
    tr.innerHTML='<td style="font-size:12px">'+r.task+'</td>'+
      '<td style="font-size:12px">'+r.model+'</td>'+
      '<td class="mono">'+r.version+'</td>'+
      '<td><span class="badge" style="background:'+_mrBg[r.data_source]+';color:'+_mrColors[r.data_source]+'">'+r.data_source+'</span>'+confBadge+'</td>'+
      '<td style="font-size:12px" class="mono">'+r.metric+'</td>';
    tb.appendChild(tr);
  }});
  renderPg('mr',_mrs,mrApply);
}}
</script>
"""


# ── TAB: USAGE ─────────────────────────────────────────────────────────────────

# Expected /usage response shape:
# {
#   "active_users_7d": int, "active_users_30d": int,
#   "total_users": int, "test_user_count": int, "users_caveat": str,
#   "total_sessions_30d": int, "sessions_caveat": str,
#   "top_plugins": [{"name": str, "runs_30d": int}, ...],
#   "top_workflows": [],  # always empty -- see top_workflows_note
#   "top_workflows_note": str,
#   "runs_by_day": [{"date": "YYYY-MM-DD", "count": int}, ...],
#   "workflow_success_rate_pct": float, "success_rate_caveat": str
# }
def usage_section_html(control_center_url: str) -> str:
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/usage", timeout=60
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] usage_section_html failed: {type(e).__name__}: {e}", flush=True)

    if not data:
        return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">product usage</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    Could not reach control center for usage stats.
  </div>
</div>
</div>"""

    au7 = data.get("active_users_7d", 0)
    au30 = data.get("active_users_30d", 0)
    total_users = data.get("total_users", 0)
    test_user_count = data.get("test_user_count", 0)
    users_caveat = data.get("users_caveat", "")
    sessions30 = data.get("total_sessions_30d", 0)
    sessions_caveat = data.get("sessions_caveat", "")
    success_pct = data.get("workflow_success_rate_pct", 0)
    success_caveat = data.get("success_rate_caveat", "")
    success_color = "#3B6D11" if success_pct >= 90 else "#854F0B" if success_pct >= 75 else "#A32D2D"

    top_plugins = data.get("top_plugins", [])
    top_workflows = data.get("top_workflows", [])
    top_workflows_note = data.get("top_workflows_note", "")
    runs_by_day = data.get("runs_by_day", [])

    day_labels = _jsl([d.get("date", "") for d in runs_by_day])
    day_counts = _jsn([d.get("count", 0) for d in runs_by_day])

    plugin_rows = "".join(f"""<tr>
          <td style="font-size:12px">{it.get('name','')}</td>
          <td class="r">{it.get('runs_30d',0)}</td>
        </tr>""" for it in top_plugins) or \
        '<tr><td colspan="2" style="text-align:center;color:var(--color-text-muted);padding:12px">no plugin data</td></tr>'

    if top_workflows:
        workflows_panel = f"""<div class="tbl-wrap">
      <table>
        <thead><tr><th>workflow</th><th class="r">runs</th></tr></thead>
        <tbody>{"".join(f'<tr><td style="font-size:12px">{it.get("name","")}</td><td class="r">{it.get("runs_30d",0)}</td></tr>' for it in top_workflows)}</tbody>
      </table>
    </div>"""
    else:
        workflows_panel = f"""<div style="border:1px dashed var(--color-border);border-radius:8px;
         display:flex;flex-direction:column;align-items:center;justify-content:center;
         gap:8px;padding:24px 16px;text-align:center;min-height:140px">
      <div style="font-size:22px;color:var(--color-text-muted);opacity:.5">—</div>
      <div style="font-size:11px;color:var(--color-text-muted);font-weight:600">not available yet</div>
      <div style="font-size:11px;color:var(--color-text-muted);max-width:280px;line-height:1.5">{top_workflows_note}</div>
    </div>"""

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">active users (7d)</div><div class="kpi-val">{au7}</div></div>
  <div class="kpi">
    <div class="kpi-label">active users (30d)</div><div class="kpi-val">{au30}</div>
    <div class="kpi-sub">{test_user_count} of {total_users} accounts are test/throwaway</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">sessions (30d)</div><div class="kpi-val">{sessions30}</div>
    <div class="kpi-sub">approximate -- see note below</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">workflow success</div><div class="kpi-val" style="color:{success_color}">{success_pct}%</div>
    <div class="kpi-sub">plugin-run level, not DAG-level</div>
  </div>
</div>
<div style="font-size:11px;color:var(--color-text-muted);line-height:1.6;margin:-6px 0 16px">
  {users_caveat}<br>{sessions_caveat}<br>{success_caveat}
</div>

<div class="section">
  <div class="sec-title">runs by day</div>
  <div class="sec-sub">last 30 days</div>
  <div style="position:relative;height:220px"><canvas id="usage-runs-chart"></canvas></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
  <div class="section">
    <div class="sec-title">top plugins</div>
    <div class="sec-sub">by run count · last 30 days</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>plugin</th><th class="r">runs</th></tr></thead>
        <tbody>{plugin_rows}</tbody>
      </table>
    </div>
  </div>
  <div class="section">
    <div class="sec-title">top workflows</div>
    <div class="sec-sub">by run count · last 30 days</div>
    {workflows_panel}
  </div>
</div>
</div>

<script>
(function(){{
  var el=document.getElementById('usage-runs-chart');
  if(!el)return;
  new Chart(el,{{
    type:'bar',
    data:{{labels:{day_labels},datasets:[{{data:{day_counts},backgroundColor:'#00e5a044',borderColor:'#00e5a0',borderWidth:1,borderRadius:4}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}}}},
      scales:{{y:{{beginAtZero:true,ticks:{{font:{{size:10}},color:'#9CA3AF'}},grid:{{color:'rgba(0,0,0,0.04)'}},border:{{display:false}}}},
               x:{{ticks:{{font:{{size:9}},color:'#9CA3AF',maxRotation:45,autoSkip:true}},grid:{{display:false}},border:{{display:false}}}}}}}}
  }});
}})();
</script>
"""


# Expected /gateway-traffic response shape:
# {
#   "requests_7d": int, "health_check_pings_7d": int,
#   "p50_latency_ms": int, "p95_latency_ms": int, "p99_latency_ms": int,
#   "auth_failure_rate_pct": float,
#   "requests_by_route": [{"route": str, "count": int}, ...],
#   "status_code_breakdown": {"2xx": int, "4xx": int, "5xx": int}
# }
def gateway_traffic_section_html(control_center_url: str) -> str:
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/gateway-traffic", timeout=15
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] gateway_traffic_section_html failed: {type(e).__name__}: {e}", flush=True)

    if not data:
        return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">API gateway traffic</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    Could not reach /gateway-traffic -- not implemented yet. Expected JSON shape:
    <pre style="font-size:11px;color:var(--color-text-muted);margin-top:8px;white-space:pre-wrap">{
  "requests_7d": int, "health_check_pings_7d": int,
  "p50_latency_ms": int, "p95_latency_ms": int, "p99_latency_ms": int,
  "auth_failure_rate_pct": float,
  "requests_by_route": [{"route": str, "count": int}, ...],
  "status_code_breakdown": {"2xx": int, "4xx": int, "5xx": int}
}</pre>
  </div>
</div>
</div>"""

    requests_7d = data.get("requests_7d", 0)
    health_pings = data.get("health_check_pings_7d", 0)
    p50 = data.get("p50_latency_ms", 0)
    p95 = data.get("p95_latency_ms", 0)
    p99 = data.get("p99_latency_ms", 0)
    auth_fail_pct = data.get("auth_failure_rate_pct", 0)
    auth_fail_color = "#3B6D11" if auth_fail_pct <= 1 else "#854F0B" if auth_fail_pct <= 5 else "#A32D2D"

    breakdown = data.get("status_code_breakdown", {}) or {}
    c2xx = breakdown.get("2xx", 0)
    c4xx = breakdown.get("4xx", 0)
    c5xx = breakdown.get("5xx", 0)

    routes = data.get("requests_by_route", [])
    route_rows = "".join(f"""<tr>
          <td class="mono">{r.get('route','')}</td>
          <td class="r">{r.get('count',0)}</td>
        </tr>""" for r in routes) or \
        '<tr><td colspan="2" style="text-align:center;color:var(--color-text-muted);padding:12px">no route data</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">requests (7d, excl. health checks)</div><div class="kpi-val">{fmt_int(requests_7d)}</div></div>
  <div class="kpi"><div class="kpi-label">health check pings (7d)</div><div class="kpi-val" style="color:var(--color-text-muted)">{fmt_int(health_pings)}</div></div>
  <div class="kpi"><div class="kpi-label">p50 latency</div><div class="kpi-val">{p50} ms</div></div>
  <div class="kpi"><div class="kpi-label">p95 latency</div><div class="kpi-val">{p95} ms</div></div>
  <div class="kpi"><div class="kpi-label">p99 latency</div><div class="kpi-val">{p99} ms</div></div>
  <div class="kpi"><div class="kpi-label">auth failure rate</div><div class="kpi-val" style="color:{auth_fail_color}">{auth_fail_pct}%</div></div>
</div>

<div style="display:grid;grid-template-columns:200px 1fr;gap:12px">
  <div class="section" style="display:flex;flex-direction:column">
    <div class="sec-title">status codes</div>
    <div class="sec-sub">last 7d, excl. health checks</div>
    <div style="position:relative;width:120px;height:120px;margin:0 auto 12px">
      <canvas id="gw-status-donut" width="120" height="120"></canvas>
      <div class="donut-center">
        <div class="donut-center-val">{fmt_int(c2xx+c4xx+c5xx)}</div>
        <div class="donut-center-lbl">requests</div>
      </div>
    </div>
    <div>
      {"".join(f'<div class="legend-item"><span class="legend-dot" style="background:{c}"></span><span>{lbl}</span><span class="legend-pct">{cnt}</span></div>' for c,lbl,cnt in [('#3B6D11','2xx',c2xx),('#854F0B','4xx',c4xx),('#A32D2D','5xx',c5xx)])}
    </div>
  </div>
  <div class="section">
    <div class="sec-title">top routes</div>
    <div class="sec-sub">by request count · last 7d, excl. health checks</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>route</th><th class="r">requests</th></tr></thead>
        <tbody>{route_rows}</tbody>
      </table>
    </div>
  </div>
</div>
</div>

<script>
(function(){{
  var el=document.getElementById('gw-status-donut');
  if(!el)return;
  new Chart(el,{{
    type:'doughnut',
    data:{{labels:['2xx','4xx','5xx'],
           datasets:[{{data:[{c2xx},{c4xx},{c5xx}],
                       backgroundColor:['#3B6D11','#854F0B','#A32D2D'],
                       borderWidth:2,borderColor:'#1a1d2e',hoverOffset:3}}]}},
    options:{{responsive:false,cutout:'68%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+c.raw;}}}}}}}}}}
  }});
}})();
</script>
"""


# ── TAB: MISC ────────────────────────────────────────────────────────────────

def misc_section_html(sub_tabs: List[Tuple[str, str, str]], group_id: str = "misc",
                       render_nav: bool = True, header_html: str = "") -> str:
    """
    sub_tabs: list of (id, label, html_content) tuples. Renders a sub-nav
    plus one panel per sub-tab; first sub-tab is active by default.

    group_id namespaces the DOM ids/JS scope for this instance -- if this
    function is called more than once on the same page (e.g. one call for
    Misc, another for a combined LLMs & Cloud tab), each call's panel ids
    and sub-tab toggling must stay independent. Panel ids are namespaced
    as "misc-panel-{group_id}-{sid}" and miscSub() only ever queries
    within this instance's own wrapper div (id "misc-wrap-{group_id}"),
    so two instances never hide/show each other's panels.

    render_nav=False skips the inline sub-nav button row (panels + the
    miscSub() toggle function are unchanged) -- used when an external
    navigation UI (the sidebar) already lists these sub-tabs and drives
    miscSub() itself, so the inline row would just be a redundant second
    nav for the same choice.

    header_html renders once, above the nav row/panels, and is never
    hidden by the sub-tab switch -- for content that applies across all
    of a group's sub-tabs (e.g. a KPI strip fed by one shared fetch).
    """
    if not sub_tabs:
        return '<div class="tab-section"><div style="font-size:12px;color:var(--color-text-muted)">No misc sections configured yet.</div></div>'

    nav_buttons = ""
    panels = ""
    for i, (sid, label, content) in enumerate(sub_tabs):
        active = i == 0
        color = "#00e5a0" if active else "#6b7280"
        weight = "600" if active else "400"
        border = "#00e5a0" if active else "transparent"
        panel_id = f"misc-panel-{group_id}-{sid}"
        if render_nav:
            nav_buttons += (
                f'<button class="misc-sub" data-sub="{panel_id}" '
                f'onclick="miscSub(\'{group_id}\',\'{panel_id}\')" '
                f'style="padding:10px 16px;font-size:13px;color:{color};font-weight:{weight};'
                f'background:none;border:none;border-bottom:2px solid {border};cursor:pointer;'
                f'white-space:nowrap;margin-bottom:-1px;font-family:inherit">{label}</button>'
            )
        display = "" if active else "display:none"
        panels += f'<div id="{panel_id}" style="{display}">{content}</div>'

    nav_row = (
        f'<div style="display:flex;border-bottom:1px solid #2a2d3e;margin-bottom:16px">\n  {nav_buttons}\n</div>\n'
        if render_nav else ""
    )

    return f"""
<div class="tab-section">
<div id="misc-wrap-{group_id}">
{header_html}{nav_row}{panels}
</div>
</div>

<script>
function miscSub(groupId, id){{
  var wrap=document.getElementById('misc-wrap-'+groupId);
  if(!wrap) return;
  wrap.querySelectorAll('[id^="misc-panel-'+groupId+'-"]').forEach(function(p){{p.style.display='none';}});
  var target=document.getElementById(id);
  if(target)target.style.display='';
  wrap.querySelectorAll('.misc-sub').forEach(function(b){{
    var a=b.dataset.sub===id;
    b.style.color=a?'#00e5a0':'#6b7280';
    b.style.fontWeight=a?'600':'400';
    b.style.borderBottomColor=a?'#00e5a0':'transparent';
  }});
}}
</script>
"""


# ── SIDEBAR NAV ────────────────────────────────────────────────────────────────
# (top_id, label, children) -- children is None for a single-view leaf, or a
# list of (child_id, child_label) tuples for a group whose panel content was
# built with misc_section_html(..., group_id=top_id, render_nav=False).
SIDEBAR_NAV_SPEC: List[Tuple[str, str, Optional[List[Tuple[str, str]]]]] = [
    ("arch",         "Architecture",      None),
    ("projects",     "Projects",          [("summary", "Code Summary"), ("languages", "Languages"), ("coverage", "Code Coverage")]),
    ("health",       "Health Status",     [("overview", "Overview"), ("services", "Services"), ("storage", "Disk & Mounts"), ("gpu", "GPU"), ("activity", "Activity"), ("errors", "Errors")]),
    ("usage",        "Usage",             [("product", "Product Usage"), ("gateway", "API Gateway")]),
    ("llmscloud",    "LLMs & Cloud",      [("llms", "LLMs"), ("cloud", "Cloud"), ("cost", "Cost Tracking")]),
    ("ref",          "Reference Data",    None),
    ("kb",           "AI Knowledge Base", None),
    ("modelreg",     "Model Registry",    None),
    ("dockerimages", "Docker Images",     [("containers", "Platform Containers"), ("sif", "Tool SIF Images"), ("plugins", "Plugin Docker Images")]),
    ("misc",         "Miscellaneous",     [("issues", "Known Issues"), ("runs", "Active Runs"), ("storage", "Storage"), ("catalog", "Catalog"), ("database", "Data Layer"), ("queue", "Task Queue"), ("license", "License"), ("secrets", "Secrets Audit"), ("images", "Image Freshness"), ("ports", "Exposed Ports"), ("cicd", "CI/CD Health"), ("backup", "Backup Status")]),
]


def sidebar_nav_html(spec: List[Tuple[str, str, Optional[List[Tuple[str, str]]]]]) -> str:
    """Renders the left sidebar nav markup from SIDEBAR_NAV_SPEC.

    Group labels toggle their own child list (sbnavToggleGroup) rather than
    navigating; leaves (top-level or child) select a panel directly
    (sbnavSelectTop / sbnavSelectChild). URL-hash read/write is layered on
    top of these same two functions separately, not handled here.
    """
    items = ""
    for i, (top_id, label, children) in enumerate(spec):
        is_default_active = i == 0
        if children:
            child_buttons = "".join(
                f'<button class="sbnav-item sbnav-child" data-top="{top_id}" data-child="{cid}" '
                f'onclick="sbnavSelectChild(\'{top_id}\',\'{cid}\')">{clabel}</button>'
                for cid, clabel in children
            )
            items += f"""
<div class="sbnav-group" data-top="{top_id}">
  <button class="sbnav-item sbnav-group-label" data-top="{top_id}" onclick="sbnavToggleGroup('{top_id}')">
    <span class="sbnav-caret">&#9656;</span>{label}
  </button>
  <div class="sbnav-children" id="sbnav-children-{top_id}">{child_buttons}</div>
</div>"""
        else:
            active_cls = " active" if is_default_active else ""
            items += (
                f'\n<button class="sbnav-item sbnav-leaf{active_cls}" data-top="{top_id}" '
                f'onclick="sbnavSelectTop(\'{top_id}\')">{label}</button>'
            )
    return items


KNOWN_ISSUES_PATH_DEFAULT = "omnibioai-work/known_issues.json"

_SEVERITY_COLOR = {"high": "#A32D2D", "medium": "#854F0B", "low": "#185FA5"}
_SEVERITY_BG    = {"high": "#FCEBEB", "medium": "#FAEEDA", "low": "#E6F1FB"}
_STATUS_COLOR   = {"open": "#A32D2D", "acknowledged": "#854F0B", "resolved": "#3B6D11"}
_STATUS_BG      = {"open": "#FCEBEB", "acknowledged": "#FAEEDA", "resolved": "#EAF3DE"}


def known_issues_section_html(ecosystem_root: Path) -> str:
    issues_path = ecosystem_root / KNOWN_ISSUES_PATH_DEFAULT
    issues: List[Dict[str, Any]] = []
    load_error = None
    if issues_path.exists():
        try:
            issues = json.loads(issues_path.read_text(encoding="utf-8"))
        except Exception as e:
            load_error = str(e)
    else:
        load_error = f"No file at {issues_path} yet -- create it to start tracking issues"

    open_count = sum(1 for i in issues if i.get("status") == "open")
    ack_count = sum(1 for i in issues if i.get("status") == "acknowledged")
    resolved_count = sum(1 for i in issues if i.get("status") == "resolved")

    cards = ""
    for issue in sorted(issues, key=lambda i: (i.get("status") != "open", i.get("opened_at", "")), reverse=False):
        sev = issue.get("severity", "medium")
        st = issue.get("status", "open")
        cards += f"""
        <div style="background:var(--color-bg-surface2);border-left:3px solid {_STATUS_COLOR.get(st,'#444441')};border-radius:8px;padding:12px 14px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px;gap:8px">
            <span style="font-size:13px;font-weight:600">{issue.get('title','(untitled)')}</span>
            <div style="display:flex;gap:6px;flex-shrink:0">
              <span class="badge" style="background:{_SEVERITY_BG.get(sev,'#F1EFE8')};color:{_SEVERITY_COLOR.get(sev,'#444441')}">{sev}</span>
              <span class="badge" style="background:{_STATUS_BG.get(st,'#F1EFE8')};color:{_STATUS_COLOR.get(st,'#444441')}">{st}</span>
            </div>
          </div>
          <div style="font-size:12px;color:var(--color-text-muted);margin-bottom:4px">{issue.get('description','')}</div>
          <div style="font-size:10px;color:var(--color-text-muted)">{issue.get('area','')} · opened {issue.get('opened_at','')}</div>
        </div>"""

    if not cards:
        cards = f'<div style="font-size:12px;color:var(--color-text-muted)">{"No known issues logged." if not load_error else load_error}</div>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">open</div><div class="kpi-val" style="color:#A32D2D">{open_count}</div></div>
  <div class="kpi"><div class="kpi-label">acknowledged</div><div class="kpi-val" style="color:#854F0B">{ack_count}</div></div>
  <div class="kpi"><div class="kpi-label">resolved</div><div class="kpi-val" style="color:#3B6D11">{resolved_count}</div></div>
</div>
<div class="section">
  <div class="sec-title">known issues</div>
  <div class="sec-sub">manually maintained · edit {KNOWN_ISSUES_PATH_DEFAULT} directly to update</div>
  {cards}
</div>
</div>
"""


_SECRET_DEFAULT_RE = re.compile(r"\$\{([A-Z0-9_]+):-([^}]*)\}")
_SECRET_MARKERS = (
    "change-me", "changeme", "admin-secret", "secret-change-in-production",
    "omnibioai-secret", "omnibioai-studio-secret", "devtoken", "password", "insecure",
)
_SECRET_SAFE_KEYS = {
    "DEBUG", "DJANGO_DEBUG", "AUTH_ENABLED", "SENTRY_ENVIRONMENT", "REPORT_SCHEDULE_HOURS",
}


def _load_compose(compose_path: Path) -> Optional[Dict[str, Any]]:
    if yaml is None or not compose_path.exists():
        return None
    try:
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _iter_service_env(env_block: Any):
    """Yield (key, raw_value) pairs from a compose `environment:` block --
    handles both dict-style (KEY: value) and list-style (- KEY=value)."""
    if isinstance(env_block, dict):
        for k, v in env_block.items():
            yield str(k), "" if v is None else str(v)
    elif isinstance(env_block, list):
        for item in env_block:
            item = str(item)
            if "=" in item:
                k, v = item.split("=", 1)
                yield k, v


def secrets_audit_section_html(compose_path: Path) -> str:
    compose = _load_compose(compose_path)
    if compose is None:
        reason = "PyYAML not installed -- cannot parse compose file" if yaml is None \
            else f"compose file not found at {compose_path}"
        return f"""
<div class="tab-section">
<div class="section"><div style="font-size:12px;color:var(--color-text-muted)">{reason}</div></div>
</div>"""

    services = compose.get("services") or {}
    flagged: List[Dict[str, str]] = []
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        for key, raw_value in _iter_service_env(svc.get("environment")):
            if key in _SECRET_SAFE_KEYS:
                continue
            m = _SECRET_DEFAULT_RE.search(raw_value)
            if not m:
                continue
            fallback = m.group(2)
            if fallback and any(marker in fallback.lower() for marker in _SECRET_MARKERS):
                flagged.append({"service": svc_name, "variable": key, "fallback": fallback})

    affected_services = len({f["service"] for f in flagged})
    kpi_color = "#A32D2D" if flagged else "#3B6D11"

    rows = "".join(f"""<tr>
          <td style="font-weight:600;font-size:12px">{f['service']}</td>
          <td class="mono">{f['variable']}</td>
          <td class="mono">{f['fallback']}</td>
          <td><span class="badge" style="background:#FCEBEB;color:#A32D2D">risky default</span></td>
        </tr>""" for f in flagged) or \
        '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px">no risky default fallback values found</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">flagged defaults</div><div class="kpi-val" style="color:{kpi_color}">{len(flagged)}</div></div>
  <div class="kpi"><div class="kpi-label">services affected</div><div class="kpi-val">{affected_services}</div></div>
</div>
<div class="section">
  <div class="sec-title">secrets audit</div>
  <div class="sec-sub">scans {compose_path.name} for ${{VAR:-default}} env fallbacks that look like placeholder secrets -- heuristic on the fallback text only, not proof the placeholder is actually deployed</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>service</th><th>variable</th><th>fallback value</th><th>flag</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
</div>
"""


def _parse_port_mapping(mapping: str) -> Dict[str, Any]:
    s = str(mapping).strip()
    m = _SECRET_DEFAULT_RE.match(s)
    if m and s.startswith(m.group(0)):
        bind = m.group(2) or "0.0.0.0"
        rest = s[len(m.group(0)):]
        if rest.startswith(":"):
            rest = rest[1:]
        parts = rest.split(":")
    else:
        parts = s.split(":")
        if len(parts) >= 3:
            bind = parts[0]
            parts = parts[1:]
        else:
            bind = "0.0.0.0"
    host_port = parts[0] if parts else ""
    container_port = parts[1] if len(parts) > 1 else host_port
    external = bind not in ("127.0.0.1", "localhost")
    return {"raw": s, "bind": bind, "host_port": host_port,
            "container_port": container_port, "external": external}


def exposed_ports_section_html(compose_path: Path) -> str:
    compose = _load_compose(compose_path)
    if compose is None:
        reason = "PyYAML not installed -- cannot parse compose file" if yaml is None \
            else f"compose file not found at {compose_path}"
        return f"""
<div class="tab-section">
<div class="section"><div style="font-size:12px;color:var(--color-text-muted)">{reason}</div></div>
</div>"""

    services = compose.get("services") or {}
    mappings: List[Dict[str, Any]] = []
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        for p in (svc.get("ports") or []):
            parsed = _parse_port_mapping(p)
            parsed["service"] = svc_name
            mappings.append(parsed)

    mappings.sort(key=lambda m: (not m["external"], m["service"]))
    external_count = sum(1 for m in mappings if m["external"])
    localhost_count = len(mappings) - external_count

    def _row(m: Dict[str, Any]) -> str:
        if m["external"]:
            badge = '<span class="badge" style="background:#FCEBEB;color:#A32D2D">external</span>'
        else:
            badge = '<span class="badge" style="background:#EAF3DE;color:#3B6D11">localhost-only</span>'
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{m['service']}</td>
          <td class="mono">{m['raw']}</td>
          <td class="mono">{m['bind']}:{m['host_port']} -> {m['container_port']}</td>
          <td>{badge}</td>
        </tr>"""

    rows = "".join(_row(m) for m in mappings) or \
        '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px">no port mappings found</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">total mappings</div><div class="kpi-val">{len(mappings)}</div></div>
  <div class="kpi"><div class="kpi-label">external</div><div class="kpi-val" style="color:#A32D2D">{external_count}</div></div>
  <div class="kpi"><div class="kpi-label">localhost-only</div><div class="kpi-val" style="color:#3B6D11">{localhost_count}</div></div>
</div>
<div class="section">
  <div class="sec-title">exposed ports</div>
  <div class="sec-sub">port mappings parsed from {compose_path.name} · sorted external-first</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>service</th><th>raw mapping</th><th>bind:host -> container</th><th>exposure</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
</div>
"""


def _run_vuln_scan(repo_path: Path) -> Optional[int]:
    """Runs whichever of pip-audit / npm audit is available and applicable for
    this repo, capped at 30s. Returns None if neither tool is available, the
    repo has no matching manifest, or the scan times out/errors."""
    has_py = (repo_path / "requirements.txt").exists() or (repo_path / "pyproject.toml").exists()
    has_js = (repo_path / "package.json").exists()
    try:
        if has_py and shutil.which("pip-audit"):
            proc = subprocess.run(["pip-audit", "--format", "json"], cwd=str(repo_path),
                                   capture_output=True, text=True, timeout=30)
            data = json.loads(proc.stdout or "[]")
            deps = data if isinstance(data, list) else data.get("dependencies", [])
            return sum(len(d.get("vulns", [])) for d in deps if isinstance(d, dict))
        if has_js and shutil.which("npm"):
            proc = subprocess.run(["npm", "audit", "--json"], cwd=str(repo_path),
                                   capture_output=True, text=True, timeout=30)
            data = json.loads(proc.stdout or "{}")
            total = ((data.get("metadata") or {}).get("vulnerabilities") or {}).get("total")
            if total is not None:
                return int(total)
            vulns = data.get("vulnerabilities") or {}
            return sum(int(v) for v in vulns.values() if isinstance(v, (int, float)))
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    return None


_CI_STATUS_COLOR = {
    "passing": ("#EAF3DE", "#3B6D11"),
    "failing": ("#FCEBEB", "#A32D2D"),
    "running": ("#FAEEDA", "#854F0B"),
    "unknown": ("#F1EFE8", "#444441"),
    "no ci":   ("#F1EFE8", "#444441"),
}


def _fetch_ci_status(owner: str, repo: str, token: str) -> Dict[str, Any]:
    import urllib.request
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/actions/runs?per_page=1",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    runs = data.get("workflow_runs", [])
    if not runs:
        return {"status": "unknown", "date": ""}
    run = runs[0]
    conclusion = run.get("conclusion")
    status = run.get("status")
    if status in ("in_progress", "queued"):
        ci_status = "running"
    elif conclusion == "success":
        ci_status = "passing"
    elif conclusion in ("failure", "timed_out", "cancelled", "action_required"):
        ci_status = "failing"
    else:
        ci_status = "unknown"
    return {"status": ci_status, "date": run.get("updated_at", run.get("created_at", ""))}


def cicd_health_section_html(ecosystem_root: Path, targets: List[str]) -> str:
    github_token = os.environ.get("GITHUB_TOKEN")
    github_owner = os.environ.get("GITHUB_OWNER", "omnibioai")

    rows: List[Dict[str, Any]] = []
    for name in targets:
        repo_path = ecosystem_root / name
        if not repo_path.is_dir():
            continue
        has_ci = (repo_path / ".github" / "workflows").is_dir()

        if not has_ci:
            ci_status, ci_date = "no ci", ""
        elif not github_token:
            ci_status, ci_date = "unknown", ""
        else:
            try:
                info = _fetch_ci_status(github_owner, name, github_token)
                ci_status, ci_date = info["status"], info["date"]
            except Exception as e:
                print(f"[report] cicd_health_section_html CI fetch failed for {name}: {type(e).__name__}: {e}", flush=True)
                ci_status, ci_date = "unknown", ""

        vuln_count = _run_vuln_scan(repo_path)
        rows.append({"repo": name, "has_ci": has_ci, "ci_status": ci_status,
                     "ci_date": ci_date, "vuln_count": vuln_count})

    passing = sum(1 for r in rows if r["ci_status"] == "passing")
    failing = sum(1 for r in rows if r["ci_status"] == "failing")
    no_ci   = sum(1 for r in rows if r["ci_status"] == "no ci")
    total_vulns = sum(r["vuln_count"] for r in rows if r["vuln_count"] is not None)

    token_note = "" if github_token else \
        '<div style="font-size:11px;color:var(--color-text-muted);margin-bottom:8px">GITHUB_TOKEN not set -- CI status unknown for repos with workflows configured (skipping unauthenticated calls)</div>'
    vuln_note = "" if (shutil.which("pip-audit") or shutil.which("npm")) else \
        '<div style="font-size:11px;color:var(--color-text-muted);margin-bottom:8px">neither pip-audit nor npm found on PATH -- vulnerability counts unavailable</div>'

    def _row(r):
        bg, color = _CI_STATUS_COLOR.get(r["ci_status"], ("#F1EFE8", "#444441"))
        vc = r["vuln_count"]
        vc_html = "—" if vc is None else (f'<span style="color:#A32D2D;font-weight:600">{vc}</span>' if vc > 0 else "0")
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{r['repo']}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{r['ci_status']}</span></td>
          <td style="font-size:11px;color:var(--color-text-muted)">{r['ci_date']}</td>
          <td class="r">{vc_html}</td>
        </tr>"""

    table_rows = "".join(_row(r) for r in rows) or \
        '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px">no repos found</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">CI passing</div><div class="kpi-val" style="color:#3B6D11">{passing}</div></div>
  <div class="kpi"><div class="kpi-label">CI failing</div><div class="kpi-val" style="color:#A32D2D">{failing}</div></div>
  <div class="kpi"><div class="kpi-label">no CI configured</div><div class="kpi-val">{no_ci}</div></div>
  <div class="kpi"><div class="kpi-label">known vulnerabilities</div><div class="kpi-val" style="color:{'#A32D2D' if total_vulns else '#3B6D11'}">{total_vulns}</div></div>
</div>
<div class="section">
  <div class="sec-title">CI/CD health</div>
  <div class="sec-sub">GitHub Actions status (latest run) + local dependency vulnerability scan, per repo</div>
  {token_note}{vuln_note}
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>repo</th><th>CI status</th><th>last run</th><th class="r">vulns</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</div>
</div>
"""


BACKUP_STATUS_PATH_DEFAULT = "backup_status.json"

_BACKUP_STATUS_COLOR = {
    "success": ("#EAF3DE", "#3B6D11"),
    "failed":  ("#FCEBEB", "#A32D2D"),
    "partial": ("#FAEEDA", "#854F0B"),
}


# Expected {work_dir}/backup_status.json shape:
# [
#   {"target": str, "last_backup_at": "ISO8601", "status": "success"|"failed"|"partial",
#    "size_mb": float, "destination": str}, ...
# ]
def backup_status_section_html(work_dir: Path) -> str:
    status_path = work_dir / BACKUP_STATUS_PATH_DEFAULT
    if not status_path.exists():
        return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">backup status</div>
  <div style="font-size:12px;color:var(--color-text-muted)">no backup status file found -- create {status_path} to start tracking</div>
</div>
</div>"""

    try:
        backups = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(backups, list):
            backups = []
    except Exception as e:
        return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">backup status</div>
  <div style="font-size:12px;color:var(--color-text-muted)">could not parse {status_path}: {type(e).__name__}: {e}</div>
</div>
</div>"""

    now = datetime.now(timezone.utc)

    def _age_hours(ts: str) -> Optional[float]:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return (now - dt).total_seconds() / 3600
        except Exception:
            return None

    for b in backups:
        b["_age_h"] = _age_hours(b.get("last_backup_at", ""))

    tracked = len(backups)
    recent_48h = sum(1 for b in backups if b["_age_h"] is not None and b["_age_h"] <= 48)
    ages = [b["_age_h"] for b in backups if b["_age_h"] is not None]
    oldest_age = max(ages) if ages else None

    def _fmt_age(h: Optional[float]) -> str:
        if h is None:
            return "—"
        if h < 48:
            return f"{h:.1f}h"
        return f"{h/24:.1f}d"

    def _row(b):
        bg, color = _BACKUP_STATUS_COLOR.get(b.get("status", ""), ("#F1EFE8", "#444441"))
        age = b["_age_h"]
        age_color = "#A32D2D" if (age is not None and age > 48) else "var(--color-text)"
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{b.get('target','')}</td>
          <td style="font-size:11px;color:var(--color-text-muted)">{b.get('last_backup_at','')}</td>
          <td style="color:{age_color};font-weight:600">{_fmt_age(age)}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{b.get('status','')}</span></td>
          <td class="r">{b.get('size_mb',0):.1f} MB</td>
          <td class="mono">{b.get('destination','')}</td>
        </tr>"""

    rows = "".join(_row(b) for b in backups) or \
        '<tr><td colspan="6" style="text-align:center;color:var(--color-text-muted);padding:20px">no backup targets tracked</td></tr>'

    oldest_color = "#A32D2D" if (oldest_age is not None and oldest_age > 48) else "#3B6D11"

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">targets tracked</div><div class="kpi-val">{tracked}</div></div>
  <div class="kpi"><div class="kpi-label">backed up in last 48h</div><div class="kpi-val" style="color:{'#3B6D11' if recent_48h else '#A32D2D'}">{recent_48h}</div></div>
  <div class="kpi"><div class="kpi-label">oldest backup</div><div class="kpi-val" style="color:{oldest_color}">{_fmt_age(oldest_age)}</div></div>
</div>
<div class="section">
  <div class="sec-title">backup status</div>
  <div class="sec-sub">from {status_path.name}</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>target</th><th>last backup</th><th>age</th><th>status</th><th class="r">size</th><th>destination</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
</div>
"""


def _scan_active_runs(work_dir: Path, active_only: bool = True) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    runs_root = work_dir / "runs"
    if not runs_root.is_dir():
        return runs
    for plugin_dir in sorted(runs_root.iterdir()):
        if not plugin_dir.is_dir():
            continue
        for run_dir in sorted(plugin_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            status_file = run_dir / "status.json"
            if not status_file.exists():
                continue
            try:
                status = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            state = status.get("state", "UNKNOWN")
            if active_only and state not in ("CREATED", "QUEUED", "RUNNING"):
                continue
            runs.append({
                "plugin": plugin_dir.name,
                "run_id": run_dir.name,
                "state": state,
                "created_at": status.get("created_at", ""),
                "updated_at": status.get("updated_at", ""),
                "detail": status.get("detail", ""),
                "n_steps": len(status.get("steps", [])),
            })
    return sorted(runs, key=lambda r: r.get("updated_at", ""), reverse=True)


_RUN_STATE_COLOR = {
    "RUNNING": "#3B6D11", "QUEUED": "#854F0B", "CREATED": "#185FA5",
    "COMPLETED": "#444441", "FAILED": "#A32D2D", "UNKNOWN": "#444441",
}
_RUN_STATE_BG = {
    "RUNNING": "#EAF3DE", "QUEUED": "#FAEEDA", "CREATED": "#E6F1FB",
    "COMPLETED": "#F1EFE8", "FAILED": "#FCEBEB", "UNKNOWN": "#F1EFE8",
}


def active_runs_section_html(work_dir: Path) -> str:
    active_runs = _scan_active_runs(work_dir, active_only=True)
    recent_runs = _scan_active_runs(work_dir, active_only=False)[:20]

    def _run_row(r: Dict[str, Any]) -> str:
        color = _RUN_STATE_COLOR.get(r["state"], "#444441")
        bg = _RUN_STATE_BG.get(r["state"], "#F1EFE8")
        return f"""<tr>
          <td style="font-size:12px;font-weight:600">{r['plugin']}</td>
          <td class="mono">{r['run_id']}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{r['state']}</span></td>
          <td style="font-size:11px;color:var(--color-text-muted)">{r['updated_at']}</td>
          <td class="r">{r['n_steps']}</td>
        </tr>"""

    active_rows = "".join(_run_row(r) for r in active_runs) or \
        '<tr><td colspan="5" style="text-align:center;color:var(--color-text-muted);padding:20px">no active runs right now</td></tr>'
    recent_rows = "".join(_run_row(r) for r in recent_runs) or \
        '<tr><td colspan="5" style="text-align:center;color:var(--color-text-muted);padding:20px">no run history found</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">active now</div><div class="kpi-val" style="color:#3B6D11">{len(active_runs)}</div><div class="kpi-sub">running/queued/created</div></div>
  <div class="kpi"><div class="kpi-label">recent (shown)</div><div class="kpi-val">{len(recent_runs)}</div><div class="kpi-sub">last 20, any state</div></div>
</div>

<div class="section">
  <div class="sec-title">active runs</div>
  <div class="sec-sub">RunStore status — refreshes on page reload · note: CREATED/RUNNING entries may include stale/orphaned status files that were never finalized, not necessarily live activity</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>plugin</th><th>run id</th><th>state</th><th>updated</th><th class="r">steps</th></tr></thead>
      <tbody>{active_rows}</tbody>
    </table>
  </div>
</div>

<div class="section">
  <div class="sec-title">recent run history</div>
  <div class="sec-sub">last 20 runs, any state</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>plugin</th><th>run id</th><th>state</th><th>updated</th><th class="r">steps</th></tr></thead>
      <tbody>{recent_rows}</tbody>
    </table>
  </div>
</div>
</div>
"""


# Expected /database response shape:
# {
#   "mysql": {"connections": int, "max_connections": int, "slow_queries": int,
#             "databases": [{"name": str, "size_mb": float}, ...]},
#   "redis": {"used_memory_human": str, "hit_rate_pct": float, "connected_clients": int},
#   "neo4j": {"node_count": int, "relationship_count": int}
# }
def database_section_html(control_center_url: str) -> str:
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/database", timeout=10
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] database_section_html failed: {type(e).__name__}: {e}", flush=True)

    mysql = data.get("mysql") if data else None
    redis = data.get("redis") if data else None
    neo4j = data.get("neo4j") if data else None

    if not (mysql or redis or neo4j):
        return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">data layer</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    /database endpoint not implemented yet. Expected JSON shape:
    <pre style="font-size:11px;color:var(--color-text-muted);margin-top:8px;white-space:pre-wrap">{
  "mysql": {"connections": int, "max_connections": int, "slow_queries": int,
            "databases": [{"name": str, "size_mb": float}, ...]},
  "redis": {"used_memory_human": str, "hit_rate_pct": float, "connected_clients": int},
  "neo4j": {"node_count": int, "relationship_count": int}
}</pre>
  </div>
</div>
</div>"""

    mysql_dbs = (mysql or {}).get("databases", [])
    mysql_rows = "".join(f"""<tr>
          <td style="font-size:12px">{d.get('name','')}</td>
          <td class="r">{d.get('size_mb',0):.1f} MB</td>
        </tr>""" for d in mysql_dbs) or \
        '<tr><td colspan="2" style="text-align:center;color:var(--color-text-muted);padding:12px">no databases reported</td></tr>'

    conns = (mysql or {}).get("connections", "—")
    max_conns = (mysql or {}).get("max_connections", "—")
    slow_q = (mysql or {}).get("slow_queries", "—")

    return f"""
<div class="tab-section">
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
  <div class="section">
    <div class="sec-title">MySQL</div>
    <div class="kpi-row" style="grid-template-columns:1fr 1fr">
      <div class="kpi"><div class="kpi-label">connections</div><div class="kpi-val">{conns}/{max_conns}</div></div>
      <div class="kpi"><div class="kpi-label">slow queries</div><div class="kpi-val">{slow_q}</div></div>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>database</th><th class="r">size</th></tr></thead>
        <tbody>{mysql_rows}</tbody>
      </table>
    </div>
  </div>
  <div class="section">
    <div class="sec-title">Redis</div>
    <div class="kpi-row" style="grid-template-columns:1fr 1fr">
      <div class="kpi"><div class="kpi-label">memory used</div><div class="kpi-val">{(redis or {}).get('used_memory_human','—')}</div></div>
      <div class="kpi"><div class="kpi-label">hit rate</div><div class="kpi-val">{(redis or {}).get('hit_rate_pct','—')}%</div></div>
    </div>
    <div class="kpi"><div class="kpi-label">connected clients</div><div class="kpi-val">{(redis or {}).get('connected_clients','—')}</div></div>
  </div>
  <div class="section">
    <div class="sec-title">Neo4j</div>
    <div class="kpi-row" style="grid-template-columns:1fr 1fr">
      <div class="kpi"><div class="kpi-label">nodes</div><div class="kpi-val">{fmt_int((neo4j or {}).get('node_count',0))}</div></div>
      <div class="kpi"><div class="kpi-label">relationships</div><div class="kpi-val">{fmt_int((neo4j or {}).get('relationship_count',0))}</div></div>
    </div>
  </div>
</div>
</div>
"""


# Expected /celery response shape:
# {
#   "workers": [{"name": str, "status": "online"|"offline", "active_tasks": int}, ...],
#   "recent_tasks": [{"name": str, "state": str, "runtime_s": float}, ...]
# }
def task_queue_section_html(control_center_url: str) -> str:
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/celery", timeout=10
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] task_queue_section_html failed: {type(e).__name__}: {e}", flush=True)

    workers = data.get("workers", []) if data else []
    recent_tasks = data.get("recent_tasks", []) if data else []

    if not workers and not recent_tasks:
        return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">task queue</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    /celery endpoint not implemented yet. Expected JSON shape:
    <pre style="font-size:11px;color:var(--color-text-muted);margin-top:8px;white-space:pre-wrap">{
  "workers": [{"name": str, "status": "online"|"offline", "active_tasks": int}, ...],
  "recent_tasks": [{"name": str, "state": str, "runtime_s": float}, ...]
}</pre>
  </div>
</div>
</div>"""

    _TASK_STATE_COLOR = {
        "SUCCESS": ("#EAF3DE", "#3B6D11"), "FAILURE": ("#FCEBEB", "#A32D2D"),
        "STARTED": ("#E6F1FB", "#185FA5"), "PENDING": ("#FAEEDA", "#854F0B"),
        "RETRY":   ("#FAEEDA", "#854F0B"),
    }

    def _worker_row(w):
        online = w.get("status") == "online"
        bg, color = ("#EAF3DE", "#3B6D11") if online else ("#FCEBEB", "#A32D2D")
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{w.get('name','')}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{w.get('status','unknown')}</span></td>
          <td class="r">{w.get('active_tasks',0)}</td>
        </tr>"""

    def _task_row(t):
        bg, color = _TASK_STATE_COLOR.get(t.get("state", ""), ("#F1EFE8", "#444441"))
        return f"""<tr>
          <td style="font-size:12px">{t.get('name','')}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{t.get('state','')}</span></td>
          <td class="r">{t.get('runtime_s','—')}s</td>
        </tr>"""

    worker_rows = "".join(_worker_row(w) for w in workers) or \
        '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px">no workers reported</td></tr>'
    task_rows = "".join(_task_row(t) for t in recent_tasks) or \
        '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px">no recent tasks</td></tr>'

    return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">workers</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>name</th><th>status</th><th class="r">active tasks</th></tr></thead>
      <tbody>{worker_rows}</tbody>
    </table>
  </div>
</div>
<div class="section">
  <div class="sec-title">recent tasks</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>task</th><th>state</th><th class="r">runtime</th></tr></thead>
      <tbody>{task_rows}</tbody>
    </table>
  </div>
</div>
</div>
"""


# Expected /license response shape:
# {
#   "seats_used": int, "seats_total": int,
#   "licenses": [{"org": str, "expires_at": str, "status": str}, ...]
# }
def license_section_html(control_center_url: str) -> str:
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/license", timeout=10
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] license_section_html failed: {type(e).__name__}: {e}", flush=True)

    if not data:
        return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">license</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    /license endpoint not implemented yet. Expected JSON shape:
    <pre style="font-size:11px;color:var(--color-text-muted);margin-top:8px;white-space:pre-wrap">{
  "seats_used": int, "seats_total": int,
  "licenses": [{"org": str, "expires_at": str, "status": str}, ...]
}</pre>
  </div>
</div>
</div>"""

    seats_used = data.get("seats_used", 0)
    seats_total = data.get("seats_total", 0)
    util_pct = round(100 * seats_used / seats_total, 1) if seats_total else 0
    licenses = data.get("licenses", [])

    _LICENSE_STATUS_COLOR = {
        "active":   ("#EAF3DE", "#3B6D11"),
        "expired":  ("#FCEBEB", "#A32D2D"),
        "expiring": ("#FAEEDA", "#854F0B"),
    }

    def _lic_row(l):
        bg, color = _LICENSE_STATUS_COLOR.get(l.get("status", ""), ("#F1EFE8", "#444441"))
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{l.get('org','')}</td>
          <td class="mono">{l.get('expires_at','')}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{l.get('status','')}</span></td>
        </tr>"""

    rows = "".join(_lic_row(l) for l in licenses) or \
        '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px">no license records</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">seats used</div><div class="kpi-val">{seats_used}/{seats_total}</div><div class="kpi-sub">{util_pct}% utilization</div></div>
</div>
<div class="section">
  <div class="sec-title">licenses</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>org</th><th>expires</th><th>status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
</div>
"""


# Expected /image-freshness response shape:
# {
#   "images": [{"service": str, "image": str, "stale": bool, "last_pushed": str}, ...]
# }
def image_freshness_section_html(control_center_url: str) -> str:
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/image-freshness", timeout=10
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] image_freshness_section_html failed: {type(e).__name__}: {e}", flush=True)

    images = data.get("images", []) if data else []

    if not images:
        return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">image freshness</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    /image-freshness endpoint not implemented yet (only applies to <code>:latest</code>-tagged images). Expected JSON shape:
    <pre style="font-size:11px;color:var(--color-text-muted);margin-top:8px;white-space:pre-wrap">{
  "images": [{"service": str, "image": str, "stale": bool, "last_pushed": str}, ...]
}</pre>
  </div>
</div>
</div>"""

    stale_count = sum(1 for i in images if i.get("stale"))

    def _img_row(i):
        stale = i.get("stale")
        bg, color = ("#FCEBEB", "#A32D2D") if stale else ("#EAF3DE", "#3B6D11")
        label = "stale" if stale else "current"
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{i.get('service','')}</td>
          <td class="mono">{i.get('image','')}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{label}</span></td>
          <td style="font-size:11px;color:var(--color-text-muted)">{i.get('last_pushed','')}</td>
        </tr>"""

    rows = "".join(_img_row(i) for i in images)

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">images checked</div><div class="kpi-val">{len(images)}</div></div>
  <div class="kpi"><div class="kpi-label">stale</div><div class="kpi-val" style="color:{'#A32D2D' if stale_count else '#3B6D11'}">{stale_count}</div></div>
</div>
<div class="section">
  <div class="sec-title">image freshness</div>
  <div class="sec-sub">applies only to :latest-tagged images</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>service</th><th>image</th><th>status</th><th>last pushed</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
</div>
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
                 control_center_url: str, ecosystem_root: Path,
                 registry_root: Path, work_dir: Path,
                 compose_path: Path = DEFAULT_COMPOSE_PATH,
                 sentry_org: str = "", sentry_project_slugs: Optional[List[str]] = None) -> None:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    cc_url = control_center_url.rstrip("/")
    total_all = grand.blank + grand.comment + grand.code
    doc_lines = language_totals.get("Markdown", Totals()).code

    arch_html     = architecture_section_html(project_totals, grand, control_center_url)
    projects_tab_html = misc_section_html([
        ("summary",   "Code Summary", projects_section_html(project_totals, grand)),
        ("languages", "Languages",    languages_section_html(language_totals, grand)),
        ("coverage",  "Code Coverage", coverage_section_html(coverage_df, timestamp)),
    ], group_id="projects", render_nav=False)
    hlth_html     = health_section_html(health, control_center_url, sentry_org, sentry_project_slugs)
    llms_html     = llm_section_html(control_center_url)
    cloud_html    = cloud_section_html(control_center_url)
    ref_html      = reference_section_html(control_center_url)
    kb_html       = knowledge_base_section_html(control_center_url)
    storage_html  = storage_section_html(control_center_url)
    catalog_html  = catalog_section_html(ecosystem_root)
    model_registry_html = model_registry_section_html(registry_root)
    dockerimages_html = misc_section_html([
        ("containers", "Platform Containers", docker_containers_section_html()),
        ("sif",        "Tool SIF Images",      docker_sif_section_html()),
        ("plugins",    "Plugin Docker Images", docker_plugins_section_html()),
    ], group_id="dockerimages", render_nav=False, header_html=docker_kpi_header_html()) + _DOCKER_IMAGES_SCRIPT
    sbnav_children_json = json.dumps({
        tid: [cid for cid, _ in children]
        for tid, _, children in SIDEBAR_NAV_SPEC if children
    })
    usage_tab_html = misc_section_html([
        ("product", "Product Usage", usage_section_html(control_center_url)),
        ("gateway", "API Gateway",   gateway_traffic_section_html(control_center_url)),
    ], group_id="usage", render_nav=False)
    misc_html = misc_section_html([
        ("issues", "Known Issues", known_issues_section_html(ecosystem_root)),
        ("runs", "Active Runs", active_runs_section_html(work_dir)),
        ("storage", "Storage", storage_html),
        ("catalog", "Catalog", catalog_html),
        ("database", "Data Layer",      database_section_html(control_center_url)),
        ("queue",    "Task Queue",      task_queue_section_html(control_center_url)),
        ("license",  "License",         license_section_html(control_center_url)),
        ("secrets",  "Secrets Audit",   secrets_audit_section_html(compose_path)),
        ("images",   "Image Freshness", image_freshness_section_html(control_center_url)),
        ("ports",    "Exposed Ports",   exposed_ports_section_html(compose_path)),
        ("cicd",   "CI/CD Health",   cicd_health_section_html(ecosystem_root, DEFAULT_TARGETS)),
        ("backup", "Backup Status",  backup_status_section_html(work_dir)),
    ], group_id="misc", render_nav=False)
    llmscloud_html = misc_section_html([
        ("llms", "LLMs", llms_html),
        ("cloud", "Cloud", cloud_html),
        ("cost", "Cost Tracking", cost_tracking_placeholder_section_html()),
    ], group_id="llmscloud", render_nav=False)

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
    .tab-panel {{display:none}}
    .tab-panel.active {{display:block}}
    .layout-split {{display:flex;align-items:flex-start;background:var(--color-bg-surface);border:1px solid var(--color-border);border-radius:12px;overflow:hidden}}
    .sidebar {{flex:0 0 240px;width:240px;box-sizing:border-box;border-right:1px solid var(--color-border);padding:10px 0;position:sticky;top:0;align-self:flex-start;height:100vh;overflow-y:auto}}
    .sbnav-item {{display:flex;align-items:center;gap:7px;width:100%;text-align:left;padding:9px 20px;font-size:13px;font-weight:600;color:var(--color-text-muted);background:transparent;border:none;border-left:3px solid transparent;cursor:pointer;white-space:nowrap;font-family:inherit;box-sizing:border-box}}
    .sbnav-item:hover {{color:var(--color-text);background:var(--color-bg-surface2)}}
    .sbnav-item.active {{color:var(--color-text);background:var(--color-bg-surface2);border-left-color:var(--color-accent)}}
    .sbnav-child {{padding-left:37px;font-weight:400;font-size:12.5px}}
    .sbnav-child.active {{padding-left:34px}}
    .sbnav-children {{display:none;flex-direction:column}}
    .sbnav-children.expanded {{display:flex}}
    .sbnav-caret {{display:inline-block;font-size:9px;transition:transform .15s;flex-shrink:0}}
    .sbnav-group.expanded .sbnav-caret {{transform:rotate(90deg)}}
    .content-pane {{flex:1;min-width:0;padding:20px}}
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

  {PAGINATION_JS}

  <div class="layout-split">
    <nav class="sidebar" id="app-sidebar">
      {sidebar_nav_html(SIDEBAR_NAV_SPEC)}
    </nav>
    <div class="content-pane">
      <div id="tab-arch"   class="tab-panel active">{arch_html}</div>
      <div id="tab-projects" class="tab-panel">{projects_tab_html}</div>
      <div id="tab-health" class="tab-panel">{hlth_html}</div>
      <div id="tab-usage"  class="tab-panel">{usage_tab_html}</div>
      <div id="tab-llmscloud" class="tab-panel">{llmscloud_html}</div>
      <div id="tab-ref"    class="tab-panel">{ref_html}</div>
      <div id="tab-kb"      class="tab-panel">{kb_html}</div>
      <div id="tab-modelreg" class="tab-panel">{model_registry_html}</div>
      <div id="tab-dockerimages" class="tab-panel">{dockerimages_html}</div>
      <div id="tab-misc" class="tab-panel">{misc_html}</div>
    </div>
  </div>

  <div class="footer">
    cloc counts exclude vendored/runtime directories and selected extensions per cloc policy.<br>
    Coverage is best-effort and does not fail the report when a repository has test or configuration issues.<br>
    Health data is live — fetched from the Control Center /summary endpoint with 30-second auto-refresh.
  </div>
</div>

<script>
function sbnavClearActive(){{
  document.querySelectorAll('.sbnav-item.active').forEach(function(b){{b.classList.remove('active');}});
}}
function sbnavShowPanel(topId){{
  document.querySelectorAll('.tab-panel').forEach(function(t){{t.classList.remove('active');}});
  var panel=document.getElementById('tab-'+topId);
  if(panel)panel.classList.add('active');
}}
function sbnavExpandGroup(topId){{
  var kids=document.getElementById('sbnav-children-'+topId);
  if(!kids)return;
  kids.classList.add('expanded');
  var grp=document.querySelector('.sbnav-group[data-top="'+topId+'"]');
  if(grp)grp.classList.add('expanded');
}}
function sbnavToggleGroup(topId){{
  var kids=document.getElementById('sbnav-children-'+topId);
  if(!kids)return;
  var grp=document.querySelector('.sbnav-group[data-top="'+topId+'"]');
  if(kids.classList.contains('expanded')){{
    kids.classList.remove('expanded');
    if(grp)grp.classList.remove('expanded');
  }} else {{
    sbnavExpandGroup(topId);
  }}
}}
function sbnavSelectTop(topId, skipHash){{
  sbnavShowPanel(topId);
  sbnavClearActive();
  var btn=document.querySelector('.sbnav-leaf[data-top="'+topId+'"]');
  if(btn)btn.classList.add('active');
  if(!skipHash) location.hash = topId;
}}
function sbnavSelectChild(topId, childId, skipHash){{
  sbnavShowPanel(topId);
  sbnavExpandGroup(topId);
  sbnavClearActive();
  var btn=document.querySelector('.sbnav-child[data-top="'+topId+'"][data-child="'+childId+'"]');
  if(btn)btn.classList.add('active');
  if(typeof miscSub==='function') miscSub(topId, 'misc-panel-'+topId+'-'+childId);
  if(!skipHash) location.hash = topId+'/'+childId;
}}
var _SBNAV_CHILDREN = {sbnav_children_json};
function sbnavApplyHash(){{
  var h=(location.hash||'').replace(/^#/,'');
  if(!h) return false;
  var parts=h.split('/');
  var topId=parts[0], childId=parts[1];
  if(_SBNAV_CHILDREN.hasOwnProperty(topId)){{
    var kids=_SBNAV_CHILDREN[topId];
    if(childId && kids.indexOf(childId)!==-1){{
      sbnavSelectChild(topId, childId, true);
    }} else {{
      sbnavSelectChild(topId, kids[0], true);
    }}
    return true;
  }}
  if(document.getElementById('tab-'+topId)){{
    sbnavSelectTop(topId, true);
    return true;
  }}
  return false;
}}
if(!sbnavApplyHash()){{
  sbnavSelectTop('arch', true);
}}
window.addEventListener('hashchange', function(){{ sbnavApplyHash(); }});

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
    p.add_argument("--compose-path", default=str(DEFAULT_COMPOSE_PATH))
    return p.parse_args()

def generate_report(ecosystem_root: Path,
                    targets: Optional[List[str]] = None,
                    out_relpath: str = str(DEFAULT_OUT_PATH),
                    title: str = DEFAULT_TITLE,
                    control_center_url: str = DEFAULT_CONTROL_CENTER_URL,
                    skip_health: bool = False,
                    skip_coverage: bool = False,
                    compose_path: str = str(DEFAULT_COMPOSE_PATH)) -> Path:
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

    work_dir = Path(os.environ.get("WORK_DIR", str(ecosystem_root / "omnibioai-work")))

    if skip_coverage:
        print("→ Skipping coverage (--skip-coverage)")
        coverage_df = pd.DataFrame(columns=[
            "repo","path","status","returncode","statements","missed",
            "branches","partial_branches","coverage_pct","coverage_band",
            "fail_under","total_line","stderr_tail"])
    else:
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

    sentry_org = os.environ.get("SENTRY_ORG", "")
    sentry_project_slugs = [s.strip() for s in os.environ.get("SENTRY_PROJECT_SLUGS", "").split(",") if s.strip()]

    out_html = ecosystem_root / out_relpath
    print("→ Building report…")
    build_report(out_html=out_html, title=title, timestamp=ts,
                 grand=grand, project_totals=project_totals,
                 language_totals=language_totals, coverage_df=coverage_df,
                 health=health, control_center_url=control_center_url,
                 ecosystem_root=ecosystem_root,
                 registry_root=ecosystem_root / "data" / "local_registry" / "model_registry",
                 work_dir=work_dir, compose_path=Path(compose_path),
                 sentry_org=sentry_org, sentry_project_slugs=sentry_project_slugs)
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
            skip_coverage=args.skip_coverage,
            compose_path=args.compose_path)
        print(f"\n✓ Report written: {out}")
        return 0
    except Exception as e:
        print(f"\n✗ {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())