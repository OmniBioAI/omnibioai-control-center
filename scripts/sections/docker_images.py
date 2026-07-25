from __future__ import annotations

def docker_section_html_UNUSED(control_center_url: str) -> str:  # kept for reference; not included in report (duplicate of React DockerPage)
    cc_url = control_center_url.rstrip("/")
    return f"""
<div class="tab-section">

<!-- KPI strip -->
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">running / total</div><div class="kpi-val" id="dk-k-run">—</div><div class="kpi-sub">containers</div></div>
  <div class="kpi"><div class="kpi-label">SIF built</div><div class="kpi-val" id="dk-k-sif-ok" style="color:#22c55e">—</div><div class="kpi-sub">images</div></div>
  <div class="kpi"><div class="kpi-label">SIF missing</div><div class="kpi-val" id="dk-k-sif-miss" style="color:#ef4444">—</div><div class="kpi-sub">not built</div></div>
  <div class="kpi"><div class="kpi-label">SIF storage</div><div class="kpi-val" id="dk-k-gb">—</div><div class="kpi-sub">GB total</div></div>
  <div class="kpi"><div class="kpi-label">plugin images</div><div class="kpi-val" id="dk-k-plug">—</div><div class="kpi-sub">tracked</div></div>
  <div class="kpi"><div class="kpi-label">plugins present</div><div class="kpi-val" id="dk-k-plug-ok" style="color:#22c55e">—</div><div class="kpi-sub">local images</div></div>
</div>

<!-- Sub-tabs -->
<div style="display:flex;border-bottom:1px solid #2a2d3e;margin-bottom:16px">
  <button class="dk-sub" data-sub="containers" onclick="dkSub('containers')" style="padding:10px 16px;font-size:13px;color:#00e5a0;font-weight:600;background:none;border:none;border-bottom:2px solid #00e5a0;cursor:pointer;white-space:nowrap;margin-bottom:-1px;font-family:inherit">Platform Containers</button>
  <button class="dk-sub" data-sub="sif"        onclick="dkSub('sif')"        style="padding:10px 16px;font-size:13px;color:#6b7280;font-weight:400;background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap;margin-bottom:-1px;font-family:inherit">Tool SIF Images</button>
  <button class="dk-sub" data-sub="plugins"    onclick="dkSub('plugins')"    style="padding:10px 16px;font-size:13px;color:#6b7280;font-weight:400;background:none;border:none;border-bottom:2px solid transparent;cursor:pointer;white-space:nowrap;margin-bottom:-1px;font-family:inherit">Plugin Docker Images</button>
</div>

<!-- Platform Containers -->
<div id="dk-containers">
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search containers…" oninput="dkCS(this.value)">
    <span class="result-count" id="dk-cont-count">—</span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>Container</th><th>Image</th><th>Status</th><th>Uptime</th><th>Ports</th></tr></thead>
      <tbody id="dk-cont-tbody"><tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="dk-cont-pg"></div>
</div>

<!-- Tool SIF Images -->
<div id="dk-sif" style="display:none">
  <div style="display:flex;gap:16px;align-items:flex-start">
    <div id="dk-sif-sidebar" style="width:154px;flex-shrink:0">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>
    </div>
    <div style="flex:1;min-width:0">
      <div class="filter-row">
        <input class="search-inp" type="text" placeholder="search tools…" oninput="dkSS(this.value)">
        <span class="result-count" id="dk-sif-count">—</span>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Tool</th><th>Category</th><th>Status</th><th>Size</th></tr></thead>
          <tbody id="dk-sif-tbody"><tr><td colspan="4" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
        </table>
      </div>
      <div class="pg-wrap" id="dk-sif-pg"></div>
    </div>
  </div>
</div>

<!-- Plugin Docker Images -->
<div id="dk-plugins" style="display:none">
  <div style="display:flex;gap:16px;align-items:flex-start">
    <div id="dk-plug-sidebar" style="width:154px;flex-shrink:0">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>
    </div>
    <div style="flex:1;min-width:0">
      <div class="filter-row">
        <input class="search-inp" type="text" placeholder="search plugins…" oninput="dkPS(this.value)">
        <label style="font-size:12px;color:#6b7280;display:flex;align-items:center;gap:5px;cursor:pointer">
          <input type="checkbox" id="dk-plug-miss-cb" onchange="dkPM(this.checked)"> Missing only
        </label>
        <span class="result-count" id="dk-plug-count">—</span>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Plugin</th><th>Category</th><th>Image</th><th>Local Status</th><th>Size</th></tr></thead>
          <tbody id="dk-plug-tbody"><tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
        </table>
      </div>
      <div class="pg-wrap" id="dk-plug-pg"></div>
    </div>
  </div>
</div>
</div>

<script>
var _DKU='';
var _DC={{pp:15,page:1,all:[],filtered:[],q:''}};
var _DS={{pp:15,page:1,all:[],filtered:[],q:'',cat:null}};
var _DP={{pp:15,page:1,all:[],filtered:[],q:'',cat:null,miss:false}};

function dkSub(id){{
  ['containers','sif','plugins'].forEach(function(s){{document.getElementById('dk-'+s).style.display=s===id?'':'none';}});
  document.querySelectorAll('.dk-sub').forEach(function(b){{
    var a=b.dataset.sub===id;
    b.style.color=a?'#00e5a0':'#6b7280';b.style.fontWeight=a?'600':'400';b.style.borderBottomColor=a?'#00e5a0':'transparent';
  }});
}}

function _dkBadge(r,re){{
  var bg=r?'rgba(34,197,94,.12)':re?'rgba(245,158,11,.12)':'rgba(239,68,68,.12)';
  var c=r?'#22c55e':re?'#f59e0b':'#ef4444';
  return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+bg+';color:'+c+';white-space:nowrap">'+(r?'running':re?'restarting':'stopped')+'</span>';
}}

function _dkChip(cat){{
  var M={{alignment:'#0094ff',assembly:'#22c55e','variant-calling':'#a855f7','rna-seq':'#f59e0b',genomics:'#0094ff',metagenomics:'#0094ff',proteomics:'#ef4444','single-cell':'#0094ff',epigenomics:'#f59e0b','protein-structure':'#a855f7','population-genetics':'#22c55e',annotation:'#f59e0b',qc:'#9ca3af',imaging:'#ef4444'}};
  var c=M[cat]||'#9ca3af';
  return '<span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:99px;background:'+c+'22;color:'+c+';white-space:nowrap">'+cat+'</span>';
}}

function _dkBuildSidebar(sid,all,curCat,onCat){{
  var cats={{}};all.forEach(function(x){{cats[x.category]=(cats[x.category]||0)+1;}});
  var el=document.getElementById(sid);
  el.innerHTML='<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>';
  var entries=[['All',null,all.length]].concat(Object.entries(cats).sort(function(a,b){{return b[1]-a[1];}}).map(function(e){{return[e[0],e[0],e[1]];}}));
  entries.forEach(function(e){{
    var active=e[1]===curCat;
    var btn=document.createElement('button');
    btn.style.cssText='width:100%;text-align:left;padding:5px 8px;border-radius:6px;font-size:11px;background:'+(active?'rgba(0,229,160,.1)':'transparent')+';color:'+(active?'#00e5a0':'#6b7280')+';border:1px solid '+(active?'rgba(0,229,160,.25)':'transparent')+';font-weight:'+(active?'600':'400')+';cursor:pointer;display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;font-family:inherit';
    var lbl=document.createElement('span');lbl.style.cssText='overflow:hidden;text-overflow:ellipsis;white-space:nowrap';lbl.textContent=e[0];
    var cnt=document.createElement('span');cnt.style.cssText='background:rgba(255,255,255,.08);color:#6b7280;border-radius:99px;font-size:10px;font-weight:700;padding:1px 5px;flex-shrink:0;margin-left:4px';cnt.textContent=e[2];
    btn.appendChild(lbl);btn.appendChild(cnt);
    btn.onclick=(function(cat){{return function(){{onCat(cat);}};}})(e[1]);
    el.appendChild(btn);
  }});
}}

/* ── Containers ── */
function dkCS(v){{_DC.q=v.toLowerCase();_DC.page=1;dkCA();}}
function dkCA(){{
  var d=_DC.all.filter(function(c){{return!_DC.q||((c.Names||'')+' '+(c.Image||'')).toLowerCase().includes(_DC.q);}});
  _DC.filtered=d;document.getElementById('dk-cont-count').textContent=d.length+' containers';
  var pg=d.slice((_DC.page-1)*_DC.pp,_DC.page*_DC.pp);
  document.getElementById('dk-cont-tbody').innerHTML=pg.length?pg.map(function(c){{
    var name=(c.Names||'').replace(/^[/]/,'')||'—';var s=(c.State||'').toLowerCase();
    var r=s==='running'||(c.Status||'').startsWith('Up');var re=s==='restarting'||(c.Status||'').toLowerCase().includes('restart');
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important;white-space:nowrap">'+name+'</td>'+
      '<td class="mono">'+(c.Image||'—')+'</td><td>'+_dkBadge(r,re)+'</td>'+
      '<td style="font-size:12px;color:#e2e8f0 !important;white-space:nowrap">'+(c.RunningFor||'—')+'</td>'+
      '<td class="mono">'+(c.Ports||'—')+'</td></tr>';
  }}).join(''):'<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">No containers found</td></tr>';
  renderPg('dk-cont',_DC,dkCA);
}}

/* ── SIF Images ── */
function dkSS(v){{_DS.q=v.toLowerCase();_DS.page=1;dkSA();}}
function dkSC(cat){{_DS.cat=cat;_DS.page=1;dkSA();_dkBuildSidebar('dk-sif-sidebar',_DS.all,_DS.cat,dkSC);}}
function dkSA(){{
  var d=_DS.all.filter(function(i){{return(!_DS.q||i.tool.toLowerCase().includes(_DS.q))&&(!_DS.cat||i.category===_DS.cat);}});
  _DS.filtered=d;document.getElementById('dk-sif-count').textContent=d.length+' images';
  var pg=d.slice((_DS.page-1)*_DS.pp,_DS.page*_DS.pp);
  document.getElementById('dk-sif-tbody').innerHTML=pg.length?pg.map(function(i){{
    var sb=i.exists?'rgba(34,197,94,.12)':'rgba(239,68,68,.12)';var sc=i.exists?'#22c55e':'#ef4444';
    var sz='—';if(i.exists){{var mb=i.size_mb,w=Math.min(100,(mb/5120)*100).toFixed(1),lbl=mb>=1024?(mb/1024).toFixed(1)+' GB':mb+' MB';sz='<div style="display:flex;align-items:center;gap:6px"><div style="width:50px;height:4px;background:#2a2d3e;border-radius:99px;overflow:hidden;flex-shrink:0"><div style="height:100%;width:'+w+'%;background:#0094ff;border-radius:99px"></div></div><span style="font-size:12px;font-family:monospace;color:#e2e8f0 !important;white-space:nowrap">'+lbl+'</span></div>';}}
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important">'+i.tool+'</td>'+
      '<td>'+_dkChip(i.category)+'</td>'+
      '<td><span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+sb+';color:'+sc+'">'+(i.exists?'built':'missing')+'</span></td>'+
      '<td>'+sz+'</td></tr>';
  }}).join(''):'<tr><td colspan="4" style="text-align:center;color:#6b7280;padding:24px 12px">No SIF images found</td></tr>';
  renderPg('dk-sif',_DS,dkSA);
}}

/* ── Plugin Images ── */
function dkPS(v){{_DP.q=v.toLowerCase();_DP.page=1;dkPA();}}
function dkPM(v){{_DP.miss=v;_DP.page=1;dkPA();}}
function dkPC(cat){{_DP.cat=cat;_DP.page=1;dkPA();_dkBuildSidebar('dk-plug-sidebar',_DP.all,_DP.cat,dkPC);}}
function dkPA(){{
  var d=_DP.all.filter(function(p){{return(!_DP.q||(p.name+' '+p.plugin).toLowerCase().includes(_DP.q))&&(!_DP.cat||p.category===_DP.cat)&&(!_DP.miss||p.local_status==='missing');}});
  _DP.filtered=d;document.getElementById('dk-plug-count').textContent=d.length+' plugins';
  var pg=d.slice((_DP.page-1)*_DP.pp,_DP.page*_DP.pp);
  document.getElementById('dk-plug-tbody').innerHTML=pg.length?pg.map(function(p){{
    var sb=p.local_status==='present'?'rgba(34,197,94,.12)':'rgba(239,68,68,.12)';var sc=p.local_status==='present'?'#22c55e':'#ef4444';
    var sz='—';if(p.local_status==='present'&&p.size_mb>0)sz=p.size_mb>=1024?(p.size_mb/1024).toFixed(1)+' GB':p.size_mb+' MB';
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important;white-space:nowrap">'+p.name+'</td>'+
      '<td>'+_dkChip(p.category)+'</td>'+
      '<td class="mono" style="max-width:260px">'+p.image+'</td>'+
      '<td><span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+sb+';color:'+sc+'">'+p.local_status+'</span></td>'+
      '<td style="font-size:12px;font-family:monospace;color:#e2e8f0 !important;white-space:nowrap">'+sz+'</td></tr>';
  }}).join(''):'<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">No plugins match filters</td></tr>';
  renderPg('dk-plug',_DP,dkPA);
}}

/* ── Fetch all three endpoints on load ── */
(function(){{
  fetch(_DKU+'/docker/containers').then(function(r){{return r.json();}}).then(function(d){{
    _DC.all=d.containers||[];
    document.getElementById('dk-k-run').textContent=(d.running||0)+'/'+_DC.all.length;
    dkCA();
  }}).catch(function(){{document.getElementById('dk-cont-tbody').innerHTML='<tr><td colspan="5" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';}});

  fetch(_DKU+'/docker/sif-images').then(function(r){{return r.json();}}).then(function(d){{
    _DS.all=d.images||[];
    document.getElementById('dk-k-sif-ok').textContent=d.built||0;
    document.getElementById('dk-k-sif-miss').textContent=d.missing||0;
    document.getElementById('dk-k-gb').textContent=(d.total_gb||0)+' GB';
    _dkBuildSidebar('dk-sif-sidebar',_DS.all,_DS.cat,dkSC);
    dkSA();
  }}).catch(function(){{document.getElementById('dk-sif-tbody').innerHTML='<tr><td colspan="4" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';}});

  fetch(_DKU+'/docker/plugin-images').then(function(r){{return r.json();}}).then(function(d){{
    _DP.all=d.plugins||[];
    document.getElementById('dk-k-plug').textContent=_DP.all.length;
    document.getElementById('dk-k-plug-ok').textContent=d.present||0;
    _dkBuildSidebar('dk-plug-sidebar',_DP.all,_DP.cat,dkPC);
    dkPA();
  }}).catch(function(){{document.getElementById('dk-plug-tbody').innerHTML='<tr><td colspan="5" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';}});
}})();
</script>
"""

