from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SEVERITY_LEVELS = ("critical", "high", "moderate", "low", "info")

def _run_vuln_scan(
    repo_path: Path,
) -> Tuple[Optional[str], Optional[int], Optional[Dict[str, int]]]:
    """Runs whichever of pip-audit / npm audit is available and applicable for
    this repo, capped at 30s. Returns (scanner, vuln_count, severity):

    - scanner is "pip-audit" | "npm-audit" | None.
    - scanner/vuln_count/severity are all None together when neither tool is
      available, the repo has no matching manifest, or the scan times
      out/errors -- distinct from a real scan that found zero issues, which
      returns vuln_count=0 (not None).
    - severity is a per-level count dict, or None. pip-audit's JSON output
      (2.10.1) carries no severity/CVSS field at all (only
      id/fix_versions/aliases/description), so severity is always None for
      pip-audit scans regardless of vuln_count -- only npm audit's JSON
      reports per-severity counts.
    """
    requirements_txt = repo_path / "requirements.txt"
    has_requirements = requirements_txt.exists()
    has_pyproject = (repo_path / "pyproject.toml").exists()
    has_py = has_requirements or has_pyproject
    has_js = (repo_path / "package.json").exists()
    try:
        if has_py and shutil.which("pip-audit"):
            # pip-audit with no explicit target audits the *current* Python
            # environment (i.e. this report-generation process's own
            # packages), not the repo at cwd -- cwd alone doesn't scope it.
            # Point it explicitly at this repo's actual manifest: -r for a
            # requirements.txt (preferred when present), else the positional
            # project_path form, which resolves a pyproject.toml project's
            # declared dependencies directly (distinct from --path, which
            # restricts to an *installation* directory, not a project source).
            if has_requirements:
                cmd = ["pip-audit", "-r", str(requirements_txt), "--format", "json"]
            else:
                cmd = ["pip-audit", str(repo_path), "--format", "json"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(proc.stdout or "[]")
            deps = data if isinstance(data, list) else data.get("dependencies", [])
            vuln_count = sum(len(d.get("vulns", [])) for d in deps if isinstance(d, dict))
            return "pip-audit", vuln_count, None
        if has_js and shutil.which("npm"):
            proc = subprocess.run(["npm", "audit", "--json"], cwd=str(repo_path),
                                   capture_output=True, text=True, timeout=30)
            data = json.loads(proc.stdout or "{}")
            meta_vulns = (data.get("metadata") or {}).get("vulnerabilities") or {}
            total = meta_vulns.get("total")
            if total is not None:
                vuln_count = int(total)
                severity_source = meta_vulns
            else:
                vulns = data.get("vulnerabilities") or {}
                vuln_count = sum(int(v) for v in vulns.values() if isinstance(v, (int, float)))
                severity_source = vulns
            severity = {
                lvl: int(severity_source[lvl]) for lvl in _SEVERITY_LEVELS
                if isinstance(severity_source.get(lvl), (int, float))
            }
            return "npm-audit", vuln_count, (severity or None)
    except subprocess.TimeoutExpired:
        return None, None, None
    except Exception:
        return None, None, None
    return None, None, None

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

def _cicd_row_for_target(
    args: Tuple[str, Path, Optional[str], str]
) -> Optional[Dict[str, Any]]:
    name, ecosystem_root, github_token, github_owner = args
    repo_path = ecosystem_root / name
    if not repo_path.is_dir():
        return None
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

    scanner, vuln_count, severity = _run_vuln_scan(repo_path)
    return {"repo": name, "has_ci": has_ci, "ci_status": ci_status,
            "ci_date": ci_date, "scanner": scanner, "vuln_count": vuln_count,
            "severity": severity}

def record_cve_history(rows: List[Dict[str, Any]], work_dir: Path, generated_at: str) -> None:
    """Appends one cve_history.json record per repo (as produced by
    _cicd_row_for_target/_run_vuln_scan) so cve_trend_section_html can chart
    vuln_count over time. Append-only -- prior runs' entries are preserved,
    never overwritten or pruned.

    scanner/vuln_count/severity are carried through as-is: all three None
    together means no scanner applied for that repo; vuln_count=0 with a
    real scanner name means a real scan found nothing.
    """
    history_path = work_dir / "cve_history.json"
    try:
        existing = json.loads(history_path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    for r in rows:
        existing.append({
            "generated_at": generated_at,
            "repo": r["repo"],
            "scanner": r.get("scanner"),
            "vuln_count": r.get("vuln_count"),
            "severity": r.get("severity"),
        })

    work_dir.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

def cicd_health_section_html(ecosystem_root: Path, targets: List[str],
                              work_dir: Path, generated_at: str) -> str:
    github_token = os.environ.get("GITHUB_TOKEN")
    github_owner = os.environ.get("GITHUB_OWNER", "omnibioai")

    # Each target's CI fetch + vuln scan is an independent network/subprocess
    # call (pip-audit/npm audit alone can take up to 30s each) -- run them
    # concurrently rather than serially, or this section alone can eat
    # several minutes and blow the 10-minute report-generation budget in
    # main.py's _run_report_job (measured: ~155s serially across 28 repos).
    # ThreadPoolExecutor.map preserves input order in its results, so row
    # order is unaffected.
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(
            _cicd_row_for_target,
            [(name, ecosystem_root, github_token, github_owner) for name in targets],
        )
    rows: List[Dict[str, Any]] = [r for r in results if r is not None]

    record_cve_history(rows, work_dir, generated_at)

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
