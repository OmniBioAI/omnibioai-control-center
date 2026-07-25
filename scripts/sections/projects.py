from __future__ import annotations

import json
from typing import Dict

from shared.cloc import Totals
from shared.helpers import fmt_int

CAT_MAP = {
    "omnibioai":                    "core",
    "omnibioai-lims":               "core",
    "omnibioai-rag":                "core",
    "omnibioai-workflow-bundles":   "core",
    "omnibioai-studio":             "sdk",
    "omnibioai-sdk":                "sdk",
    "omnibioai-dev-hub":            "sdk",
    "omnibioai-videos":             "sdk",
    "omnibioai-tes":                "exec",
    "omnibioai-tool-runtime":       "exec",
    "omnibioai-tool-images":        "exec",
    "omnibioai-dev-docker":         "exec",
    "omnibioai-toolserver":         "infra",
    "omnibioai-model-registry":     "infra",
    "omnibioai-control-center":     "infra",
    "omnibioai-api-gateway":        "sec",
    "omnibioai-auth":               "sec",
    "omnibioai-policy-engine":      "sec",
    "omnibioai-hpc-policy-engine":  "sec",
    "omnibioai-security-audit":     "sec",
    "omnibioai-security-sdk":       "sec",
    "omnibioai-iam-client":         "sec",
}

CAT_META = {
    "core":  {"label": "core workbench", "color": "#0F6E56", "bg": "#E1F5EE"},
    "sec":   {"label": "security",       "color": "#A32D2D", "bg": "#FCEBEB"},
    "exec":  {"label": "execution",      "color": "#3C3489", "bg": "#EEEDFE"},
    "infra": {"label": "infrastructure", "color": "#854F0B", "bg": "#FAEEDA"},
    "sdk":   {"label": "sdk / clients",  "color": "#185FA5", "bg": "#E6F1FB"},
}

def projects_section_html(project_totals: Dict[str, Totals], grand: Totals) -> str:
    proj = sorted(project_totals.items(), key=lambda kv: kv[1].code, reverse=True)
    total_code = grand.code or 1
    cat_totals: Dict[str, int] = {k: 0 for k in CAT_META}
    for name, t in proj:
        cat = CAT_MAP.get(name, "infra")
        cat_totals[cat] = cat_totals.get(cat, 0) + t.code
    cat_order = sorted(cat_totals, key=lambda k: cat_totals[k], reverse=True)

    donut_data   = json.dumps([cat_totals[k] for k in cat_order])
    donut_colors = json.dumps([CAT_META[k]["color"] for k in cat_order])
    donut_labels = json.dumps([CAT_META[k]["label"] for k in cat_order])

    rows_js = []
    for name, t in proj:
        cat = CAT_MAP.get(name, "infra")
        m = CAT_META[cat]
        pct = round(100 * t.code / total_code, 2)
        short = name.replace("omnibioai-", "").replace("omnibioai_", "").replace("omnibioai", "omnibioai")
        rows_js.append(json.dumps({
            "name": short, "full": name, "cat": cat,
            "catLabel": m["label"], "color": m["color"], "bg": m["bg"],
            "files": t.files, "code": t.code,
            "comment": t.comment, "blank": t.blank, "pct": pct
        }))
    rows_js_str = "[" + ",".join(rows_js) + "]"
    max_code = proj[0][1].code if proj else 1

    legend_html = "".join(
        f'<div class="legend-item"><span class="legend-dot" style="background:{CAT_META[k]["color"]}"></span>'
        f'<span>{CAT_META[k]["label"]}</span>'
        f'<span class="legend-pct">{round(100*cat_totals[k]/total_code,1)}%</span></div>'
        for k in cat_order
    )

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">repositories</div><div class="kpi-val">{len(proj)}</div><div class="kpi-sub">tracked by cloc</div></div>
  <div class="kpi"><div class="kpi-label">code lines</div><div class="kpi-val">{fmt_int(grand.code)}</div><div class="kpi-sub">excl. vendored</div></div>
  <div class="kpi"><div class="kpi-label">largest repo</div><div class="kpi-val">{proj[0][0].replace('omnibioai','omni') if proj else '—'}</div><div class="kpi-sub">{fmt_int(proj[0][1].code)+' LOC' if proj else ''}</div></div>
  <div class="kpi"><div class="kpi-label">categories</div><div class="kpi-val">5</div><div class="kpi-sub">core · sec · exec · infra · sdk</div></div>
</div>

<div class="section">
  <div class="sec-title">share by project</div>
  <div class="sec-sub">code lines · categorized by function</div>
  <div style="display:grid;grid-template-columns:180px 1fr;gap:16px">
    <div style="display:flex;flex-direction:column;align-items:center">
      <div style="position:relative;width:140px;height:140px;margin:0 auto 12px">
        <canvas id="proj-donut" width="140" height="140"></canvas>
        <div class="donut-center">
          <div class="donut-center-val">{fmt_int(grand.code)}</div>
          <div class="donut-center-lbl">total LOC</div>
        </div>
      </div>
      {legend_html}
    </div>
    <div id="proj-bars" style="display:flex;flex-direction:column;justify-content:center"></div>
  </div>
