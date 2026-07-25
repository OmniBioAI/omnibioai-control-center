from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from shared.helpers import _jsl, _jsn
from sections.misc.cicd_health import _SEVERITY_LEVELS

_CVE_MIN_TREND_POINTS = 3

def _cve_repo_table_html(rows: List[Dict[str, Any]]) -> str:
    def _row(r):
        vc = r.get("vuln_count")
        scanner = r.get("scanner") or "—"
        vc_html = "—" if vc is None else \
            (f'<span style="color:#A32D2D;font-weight:600">{vc}</span>' if vc > 0 else "0")
        severity = r.get("severity") or {}
        sev_parts = [f"{lvl}: {severity[lvl]}" for lvl in _SEVERITY_LEVELS if severity.get(lvl)]
        sev_html = ", ".join(sev_parts) if sev_parts else ("—" if not severity else "0")
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{r.get('repo', '')}</td>
          <td style="font-size:11px;color:var(--color-text-muted)">{scanner}</td>
          <td class="r">{vc_html}</td>
          <td style="font-size:11px;color:var(--color-text-muted)">{sev_html}</td>
        </tr>"""

    table_rows = "".join(_row(r) for r in sorted(rows, key=lambda r: r.get("repo", ""))) or \
        '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px">no repos found</td></tr>'

    return f"""<div class="section">
  <div class="sec-title">latest scan, per repo</div>
  <div class="sec-sub">severity breakdown is only available for npm-audit scans -- pip-audit's JSON output doesn't classify severity, so pip-audit-scanned repos always show "—" there even with a real vuln count</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>repo</th><th>scanner</th><th class="r">vulns</th><th>severity</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</div>"""

def cve_trend_section_html(work_dir: Path) -> str:
    """
    Reads {work_dir}/cve_history.json -- one record per repo per report
    generation run, appended by record_cve_history() -- and renders an
    aggregate known-vulnerabilities trend line across runs, plus a per-repo
    breakdown table for the latest run.

    Needs at least _CVE_MIN_TREND_POINTS distinct runs before a trend line
    is meaningful; below that, shows the latest scan's table alone with an
    explanatory note instead of an empty/misleading chart.
    """
    history_path = work_dir / "cve_history.json"
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
        if not isinstance(history, list):
            history = []
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    if not history:
        return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">CVE trend</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    No CVE history recorded yet -- this fills in automatically each time a
    report is generated (see the CI/CD Health tab for the current scan).
  </div>
</div>
</div>"""

    # cve_history.json is append-only and each run's per-repo rows are
    # written together, so grouping by generated_at (dict preserves
    # insertion order) recovers one ordered point per run without needing
    # a separate sort key.
    runs: Dict[str, List[Dict[str, Any]]] = {}
    for rec in history:
        runs.setdefault(rec.get("generated_at", ""), []).append(rec)
    run_timestamps = list(runs.keys())
    latest_rows = runs[run_timestamps[-1]]
    repo_table_html = _cve_repo_table_html(latest_rows)

    if len(run_timestamps) < _CVE_MIN_TREND_POINTS:
        schedule_hours = os.environ.get("REPORT_SCHEDULE_HOURS", "6")
        return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">CVE trend</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    Not enough history yet to chart a trend ({len(run_timestamps)} of
    {_CVE_MIN_TREND_POINTS} minimum report runs recorded) -- this fills in
    automatically as scheduled reports run (every {schedule_hours}h).
    Showing the latest scan below.
  </div>
</div>
{repo_table_html}
</div>"""

    trend_labels = _jsl(run_timestamps)
    trend_totals = _jsn([
        sum(r.get("vuln_count") or 0 for r in runs[ts] if r.get("vuln_count") is not None)
        for ts in run_timestamps
    ])

    return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">CVE trend</div>
  <div class="sec-sub">total known vulnerabilities across all scanned repos, per report run</div>
  <div style="position:relative;height:220px"><canvas id="cve-trend-chart"></canvas></div>
</div>
{repo_table_html}
</div>

<script>
(function(){{
  var el=document.getElementById('cve-trend-chart');
  if(!el)return;
  new Chart(el,{{
    type:'line',
    data:{{labels:{trend_labels},datasets:[{{data:{trend_totals},borderColor:'#A32D2D',backgroundColor:'#A32D2D22',fill:true,tension:0.25,pointRadius:2}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}}}},
      scales:{{y:{{beginAtZero:true,ticks:{{font:{{size:10}},color:'#9CA3AF'}},grid:{{color:'rgba(0,0,0,0.04)'}},border:{{display:false}}}},
               x:{{ticks:{{font:{{size:9}},color:'#9CA3AF',maxRotation:45,autoSkip:true}},grid:{{display:false}},border:{{display:false}}}}}}}}
  }});
}})();
</script>
"""
