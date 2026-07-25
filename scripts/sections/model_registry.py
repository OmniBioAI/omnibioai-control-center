from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from shared.helpers import fmt_int

def _classify_data_source(version_name: str, meta: Dict[str, Any],
                          metrics: Dict[str, Any]) -> Tuple[str, str]:
    """
    Returns (classification, confidence) where classification is one of
    "real" / "synthetic" / "unknown", and confidence is "explicit"
    (meta.json has a real data_source field -- trust this) or "inferred"
    (guessed from naming patterns -- show as heuristic, not fact).
    """
    explicit = meta.get("data_source")
    if explicit in ("real", "synthetic"):
        return explicit, "explicit"

    vname = (version_name or "").lower()
    if "real" in vname:
        return "real", "inferred"
    if vname.endswith("_test") or "_test_" in vname or vname == "test":
        return "synthetic", "inferred"

    if metrics.get("seed") == 42 or metrics.get("random_state") == 42:
        return "synthetic", "inferred"
    n_train = metrics.get("n_train") or metrics.get("n_train_cells")
    if isinstance(n_train, (int, float)) and n_train < 100:
        return "synthetic", "inferred"
    if meta.get("git_commit") == "abc123":
        return "synthetic", "inferred"

    return "unknown", "inferred"

def _scan_model_registry(registry_root: Path) -> List[Dict[str, Any]]:
    """
    Walks registry_root/tasks/<task>/models/<model_name>/versions/<version>/
    reading metrics.json and model_meta.json for each.

    Some version directories (verified: real-data training runs under
    admet_properties/admet_mlp) are written mode 700 owned by the
    container's training process -- reading them succeeds when this script
    runs as root inside the control-center container (confirmed: that's
    the only context it actually runs in, per _run_report_job), but would
    PermissionError on a bare-host run as an unprivileged user. Each
    version is scanned independently so one unreadable directory doesn't
    take down the whole registry scan.
    """
    rows: List[Dict[str, Any]] = []
    tasks_dir = registry_root / "tasks"
    if not tasks_dir.is_dir():
        return rows
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        models_dir = task_dir / "models"
        if not models_dir.is_dir():
            continue
        for model_dir in sorted(models_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            versions_dir = model_dir / "versions"
            if not versions_dir.is_dir():
                continue
            for version_dir in sorted(versions_dir.iterdir()):
                if not version_dir.is_dir():
                    continue
                metrics: Dict[str, Any] = {}
                meta: Dict[str, Any] = {}
                mtime = 0.0
                try:
                    mtime = version_dir.stat().st_mtime
                    mf = version_dir / "metrics.json"
                    mmf = version_dir / "model_meta.json"
                    if mf.exists():
                        metrics = json.loads(mf.read_text(encoding="utf-8"))
                    if mmf.exists():
                        meta = json.loads(mmf.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                cls, confidence = _classify_data_source(version_dir.name, meta, metrics)
                metric_display = None
                for k in ("test_accuracy", "val_accuracy", "accuracy",
                          "test_mae", "val_mae", "val_mae_pki", "mae",
                          "auroc", "test_auroc"):
                    if k in metrics:
                        metric_display = f"{k}={metrics[k]}"
                        break
                rows.append({
                    "task": task_dir.name,
                    "model": model_dir.name,
                    "version": version_dir.name,
                    "data_source": cls,
                    "confidence": confidence,
                    "metric": metric_display or "—",
                    "mtime": mtime,
                })
    return rows

def model_registry_section_html(registry_root: Path) -> str:
    rows = _scan_model_registry(registry_root)

    total_versions = len(rows)
    real_rows = [r for r in rows if r["data_source"] == "real"]
    synth_rows = [r for r in rows if r["data_source"] == "synthetic"]
    unknown_rows = [r for r in rows if r["data_source"] == "unknown"]

    tasks_with_real = len(set(r["task"] for r in real_rows))
    total_tasks = len(set(r["task"] for r in rows))

    inferred_count = sum(1 for r in rows if r["confidence"] == "inferred")

    rows_js = [json.dumps(r) for r in sorted(rows, key=lambda r: r["mtime"], reverse=True)]
    rows_js_str = "[" + ",".join(rows_js) + "]"

    return f"""
<div class="tab-section">
<div style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px">
  data_source classification: explicit field if present in model_meta.json, otherwise
  <span style="color:#854F0B;font-weight:600">inferred</span> from naming/metric patterns —
  {inferred_count}/{total_versions} versions are inferred, not confirmed.
</div>

<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">tasks</div><div class="kpi-val">{total_tasks}</div><div class="kpi-sub">{tasks_with_real} with ≥1 real version</div></div>
  <div class="kpi"><div class="kpi-label">total versions</div><div class="kpi-val">{fmt_int(total_versions)}</div><div class="kpi-sub">all registered</div></div>
  <div class="kpi"><div class="kpi-label">real</div><div class="kpi-val" style="color:#3B6D11">{fmt_int(len(real_rows))}</div><div class="kpi-sub">confirmed/inferred real data</div></div>
  <div class="kpi"><div class="kpi-label">synthetic</div><div class="kpi-val" style="color:#A32D2D">{fmt_int(len(synth_rows))}</div><div class="kpi-sub">dummy/placeholder data</div></div>
  <div class="kpi"><div class="kpi-label">unknown</div><div class="kpi-val" style="color:#854F0B">{fmt_int(len(unknown_rows))}</div><div class="kpi-sub">unclassified</div></div>
</div>

<div class="section">
  <div class="sec-title">all model versions</div>
  <div class="sec-sub">sorted by most recent · click headers to sort</div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search task/model/version..." oninput="mrFilter(this.value)">
    <select class="filter-sel" onchange="mrSourceFilter(this.value)">
      <option value="">all data sources</option>
      <option value="real">real</option>
      <option value="synthetic">synthetic</option>
      <option value="unknown">unknown</option>
    </select>
    <span class="result-count" id="mr-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="mrPerPage(this.value)"><option value="15" selected>15</option><option value="30">30</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="mrSort('task')">task</th>
        <th onclick="mrSort('model')">model</th>
        <th onclick="mrSort('version')">version</th>
        <th onclick="mrSort('data_source')">data source</th>
        <th onclick="mrSort('metric')">metric</th>
      </tr></thead>
      <tbody id="mr-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="mr-pg"></div>
</div>
</div>

<script>
var _mrd={rows_js_str},_mrs={{data:[],filtered:[],page:1,pp:15,sort:'mtime',dir:-1,search:'',source:''}};
var _mrColors={{real:'#3B6D11',synthetic:'#A32D2D',unknown:'#854F0B'}};
var _mrBg={{real:'#EAF3DE',synthetic:'#FCEBEB',unknown:'#FAEEDA'}};
(function(){{_mrs.data=_mrd.slice();mrApply();}})();
function mrFilter(v){{_mrs.search=v.toLowerCase();_mrs.page=1;mrApply();}}
function mrSourceFilter(v){{_mrs.source=v;_mrs.page=1;mrApply();}}
function mrPerPage(v){{_mrs.pp=parseInt(v);_mrs.page=1;mrApply();}}
function mrSort(col){{if(_mrs.sort===col)_mrs.dir*=-1;else{{_mrs.sort=col;_mrs.dir=1;}} _mrs.page=1;mrApply();}}
function mrApply(){{
  var d=_mrs.data.slice();
  if(_mrs.search)d=d.filter(function(r){{return (r.task+r.model+r.version).toLowerCase().includes(_mrs.search);}});
  if(_mrs.source)d=d.filter(function(r){{return r.data_source===_mrs.source;}});
  var col=_mrs.sort;
  d.sort(function(a,b){{var av=(a[col]||'').toString().toLowerCase();var bv=(b[col]||'').toString().toLowerCase();return av<bv?_mrs.dir:av>bv?-_mrs.dir:0;}});
  _mrs.filtered=d;
  document.getElementById('mr-count').textContent=d.length+' items';
  var start=(_mrs.page-1)*_mrs.pp,page=d.slice(start,start+_mrs.pp);
  var tb=document.getElementById('mr-tbody');tb.innerHTML='';
  page.forEach(function(r){{
    var tr=document.createElement('tr');
    var confBadge=r.confidence==='inferred'?' <span style="font-size:9px;color:#854F0B;opacity:.8">(inferred)</span>':'';
    tr.innerHTML='<td style="font-size:12px">'+r.task+'</td>'+
      '<td style="font-size:12px">'+r.model+'</td>'+
      '<td class="mono">'+r.version+'</td>'+
      '<td><span class="badge" style="background:'+_mrBg[r.data_source]+';color:'+_mrColors[r.data_source]+'">'+r.data_source+'</span>'+confBadge+'</td>'+
      '<td style="font-size:12px" class="mono">'+r.metric+'</td>';
    tb.appendChild(tr);
  }});
  renderPg('mr',_mrs,mrApply);
}}
</script>
"""
