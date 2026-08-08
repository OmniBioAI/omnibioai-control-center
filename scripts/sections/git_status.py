from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

# Mirrors omnibioai-utils/ecosystem_status.sh's own git plumbing (branch,
# `status --porcelain`, `log @{u}..`) so this panel and `bash
# omnibioai-utils/ecosystem_status.sh` always agree -- this is the same
# check, just rendered in the report instead of a terminal.

# Same exclude list ecosystem_status.sh's own `case` guard uses: legacy,
# un-prefixed duplicate dirs (e.g. "data/", "work/" alongside the real
# "omnibioai-data/", "omnibioai-work/") that still happen to be git repos
# but aren't part of the canonical ecosystem.
_EXCLUDE_DIRS = {"db-init", "obsolete", "utils", "data", "work"}

_STATUS_COLOR = {
    "clean": ("#EAF3DE", "#3B6D11"),
    "dirty": ("#FCEBEB", "#A32D2D"),
}


def _run(args: List[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=10)
        return proc.stdout
    except Exception:
        return ""


def _row_for_repo(repo_path: Path) -> Dict[str, Any]:
    name = repo_path.name
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path).strip() or "unknown"

    porcelain = _run(["git", "status", "--porcelain"], repo_path)
    lines = [ln for ln in porcelain.splitlines() if ln]
    untracked = sum(1 for ln in lines if ln.startswith("??"))
    modified = len(lines) - untracked

    unpushed_out = _run(["git", "log", "@{u}..", "--oneline"], repo_path)
    unpushed = len([ln for ln in unpushed_out.splitlines() if ln])

    is_clean = not lines and unpushed == 0
    details: List[str] = []
    if modified:
        details.append(f"{modified} modified")
    if untracked:
        details.append(f"{untracked} untracked")
    if unpushed:
        details.append(f"{unpushed} unpushed")

    return {
        "repo": name,
        "branch": branch,
        "non_main": branch not in ("main", "master"),
        "clean": is_clean,
        "modified": modified,
        "untracked": untracked,
        "unpushed": unpushed,
        "details": ", ".join(details),
    }


def collect_git_status(ecosystem_root: Path) -> List[Dict[str, Any]]:
    """Per-repo git working-tree status across every repo under
    `ecosystem_root` -- branch, clean/dirty, and modified/untracked/
    unpushed counts. Same scan `omnibioai-utils/ecosystem_status.sh`
    performs. Public: `git_status_section_html` (this report's own HTML
    tab) and `generate_report.py`'s `report_data.json` export (consumed
    by the React Admin Console's EcosystemPage) both call this directly,
    so the two never drift out of sync with each other.
    """
    repo_dirs = sorted(
        p for p in ecosystem_root.iterdir()
        if p.is_dir() and p.name not in _EXCLUDE_DIRS and (p / ".git").is_dir()
    )
    if not repo_dirs:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(_row_for_repo, repo_dirs))


def git_status_section_html(ecosystem_root: Path) -> str:
    """Per-repo git working-tree status rendered as this report's own
    HTML tab -- see `collect_git_status` for the underlying scan.
    """
    rows = collect_git_status(ecosystem_root)

    total = len(rows)
    clean = sum(1 for r in rows if r["clean"])
    dirty = total - clean
    non_main = sum(1 for r in rows if r["non_main"])

    def _row(r: Dict[str, Any]) -> str:
        status = "clean" if r["clean"] else "dirty"
        bg, color = _STATUS_COLOR[status]
        branch_color = "#854F0B" if r["non_main"] else "var(--color-text-muted)"
        details = r["details"] or "—"
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{r['repo']}</td>
          <td class="mono" style="color:{branch_color}">{r['branch']}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{'✓ clean' if r['clean'] else '✗ dirty'}</span></td>
          <td style="font-size:11px;color:var(--color-text-muted)">{details}</td>
        </tr>"""

    table_rows = "".join(_row(r) for r in rows) or \
        '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px">no repos found</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">repos scanned</div><div class="kpi-val">{total}</div></div>
  <div class="kpi"><div class="kpi-label">clean</div><div class="kpi-val" style="color:#3B6D11">{clean}</div></div>
  <div class="kpi"><div class="kpi-label">dirty</div><div class="kpi-val" style="color:{'#A32D2D' if dirty else '#3B6D11'}">{dirty}</div></div>
  <div class="kpi"><div class="kpi-label">non-main branch</div><div class="kpi-val" style="color:{'#854F0B' if non_main else '#3B6D11'}">{non_main}</div></div>
</div>
<div class="section">
  <div class="sec-title">git working-tree status</div>
  <div class="sec-sub">every repo under the ecosystem root · same check as `bash omnibioai-utils/ecosystem_status.sh`</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>repository</th><th>branch</th><th>status</th><th>details</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</div>
</div>
"""
