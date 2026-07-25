from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BACKUP_STATUS_PATH_DEFAULT = "backup_status.json"

_BACKUP_STATUS_COLOR = {
    "success": ("#EAF3DE", "#3B6D11"),
    "failed":  ("#FCEBEB", "#A32D2D"),
    "partial": ("#FAEEDA", "#854F0B"),
}

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