def docker_kpi_header_html() -> str:
    """Shared KPI strip -- rendered once via misc_section_html's header_html,
    so it stays visible across all three Docker Images sub-tabs rather than
    being tied to (and duplicated across) each one."""
    return """
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">running / total</div><div class="kpi-val" id="dk-k-run">—</div><div class="kpi-sub">containers</div></div>
  <div class="kpi"><div class="kpi-label">SIF built</div><div class="kpi-val" id="dk-k-sif-ok" style="color:#22c55e">—</div><div class="kpi-sub">images</div></div>
  <div class="kpi"><div class="kpi-label">SIF missing</div><div class="kpi-val" id="dk-k-sif-miss" style="color:#ef4444">—</div><div class="kpi-sub">not built</div></div>
  <div class="kpi"><div class="kpi-label">SIF storage</div><div class="kpi-val" id="dk-k-gb">—</div><div class="kpi-sub">GB total</div></div>
  <div class="kpi"><div class="kpi-label">plugin images</div><div class="kpi-val" id="dk-k-plug">—</div><div class="kpi-sub">tracked</div></div>
  <div class="kpi"><div class="kpi-label">plugins present</div><div class="kpi-val" id="dk-k-plug-ok" style="color:#22c55e">—</div><div class="kpi-sub">local images</div></div>
</div>
"""

