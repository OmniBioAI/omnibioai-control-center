from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from shared.helpers import _read_text_if_exists

def _cov_source_args(cwd: Path) -> List[str]:
    text = _read_text_if_exists(cwd / "pyproject.toml")
    if text:
        m = re.search(r'\[tool\.coverage\.run\](.*?)(?=\n\[|\Z)', text, re.DOTALL)
        if m:
            sm = re.search(r'^source\s*=\s*\[([^\]]*)\]', m.group(1), re.MULTILINE)
            if sm:
                sources = re.findall(r'["\']([^"\']+)["\']', sm.group(1))
                if sources: return [f"--cov={s}" for s in sources]
    text = _read_text_if_exists(cwd / ".coveragerc")
    if text:
        m = re.search(r'\[run\](.*?)(?=\n\[|\Z)', text, re.DOTALL)
        if m:
            sm = re.search(r'^source\s*=\s*(.+?)$', m.group(1), re.MULTILINE)
            if sm:
                sources = [s.strip() for s in sm.group(1).split(',') if s.strip()]
                if sources: return [f"--cov={s}" for s in sources]
    if (cwd / "src").is_dir(): return ["--cov=src"]
    return ["--cov=."]

def _coverage_cmd(cov_args, noconftest=False):
    cmd = [sys.executable, "-m", "pytest", *cov_args,
           "--cov-report=term-missing", "--cov-report=json",
           "--tb=no", "-q", "-p", "no:cacheprovider",
           "--continue-on-collection-errors", "--ignore=node_modules"]
    if noconftest: cmd.append("--noconftest")
    return cmd

def _pytest_available() -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception: return False

def _has_pytest_project(repo: Path) -> bool:
    return any((repo / p).exists() for p in
               ["pyproject.toml", "pytest.ini", "tests",
                "backend/pyproject.toml"])

def _pytest_cwd(repo: Path) -> Path:
    return repo / "backend" if (repo / "backend" / "pyproject.toml").exists() else repo

def _subprocess_env(cwd: Path) -> dict:
    import os; env = os.environ.copy()
    for cfg in [cwd / "pytest.ini", cwd / "setup.cfg",
                cwd.parent / "pytest.ini", cwd.parent / "setup.cfg"]:
        if not cfg.exists(): continue
        text = _read_text_if_exists(cfg)
        m = re.search(r"DJANGO_SETTINGS_MODULE\s*[=:]\s*(\S+)", text)
        if m: env.setdefault("DJANGO_SETTINGS_MODULE", m.group(1)); break
    return env

def _extract_total_line(output: str) -> Optional[str]:
    for line in output.splitlines():
        if re.match(r"^\s*TOTAL\b", line): return line.strip()
    return None

def _parse_total_line(total_line: str) -> Dict[str, Any]:
    parts = re.split(r"\s+", total_line.strip())
    nums = parts[1:]
    if len(nums) == 3:
        stmts, miss, cover = nums
        return {"statements": int(stmts), "missed": int(miss),
                "branches": None, "partial_branches": None,
                "coverage_pct": float(cover.rstrip("%"))}
    if len(nums) == 5:
        stmts, miss, branches, bpart, cover = nums
        return {"statements": int(stmts), "missed": int(miss),
                "branches": int(branches), "partial_branches": int(bpart),
                "coverage_pct": float(cover.rstrip("%"))}
    raise ValueError(f"Unexpected TOTAL format: {total_line}")

def _classify_coverage_band(pct: Optional[float]) -> str:
    if pct is None: return "No data"
    if pct >= 95:   return "Excellent (>=95%)"
    if pct >= 85:   return "Good (85-94.99%)"
    return "Needs attention (<85%)"

def _stderr_tail(stderr: str, n: int = 10) -> Optional[str]:
    stderr = stderr.strip()
    return "\n".join(stderr.splitlines()[-n:]) if stderr else None

