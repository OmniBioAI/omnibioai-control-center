from __future__ import annotations

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
