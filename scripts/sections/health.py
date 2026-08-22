from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from shared.health_fetch import EcosystemHealth
from shared.css import misc_section_html
from shared.helpers import fmt_int
from sections.misc.audit_trail import _health_audit_trail_section_html

_SENTRY_LEVEL_COLOR = {
    "error":   ("#FCEBEB", "#A32D2D"),
    "fatal":   ("#FCEBEB", "#A32D2D"),
    "warning": ("#FAEEDA", "#854F0B"),
    "info":    ("#E6F1FB", "#185FA5"),
}

def error_aggregation_section_html(sentry_org: str, sentry_project_slugs: List[str]) -> str:
    """One-shot fetch of recent Sentry issues per project -- intentionally NOT
    live/polling like the rest of the Health Status tab, since Sentry's API has
    its own rate limits; this runs once at report-generation time."""
    token = os.environ.get("SENTRY_API_TOKEN")
    if not token or not sentry_org or not sentry_project_slugs:
        return """
<div class="section" style="margin-top:12px">
  <div class="sec-title">errors (Sentry)</div>
  <div style="font-size:12px;color:var(--color-text-muted)">SENTRY_API_TOKEN not configured -- skipping error aggregation. Set SENTRY_API_TOKEN, SENTRY_ORG and SENTRY_PROJECT_SLUGS to enable this section.</div>
</div>"""

    import urllib.request

    per_project: List[Dict[str, Any]] = []
    for slug in sentry_project_slugs:
        issues = None
        try:
            req = urllib.request.Request(
                f"https://sentry.io/api/0/projects/{sentry_org}/{slug}/issues/?statsPeriod=24h",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                issues = json.loads(r.read())
        except Exception as e:
            print(f"[report] error_aggregation_section_html failed for {slug}: {type(e).__name__}: {e}", flush=True)

        if issues is None:
            per_project.append({"project": slug, "unresolved": None, "events_24h": None, "issues": [], "error": True})
            continue

        unresolved = [i for i in issues if i.get("status") == "unresolved"]
        events_24h = sum(int(i.get("count", 0) or 0) for i in issues)
        top5 = sorted(issues, key=lambda i: int(i.get("count", 0) or 0), reverse=True)[:5]
        per_project.append({
            "project": slug, "unresolved": len(unresolved),
            "events_24h": events_24h, "issues": top5, "error": False,
        })

    total_unresolved = sum(p["unresolved"] for p in per_project if not p["error"])
    total_events = sum(p["events_24h"] for p in per_project if not p["error"])

    def _proj_row(p):
        if p["error"]:
            return f"""<tr>
              <td style="font-weight:600;font-size:12px">{p['project']}</td>
              <td colspan="2" style="color:var(--color-text-muted)">unreachable</td>
            </tr>"""
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{p['project']}</td>
          <td class="r">{p['unresolved']}</td>
          <td class="r">{fmt_int(p['events_24h'])}</td>
        </tr>"""

    proj_rows = "".join(_proj_row(p) for p in per_project) or \
        '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px">no projects configured</td></tr>'

    all_issues = []
    for p in per_project:
        for issue in p.get("issues", []):
            all_issues.append({
                "project": p["project"], "title": issue.get("title", ""),
                "level": issue.get("level", ""),
                "count": int(issue.get("count", 0) or 0),
                "last_seen": issue.get("lastSeen", ""),
            })
    all_issues.sort(key=lambda i: i["count"], reverse=True)

    def _issue_row(i):
        bg, color = _SENTRY_LEVEL_COLOR.get(i["level"], ("#F1EFE8", "#444441"))
        return f"""<tr>
          <td style="font-size:12px">{i['project']}</td>
          <td style="font-size:12px">{i['title']}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{i['level']}</span></td>
          <td class="r">{fmt_int(i['count'])}</td>
          <td style="font-size:11px;color:var(--color-text-muted)">{i['last_seen']}</td>
        </tr>"""

    top_issues_rows = "".join(_issue_row(i) for i in all_issues) or \
        '<tr><td colspan="5" style="text-align:center;color:var(--color-text-muted);padding:20px">no issues found</td></tr>'

    return f"""
<div class="section" style="margin-top:12px">
  <div class="sec-title">errors (Sentry)</div>
  <div class="sec-sub">fetched once at report-generation time, not live · last 24h · org: {sentry_org}</div>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-label">unresolved</div><div class="kpi-val" style="color:{'#A32D2D' if total_unresolved else '#3B6D11'}">{total_unresolved}</div></div>
    <div class="kpi"><div class="kpi-label">events (24h)</div><div class="kpi-val">{fmt_int(total_events)}</div></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>project</th><th class="r">unresolved</th><th class="r">events (24h)</th></tr></thead>
      <tbody>{proj_rows}</tbody>
    </table>
  </div>
  <div class="sec-title" style="margin-top:12px">top issues across all services</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>project</th><th>issue</th><th>level</th><th class="r">events</th><th>last seen</th></tr></thead>
      <tbody>{top_issues_rows}</tbody>
    </table>
  </div>
</div>"""

def _health_overview_section_html() -> str:
    return f"""
<div class="tab-section">
<div id="hlth-banner" style="border-radius:12px;padding:12px 16px;display:flex;align-items:center;gap:10px;margin-bottom:16px;border:0.5px solid var(--color-border);background:var(--color-bg-surface)">
  <span class="status-dot dot-loading" id="hlth-dot"></span>
  <div style="flex:1">
    <div style="font-size:13px;font-weight:600;color:var(--color-text)" id="hlth-title">fetching health data...</div>
    <div style="font-size:11px;color:var(--color-text-muted);margin-top:2px" id="hlth-sub">connecting to control center</div>
  </div>
  <span style="font-size:11px;color:var(--color-text-muted)" id="hlth-countdown">next refresh in 30s</span>
  <button onclick="hlthFetch()" style="display:flex;align-items:center;gap:5px;padding:6px 12px;border:0.5px solid var(--color-border);border-radius:8px;background:var(--color-bg-surface);font-size:12px;color:var(--color-text-muted);cursor:pointer">↻ refresh</button>
</div>

<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">monitored</div><div class="kpi-val" id="hk-total">—</div><div class="kpi-sub">services</div></div>
  <div class="kpi"><div class="kpi-label">healthy</div><div class="kpi-val" id="hk-up" style="color:#3B6D11">—</div><div class="kpi-sub">UP</div></div>
  <div class="kpi"><div class="kpi-label">down</div><div class="kpi-val" id="hk-down" style="color:#A32D2D">—</div><div class="kpi-sub">need attention</div></div>
  <div class="kpi"><div class="kpi-label">degraded</div><div class="kpi-val" id="hk-warn" style="color:#854F0B">—</div><div class="kpi-sub">WARN</div></div>
  <div class="kpi"><div class="kpi-label">disk warnings</div><div class="kpi-val" id="hk-disk">—</div><div class="kpi-sub">paths checked</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
  <div class="section">
    <div class="sec-title">status distribution</div>
    <div class="sec-sub">across all monitored services</div>
    <div style="display:flex;align-items:center;gap:16px">
      <div style="position:relative;width:100px;height:100px;flex-shrink:0">
        <canvas id="hlth-donut" width="100" height="100"></canvas>
        <div class="donut-center"><div class="donut-center-val" id="hlth-up-val">—</div><div class="donut-center-lbl" id="hlth-of-lbl">of — UP</div></div>
      </div>
      <div>
        <div class="legend-item"><span class="legend-dot" style="background:#3B6D11;border-radius:50%"></span><span>healthy</span><span class="legend-pct" id="hl-up">—</span></div>
        <div class="legend-item"><span class="legend-dot" style="background:#A32D2D;border-radius:50%"></span><span>down</span><span class="legend-pct" id="hl-down">—</span></div>
        <div class="legend-item"><span class="legend-dot" style="background:#854F0B;border-radius:50%"></span><span>degraded</span><span class="legend-pct" id="hl-warn">—</span></div>
      </div>
    </div>
  </div>
  <div class="section">
    <div class="sec-title">response latency</div>
    <div class="sec-sub">per service · proportional bars · color = health</div>
    <div id="hlth-lat-bars"><div style="font-size:12px;color:#6b7280">loading...</div></div>
  </div>
</div>
</div>
"""

def _health_services_section_html() -> str:
    return f"""
<div class="tab-section">
<div style="font-size:11px;font-weight:600;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">services</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px;margin-bottom:12px" id="hlth-svc-grid">
  <div style="font-size:12px;color:var(--color-text-muted);grid-column:1/-1">loading service cards...</div>
</div>
</div>
"""

def _health_storage_section_html() -> str:
    return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">disk checks</div>
  <div class="sec-sub">storage paths monitored by control center</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px" id="hlth-disk-grid">
    <div style="font-size:12px;color:var(--color-text-muted)">loading...</div>
  </div>
</div>

<div class="section" style="margin-top:12px">
  <div class="sec-title">symlink &amp; mount integrity</div>
  <div class="sec-sub">known-important paths, checked live</div>
  <div id="integrity-panel-body">
    <div style="font-size:12px;color:var(--color-text-muted)">loading...</div>
  </div>
</div>
</div>
"""

def _health_gpu_section_html() -> str:
    return f"""
<div class="tab-section">
<div class="section" style="margin-top:12px">
  <div class="sec-title">GPU health</div>
  <div class="sec-sub">nvidia-smi · live, refreshes with the rest of this tab</div>
  <div id="gpu-panel-body">
    <div style="font-size:12px;color:var(--color-text-muted)">loading...</div>
  </div>
</div>
</div>
"""

def _health_activity_section_html() -> str:
    return f"""
<div class="tab-section">
<div class="section" style="margin-top:12px">
  <div class="sec-title">activity monitor</div>
  <div class="sec-sub">live CPU / memory / network via Prometheus + cAdvisor, host stats via node_exporter</div>
  <div id="am-host-summary" style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">
    <div style="font-size:12px;color:var(--color-text-muted);grid-column:1/-1">loading host summary...</div>
  </div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search containers..." oninput="amFilter(this.value)">
    <span class="result-count" id="am-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="amPerPage(this.value)"><option value="15" selected>15</option><option value="30">30</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="amSort('name')">container</th>
        <th class="r" onclick="amSort('cpu_pct')">% cpu</th>
        <th class="r" onclick="amSort('memory_used_mb')">memory</th>
        <th class="r" onclick="amSort('memory_pct')">mem %</th>
        <th class="r" onclick="amSort('net_rx_mb')">net rx</th>
        <th class="r" onclick="amSort('net_tx_mb')">net tx</th>
        <th class="r" onclick="amSort('pids')">pids</th>
      </tr></thead>
      <tbody id="am-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="am-pg"></div>
</div>
</div>
"""

_HEALTH_SCRIPT = f"""
<script>
var _hChart=null,_hTimer=null,_hCd=30,_hUrl='';
var _hIcons={{mysql:'🗄️',redis:'⚡',http:'🌐',tcp:'🔌'}};
function _hLatCol(ms){{return ms<5?'#3B6D11':ms<20?'#854F0B':'#A32D2D';}}
function hlthFetch(){{
  clearInterval(_hTimer);_hCd=30;
  fetch(_hUrl+'/health').then(function(r){{if(!r.ok)throw new Error('health request failed');return r.json();}}).then(function(d){{
    _hlthRender(d);_hStartCd();
  }}).catch(function(){{_hlthError();_hStartCd();}});
}}
function _hStartCd(){{
  _hTimer=setInterval(function(){{
    _hCd--;
    document.getElementById('hlth-countdown').textContent='next refresh in '+_hCd+'s';
    if(_hCd<=0){{clearInterval(_hTimer);hlthFetch();gpuFetch();integrityFetch();activityFetch();atFetch();}}
  }},1000);
}}
function _hlthRender(data){{
  var svcs=Array.isArray(data.services)?data.services:[];var disk=Array.isArray((data.system||{{}}).disk)?data.system.disk:[];
  var hasServices=svcs.length>0,hasDisk=disk.length>0;
  var raw=String(data.overall_status||data.status||'UNKNOWN').toUpperCase();
  var ov=(raw==='OK'||raw==='HEALTHY')?'UP':raw;
  var ts=data.generated_at||'';
  var up=svcs.filter(function(s){{return s.status==='UP';}}).length;
  var dn=svcs.filter(function(s){{return s.status==='DOWN';}}).length;
  var wn=svcs.filter(function(s){{return s.status==='WARN';}}).length;
  var dw=disk.filter(function(d){{return d.status!=='UP';}}).length;
  var bn=document.getElementById('hlth-banner');
  var bgMap={{UP:'#EAF3DE',DOWN:'#FCEBEB',WARN:'#FAEEDA'}};
  var bdMap={{UP:'#97C459',DOWN:'#E24B4A',WARN:'#EF9F27'}};
  bn.style.background=bgMap[ov]||'#1a1d2e';bn.style.borderColor=bdMap[ov]||'#2a2d3e';
  document.getElementById('hlth-dot').className='status-dot dot-'+(ov==='UP'?'up':(ov==='DOWN'||ov==='UNREACHABLE'||ov==='UNAVAILABLE')?'down':'warn');
  document.getElementById('hlth-title').textContent=ov==='UP'?'Healthy':ov==='DOWN'?'One or more services are down':ov==='WARN'?'One or more services degraded':ov==='UNREACHABLE'||ov==='UNAVAILABLE'?'Control center unreachable':'Health status unknown';
  document.getElementById('hlth-sub').textContent='Checked: '+(ts?new Date(ts).toLocaleTimeString():'')+' · Source: Control Center /health';
  document.getElementById('hk-total').textContent=hasServices?svcs.length:'\u2014';
  document.getElementById('hk-up').textContent=hasServices?up:'\u2014';
  document.getElementById('hk-down').textContent=hasServices?dn:'\u2014';
  document.getElementById('hk-warn').textContent=hasServices?wn:'\u2014';
  document.getElementById('hk-disk').textContent=hasDisk?dw:'\u2014';
  document.getElementById('hl-up').textContent=hasServices?up:'\u2014';
  document.getElementById('hl-down').textContent=hasServices?dn:'\u2014';
  document.getElementById('hl-warn').textContent=hasServices?wn:'\u2014';
  document.getElementById('hlth-up-val').textContent=hasServices?up:(ov==='UP'?'HEALTHY':ov);
  document.getElementById('hlth-of-lbl').textContent=hasServices?'of '+svcs.length+' UP':'service details unavailable';
  if(_hChart)_hChart.destroy();
  _hChart=null;
  if(hasServices){{
    _hChart=new Chart(document.getElementById('hlth-donut'),{{
      type:'doughnut',
      data:{{labels:['healthy','down','degraded'],
             datasets:[{{data:[up,dn,wn],backgroundColor:['#22c55e','#ef4444','#f59e0b'],borderWidth:2,borderColor:'#1a1d2e',hoverOffset:3}}]}},
      options:{{responsive:false,cutout:'70%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+c.raw;}}}}}}}}}}
    }});
  }}
  var latEl=document.getElementById('hlth-lat-bars');latEl.innerHTML='';
  var wl=svcs.filter(function(s){{return s.latency_ms!==null&&s.latency_ms!==undefined;}});
  var ml=Math.max.apply(null,wl.map(function(s){{return s.latency_ms;}}));if(!ml)ml=1;
  if(wl.length===0){{latEl.innerHTML='<div style="font-size:12px;color:#6b7280">no latency data</div>';}}
  wl.forEach(function(s){{
    var pct=Math.round(s.latency_ms/ml*100);var c=_hLatCol(s.latency_ms);
    var d=document.createElement('div');d.className='bar-row';
    d.innerHTML='<span class="bar-label" style="width:100px" title="'+s.name+'">'+s.name+'</span>'+
      '<div class="bar-track" style="height:14px"><div class="bar-fill" style="width:'+pct+'%;background:'+c+'33"></div>'+
      '<span class="bar-val" style="color:'+c+'">'+s.latency_ms+' ms</span></div>';
    latEl.appendChild(d);
  }});
  var grid=document.getElementById('hlth-svc-grid');grid.innerHTML='';
  if(!hasServices){{grid.innerHTML='<div style="font-size:12px;color:#6b7280;grid-column:1/-1">service-level health details were not provided</div>';}}
  svcs.forEach(function(s){{
    var sc=s.status==='UP'?'up':s.status==='DOWN'?'down':'warn';
    var bgC={{up:'#F0FDF4',down:'#FEF2F2',warn:'#FFFBEB'}};
    var bdC={{up:'#97C459',down:'#E24B4A',warn:'#EF9F27'}};
    var stC={{up:'#3B6D11',down:'#A32D2D',warn:'#854F0B'}};
    var icon=_hIcons[s.type]||'⚙️';
    var latH=s.latency_ms!=null?'<span style="color:'+_hLatCol(s.latency_ms)+';font-weight:600">'+s.latency_ms+' ms</span>':'—';
    var openH=s.ui_url?'<a href="'+s.ui_url+'" style="font-size:11px;color:#0094ff;display:inline-flex;align-items:center;gap:3px;margin-top:8px;text-decoration:none" target="_blank">open UI ↗</a>':'';
    var card=document.createElement('div');
    card.style.cssText='background:'+bgC[sc]+';border:1px solid '+bdC[sc]+'33;border-left:4px solid '+bdC[sc]+';border-radius:12px;padding:14px';
    card.innerHTML='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">'+
      '<div style="display:flex;align-items:center;gap:7px"><span style="font-size:18px">'+icon+'</span>'+
      '<span style="font-size:13px;font-weight:600;color:#ffffff">'+s.name+'</span></div>'+
      '<span class="badge" style="background:'+stC[sc]+'22;color:'+stC[sc]+'">'+s.status+'</span></div>'+
      '<div style="display:grid;grid-template-columns:60px 1fr;gap:3px 8px;font-size:11px">'+
      '<span style="color:#6b7280">target</span><span style="color:#6b7280;font-family:monospace;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+s.target+'</span>'+
      '<span style="color:#6b7280">latency</span><span>'+latH+'</span>'+
      '<span style="color:#6b7280">message</span><span style="color:#6b7280">'+(s.message||'—')+'</span>'+
      '</div>'+openH;
    grid.appendChild(card);
  }});
  var dg=document.getElementById('hlth-disk-grid');dg.innerHTML='';
  if(disk.length===0){{dg.innerHTML='<div style="font-size:12px;color:#6b7280">no disk checks configured</div>';return;}}
  disk.forEach(function(d){{
    var m=(d.message||'').match(/([0-9.]+)%/);var pct=m?parseFloat(m[1]):0;
    var c=d.status==='UP'?'#3B6D11':d.status==='WARN'?'#854F0B':'#A32D2D';
    var card=document.createElement('div');
    card.style.cssText='background:#1a1d2e;border-radius:8px;padding:10px 12px';
    card.innerHTML='<div style="display:flex;justify-content:space-between;margin-bottom:4px">'+
      '<span style="font-size:12px;font-weight:600;color:#ffffff">'+d.name.replace('disk:','')+'</span>'+
      '<span style="font-size:11px;font-weight:600;color:'+c+'">'+d.message+'</span></div>'+
      '<div style="font-size:10px;color:#6b7280;margin-bottom:6px">'+d.target+'</div>'+
      '<div style="background:#2a2d3e;border-radius:3px;height:5px;overflow:hidden">'+
      '<div style="width:'+Math.min(100,pct).toFixed(1)+'%;height:100%;background:'+c+';border-radius:3px"></div></div>';
    dg.appendChild(card);
  }});
}}
function _gpuMemColor(usedMb, totalMb, memoryUnsupported){{
  if(memoryUnsupported) return 'var(--color-text-muted)';
  if(usedMb===null||usedMb===undefined) return '#A32D2D';
  var pct=usedMb/totalMb*100;
  return pct<70?'#3B6D11':pct<90?'#854F0B':'#A32D2D';
}}
function gpuFetch(){{
  fetch(_hUrl+'/gpu').then(function(r){{return r.json();}}).then(function(d){{
    var el=document.getElementById('gpu-panel-body');
    if(!d.reachable){{
      el.innerHTML='<div style="font-size:12px;color:#A32D2D">GPU unreachable: '+(d.error||'unknown error')+'</div>';
      return;
    }}
    var memNull = d.memory_used_mb===null||d.memory_used_mb===undefined;
    var memColor=_gpuMemColor(d.memory_used_mb,d.memory_total_mb,d.memory_unsupported);
    var memText = d.memory_unsupported
      ? '<span style="color:var(--color-text-muted)">memory reporting not supported on this GPU</span>'
      : memNull
      ? '<span style="color:#A32D2D;font-weight:600">N/A — driver may be in a bad state</span>'
      : (d.memory_used_mb/1024).toFixed(1)+' / '+(d.memory_total_mb/1024).toFixed(1)+' GB';
    var procRows = (d.processes||[]).map(function(p){{
      return '<div style="font-size:11px;color:var(--color-text-muted)">'+p.name+' (pid '+p.pid+') — '+p.memory_mb+' MB</div>';
    }}).join('') || '<div style="font-size:11px;color:var(--color-text-muted)">no processes</div>';
    var modelRows = (d.ollama_loaded_models||[]).map(function(m){{
      return '<div style="font-size:11px;color:var(--color-text)">'+m.name+' — '+m.size_gb+' GB (until '+(m.until?new Date(m.until).toLocaleTimeString():'?')+')</div>';
    }}).join('') || '<div style="font-size:11px;color:var(--color-text-muted)">no models currently loaded</div>';
    el.innerHTML =
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'+
      '<div><div style="font-size:11px;color:var(--color-text-muted)">GPU</div>'+
      '<div style="font-size:13px;font-weight:600">'+d.gpu_name+'</div></div>'+
      '<div><div style="font-size:11px;color:var(--color-text-muted)">memory</div>'+
      '<div style="font-size:13px;font-weight:600;color:'+memColor+'">'+memText+'</div></div>'+
      '<div><div style="font-size:11px;color:var(--color-text-muted)">utilization</div>'+
      '<div style="font-size:13px">'+d.utilization_pct+'%</div></div>'+
      '<div><div style="font-size:11px;color:var(--color-text-muted)">temp / power</div>'+
      '<div style="font-size:13px">'+d.temperature_c+'°C · '+d.power_draw_w+'W</div></div>'+
      '<div style="grid-column:1/-1"><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:4px">GPU processes</div>'+procRows+'</div>'+
      '<div style="grid-column:1/-1"><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:4px">ollama loaded models</div>'+modelRows+'</div>'+
      '</div>'+
      (d.error?'<div style="margin-top:8px;font-size:11px;color:#854F0B">⚠ '+d.error+'</div>':'');
  }}).catch(function(){{
    document.getElementById('gpu-panel-body').innerHTML='<div style="font-size:12px;color:#A32D2D">could not reach /gpu endpoint</div>';
  }});
}}
var _AM={{pp:15,page:1,sort:'cpu_pct',dir:-1,search:'',all:[],filtered:[]}};
function amFilter(v){{_AM.search=v.toLowerCase();_AM.page=1;amApply();}}
function amPerPage(v){{_AM.pp=parseInt(v);_AM.page=1;amApply();}}
function amSort(col){{if(_AM.sort===col){{_AM.dir*=-1;}}else{{_AM.sort=col;_AM.dir=col==='name'?1:-1;}} _AM.page=1;amApply();}}
function _amNum(v,digits){{return (v===null||v===undefined)?'—':v.toFixed(digits);}}
function amApply(){{
  var d=_AM.all.filter(function(c){{return !_AM.search||c.name.toLowerCase().includes(_AM.search);}});
  var col=_AM.sort;
  d.sort(function(a,b){{
    var av=a[col],bv=b[col];
    if(av===null||av===undefined)av=-Infinity;
    if(bv===null||bv===undefined)bv=-Infinity;
    if(typeof av==='string')av=av.toLowerCase();
    if(typeof bv==='string')bv=bv.toLowerCase();
    return av<bv?_AM.dir:av>bv?-_AM.dir:0;
  }});
  _AM.filtered=d;
  document.getElementById('am-count').textContent=d.length+' containers';
  var start=(_AM.page-1)*_AM.pp,page=d.slice(start,start+_AM.pp);
  var tb=document.getElementById('am-tbody');tb.innerHTML='';
  page.forEach(function(c){{
    var cpuColor=c.cpu_pct>50?'#A32D2D':c.cpu_pct>15?'#854F0B':'#3B6D11';
    var memColor=c.memory_pct===null?'inherit':(c.memory_pct>80?'#A32D2D':c.memory_pct>50?'#854F0B':'#3B6D11');
    var tr=document.createElement('tr');
    tr.innerHTML='<td style="font-size:12px;font-weight:600">'+c.name+'</td>'+
      '<td class="r" style="color:'+cpuColor+';font-weight:600">'+_amNum(c.cpu_pct,2)+'%</td>'+
      '<td class="r">'+_amNum(c.memory_used_mb,1)+' MB</td>'+
      '<td class="r" style="color:'+memColor+'">'+(c.memory_pct===null?'—':_amNum(c.memory_pct,2)+'%')+'</td>'+
      '<td class="r">'+_amNum(c.net_rx_mb,1)+' MB</td>'+
      '<td class="r">'+_amNum(c.net_tx_mb,1)+' MB</td>'+
      '<td class="r">'+(c.pids===null||c.pids===undefined?'—':c.pids)+'</td>';
    tb.appendChild(tr);
  }});
  renderPg('am',_AM,amApply);
}}
function amHostRender(h){{
  var el=document.getElementById('am-host-summary');
  if(!h){{el.innerHTML='<div style="font-size:12px;color:#854F0B;grid-column:1/-1">node_exporter not configured — host-level stats unavailable (container-level stats below still work)</div>';return;}}
  function card(label,val,color){{return '<div class="kpi"><div class="kpi-label">'+label+'</div><div class="kpi-val" style="color:'+(color||'inherit')+'">'+val+'</div></div>';}}
  var memPct = (h.memory_available_gb!==null&&h.memory_total_gb) ? h.memory_available_gb/h.memory_total_gb : null;
  el.innerHTML =
    card('cpu load (1m)', _amNum(h.load_1m,2)) +
    card('memory available', _amNum(h.memory_available_gb,1)+' / '+(h.memory_total_gb===null?'—':h.memory_total_gb)+' GB',
         memPct!==null&&memPct<0.15?'#A32D2D':'inherit') +
    card('swap used', _amNum(h.swap_used_gb,1)+' / '+_amNum(h.swap_total_gb,1)+' GB',
         h.swap_used_gb>2?'#854F0B':'inherit') +
    card('processes', h.processes_total===null?'—':h.processes_total) +
    card('threads', h.threads_total===null?'—':h.threads_total) +
    card('cpu idle', _amNum(h.cpu_idle_pct,1)+'%');
}}
function activityFetch(){{
  fetch(_hUrl+'/activity').then(function(r){{return r.json();}}).then(function(d){{
    if(!d.reachable){{document.getElementById('am-host-summary').innerHTML='<div style="font-size:12px;color:#A32D2D;grid-column:1/-1">activity data unreachable: '+(d.error||'unknown')+'</div>';return;}}
    amHostRender(d.host);
    _AM.all=d.containers||[];
    amApply();
  }}).catch(function(){{
    document.getElementById('am-host-summary').innerHTML='<div style="font-size:12px;color:#A32D2D;grid-column:1/-1">could not reach /activity endpoint</div>';
  }});
}}
function integrityFetch(){{
  fetch(_hUrl+'/integrity').then(function(r){{return r.json();}}).then(function(d){{
    var el=document.getElementById('integrity-panel-body');
    var checks=d.checks||[];
    if(checks.length===0){{el.innerHTML='<div style="font-size:12px;color:var(--color-text-muted)">no paths configured for checking</div>';return;}}
    var statusColor={{ok:'#3B6D11',broken:'#A32D2D',missing:'#A32D2D',empty:'#854F0B'}};
    var statusBg={{ok:'#EAF3DE',broken:'#FCEBEB',missing:'#FCEBEB',empty:'#FAEEDA'}};
    el.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px">' +
      checks.map(function(c){{
        var c1=statusColor[c.status]||'#444441', bg=statusBg[c.status]||'#F1EFE8';
        return '<div style="background:var(--color-bg-surface2);border-left:3px solid '+c1+';border-radius:8px;padding:10px 12px">'+
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'+
          '<span style="font-size:12px;font-weight:600">'+c.name+'</span>'+
          '<span class="badge" style="background:'+bg+';color:'+c1+'">'+c.status+'</span></div>'+
          '<div style="font-size:10px;color:var(--color-text-muted);font-family:monospace;word-break:break-all">'+c.path+'</div>'+
          (c.is_symlink?'<div style="font-size:10px;color:var(--color-text-muted);font-family:monospace;word-break:break-all">→ '+c.resolves_to+'</div>':'')+
          '</div>';
      }}).join('') + '</div>';
  }}).catch(function(){{
    document.getElementById('integrity-panel-body').innerHTML='<div style="font-size:12px;color:#A32D2D">could not reach /integrity endpoint</div>';
  }});
}}
function _hlthError(){{
  document.getElementById('hlth-dot').className='status-dot dot-down';
  document.getElementById('hlth-title').textContent='Control center unreachable';
  document.getElementById('hlth-sub').textContent='Check that the control center is running on the configured URL';
  ['hk-total','hk-up','hk-down','hk-warn','hk-disk'].forEach(function(id){{document.getElementById(id).textContent='—';}});
  ['hl-up','hl-down','hl-warn'].forEach(function(id){{document.getElementById(id).textContent='\u2014';}});
  document.getElementById('hlth-up-val').textContent='UNAVAILABLE';
  document.getElementById('hlth-of-lbl').textContent='service details unavailable';
  if(_hChart){{_hChart.destroy();_hChart=null;}}
  document.getElementById('hlth-svc-grid').innerHTML='<div style="font-size:12px;color:#6b7280;grid-column:1/-1">unable to reach '+_hUrl+'/health</div>';
  document.getElementById('hlth-disk-grid').innerHTML='<div style="font-size:12px;color:#6b7280">no data</div>';
  document.getElementById('hlth-lat-bars').innerHTML='<div style="font-size:12px;color:#6b7280">no data</div>';
}}
var _AT={{pp:15,page:1,sort:'timestamp',dir:-1,search:'',all:[],filtered:[]}};
var _atFiltersBuilt=false;
function _atBuildOptions(sel,values){{
  values.forEach(function(v){{
    var o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o);
  }});
}}
function _atStatusColor(code){{
  if(code===null||code===undefined)return 'var(--color-text-muted)';
  return code<300?'#3B6D11':code<500?'#854F0B':'#A32D2D';
}}
function atFilter(v){{_AT.search=v.toLowerCase();_AT.page=1;atApply();}}
function atPerPage(v){{_AT.pp=parseInt(v);_AT.page=1;atApply();}}
function atSort(col){{if(_AT.sort===col){{_AT.dir*=-1;}}else{{_AT.sort=col;_AT.dir=col==='timestamp'?-1:1;}} _AT.page=1;atApply();}}
function atApply(){{
  var hideHealth=document.getElementById('at-hide-health').checked;
  var fType=document.getElementById('at-f-type').value;
  var fDecision=document.getElementById('at-f-decision').value;
  var fStatus=document.getElementById('at-f-status').value;
  var fReason=document.getElementById('at-f-reason').value;
  var fFrom=document.getElementById('at-f-from').value;
  var fTo=document.getElementById('at-f-to').value;
  var q=(document.getElementById('at-search').value||'').toLowerCase();
  var d=_AT.all.filter(function(e){{
    if(hideHealth&&e.is_health_check)return false;
    if(fType&&e.event_type!==fType)return false;
    if(fDecision&&e.decision!==fDecision)return false;
    if(fStatus&&String(e.status_code)!==fStatus)return false;
    if(fReason&&e.reason!==fReason)return false;
    if(fFrom&&e.timestamp.slice(0,10)<fFrom)return false;
    if(fTo&&e.timestamp.slice(0,10)>fTo)return false;
    if(q&&!((e.action||'')+' '+(e.endpoint||'')+' '+(e.trace_id||'')).toLowerCase().includes(q))return false;
    return true;
  }});
  var col=_AT.sort;
  d.sort(function(a,b){{
    var av=a[col],bv=b[col];
    if(av===null||av===undefined)av='';
    if(bv===null||bv===undefined)bv='';
    return av<bv?_AT.dir:av>bv?-_AT.dir:0;
  }});
  _AT.filtered=d;
  document.getElementById('at-count').textContent=d.length+' events';
  var start=(_AT.page-1)*_AT.pp,page=d.slice(start,start+_AT.pp);
  var tb=document.getElementById('at-tbody');tb.innerHTML='';
  if(page.length===0){{
    tb.innerHTML='<tr><td colspan="8" style="text-align:center;color:var(--color-text-muted);padding:20px">no events match filters</td></tr>';
  }}
  page.forEach(function(e){{
    var tr=document.createElement('tr');
    var decColor=e.decision==='deny'?'#A32D2D':'#3B6D11';
    var traceShort=e.trace_id?e.trace_id.slice(0,8):'—';
    tr.innerHTML='<td style="font-size:11px;color:var(--color-text-muted);white-space:nowrap">'+new Date(e.timestamp).toLocaleString()+'</td>'+
      '<td style="font-size:12px;font-weight:600">'+e.event_type+'</td>'+
      '<td class="mono" style="font-size:11px">'+(e.action||'—')+'</td>'+
      '<td style="color:'+decColor+';font-weight:600;font-size:12px">'+(e.decision||'—')+'</td>'+
      '<td class="r" style="color:'+_atStatusColor(e.status_code)+';font-weight:600">'+(e.status_code===null||e.status_code===undefined?'—':e.status_code)+'</td>'+
      '<td style="font-size:11px;color:var(--color-text-muted)">'+(e.reason||'—')+'</td>'+
      '<td style="font-size:12px">'+(e.user_id||'—')+'</td>'+
      '<td class="mono" style="font-size:10px;color:var(--color-text-muted)" title="'+(e.trace_id||'')+'">'+traceShort+'</td>';
    tb.appendChild(tr);
  }});
  renderPg('at',_AT,atApply);
}}
function atFetch(){{
  fetch(_hUrl+'/audit-trail').then(function(r){{return r.json();}}).then(function(d){{
    document.getElementById('at-k-total').textContent=d.total_events;
    document.getElementById('at-k-health').textContent=d.health_check_pings;
    var pct=d.total_events?Math.round(100*d.health_check_pings/d.total_events):0;
    document.getElementById('at-k-health-pct').textContent=pct+'% of window';
    document.getElementById('at-k-deny').textContent=(d.decision_breakdown||{{}}).deny||0;
    document.getElementById('at-k-actors').textContent=d.distinct_actors;
    if(!_atFiltersBuilt){{
      _atBuildOptions(document.getElementById('at-f-type'),(d.event_type_breakdown||[]).map(function(x){{return x.event_type;}}));
      _atBuildOptions(document.getElementById('at-f-status'),Object.keys(d.status_code_breakdown||{{}}).sort());
      _atBuildOptions(document.getElementById('at-f-reason'),(d.reason_breakdown||[]).map(function(x){{return x.reason;}}));
      _atFiltersBuilt=true;
    }}
    _AT.all=d.events||[];
    atApply();
  }}).catch(function(){{
    document.getElementById('at-tbody').innerHTML='<tr><td colspan="8" style="text-align:center;color:#A32D2D;padding:20px">could not reach /audit-trail endpoint</td></tr>';
  }});
}}
hlthFetch();gpuFetch();integrityFetch();activityFetch();atFetch();
</script>
"""

def health_section_html(health: EcosystemHealth, control_center_url: str,
                        sentry_org: str = "", sentry_project_slugs: Optional[List[str]] = None) -> str:
    sub_tabs = [
        ("overview", "Overview",      _health_overview_section_html()),
        ("services", "Services",      _health_services_section_html()),
        ("storage",  "Disk & Mounts", _health_storage_section_html()),
        ("gpu",      "GPU",           _health_gpu_section_html()),
        ("activity", "Activity",      _health_activity_section_html()),
        ("audit",    "Audit Trail",   _health_audit_trail_section_html()),
        ("errors",   "Errors",        error_aggregation_section_html(sentry_org, sentry_project_slugs or [])),
    ]
    return misc_section_html(sub_tabs, group_id="health", render_nav=False) + _HEALTH_SCRIPT