def _classify_status(rc, total_line, coverage_pct, fail_under, stdout, stderr) -> str:
    if total_line is None: return "no_total_found"
    if rc == 0: return "ok"
    combined = f"{stdout}\n{stderr}".lower()
    cov_fail  = ("required test coverage" in combined or "fail-under" in combined
                 or (fail_under is not None and coverage_pct is not None
                     and coverage_pct < fail_under))
    test_fail = (" failed" in combined or "interrupted" in combined
                 or re.search(r"\b\d+ failed\b", combined) is not None)
    if cov_fail and test_fail: return "test_and_coverage_failure"
    if cov_fail:               return "coverage_threshold_failure"
    if test_fail:              return "test_failure"
    return "collection_errors"

def _extract_fail_under(repo: Path) -> Optional[float]:
    text = (_read_text_if_exists(repo / "pyproject.toml")
            + "\n" + _read_text_if_exists(repo / "pytest.ini"))
    for pat in [r"--cov-fail-under[=\s]+([0-9]+(?:\.[0-9]+)?)",
                r"fail[_-]under\s*=\s*([0-9]+(?:\.[0-9]+)?)"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m: return float(m.group(1))
    return None

def _parse_coverage_json(cwd: Path) -> Optional[Dict[str, Any]]:
    cov_file = cwd / "coverage.json"
    if not cov_file.exists(): return None
    try:
        data = json.loads(cov_file.read_text(encoding="utf-8"))
        totals = data.get("totals", {})
        pct    = totals.get("percent_covered")
        stmts  = totals.get("num_statements")
        missed = totals.get("missing_lines")
        if pct is None or stmts is None: return None
        return {"statements": int(stmts), "missed": int(missed or 0),
                "branches": totals.get("num_partial_branches"),
                "partial_branches": None,
                "coverage_pct": round(float(pct), 2)}
    except Exception: return None

def _load_precomputed(repo: Path, precomputed_dir: Path) -> Optional[Dict[str, Any]]:
    f = precomputed_dir / f"{repo.name}.json"
    if not f.exists(): return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict): return None
        if "totals" in data and "coverage_pct" not in data:
            t = data["totals"]
            return {"coverage_pct": t.get("percent_covered"),
                    "statements": t.get("num_statements"),
                    "missed": t.get("missing_lines"),
                    "branches": t.get("num_branches"),
                    "partial_branches": t.get("num_partial_branches"),
                    "returncode": 0, "total_line": None, "stderr_tail": None}
        return data
    except Exception: return None

def collect_coverage(target_paths: List[Path],
                     precomputed_dir: Optional[Path] = None) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    pytest_ok = _pytest_available()
    for repo in target_paths:
        row: Dict[str, Any] = {
            "repo": repo.name, "path": str(repo), "status": "ok",
            "returncode": None, "statements": None, "missed": None,
            "branches": None, "partial_branches": None,
            "coverage_pct": None, "coverage_band": "No data",
            "fail_under": _extract_fail_under(repo),
            "total_line": None, "stderr_tail": None,
        }
        if not repo.exists():
            row["status"] = "missing_path"; rows.append(row); continue
        if precomputed_dir and precomputed_dir.is_dir():
            precomp = _load_precomputed(repo, precomputed_dir)
            if precomp is not None:
                for k in ("returncode", "statements", "missed", "branches",
                          "partial_branches", "coverage_pct", "total_line",
                          "stderr_tail"):
                    if k in precomp: row[k] = precomp[k]
                if row["coverage_pct"] is not None:
                    row["coverage_band"] = _classify_coverage_band(row["coverage_pct"])
                    row["status"] = _classify_status(
                        row.get("returncode"), row.get("total_line"),
                        row["coverage_pct"], row["fail_under"],
                        precomp.get("stdout_tail") or "",
                        precomp.get("stderr_tail") or "")
                else:
                    row["status"] = precomp.get("status", "no_total_found")
                rows.append(row); continue
        if not pytest_ok:
            row["status"] = "skipped_no_pytest"; rows.append(row); continue
        if not _has_pytest_project(repo):
            row["status"] = "skipped_no_pytest_project"; rows.append(row); continue
        try:
            cwd = _pytest_cwd(repo)
            cov_args = _cov_source_args(cwd)
            env = _subprocess_env(cwd)
            def _run(noconftest):
                p = subprocess.run(
                    _coverage_cmd(cov_args, noconftest),
                    cwd=str(cwd), env=env,
                    capture_output=True, text=True, timeout=300)
                t = _extract_total_line(p.stdout)
                c = None if t else _parse_coverage_json(cwd)
                return p, t, c
            proc, total_line, cov_data = _run(False)
            if total_line is None and cov_data is None:
                ce = ("ImportError while loading conftest" in proc.stderr
                      or "ERROR while loading conftest" in proc.stderr)
                if ce:
                    proc, total_line, cov_data = _run(True)
            row["returncode"] = proc.returncode
            if not row.get("stderr_tail"): row["stderr_tail"] = _stderr_tail(proc.stderr)
            if total_line and total_line != "json":
                row["total_line"] = total_line; row.update(_parse_total_line(total_line))
            elif cov_data:
                row["total_line"] = "json"; row.update(cov_data)
            if row["coverage_pct"] is not None:
                row["coverage_band"] = _classify_coverage_band(row["coverage_pct"])
                row["status"] = _classify_status(
                    proc.returncode, row["total_line"], row["coverage_pct"],
                    row["fail_under"], proc.stdout, proc.stderr)
            else:
                row["status"] = "no_total_found"
        except Exception as e:
            row["status"] = f"error: {e}"
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["coverage_pct", "repo"], ascending=[False, True],
                            na_position="last").reset_index(drop=True)
    return df

