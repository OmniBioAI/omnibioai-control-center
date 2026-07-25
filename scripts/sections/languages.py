from __future__ import annotations

import json
from typing import Dict

from shared.cloc import Totals
from shared.helpers import fmt_int

LANG_TYPE = {
    "Python":"backend","Jupyter Notebook":"backend","SQL":"backend",
    "Mojo":"backend","Metal":"backend","C++":"backend","C/C++ Header":"backend",
    "HTML":"frontend","TypeScript":"frontend","JavaScript":"frontend","CSS":"frontend",
    "Markdown":"docs","reStructuredText":"docs",
    "YAML":"config","TOML":"config","INI":"config","Properties":"config","JSON":"config",
    "Dockerfile":"infra","Bourne Shell":"infra","Bourne Again Shell":"infra",
    "Source Shell":"infra","Source Again Shell":"infra","make":"infra",
    "Windows Module Definition":"infra",
}

LANG_TYPE_META = {
    "backend":  {"label":"backend",  "color":"#0F6E56","bg":"#E1F5EE","icon":"🐍"},
    "frontend": {"label":"frontend", "color":"#185FA5","bg":"#E6F1FB","icon":"🌐"},
    "docs":     {"label":"docs",     "color":"#444441","bg":"#F1EFE8","icon":"📄"},
    "config":   {"label":"config",   "color":"#854F0B","bg":"#FAEEDA","icon":"⚙️"},
    "infra":    {"label":"infra",    "color":"#3C3489","bg":"#EEEDFE","icon":"🔧"},
}

def languages_section_html(language_totals: Dict[str, Totals], grand: Totals) -> str:
    langs = sorted(language_totals.items(), key=lambda kv: kv[1].code, reverse=True)
    total_code = grand.code or 1
    type_totals: Dict[str, int] = {k: 0 for k in LANG_TYPE_META}
    for name, t in langs:
        lt = LANG_TYPE.get(name, "infra")
        type_totals[lt] = type_totals.get(lt, 0) + t.code
    type_order = sorted(type_totals, key=lambda k: type_totals[k], reverse=True)

    donut_data   = json.dumps([type_totals[k] for k in type_order])
    donut_colors = json.dumps([LANG_TYPE_META[k]["color"] for k in type_order])
    donut_labels = json.dumps([LANG_TYPE_META[k]["label"] for k in type_order])

    rows_js = []
    for name, t in langs:
        lt = LANG_TYPE.get(name, "infra")
        m  = LANG_TYPE_META[lt]
        pct = round(100 * t.code / total_code, 2)
        rows_js.append(json.dumps({
            "name": name, "type": lt, "typeLabel": m["label"],
            "color": m["color"], "bg": m["bg"],
            "files": t.files, "code": t.code,
            "comment": t.comment, "blank": t.blank, "pct": pct
        }))
    rows_js_str = "[" + ",".join(rows_js) + "]"
    max_code = langs[0][1].code if langs else 1

    type_cards = "".join(
        f'<div style="background:var(--color-bg-surface);border-radius:8px;padding:10px 12px;display:flex;align-items:center;gap:10px">'
        f'<div style="width:32px;height:32px;border-radius:8px;background:{LANG_TYPE_META[k]["bg"]};display:flex;align-items:center;justify-content:center;font-size:16px">{LANG_TYPE_META[k]["icon"]}</div>'
        f'<div style="flex:1"><div style="font-size:12px;font-weight:600;color:var(--color-text)">{LANG_TYPE_META[k]["label"]}</div>'
        f'<div style="font-size:11px;color:var(--color-text-muted)">{fmt_int(type_totals[k])} LOC</div></div>'
        f'<div style="font-size:14px;font-weight:700;color:{LANG_TYPE_META[k]["color"]}">{round(100*type_totals[k]/total_code,1)}%</div>'
        f'</div>'
        for k in type_order
    )

    legend_html = "".join(
        f'<div class="legend-item"><span class="legend-dot" style="background:{LANG_TYPE_META[k]["color"]}"></span>'
        f'<span>{LANG_TYPE_META[k]["label"]}</span>'
        f'<span class="legend-pct">{round(100*type_totals[k]/total_code,1)}%</span></div>'
        for k in type_order
    )

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">languages</div><div class="kpi-val">{len(langs)}</div><div class="kpi-sub">detected by cloc</div></div>
  <div class="kpi"><div class="kpi-label">dominant</div><div class="kpi-val">{langs[0][0] if langs else '—'}</div><div class="kpi-sub">{round(100*langs[0][1].code/total_code,1) if langs else 0}% of codebase</div></div>
  <div class="kpi"><div class="kpi-label">backend</div><div class="kpi-val">{round(100*type_totals.get('backend',0)/total_code,1)}%</div><div class="kpi-sub">Python + SQL + notebooks</div></div>
  <div class="kpi"><div class="kpi-label">frontend</div><div class="kpi-val">{round(100*type_totals.get('frontend',0)/total_code,1)}%</div><div class="kpi-sub">HTML + CSS + TS + JS</div></div>
</div>

<div class="section">
  <div class="sec-title">language type distribution</div>
  <div class="sec-sub">grouped by role in the stack</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:4px">{type_cards}</div>
</div>

