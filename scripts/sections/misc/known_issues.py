from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

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