def _cov_color(pct: Optional[float]) -> str:
    if pct is None: return "#888780"
    return "#3B6D11" if pct >= 95 else ("#854F0B" if pct >= 85 else "#A32D2D")

def _cov_bg(pct: Optional[float]) -> str:
    if pct is None: return "#F1EFE8"
    return "#EAF3DE" if pct >= 95 else ("#FAEEDA" if pct >= 85 else "#FCEBEB")

def coverage_section_html(df: pd.DataFrame, timestamp: str) -> str:
    valid   = df[df["coverage_pct"].notna()].copy()
    covered = len(valid)
    avg_cov = float(valid["coverage_pct"].mean()) if covered else 0.0
    excellent = int((valid["coverage_pct"] >= 95).sum()) if covered else 0
    good_cnt  = int(valid["coverage_pct"].between(85, 95, inclusive="left").sum()) if covered else 0
    below_85  = int((valid["coverage_pct"] < 85).sum()) if covered else 0
    no_data   = len(df) - covered

    rows_js = []
    for _, row in df.iterrows():
        pct = row.get("coverage_pct")
        rows_js.append(json.dumps({
            "repo":      str(row.get("repo", "")),
            "status":    str(row.get("status", "")),
            "pct":       round(float(pct), 2) if pct is not None and pct == pct else None,
            "stmts":     int(row["statements"]) if row.get("statements") == row.get("statements") and row.get("statements") is not None else None,
            "missed":    int(row["missed"])     if row.get("missed")     == row.get("missed")     and row.get("missed")     is not None else None,
            "branches":  int(row["branches"])   if row.get("branches")   == row.get("branches")   and row.get("branches")   is not None else None,
            "failUnder": float(row["fail_under"]) if row.get("fail_under") == row.get("fail_under") and row.get("fail_under") is not None else None,
            "color":     _cov_color(pct if pct == pct else None),
            "bg":        _cov_bg(pct if pct == pct else None),
        }))
    rows_js_str = "[" + ",".join(rows_js) + "]"

    return f"""
<div class="tab-section">
<div style="font-size:12px;color:var(--color-text-muted);margin-bottom:12px">best-effort pytest collection · {timestamp}</div>
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">repos scanned</div><div class="kpi-val">{len(df)}</div><div class="kpi-sub">full ecosystem</div></div>
  <div class="kpi"><div class="kpi-label">with data</div><div class="kpi-val">{covered}</div><div class="kpi-sub">coverage collected</div></div>
  <div class="kpi"><div class="kpi-label">average</div><div class="kpi-val" style="color:#3B6D11">{avg_cov:.1f}%</div><div class="kpi-sub">across {covered} repos</div></div>
  <div class="kpi"><div class="kpi-label">excellent ≥95%</div><div class="kpi-val" style="color:#3B6D11">{excellent}</div><div class="kpi-sub">repos</div></div>
  <div class="kpi"><div class="kpi-label">needs attention</div><div class="kpi-val" style="color:#A32D2D">{below_85}</div><div class="kpi-sub">below 85%</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 200px;gap:12px;margin-bottom:12px">
  <div class="section">
    <div class="sec-title">coverage by repository</div>
    <div class="sec-sub">sorted high to low</div>
    <div style="position:relative;height:260px"><canvas id="cov-bar"></canvas></div>
  </div>
  <div class="section" style="display:flex;flex-direction:column">
    <div class="sec-title">band distribution</div>
    <div class="sec-sub">repos per band</div>
    <div style="position:relative;width:120px;height:120px;margin:0 auto 12px">
      <canvas id="cov-donut" width="120" height="120"></canvas>
      <div class="donut-center">
        <div class="donut-center-val">{covered}</div>
        <div class="donut-center-lbl">repos</div>
      </div>
    </div>
    <div>
      {"".join(f'<div class="legend-item"><span class="legend-dot" style="background:{c}"></span><span>{lbl}</span><span class="legend-pct">{cnt}</span></div>' for c,lbl,cnt in [('#3B6D11','≥95%',excellent),('#854F0B','85–94%',good_cnt),('#A32D2D','<85%',below_85),('#888780','no data',no_data)])}
    </div>
  </div>
</div>

<div class="section">
  <div class="sec-title">coverage summary</div>
  <div class="sec-sub">all repos · status · thresholds · click headers to sort</div>
  <div class="filter-row">
    <input class="search-inp" type="text" placeholder="search repo..." oninput="covFilter(this.value)">
    <select class="filter-sel" onchange="covBandFilter(this.value)">
      <option value="">all bands</option>
      <option value="excellent">excellent ≥95%</option>
      <option value="good">good 85–94%</option>
      <option value="low">needs attention</option>
      <option value="none">no data</option>
    </select>
    <span class="result-count" id="cov-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="covPerPage(this.value)"><option value="10" selected>10</option><option value="20">20</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="covSort('repo')">repository</th>
        <th onclick="covSort('status')">status</th>
        <th onclick="covSort('pct')">coverage</th>
        <th class="r" onclick="covSort('stmts')">statements</th>
        <th class="r" onclick="covSort('missed')">missed</th>
        <th class="r" onclick="covSort('branches')">branches</th>
        <th class="r" onclick="covSort('failUnder')">fail under</th>
      </tr></thead>
      <tbody id="cov-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="cov-pg"></div>
</div>
</div>

<script>
var _cvd={rows_js_str},_cvs={{data:[],filtered:[],page:1,pp:10,sort:'pct',dir:-1,search:'',band:''}};
(function(){{
  _cvs.data=_cvd.slice();
  var wd=_cvd.filter(function(r){{return r.pct!==null;}}).sort(function(a,b){{return b.pct-a.pct;}});
  new Chart(document.getElementById('cov-bar'),{{
    type:'bar',
    data:{{labels:wd.map(function(r){{return r.repo.replace('omnibioai-','').replace('omnibioai_','');}}),
           datasets:[{{data:wd.map(function(r){{return r.pct;}}),
                       backgroundColor:wd.map(function(r){{return r.color+'44';}}),
                       borderColor:wd.map(function(r){{return r.color;}}),
                       borderWidth:1,borderRadius:4}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.parsed.y.toFixed(2)+'%';}}}}}}}},
      scales:{{y:{{min:0,max:102,ticks:{{callback:function(v){{return v+'%';}},font:{{size:10}},color:'#9CA3AF'}},grid:{{color:'rgba(0,0,0,0.04)'}},border:{{display:false}}}},
               x:{{ticks:{{font:{{size:9}},color:'#9CA3AF',maxRotation:45,autoSkip:false}},grid:{{display:false}},border:{{display:false}}}}}}}}
  }});
  new Chart(document.getElementById('cov-donut'),{{
    type:'doughnut',
    data:{{labels:['≥95%','85–94%','<85%','no data'],
           datasets:[{{data:[{excellent},{good_cnt},{below_85},{no_data}],
                       backgroundColor:['#3B6D11','#854F0B','#A32D2D','#888780'],
                       borderWidth:2,borderColor:'#1a1d2e',hoverOffset:3}}]}},
    options:{{responsive:false,cutout:'68%',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return c.label+': '+c.raw+' repos';}}}}}}}}}}
  }});
  covApply();
}})();
function covFilter(v){{_cvs.search=v.toLowerCase();_cvs.page=1;covApply();}}
function covBandFilter(v){{_cvs.band=v;_cvs.page=1;covApply();}}
function covPerPage(v){{_cvs.pp=parseInt(v);_cvs.page=1;covApply();}}
function covSort(col){{if(_cvs.sort===col)_cvs.dir*=-1;else{{_cvs.sort=col;_cvs.dir=col==='repo'||col==='status'?1:-1;}} _cvs.page=1;covApply();}}
function covApply(){{
  var d=_cvs.data.slice();
  if(_cvs.search)d=d.filter(function(r){{return r.repo.toLowerCase().includes(_cvs.search);}});
  if(_cvs.band){{
    d=d.filter(function(r){{
      if(_cvs.band==='excellent')return r.pct!==null&&r.pct>=95;
      if(_cvs.band==='good')return r.pct!==null&&r.pct>=85&&r.pct<95;
      if(_cvs.band==='low')return r.pct!==null&&r.pct<85;
      if(_cvs.band==='none')return r.pct===null;
      return true;
    }});
  }}
  var col=_cvs.sort;
  d.sort(function(a,b){{
    var av=a[col]===null?-999:typeof a[col]==='number'?a[col]:(a[col]||'').toLowerCase();
    var bv=b[col]===null?-999:typeof b[col]==='number'?b[col]:(b[col]||'').toLowerCase();
    return av<bv?_cvs.dir:av>bv?-_cvs.dir:0;
  }});
  _cvs.filtered=d;
  document.getElementById('cov-count').textContent=d.length+' items';
  var start=(_cvs.page-1)*_cvs.pp,page=d.slice(start,start+_cvs.pp);
  var tb=document.getElementById('cov-tbody');tb.innerHTML='';
  page.forEach(function(r){{
    var pctHtml=r.pct!==null
      ?'<div style="font-size:12px;font-weight:600;color:'+r.color+'">'+r.pct.toFixed(2)+'%</div>'+
        '<div style="height:4px;background:#2a2d3e;border-radius:2px;margin-top:3px;overflow:hidden">'+
        '<div style="height:100%;width:'+r.pct.toFixed(1)+'%;background:'+r.color+';border-radius:2px"></div></div>'
      :'<span style="color:#6b7280;font-size:12px">—</span>';
    var stBg=r.status==='ok'?'#EAF3DE':r.status.includes('skip')||r.status.includes('missing')?'#F1EFE8':'#FAEEDA';
    var stCol=r.status==='ok'?'#3B6D11':r.status.includes('skip')||r.status.includes('missing')?'#444441':'#854F0B';
    var stLbl=r.status==='ok'?'ok':r.status.includes('skip')?'skipped':r.status.includes('miss')?'missing':r.status.startsWith('error')?'error':'partial';
    var tr=document.createElement('tr');
    var short=r.repo.replace('omnibioai-','').replace('omnibioai_','').replace('omnibioai','omnibioai');
    tr.innerHTML='<td style="font-weight:600;font-size:12px">'+short+'</td>'+
      '<td><span class="badge" style="background:'+stBg+';color:'+stCol+'">'+stLbl+'</span></td>'+
      '<td style="min-width:120px">'+pctHtml+'</td>'+
      '<td class="r">'+(r.stmts!==null?r.stmts.toLocaleString():'—')+'</td>'+
      '<td class="r">'+(r.missed!==null?r.missed.toLocaleString():'—')+'</td>'+
      '<td class="r">'+(r.branches!==null?r.branches.toLocaleString():'—')+'</td>'+
      '<td class="r">'+(r.failUnder!==null?r.failUnder:'—')+'</td>';
    tb.appendChild(tr);
  }});
  renderPg('cov',_cvs,covApply);
}}
</script>
"""
