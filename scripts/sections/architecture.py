from __future__ import annotations

from typing import Dict, Optional

from shared.colors import COLORS
from shared.cloc import Totals

def architecture_section_html(project_totals: Dict[str, Totals],
                               grand: Totals,
                               control_center_url: str) -> str:
    cc_url = control_center_url.rstrip("/")
    return f"""
<div class="tab-section">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px">
  <div>
    <div style="font-size:15px;font-weight:600;color:var(--color-text)">OmniBioAI ecosystem</div>
    <div style="font-size:12px;color:var(--color-text-muted);margin-top:2px">Click any node to see live health, latency and metrics</div>
  </div>
  <div style="display:flex;align-items:center;gap:8px">
    <div style="display:flex;align-items:center;gap:5px;font-size:11px;padding:3px 8px;border-radius:99px;background:var(--color-bg-surface);border:0.5px solid var(--color-border);color:var(--color-text-muted)">
      <span class="status-dot dot-loading" id="g-dot"></span>
      <span id="g-status">fetching...</span>
    </div>
    <button onclick="fetchH()" style="display:flex;align-items:center;gap:5px;padding:6px 12px;border:0.5px solid var(--color-border);border-radius:8px;background:var(--color-bg-surface);font-size:12px;color:var(--color-text-muted);cursor:pointer">
      ↻ refresh
    </button>
  </div>
</div>

<div style="display:flex;align-items:center;gap:0;margin-bottom:8px">
  <div style="flex:1;height:1px;background:var(--c-red-bd);opacity:.4"></div>
  <span style="font-size:11px;color:var(--c-red);font-weight:600;padding:0 10px">enforced request path →</span>
  <div style="flex:1;height:1px;background:var(--c-red-bd);opacity:.4"></div>
</div>

<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px">

  <!-- DEV / CLIENTS -->
  <div style="border-radius:12px;border:0.5px solid var(--c-blue-bd);background:var(--c-blue-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-blue);margin-bottom:8px">dev / clients</div>
    {"".join(_arch_node(n,d,p,u,'blue') for n,d,p,u in [
      ('studio','Electron · v0.2.0',None,None),
      ('dev-hub','knowledge graph','5173',None),
      ('sdk','Python SDK','5190',None),
      ('iam-client','auth SDK',None,None),
      ('security-sdk','policy client',None,None),
    ])}
  </div>

  <!-- SECURITY -->
  <div style="border-radius:12px;border:1px solid var(--c-red-bd);background:var(--c-red-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-red);margin-bottom:2px">🔐 security plane</div>
    <div style="font-size:10px;text-align:center;color:var(--c-red);opacity:.8;margin-bottom:6px">zero-trust boundary</div>
    {"".join(_arch_node(n,d,p,u,'red') for n,d,p,u in [
      ('api-gateway','JWT · trace prop','8080',None),
      ('auth-service','bcrypt · JWT','8001',None),
      ('policy-engine','RBAC/ABAC','8002',None),
      ('hpc-policy-engine','GPU quota','8003',None),
      ('security-audit','Redis streams','8004',None),
    ])}
  </div>

  <!-- WORKBENCH -->
  <div style="border-radius:12px;border:0.5px solid var(--c-teal-bd);background:var(--c-teal-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-teal);margin-bottom:8px">workbench</div>
    {"".join(_arch_node(n,d,p,u,'teal') for n,d,p,u in [
      ('workbench','Django · 80+ plugins','8000','https://webstudio.omnibioai.org'),
      ('lims','lab data','7000','https://lims.omnibioai.org'),
      ('rag','PubMed · DeepSeek','8090','https://rag.omnibioai.org'),
      ('workflow-bundles','WDL/Nextflow/CWL','8098','https://bundles.omnibioai.org'),
      ('control-center','health · images','7070','https://control.omnibioai.org'),
    ])}
  </div>

  <!-- SERVICES -->
  <div style="border-radius:12px;border:0.5px solid var(--c-amber-bd);background:var(--c-amber-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-amber);margin-bottom:8px">services</div>
    {"".join(_arch_node(n,d,p,u,'amber') for n,d,p,u in [
      ('toolserver','FastAPI bio tools','9090','https://tools.omnibioai.org'),
      ('model-registry','ML versioning','8095','https://models.omnibioai.org'),
      ('opa','Open Policy Agent','8181',None),
      ('ollama','Llama/DeepSeek','11434',None),
      ('videos','tutorials · SDK','8086',None),
    ])}
  </div>

  <!-- EXECUTION -->
  <div style="border-radius:12px;border:0.5px solid var(--c-purple-bd);background:var(--c-purple-bg);padding:10px 8px 12px">
    <div style="font-size:11px;font-weight:600;text-align:center;color:var(--c-purple);margin-bottom:8px">execution</div>
    {"".join(_arch_node(n,d,p,u,'purple') for n,d,p,u in [
      ('tes','Slurm/AWS/Azure/GCP','8081','https://webstudio.omnibioai.org/_svc/tes'),
      ('tool-runtime','Docker/Singularity',None,None),
      ('tool-images','80+ bio tools','8097',None),
      ('dev-docker','DGX · GPU env','8082','https://dev.omnibioai.org'),
    ])}
  </div>

</div>

<!-- DETAIL PANEL -->
<div id="det-panel" style="display:none;border:0.5px solid var(--color-border);border-radius:12px;background:var(--color-bg-surface);overflow:hidden;margin-bottom:12px">
  <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:0.5px solid var(--color-border)">
    <div>
      <div style="font-size:14px;font-weight:600;color:var(--color-text)" id="det-name">—</div>
      <div style="font-size:11px;color:var(--color-text-muted);margin-top:2px" id="det-lane">—</div>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <a id="det-open" style="display:none;font-size:11px;padding:3px 8px;border:0.5px solid var(--color-border);border-radius:6px;background:var(--color-info-dim);color:var(--color-info);text-decoration:none" target="_blank">open UI ↗</a>
      <button onclick="document.getElementById('det-panel').style.display='none'" style="padding:4px 10px;border:0.5px solid var(--color-border);border-radius:6px;background:transparent;font-size:11px;color:var(--color-text-muted);cursor:pointer">close</button>
    </div>
  </div>
  <div style="padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:3px">health status</div><div style="font-size:13px;font-weight:600" id="det-status">—</div></div>
    <div><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:3px">latency</div><div style="font-size:13px" id="det-lat">—</div></div>
    <div><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:3px">port</div><div style="font-size:13px;font-weight:600" id="det-port">—</div></div>
    <div><div style="font-size:11px;color:var(--color-text-muted);margin-bottom:3px">message</div><div style="font-size:12px;color:var(--color-text-muted)" id="det-msg">—</div></div>
    <div style="grid-column:1/-1">
      <div style="font-size:11px;color:var(--color-text-muted);margin-bottom:4px">description</div>
      <div style="font-size:12px;color:var(--color-text-muted)" id="det-desc">—</div>
    </div>
  </div>
</div>

<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:8px 0;border-top:0.5px solid var(--color-border)">
  <div class="legend-item"><span class="legend-dot" style="background:#3B6D11;border-radius:50%"></span>healthy</div>
  <div class="legend-item"><span class="legend-dot" style="background:#A32D2D;border-radius:50%"></span>down</div>
  <div class="legend-item"><span class="legend-dot" style="background:#888780;border-radius:50%"></span>not monitored</div>
  <div style="margin-left:auto;font-size:11px;color:var(--color-text-muted)">live from <code style="font-size:10px">/health</code> · auto-refreshes every 30s</div>
</div>
</div>

<script>
var _hd={{}};var _cc='';
function _ccAuthHeader(){{
  var t=localStorage.getItem('omnibioai_access_token');
  return t?{{'Authorization':'Bearer '+t}}:{{}};
}}
function fetchH(){{
  fetch(_cc+'/health',{{headers:_ccAuthHeader()}}).then(function(r){{if(!r.ok)throw new Error('health request failed');return r.json();}}).then(function(d){{
    var svcs=Array.isArray(d.services)?d.services:[];
    _hd={{}};svcs.forEach(function(s){{_hd[s.name]=s;}});
    var raw=String(d.overall_status||d.status||'UNKNOWN').toUpperCase();
    var ov=(raw==='OK'||raw==='HEALTHY')?'UP':raw;
    var gd=document.getElementById('g-dot');
    var gs=document.getElementById('g-status');
    gd.className='status-dot '+(ov==='UP'?'dot-up':(ov==='DOWN'||ov==='UNREACHABLE'||ov==='UNAVAILABLE')?'dot-down':'dot-warn');
    gs.textContent=ov==='UP'?'healthy':ov==='WARN'?'degraded':ov.toLowerCase();
    Object.keys(_hd).forEach(function(k){{
      var el=document.getElementById('nd-'+k);
      if(el){{var s=(_hd[k].status||'').toUpperCase();el.className='status-dot '+(s==='UP'?'dot-up':'dot-down');}}
    }});
  }}).catch(function(){{
    document.getElementById('g-dot').className='status-dot dot-down';
    document.getElementById('g-status').textContent='unreachable';
  }});
}}
function showDet(name,lane,desc,port,ui){{
  var p=document.getElementById('det-panel');
  p.style.display='block';
  document.getElementById('det-name').textContent=name;
  document.getElementById('det-lane').textContent=lane;
  document.getElementById('det-desc').textContent=desc;
  document.getElementById('det-port').textContent=port?':'+port:'—';
  var oa=document.getElementById('det-open');
  if(ui){{oa.style.display='inline';oa.href=ui;}}else{{oa.style.display='none';}}
  var s=_hd[name];
  if(s){{
    var st=(s.status||'UNKNOWN').toUpperCase();
    var sel=document.getElementById('det-status');
    sel.textContent=st;sel.style.color=st==='UP'?'#3B6D11':'#A32D2D';
    var lat=s.latency_ms;
    document.getElementById('det-lat').innerHTML=lat!=null?'<span style="color:'+(lat<5?'#3B6D11':lat<20?'#854F0B':'#A32D2D')+';font-weight:600">'+lat+' ms</span>':'—';
    document.getElementById('det-msg').textContent=s.message||'—';
  }}else{{
    document.getElementById('det-status').textContent='not monitored';
    document.getElementById('det-status').style.color='#888780';
    document.getElementById('det-lat').textContent='—';
    document.getElementById('det-msg').textContent='—';
  }}
  p.scrollIntoView({{behavior:'smooth',block:'nearest'}});
}}
fetchH();setInterval(fetchH,30000);
</script>
"""

def _arch_node(name: str, desc: str, port: Optional[str],
               ui: Optional[str], color: str) -> str:
    c = COLORS[color]
    ui_js = f"'{ui}'" if ui else "null"
    port_js = f"'{port}'" if port else "null"
    short = name.replace("omnibioai-", "").replace("omnibioai", "omnibioai")
    return f"""<div onclick="showDet('{name}','{color} lane','{desc}',{port_js},{ui_js})"
  style="border-radius:8px;border:0.5px solid {c['stroke']};background:var(--color-bg-surface);
         padding:8px 10px;margin-bottom:6px;cursor:pointer;
         transition:transform .15s;position:relative"
  onmouseover="this.style.transform='translateY(-1px)'"
  onmouseout="this.style.transform=''"
>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:2px">
    <span style="font-size:11px;font-weight:600;color:{c['text']}">{short}</span>
    <span class="status-dot dot-loading" id="nd-{name}"></span>
  </div>
  <div style="font-size:10px;color:var(--color-text-muted);line-height:1.3">{desc}{(' · :'+port) if port else ''}</div>
</div>"""