def docker_containers_section_html() -> str:
    return """
<div class="filter-row">
  <input class="search-inp" type="text" placeholder="search containers…" oninput="dkCS(this.value)">
  <span class="result-count" id="dk-cont-count">—</span>
</div>
<div class="tbl-wrap">
  <table>
    <thead><tr><th>Container</th><th>Image</th><th>Status</th><th>Uptime</th><th>Ports</th></tr></thead>
    <tbody id="dk-cont-tbody"><tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
  </table>
</div>
<div class="pg-wrap" id="dk-cont-pg"></div>
"""

def docker_sif_section_html() -> str:
    return """
<div style="display:flex;gap:16px;align-items:flex-start">
  <div id="dk-sif-sidebar" style="width:154px;flex-shrink:0">
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>
  </div>
  <div style="flex:1;min-width:0">
    <div class="filter-row">
      <input class="search-inp" type="text" placeholder="search tools…" oninput="dkSS(this.value)">
      <span class="result-count" id="dk-sif-count">—</span>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>Tool</th><th>Category</th><th>Status</th><th>Size</th></tr></thead>
        <tbody id="dk-sif-tbody"><tr><td colspan="4" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
      </table>
    </div>
    <div class="pg-wrap" id="dk-sif-pg"></div>
  </div>
</div>
"""

