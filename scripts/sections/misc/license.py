from __future__ import annotations

from shared.health_fetch import _admin_header

def license_section_html(control_center_url: str) -> str:
    import urllib.request, json
    data: dict = {}
    try:
        request = urllib.request.Request(
            f"{control_center_url.rstrip('/')}/license",
            headers={"User-Agent": "omnibioai-report/1.0", **_admin_header()},
        )
        with urllib.request.urlopen(request, timeout=10) as r:
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
