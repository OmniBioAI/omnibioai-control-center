from __future__ import annotations

from shared.helpers import fmt_int

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