def docker_plugins_section_html() -> str:
    return """
<div style="display:flex;gap:16px;align-items:flex-start">
  <div id="dk-plug-sidebar" style="width:154px;flex-shrink:0">
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>
  </div>
  <div style="flex:1;min-width:0">
    <div class="filter-row">
      <input class="search-inp" type="text" placeholder="search plugins…" oninput="dkPS(this.value)">
      <label style="font-size:12px;color:#6b7280;display:flex;align-items:center;gap:5px;cursor:pointer">
        <input type="checkbox" id="dk-plug-miss-cb" onchange="dkPM(this.checked)"> Missing only
      </label>
      <span class="result-count" id="dk-plug-count">—</span>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>Plugin</th><th>Category</th><th>Image</th><th>Local Status</th><th>Size</th></tr></thead>
        <tbody id="dk-plug-tbody"><tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">loading…</td></tr></tbody>
      </table>
    </div>
    <div class="pg-wrap" id="dk-plug-pg"></div>
  </div>
</div>
"""

_DOCKER_IMAGES_SCRIPT = """
<script>
var _DKU='';
var _DC={pp:15,page:1,all:[],filtered:[],q:''};
var _DS={pp:15,page:1,all:[],filtered:[],q:'',cat:null};
var _DP={pp:15,page:1,all:[],filtered:[],q:'',cat:null,miss:false};

function _dkBadge(r,re){
  var bg=r?'rgba(34,197,94,.12)':re?'rgba(245,158,11,.12)':'rgba(239,68,68,.12)';
  var c=r?'#22c55e':re?'#f59e0b':'#ef4444';
  return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+bg+';color:'+c+';white-space:nowrap">'+(r?'running':re?'restarting':'stopped')+'</span>';
}

function _dkChip(cat){
  var M={alignment:'#0094ff',assembly:'#22c55e','variant-calling':'#a855f7','rna-seq':'#f59e0b',genomics:'#0094ff',metagenomics:'#0094ff',proteomics:'#ef4444','single-cell':'#0094ff',epigenomics:'#f59e0b','protein-structure':'#a855f7','population-genetics':'#22c55e',annotation:'#f59e0b',qc:'#9ca3af',imaging:'#ef4444'};
  var c=M[cat]||'#9ca3af';
  return '<span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:99px;background:'+c+'22;color:'+c+';white-space:nowrap">'+cat+'</span>';
}

function _dkBuildSidebar(sid,all,curCat,onCat){
  var cats={};all.forEach(function(x){cats[x.category]=(cats[x.category]||0)+1;});
  var el=document.getElementById(sid);
  el.innerHTML='<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Categories</div>';
  var entries=[['All',null,all.length]].concat(Object.entries(cats).sort(function(a,b){return b[1]-a[1];}).map(function(e){return[e[0],e[0],e[1]];}));
  entries.forEach(function(e){
    var active=e[1]===curCat;
    var btn=document.createElement('button');
    btn.style.cssText='width:100%;text-align:left;padding:5px 8px;border-radius:6px;font-size:11px;background:'+(active?'rgba(0,229,160,.1)':'transparent')+';color:'+(active?'#00e5a0':'#6b7280')+';border:1px solid '+(active?'rgba(0,229,160,.25)':'transparent')+';font-weight:'+(active?'600':'400')+';cursor:pointer;display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;font-family:inherit';
    var lbl=document.createElement('span');lbl.style.cssText='overflow:hidden;text-overflow:ellipsis;white-space:nowrap';lbl.textContent=e[0];
    var cnt=document.createElement('span');cnt.style.cssText='background:rgba(255,255,255,.08);color:#6b7280;border-radius:99px;font-size:10px;font-weight:700;padding:1px 5px;flex-shrink:0;margin-left:4px';cnt.textContent=e[2];
    btn.appendChild(lbl);btn.appendChild(cnt);
    btn.onclick=(function(cat){return function(){onCat(cat);};})(e[1]);
    el.appendChild(btn);
  });
}

/* ── Containers ── */
function dkCS(v){_DC.q=v.toLowerCase();_DC.page=1;dkCA();}
function dkCA(){
  var d=_DC.all.filter(function(c){return!_DC.q||((c.Names||'')+' '+(c.Image||'')).toLowerCase().includes(_DC.q);});
  _DC.filtered=d;document.getElementById('dk-cont-count').textContent=d.length+' containers';
  var pg=d.slice((_DC.page-1)*_DC.pp,_DC.page*_DC.pp);
  document.getElementById('dk-cont-tbody').innerHTML=pg.length?pg.map(function(c){
    var name=(c.Names||'').replace(/^[/]/,'')||'—';var s=(c.State||'').toLowerCase();
    var r=s==='running'||(c.Status||'').startsWith('Up');var re=s==='restarting'||(c.Status||'').toLowerCase().includes('restart');
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important;white-space:nowrap">'+name+'</td>'+
      '<td class="mono">'+(c.Image||'—')+'</td><td>'+_dkBadge(r,re)+'</td>'+
      '<td style="font-size:12px;color:#e2e8f0 !important;white-space:nowrap">'+(c.RunningFor||'—')+'</td>'+
      '<td class="mono">'+(c.Ports||'—')+'</td></tr>';
  }).join(''):'<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">No containers found</td></tr>';
  renderPg('dk-cont',_DC,dkCA);
}

/* ── SIF Images ── */
function dkSS(v){_DS.q=v.toLowerCase();_DS.page=1;dkSA();}
function dkSC(cat){_DS.cat=cat;_DS.page=1;dkSA();_dkBuildSidebar('dk-sif-sidebar',_DS.all,_DS.cat,dkSC);}
function dkSA(){
  var d=_DS.all.filter(function(i){return(!_DS.q||i.tool.toLowerCase().includes(_DS.q))&&(!_DS.cat||i.category===_DS.cat);});
  _DS.filtered=d;document.getElementById('dk-sif-count').textContent=d.length+' images';
  var pg=d.slice((_DS.page-1)*_DS.pp,_DS.page*_DS.pp);
  document.getElementById('dk-sif-tbody').innerHTML=pg.length?pg.map(function(i){
    var sb=i.exists?'rgba(34,197,94,.12)':'rgba(239,68,68,.12)';var sc=i.exists?'#22c55e':'#ef4444';
    var sz='—';if(i.exists){var mb=i.size_mb,w=Math.min(100,(mb/5120)*100).toFixed(1),lbl=mb>=1024?(mb/1024).toFixed(1)+' GB':mb+' MB';sz='<div style="display:flex;align-items:center;gap:6px"><div style="width:50px;height:4px;background:#2a2d3e;border-radius:99px;overflow:hidden;flex-shrink:0"><div style="height:100%;width:'+w+'%;background:#0094ff;border-radius:99px"></div></div><span style="font-size:12px;font-family:monospace;color:#e2e8f0 !important;white-space:nowrap">'+lbl+'</span></div>';}
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important">'+i.tool+'</td>'+
      '<td>'+_dkChip(i.category)+'</td>'+
      '<td><span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+sb+';color:'+sc+'">'+(i.exists?'built':'missing')+'</span></td>'+
      '<td>'+sz+'</td></tr>';
  }).join(''):'<tr><td colspan="4" style="text-align:center;color:#6b7280;padding:24px 12px">No SIF images found</td></tr>';
  renderPg('dk-sif',_DS,dkSA);
}

/* ── Plugin Images ── */
function dkPS(v){_DP.q=v.toLowerCase();_DP.page=1;dkPA();}
function dkPM(v){_DP.miss=v;_DP.page=1;dkPA();}
function dkPC(cat){_DP.cat=cat;_DP.page=1;dkPA();_dkBuildSidebar('dk-plug-sidebar',_DP.all,_DP.cat,dkPC);}
function dkPA(){
  var d=_DP.all.filter(function(p){return(!_DP.q||(p.name+' '+p.plugin).toLowerCase().includes(_DP.q))&&(!_DP.cat||p.category===_DP.cat)&&(!_DP.miss||p.local_status==='missing');});
  _DP.filtered=d;document.getElementById('dk-plug-count').textContent=d.length+' plugins';
  var pg=d.slice((_DP.page-1)*_DP.pp,_DP.page*_DP.pp);
  document.getElementById('dk-plug-tbody').innerHTML=pg.length?pg.map(function(p){
    var sb=p.local_status==='present'?'rgba(34,197,94,.12)':'rgba(239,68,68,.12)';var sc=p.local_status==='present'?'#22c55e':'#ef4444';
    var sz='—';if(p.local_status==='present'&&p.size_mb>0)sz=p.size_mb>=1024?(p.size_mb/1024).toFixed(1)+' GB':p.size_mb+' MB';
    return '<tr><td style="font-size:13px;font-weight:600;color:#e2e8f0 !important;white-space:nowrap">'+p.name+'</td>'+
      '<td>'+_dkChip(p.category)+'</td>'+
      '<td class="mono" style="max-width:260px">'+p.image+'</td>'+
      '<td><span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:'+sb+';color:'+sc+'">'+p.local_status+'</span></td>'+
      '<td style="font-size:12px;font-family:monospace;color:#e2e8f0 !important;white-space:nowrap">'+sz+'</td></tr>';
  }).join(''):'<tr><td colspan="5" style="text-align:center;color:#6b7280;padding:24px 12px">No plugins match filters</td></tr>';
  renderPg('dk-plug',_DP,dkPA);
}

/* ── Fetch all three endpoints on load ── */
(function(){
  fetch(_DKU+'/docker/containers').then(function(r){return r.json();}).then(function(d){
    _DC.all=d.containers||[];
    document.getElementById('dk-k-run').textContent=(d.running||0)+'/'+_DC.all.length;
    dkCA();
  }).catch(function(){document.getElementById('dk-cont-tbody').innerHTML='<tr><td colspan="5" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';});

  fetch(_DKU+'/docker/sif-images').then(function(r){return r.json();}).then(function(d){
    _DS.all=d.images||[];
    document.getElementById('dk-k-sif-ok').textContent=d.built||0;
    document.getElementById('dk-k-sif-miss').textContent=d.missing||0;
    document.getElementById('dk-k-gb').textContent=(d.total_gb||0)+' GB';
    _dkBuildSidebar('dk-sif-sidebar',_DS.all,_DS.cat,dkSC);
    dkSA();
  }).catch(function(){document.getElementById('dk-sif-tbody').innerHTML='<tr><td colspan="4" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';});

  fetch(_DKU+'/docker/plugin-images').then(function(r){return r.json();}).then(function(d){
    _DP.all=d.plugins||[];
    document.getElementById('dk-k-plug').textContent=_DP.all.length;
    document.getElementById('dk-k-plug-ok').textContent=d.present||0;
    _dkBuildSidebar('dk-plug-sidebar',_DP.all,_DP.cat,dkPC);
    dkPA();
  }).catch(function(){document.getElementById('dk-plug-tbody').innerHTML='<tr><td colspan="5" style="text-align:center;color:#ef4444;padding:24px 12px">Control center unreachable</td></tr>';});
})();
</script>
"""
