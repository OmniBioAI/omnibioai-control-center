from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

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
