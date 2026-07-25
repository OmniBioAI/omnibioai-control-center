from __future__ import annotations

from shared.helpers import _jsl, _jsn, fmt_int

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