</div>

<div class="section">
  <div class="sec-title">per-project breakdown</div>
  <div class="sec-sub">all repositories · sorted by code lines · click headers to sort</div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search..." oninput="projFilter(this.value)" id="proj-search">
    <select class="filter-sel" onchange="projCatFilter(this.value)">
      <option value="">all categories</option>
      {"".join(f'<option value="{k}">{CAT_META[k]["label"]}</option>' for k in CAT_META)}
    </select>
    <span class="result-count" id="proj-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="projPerPage(this.value)"><option value="10" selected>10</option><option value="20">20</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="projSort('name')">repository</th>
        <th>category</th>
        <th class="r" onclick="projSort('files')">files</th>
        <th class="r" onclick="projSort('code')">code</th>
        <th class="r" onclick="projSort('comment')">comment</th>
        <th class="r" onclick="projSort('blank')">blank</th>
        <th class="r" onclick="projSort('pct')">share</th>
      </tr></thead>
      <tbody id="proj-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="proj-pg"></div>
</div>
</div>

<script>
var _pd={rows_js_str},_ps={{data:[],filtered:[],page:1,pp:10,sort:'code',dir:-1,search:'',cat:''}};
var _pm={max_code};
(function(){{
  _ps.data=_pd.slice();
  new Chart(document.getElementById('proj-donut'),{{
    type:'doughnut',
    data:{{labels:{donut_labels},datasets:[{{data:{donut_data},backgroundColor:{donut_colors},borderWidth:2,borderColor:'#1a1d2e',hoverOffset:4}}]}},
    options:{{responsive:false,cutout:'68%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+(c.raw/1000).toFixed(0)+'k LOC ('+(c.raw/{total_code}*100).toFixed(1)+'%)';}}}}}}}}}}
  }});
  var bEl=document.getElementById('proj-bars');
  _pd.slice(0,16).forEach(function(r){{
    var pct=Math.round(r.code/_pm*100);
    var loc=r.code>=1000?(r.code/1000).toFixed(0)+'k':r.code;
    var d=document.createElement('div');d.className='bar-row';
    d.innerHTML='<span class="bar-label" style="width:110px" title="'+r.full+'">'+r.name+'</span>'+
      '<div class="bar-track" style="height:16px"><div class="bar-fill" style="width:'+pct+'%;background:'+r.color+'22"></div>'+
      '<span class="bar-val" style="color:'+r.color+'">'+loc+'</span></div>'+
      '<span class="badge" style="background:'+r.bg+';color:'+r.color+';width:64px;text-align:center">'+r.catLabel.split(' ')[0]+'</span>';
    bEl.appendChild(d);
  }});
  projApply();
}})();
function projFilter(v){{_ps.search=v.toLowerCase();_ps.page=1;projApply();}}
function projCatFilter(v){{_ps.cat=v;_ps.page=1;projApply();}}
function projPerPage(v){{_ps.pp=parseInt(v);_ps.page=1;projApply();}}
function projSort(col){{if(_ps.sort===col){{_ps.dir*=-1;}}else{{_ps.sort=col;_ps.dir=col==='name'?1:-1;}} _ps.page=1;projApply();}}
function projApply(){{
  var d=_ps.data.slice();
  if(_ps.search)d=d.filter(function(r){{return (r.name+r.catLabel).toLowerCase().includes(_ps.search);}});
  if(_ps.cat)d=d.filter(function(r){{return r.cat===_ps.cat;}});
  var col=_ps.sort;
  d.sort(function(a,b){{
    var av=typeof a[col]==='number'?a[col]:(a[col]||'').toLowerCase();
    var bv=typeof b[col]==='number'?b[col]:(b[col]||'').toLowerCase();
    return av<bv?_ps.dir:av>bv?-_ps.dir:0;
  }});
  _ps.filtered=d;
  document.getElementById('proj-count').textContent=d.length+' items';
  var start=(_ps.page-1)*_ps.pp,page=d.slice(start,start+_ps.pp);
  var tb=document.getElementById('proj-tbody');tb.innerHTML='';
  page.forEach(function(r){{
    var tr=document.createElement('tr');
    tr.innerHTML='<td style="font-weight:600;font-size:12px">'+r.name+'</td>'+
      '<td><span class="badge" style="background:'+r.bg+';color:'+r.color+'">'+r.catLabel+'</span></td>'+
      '<td class="r">'+r.files.toLocaleString()+'</td>'+
      '<td class="r" style="font-weight:600">'+r.code.toLocaleString()+'</td>'+
      '<td class="r">'+r.comment.toLocaleString()+'</td>'+
      '<td class="r">'+r.blank.toLocaleString()+'</td>'+
      '<td class="r">'+r.pct.toFixed(1)+'%<span class="share-bar"><span class="share-fill" style="width:'+Math.min(100,r.pct*2).toFixed(1)+'%;background:'+r.color+'"></span></span></td>';
    tb.appendChild(tr);
  }});
  renderPg('proj',_ps,projApply);
}}
</script>
"""