<div class="section">
  <div class="sec-title">lines of code by language</div>
  <div class="sec-sub">top languages · color = type</div>
  <div style="display:grid;grid-template-columns:180px 1fr;gap:16px">
    <div style="display:flex;flex-direction:column;align-items:center">
      <div style="position:relative;width:140px;height:140px;margin:0 auto 12px">
        <canvas id="lang-donut" width="140" height="140"></canvas>
        <div class="donut-center">
          <div class="donut-center-val">{len(langs)}</div>
          <div class="donut-center-lbl">languages</div>
        </div>
      </div>
      {legend_html}
    </div>
    <div id="lang-bars" style="display:flex;flex-direction:column;justify-content:center"></div>
  </div>
</div>

<div class="section">
  <div class="sec-title">all languages</div>
  <div class="sec-sub">complete breakdown · click headers to sort</div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search language..." oninput="langFilter(this.value)">
    <select class="filter-sel" onchange="langTypeFilter(this.value)">
      <option value="">all types</option>
      {"".join(f'<option value="{k}">{LANG_TYPE_META[k]["label"]}</option>' for k in LANG_TYPE_META)}
    </select>
    <span class="result-count" id="lang-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="langPerPage(this.value)"><option value="10" selected>10</option><option value="20">20</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="langSort('name')">language</th>
        <th>type</th>
        <th class="r" onclick="langSort('files')">files</th>
        <th class="r" onclick="langSort('code')">code</th>
        <th class="r" onclick="langSort('comment')">comment</th>
        <th class="r" onclick="langSort('blank')">blank</th>
        <th class="r" onclick="langSort('pct')">share</th>
      </tr></thead>
      <tbody id="lang-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="lang-pg"></div>
</div>
</div>

<script>
var _ld={rows_js_str},_ls={{data:[],filtered:[],page:1,pp:10,sort:'code',dir:-1,search:'',type:''}};
var _lm={max_code};
(function(){{
  _ls.data=_ld.slice();
  new Chart(document.getElementById('lang-donut'),{{
    type:'doughnut',
    data:{{labels:{donut_labels},datasets:[{{data:{donut_data},backgroundColor:{donut_colors},borderWidth:2,borderColor:'#1a1d2e',hoverOffset:4}}]}},
    options:{{responsive:false,cutout:'68%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+(c.raw/1000).toFixed(0)+'k LOC ('+(c.raw/{total_code}*100).toFixed(1)+'%)';}}}}}}}}}}
  }});
  var bEl=document.getElementById('lang-bars');
  _ld.slice(0,18).forEach(function(r){{
    var pct=Math.round(r.code/_lm*100);
    var loc=r.code>=1000?(r.code/1000).toFixed(0)+'k':r.code;
    var d=document.createElement('div');d.className='bar-row';
    d.innerHTML='<span class="bar-label" style="width:110px">'+r.name+'</span>'+
      '<div class="bar-track" style="height:14px"><div class="bar-fill" style="width:'+pct+'%;background:'+r.color+'22"></div>'+
      '<span class="bar-val" style="color:'+r.color+'">'+loc+'</span></div>'+
      '<span class="badge" style="background:'+r.bg+';color:'+r.color+';width:60px;text-align:center">'+r.typeLabel+'</span>';
    bEl.appendChild(d);
  }});
  langApply();
}})();
function langFilter(v){{_ls.search=v.toLowerCase();_ls.page=1;langApply();}}
function langTypeFilter(v){{_ls.type=v;_ls.page=1;langApply();}}
function langPerPage(v){{_ls.pp=parseInt(v);_ls.page=1;langApply();}}
function langSort(col){{if(_ls.sort===col)_ls.dir*=-1;else{{_ls.sort=col;_ls.dir=col==='name'?1:-1;}} _ls.page=1;langApply();}}
function langApply(){{
  var d=_ls.data.slice();
  if(_ls.search)d=d.filter(function(r){{return r.name.toLowerCase().includes(_ls.search);}});
  if(_ls.type)d=d.filter(function(r){{return r.type===_ls.type;}});
  var col=_ls.sort;
  d.sort(function(a,b){{var av=typeof a[col]==='number'?a[col]:(a[col]||'').toLowerCase();var bv=typeof b[col]==='number'?b[col]:(b[col]||'').toLowerCase();return av<bv?_ls.dir:av>bv?-_ls.dir:0;}});
  _ls.filtered=d;
  document.getElementById('lang-count').textContent=d.length+' items';
  var start=(_ls.page-1)*_ls.pp,page=d.slice(start,start+_ls.pp);
  var tb=document.getElementById('lang-tbody');tb.innerHTML='';
  page.forEach(function(r){{
    var tr=document.createElement('tr');
    tr.innerHTML='<td style="font-weight:600;font-size:12px">'+r.name+'</td>'+
      '<td><span class="badge" style="background:'+r.bg+';color:'+r.color+'">'+r.typeLabel+'</span></td>'+
      '<td class="r">'+r.files.toLocaleString()+'</td>'+
      '<td class="r" style="font-weight:600">'+r.code.toLocaleString()+'</td>'+
      '<td class="r">'+r.comment.toLocaleString()+'</td>'+
      '<td class="r">'+r.blank.toLocaleString()+'</td>'+
      '<td class="r">'+r.pct.toFixed(1)+'%<span class="share-bar"><span class="share-fill" style="width:'+Math.min(100,r.pct*3).toFixed(1)+'%;background:'+r.color+'"></span></span></td>';
    tb.appendChild(tr);
  }});
  renderPg('lang',_ls,langApply);
}}
</script>
"""
