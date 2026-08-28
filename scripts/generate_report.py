# omnibioai-control-center/scripts/generate_report.py

#!/usr/bin/env python3
"""
OmniBioAI Ecosystem Report — scripts/generate_report.py  (redesigned)

Five tabs, consistent color palette across all tabs:
  teal   = core workbench / backend
  blue   = sdk / clients / frontend
  red    = security plane
  amber  = infrastructure / services
  purple = execution
  green  = healthy status
  gray   = neutral / unknown

Usage
-----
python omnibioai-control-center/scripts/generate_report.py

Options
-------
--root PATH              ecosystem root (default: auto-detect)
--health-url URL         default http://127.0.0.1:7070 (alias: --control-center-url)
--out PATH               default ${WORK_DIR}/out/reports/omnibioai_ecosystem_report.html
--skip-health            skip live health fetch
--skip-coverage          skip pytest coverage collection
--compose-path PATH      docker-compose.yml used by the Secrets Audit / Exposed Ports tabs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from shared.cloc import Totals, ensure_cloc, run_cloc, validate_paths, _resolve_target_paths
from shared.health_fetch import EcosystemHealth, fetch_health
from shared.css import SHARED_CSS, _CHARTJS, misc_section_html, sidebar_nav_html
from shared.pagination_js import PAGINATION_JS
from shared.helpers import fmt_int

from sections.architecture import architecture_section_html
from sections.projects import CAT_MAP, CAT_META, projects_section_html
from sections.languages import LANG_TYPE, LANG_TYPE_META, languages_section_html
from sections.coverage import coverage_section_html, collect_coverage
from sections.git_status import collect_git_status, git_status_section_html
from sections.health import health_section_html
from sections.usage import usage_section_html, gateway_traffic_section_html
from sections.llms_cloud import llm_section_html, cloud_section_html, cost_tracking_placeholder_section_html
from sections.reference import reference_section_html
from sections.knowledge_base import knowledge_base_section_html
from sections.model_registry import model_registry_section_html
from sections.docker_images import (
    docker_kpi_header_html, docker_containers_section_html,
    docker_sif_section_html, docker_plugins_section_html, _DOCKER_IMAGES_SCRIPT,
)

from sections.misc.active_runs import active_runs_section_html
from sections.misc.storage import storage_section_html
from sections.misc.catalog import catalog_section_html
from sections.misc.database import database_section_html
from sections.misc.task_queue import task_queue_section_html
from sections.misc.license import license_section_html
from sections.misc.secrets_audit import secrets_audit_section_html
from sections.misc.image_freshness import image_freshness_section_html
from sections.misc.exposed_ports import exposed_ports_section_html
from sections.misc.cicd_health import cicd_health_section_html
from sections.misc.cve_trend import cve_trend_section_html
from sections.misc.backup_status import backup_status_section_html

# ── constants ──────────────────────────────────────────────────────────────────

DEFAULT_TARGETS = [
    "omnibioai-tes", "omnibioai-workbench", "omnibioai-rag", "omnibioai-lims",
    "omnibioai-toolserver", "omnibioai-tool-runtime",
    "omnibioai-control-center", "omnibioai-dev-docker", "omnibioai-sdk",
    "omnibioai-workflow-bundles", "omnibioai-model-registry",
    "omnibioai-tool-images", "omnibioai-studio", "omnibioai-dev-hub",
    "omnibioai-videos", "omnibioai-iam-client", "omnibioai-usage-client",
    "omnibioai-policy-engine",
    "omnibioai-ecosystem-regression",
    "omnibioai-security-audit", "omnibioai-security-sdk",
    "omnibioai-api-gateway", "omnibioai-hpc-policy-engine", "omnibioai-docs", "omnibioai-auth", "omnibioai-landing", "omnibioai-design-tokens", "omnibioai-ui",
    "omnibioai-utils",
    "omnibioai-launcher",
    "omnibioai-billing", "omnibioai-db-init",
]

_work_dir = Path(os.environ.get(
    "WORK_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "omnibioai-work")
))

DEFAULT_OUT_PATH = _work_dir / "out" / "reports" / "omnibioai_ecosystem_report.html"

DEFAULT_TITLE              = "OmniBioAI Ecosystem"

DEFAULT_CONTROL_CENTER_URL = "http://127.0.0.1:7070"

def _default_compose_path() -> Path:
    env_path = os.environ.get("OMNIBIOAI_COMPOSE_PATH")
    if env_path:
        return Path(env_path)
    # Two fallbacks because this script runs in two different contexts:
    # inside the control-center container, ${MACHINE_DIR} on the host is
    # mounted to /workspace (see docker-compose.yml), so the compose file
    # lives under /workspace there; run directly on the host instead, it's
    # still at its normal Desktop/machine location.
    container_path = Path("/workspace/omnibioai-studio/docker-compose.yml")
    if container_path.exists():
        return container_path
    return Path("/home/manish/Desktop/machine/omnibioai-studio/docker-compose.yml")

DEFAULT_COMPOSE_PATH = _default_compose_path()

def _load_env_file(path: Path) -> None:
    """Best-effort .env loader (KEY=VALUE lines, optional 'export ' prefix,
    '#' comments and blank lines skipped). Never overrides a variable
    already present in the process environment, so an explicit shell
    export still wins over the file. Silently no-ops if the file doesn't
    exist or can't be read -- mirrors docker-compose's own env_file
    handling for the same file, without adding a python-dotenv dependency.
    """
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass

_load_env_file(DEFAULT_COMPOSE_PATH.parent / ".env")


# ── SIDEBAR NAV ────────────────────────────────────────────────────────────────
SIDEBAR_NAV_SPEC: List[Tuple[str, str, Optional[List[Tuple[str, str]]]]] = [
    ("arch",         "Architecture",      None),
    ("projects",     "Projects",          [("summary", "Code Summary"), ("languages", "Languages"), ("coverage", "Code Coverage")]),
    ("gitstatus",    "Ecosystem Status",  None),
    ("health",       "Health Status",     [("overview", "Overview"), ("services", "Services"), ("storage", "Disk & Mounts"), ("gpu", "GPU"), ("activity", "Activity"), ("audit", "Audit Trail"), ("errors", "Errors")]),
    ("usage",        "Usage",             [("product", "Product Usage"), ("gateway", "API Gateway")]),
    ("llmscloud",    "LLMs & Cloud",      [("llms", "LLMs"), ("cloud", "Cloud"), ("cost", "Cost Tracking")]),
    ("ref",          "Reference Data",    None),
    ("kb",           "AI Knowledge Base", None),
    ("modelreg",     "Model Registry",    None),
    ("dockerimages", "Docker Images",     [("containers", "Platform Containers"), ("sif", "Tool SIF Images"), ("plugins", "Plugin Docker Images")]),
    ("misc",         "Miscellaneous",     [("runs", "Active Runs"), ("storage", "Storage"), ("catalog", "Catalog"), ("database", "Data Layer"), ("queue", "Task Queue"), ("license", "License"), ("secrets", "Secrets Audit"), ("images", "Image Freshness"), ("ports", "Exposed Ports"), ("cicd", "CI/CD Health"), ("cvetrend", "CVE Trend"), ("backup", "Backup Status")]),
    # Public Read-Only Control Center architecture: the "Admin" tab
    # (Actions / Scheduled Jobs / Known Issues) used to live here --
    # this report is served unauthenticated at GET / on
    # control.omnibioai.org (routes_report.py's own public allowlist),
    # so anything rendered into it ships to every anonymous visitor
    # regardless of the login form admin.py's own JS used to gate on.
    # Moved to the Admin Console (admin.omnibioai.org, cc-ui's own
    # ActionsPage/ScheduledJobsPage/KnownIssuesPage, which sit behind
    # AdminApp's real AuthGate) -- see
    # docs/admin-console-navigation-move.md. Not rendered here at all
    # anymore, not just hidden.
]


def build_report(out_html: Path, title: str, timestamp: str,
                 grand: Totals, project_totals: Dict[str, Totals],
                 language_totals: Dict[str, Totals],
                 coverage_df: pd.DataFrame, health: EcosystemHealth,
                 control_center_url: str, ecosystem_root: Path,
                 registry_root: Path, work_dir: Path,
                 compose_path: Path = DEFAULT_COMPOSE_PATH,
                 sentry_org: str = "", sentry_project_slugs: Optional[List[str]] = None) -> None:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    cc_url = control_center_url.rstrip("/")
    total_all = grand.blank + grand.comment + grand.code
    doc_lines = language_totals.get("Markdown", Totals()).code

    arch_html     = architecture_section_html(project_totals, grand, control_center_url)
    projects_tab_html = misc_section_html([
        ("summary",   "Code Summary", projects_section_html(project_totals, grand)),
        ("languages", "Languages",    languages_section_html(language_totals, grand)),
        ("coverage",  "Code Coverage", coverage_section_html(coverage_df, timestamp)),
    ], group_id="projects", render_nav=False)
    gitstatus_html = git_status_section_html(ecosystem_root)
    hlth_html     = health_section_html(health, control_center_url, sentry_org, sentry_project_slugs)
    llms_html     = llm_section_html(control_center_url)
    cloud_html    = cloud_section_html(control_center_url)
    ref_html      = reference_section_html(control_center_url)
    kb_html       = knowledge_base_section_html(control_center_url)
    storage_html  = storage_section_html(control_center_url)
    catalog_html  = catalog_section_html(ecosystem_root)
    model_registry_html = model_registry_section_html(registry_root)
    dockerimages_html = misc_section_html([
        ("containers", "Platform Containers", docker_containers_section_html()),
        ("sif",        "Tool SIF Images",      docker_sif_section_html()),
        ("plugins",    "Plugin Docker Images", docker_plugins_section_html()),
    ], group_id="dockerimages", render_nav=False, header_html=docker_kpi_header_html()) + _DOCKER_IMAGES_SCRIPT
    sbnav_children_json = json.dumps({
        tid: [cid for cid, _ in children]
        for tid, _, children in SIDEBAR_NAV_SPEC if children
    })
    usage_tab_html = misc_section_html([
        ("product", "Product Usage", usage_section_html(control_center_url)),
        ("gateway", "API Gateway",   gateway_traffic_section_html(control_center_url)),
    ], group_id="usage", render_nav=False)
    # ISO8601 (distinct from the display-formatted `timestamp` string used
    # elsewhere) so cve_history.json entries sort/parse predictably; must be
    # computed before cve_trend_section_html runs, since that reads back
    # the entries cicd_health_section_html's record_cve_history() call just
    # appended for this run.
    cve_generated_at = datetime.now(timezone.utc).isoformat()
    cicd_health_html = cicd_health_section_html(ecosystem_root, DEFAULT_TARGETS, work_dir, cve_generated_at)
    misc_html = misc_section_html([
        ("runs", "Active Runs", active_runs_section_html(work_dir)),
        ("storage", "Storage", storage_html),
        ("catalog", "Catalog", catalog_html),
        ("database", "Data Layer",      database_section_html(control_center_url)),
        ("queue",    "Task Queue",      task_queue_section_html(control_center_url)),
        ("license",  "License",         license_section_html(control_center_url)),
        ("secrets",  "Secrets Audit",   secrets_audit_section_html(compose_path)),
        ("images",   "Image Freshness", image_freshness_section_html(control_center_url)),
        ("ports",    "Exposed Ports",   exposed_ports_section_html(compose_path)),
        ("cicd",     "CI/CD Health",    cicd_health_html),
        ("cvetrend", "CVE Trend",       cve_trend_section_html(work_dir)),
        ("backup",   "Backup Status",   backup_status_section_html(work_dir)),
    ], group_id="misc", render_nav=False)
    llmscloud_html = misc_section_html([
        ("llms", "LLMs", llms_html),
        ("cloud", "Cloud", cloud_html),
        ("cost", "Cost Tracking", cost_tracking_placeholder_section_html()),
    ], group_id="llmscloud", render_nav=False)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
  {_CHARTJS}
  {SHARED_CSS}
  <style>
    body {{font-family:var(--font-sans);background:var(--color-bg);color:var(--color-text);min-height:100vh}}
    .page {{max-width:1400px;margin:0 auto;padding:24px 24px 48px}}
    .hero {{background:var(--color-bg-surface);border:0.5px solid var(--color-border);border-radius:16px;padding:20px 24px;margin-bottom:20px;display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:12px}}
    .hero-title {{font-size:22px;font-weight:500;color:var(--color-text);margin-bottom:4px}}
    .hero-sub {{font-size:13px;color:var(--color-text)}}
    .hero-ts {{font-size:11px;color:var(--color-text-muted);margin-top:4px}}
    .hero-right {{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
    .hero-link {{font-size:12px;color:var(--color-text-muted);text-decoration:none;padding:5px 10px;border:0.5px solid var(--color-border);border-radius:99px;white-space:nowrap}}
    .hero-link:hover {{color:var(--color-text);border-color:var(--color-accent)}}
    .regen-btn {{display:flex;align-items:center;gap:5px;padding:8px 16px;border-radius:8px;background:var(--color-accent);color:#000;font-size:13px;font-weight:600;border:none;cursor:pointer;text-decoration:none}}
    .regen-btn:hover {{background:var(--color-bg-surface2)}}
    .status-badge {{display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:99px;font-size:12px;font-weight:600}}
    .sb-up {{background:#EAF3DE;color:#3B6D11}}
    .sb-down {{background:#FCEBEB;color:#A32D2D}}
    .sb-warn {{background:#FAEEDA;color:#854F0B}}
    .sb-unknown {{background:#F1EFE8;color:#444441}}
    .global-kpi {{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}}
    .gk {{background:var(--color-bg-surface);border:0.5px solid var(--color-border);border-radius:10px;padding:12px 18px;flex:1;min-width:100px}}
    .gk-lbl {{font-size:11px;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}}
    .gk-val {{font-size:24px;font-weight:500;color:var(--color-text)}}
    .tab-panel {{display:none}}
    .tab-panel.active {{display:block}}
    .layout-split {{display:flex;align-items:flex-start;background:var(--color-bg-surface);border:1px solid var(--color-border);border-radius:12px;overflow:hidden}}
    .sidebar {{flex:0 0 240px;width:240px;box-sizing:border-box;border-right:1px solid var(--color-border);padding:10px 0;position:sticky;top:0;align-self:flex-start;height:100vh;overflow-y:auto}}
    .sbnav-item {{display:flex;align-items:center;gap:7px;width:100%;text-align:left;padding:9px 20px;font-size:13px;font-weight:600;color:var(--color-text-muted);background:transparent;border:none;border-left:3px solid transparent;cursor:pointer;white-space:nowrap;font-family:inherit;box-sizing:border-box}}
    .sbnav-item:hover {{color:var(--color-text);background:var(--color-bg-surface2)}}
    .sbnav-item.active {{color:var(--color-text);background:var(--color-bg-surface2);border-left-color:var(--color-accent)}}
    .sbnav-child {{padding-left:37px;font-weight:400;font-size:12.5px}}
    .sbnav-child.active {{padding-left:34px}}
    .sbnav-children {{display:none;flex-direction:column}}
    .sbnav-children.expanded {{display:flex}}
    .sbnav-caret {{display:inline-block;font-size:9px;transition:transform .15s;flex-shrink:0}}
    .sbnav-group.expanded .sbnav-caret {{transform:rotate(90deg)}}
    .content-pane {{flex:1;min-width:0;padding:20px}}
    .footer {{margin-top:24px;padding-top:16px;border-top:0.5px solid var(--color-border);font-size:11px;color:var(--color-text-muted);line-height:1.8}}
  </style>
</head>
<body>
<div class="page">

  <div class="hero">
    <div>
      <div class="hero-title">{title}</div>
      <div class="hero-sub">Architecture · Codebase · Coverage · Health</div>
      <div class="hero-ts">Generated: {timestamp}</div>
    </div>
    <div class="hero-right">
      <a class="hero-link" href="https://webstudio.omnibioai.org" target="_blank" rel="noopener noreferrer">&#127760; Open Web App</a>
      <div class="status-badge sb-unknown" id="global-health-badge">
        <span class="status-dot dot-loading" id="global-health-dot"></span>
        <span id="global-health-text">checking...</span>
      </div>
      <span style="font-size:12px;color:var(--color-text-muted)" id="global-health-ts"></span>
    </div>
  </div>

  <div class="global-kpi">
    <div class="gk"><div class="gk-lbl">files</div><div class="gk-val">{fmt_int(grand.files)}</div></div>
    <div class="gk"><div class="gk-lbl">documentation</div><div class="gk-val">{fmt_int(doc_lines)}</div></div>
    <div class="gk"><div class="gk-lbl">code lines</div><div class="gk-val">{fmt_int(grand.code)}</div></div>
    <div class="gk"><div class="gk-lbl">comment lines</div><div class="gk-val">{fmt_int(grand.comment)}</div></div>
    <div class="gk"><div class="gk-lbl">blank lines</div><div class="gk-val">{fmt_int(grand.blank)}</div></div>
    <div class="gk"><div class="gk-lbl">total lines</div><div class="gk-val">{fmt_int(total_all)}</div></div>
  </div>

  {PAGINATION_JS}

  <div class="layout-split">
    <nav class="sidebar" id="app-sidebar">
      {sidebar_nav_html(SIDEBAR_NAV_SPEC)}
    </nav>
    <div class="content-pane">
      <div id="tab-arch"   class="tab-panel active">{arch_html}</div>
      <div id="tab-projects" class="tab-panel">{projects_tab_html}</div>
      <div id="tab-gitstatus" class="tab-panel">{gitstatus_html}</div>
      <div id="tab-health" class="tab-panel">{hlth_html}</div>
      <div id="tab-usage"  class="tab-panel">{usage_tab_html}</div>
      <div id="tab-llmscloud" class="tab-panel">{llmscloud_html}</div>
      <div id="tab-ref"    class="tab-panel">{ref_html}</div>
      <div id="tab-kb"      class="tab-panel">{kb_html}</div>
      <div id="tab-modelreg" class="tab-panel">{model_registry_html}</div>
      <div id="tab-dockerimages" class="tab-panel">{dockerimages_html}</div>
      <div id="tab-misc" class="tab-panel">{misc_html}</div>
    </div>
  </div>

  <div class="footer">
    cloc counts exclude vendored/runtime directories and selected extensions per cloc policy.<br>
    Coverage is best-effort and does not fail the report when a repository has test or configuration issues.<br>
    Health data is live — fetched from the Control Center /health endpoint with 30-second auto-refresh.<br>
    <a href="https://omnibioai.org" target="_blank" rel="noopener noreferrer" style="color:var(--color-accent);text-decoration:none">← Back to omnibioai.org</a>
  </div>
</div>

<script>
function sbnavClearActive(){{
  document.querySelectorAll('.sbnav-item.active').forEach(function(b){{b.classList.remove('active');}});
}}
function sbnavShowPanel(topId){{
  document.querySelectorAll('.tab-panel').forEach(function(t){{t.classList.remove('active');}});
  var panel=document.getElementById('tab-'+topId);
  if(panel)panel.classList.add('active');
}}
function sbnavExpandGroup(topId){{
  var kids=document.getElementById('sbnav-children-'+topId);
  if(!kids)return;
  kids.classList.add('expanded');
  var grp=document.querySelector('.sbnav-group[data-top="'+topId+'"]');
  if(grp)grp.classList.add('expanded');
}}
function sbnavToggleGroup(topId){{
  var kids=document.getElementById('sbnav-children-'+topId);
  if(!kids)return;
  var grp=document.querySelector('.sbnav-group[data-top="'+topId+'"]');
  if(kids.classList.contains('expanded')){{
    kids.classList.remove('expanded');
    if(grp)grp.classList.remove('expanded');
  }} else {{
    sbnavExpandGroup(topId);
  }}
}}
function sbnavSelectTop(topId, skipHash){{
  sbnavShowPanel(topId);
  sbnavClearActive();
  var btn=document.querySelector('.sbnav-leaf[data-top="'+topId+'"]');
  if(btn)btn.classList.add('active');
  if(!skipHash) location.hash = topId;
}}
function sbnavSelectChild(topId, childId, skipHash){{
  sbnavShowPanel(topId);
  sbnavExpandGroup(topId);
  sbnavClearActive();
  var btn=document.querySelector('.sbnav-child[data-top="'+topId+'"][data-child="'+childId+'"]');
  if(btn)btn.classList.add('active');
  if(typeof miscSub==='function') miscSub(topId, 'misc-panel-'+topId+'-'+childId);
  if(!skipHash) location.hash = topId+'/'+childId;
}}
var _SBNAV_CHILDREN = {sbnav_children_json};
function sbnavApplyHash(){{
  var h=(location.hash||'').replace(/^#/,'');
  if(!h) return false;
  var parts=h.split('/');
  var topId=parts[0], childId=parts[1];
  if(_SBNAV_CHILDREN.hasOwnProperty(topId)){{
    var kids=_SBNAV_CHILDREN[topId];
    if(childId && kids.indexOf(childId)!==-1){{
      sbnavSelectChild(topId, childId, true);
    }} else {{
      sbnavSelectChild(topId, kids[0], true);
    }}
    return true;
  }}
  if(document.getElementById('tab-'+topId)){{
    sbnavSelectTop(topId, true);
    return true;
  }}
  return false;
}}
if(!sbnavApplyHash()){{
  sbnavSelectTop('arch', true);
}}
window.addEventListener('hashchange', function(){{ sbnavApplyHash(); }});

(function globalHealthBadge(){{
  fetch('/health').then(function(r){{if(!r.ok)throw new Error('health request failed');return r.json();}}).then(function(d){{
    var raw=String(d.overall_status||d.status||'UNKNOWN').toUpperCase();
    var ov=(raw==='OK'||raw==='HEALTHY')?'UP':raw;
    var badge=document.getElementById('global-health-badge');
    var dot=document.getElementById('global-health-dot');
    var txt=document.getElementById('global-health-text');
    var ts=document.getElementById('global-health-ts');
    var cls={{UP:'sb-up',DOWN:'sb-down',WARN:'sb-warn'}};
    badge.className='status-badge '+(cls[ov]||'sb-unknown');
    dot.className='status-dot '+(ov==='UP'?'dot-up':(ov==='DOWN'||ov==='UNREACHABLE'||ov==='UNAVAILABLE')?'dot-down':'dot-warn');
    var svcs=Array.isArray(d.services)?d.services:[];
    if(svcs.length){{
      var up=svcs.filter(function(s){{return String(s.status||'').toUpperCase()==='UP';}}).length;
      txt.textContent=up+'/'+svcs.length+' UP';
    }}else{{
      txt.textContent=ov==='UP'?'HEALTHY':ov==='WARN'?'DEGRADED':ov;
    }}
    if(d.generated_at)ts.textContent=new Date(d.generated_at).toLocaleTimeString();
  }}).catch(function(){{
    document.getElementById('global-health-dot').className='status-dot dot-down';
    document.getElementById('global-health-text').textContent='unreachable';
  }});
}})();
</script>
</body>
</html>
"""
    out_html.write_text(html, encoding="utf-8")

    # ── Save structured JSON for React frontend ──────────────────────────────
    total_code = grand.code or 1
    proj_sorted = sorted(project_totals.items(), key=lambda kv: kv[1].code, reverse=True)
    lang_sorted  = sorted(language_totals.items(), key=lambda kv: kv[1].code, reverse=True)

    projects_json = []
    for name, t in proj_sorted:
        cat = CAT_MAP.get(name, "infra")
        m   = CAT_META[cat]
        projects_json.append({
            "name": name.replace("omnibioai-", "").replace("omnibioai_", ""),
            "full": name, "cat": cat, "catLabel": m["label"],
            "files": t.files, "code": t.code,
            "comment": t.comment, "blank": t.blank,
            "pct": round(100 * t.code / total_code, 2),
        })

    languages_json = []
    for name, t in lang_sorted:
        lt = LANG_TYPE.get(name, "infra")
        m  = LANG_TYPE_META[lt]
        languages_json.append({
            "name": name, "type": lt, "typeLabel": m["label"],
            "files": t.files, "code": t.code,
            "comment": t.comment, "blank": t.blank,
            "pct": round(100 * t.code / total_code, 2),
        })

    coverage_json = []
    for _, row in coverage_df.iterrows():
        pct = row.get("coverage_pct")
        pct_val = round(float(pct), 2) if (pct is not None and pct == pct) else None
        stmts    = row.get("statements")
        missed   = row.get("missed")
        branches = row.get("branches")
        fail_u   = row.get("fail_under")
        coverage_json.append({
            "repo":      str(row.get("repo", "")),
            "status":    str(row.get("status", "")),
            "pct":       pct_val,
            "stmts":     int(stmts)    if (stmts    is not None and stmts    == stmts)    else None,
            "missed":    int(missed)   if (missed    is not None and missed   == missed)   else None,
            "branches":  int(branches) if (branches  is not None and branches == branches) else None,
            "failUnder": float(fail_u) if (fail_u    is not None and fail_u   == fail_u)   else None,
        })

    # collect_git_status() was already run once above for gitstatus_html;
    # re-running it here (rather than threading its result through) keeps
    # this JSON block symmetric with projects_json/languages_json/
    # coverage_json, each of which re-derives from its own already-computed
    # input above -- the scan itself is a few seconds across ~35 local
    # repos, not worth the extra plumbing to avoid.
    git_status_json = [
        {
            "repo": r["repo"], "branch": r["branch"], "nonMain": r["non_main"],
            "clean": r["clean"], "modified": r["modified"],
            "untracked": r["untracked"], "unpushed": r["unpushed"],
            "details": r["details"],
        }
        for r in collect_git_status(ecosystem_root)
    ]

    json_out = out_html.with_name("report_data.json")
    json_out.write_text(json.dumps({
        "generated_at": timestamp,
        "grand":     {"files": grand.files, "code": grand.code, "comment": grand.comment, "blank": grand.blank},
        "projects":  projects_json,
        "languages": languages_json,
        "coverage":  coverage_json,
        "gitStatus": git_status_json,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate OmniBioAI ecosystem report")
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--targets", nargs="+", default=None)
    p.add_argument("--out", default=str(DEFAULT_OUT_PATH))
    p.add_argument("--title", default=DEFAULT_TITLE)
    p.add_argument("--health-url", "--control-center-url",
                   default=DEFAULT_CONTROL_CENTER_URL,
                   dest="control_center_url")
    p.add_argument("--skip-health",    action="store_true")
    p.add_argument("--skip-coverage",  action="store_true")
    p.add_argument("--compose-path", default=str(DEFAULT_COMPOSE_PATH))
    return p.parse_args()


def generate_report(ecosystem_root: Path,
                    targets: Optional[List[str]] = None,
                    out_relpath: str = str(DEFAULT_OUT_PATH),
                    title: str = DEFAULT_TITLE,
                    control_center_url: str = DEFAULT_CONTROL_CENTER_URL,
                    skip_health: bool = False,
                    skip_coverage: bool = False,
                    compose_path: str = str(DEFAULT_COMPOSE_PATH)) -> Path:
    ensure_cloc()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not targets:
        targets = DEFAULT_TARGETS

    target_paths = _resolve_target_paths(ecosystem_root, targets)
    validate_paths(target_paths)

    print("→ Running cloc…")
    project_totals:  Dict[str, Totals] = {}
    language_totals: Dict[str, Totals] = {}
    grand = Totals()
    for tp in target_paths:
        if not tp.exists(): continue
        overall, per_lang = run_cloc(tp)
        project_totals[tp.name] = overall
        grand.add(overall)
        for lang, tot in per_lang.items():
            language_totals.setdefault(lang, Totals()).add(tot)

    work_dir = Path(os.environ.get("WORK_DIR", str(ecosystem_root / "omnibioai-work")))

    if skip_coverage:
        print("→ Skipping coverage (--skip-coverage)")
        coverage_df = pd.DataFrame(columns=[
            "repo","path","status","returncode","statements","missed",
            "branches","partial_branches","coverage_pct","coverage_band",
            "fail_under","total_line","stderr_tail"])
    else:
        precomputed_dir = work_dir / "out" / "coverage"
        if precomputed_dir.is_dir():
            print(f"→ Loading pre-computed coverage from {precomputed_dir}…")
        else:
            print("→ Collecting pytest coverage (live)…")
        coverage_df = collect_coverage(
            target_paths,
            precomputed_dir=precomputed_dir if precomputed_dir.is_dir() else None)

    if skip_health:
        health = EcosystemHealth(overall_status="UNREACHABLE", generated_at="",
                                  error="Health check skipped")
    else:
        print(f"→ Fetching health from {control_center_url}…")
        health = fetch_health(control_center_url)
        print(f"  {'✓' if health.overall_status=='UP' else '⚠'} Overall: {health.overall_status}")

    sentry_org = os.environ.get("SENTRY_ORG", "")
    sentry_project_slugs = [s.strip() for s in os.environ.get("SENTRY_PROJECT_SLUGS", "").split(",") if s.strip()]

    out_html = ecosystem_root / out_relpath
    print("→ Building report…")
    build_report(out_html=out_html, title=title, timestamp=ts,
                 grand=grand, project_totals=project_totals,
                 language_totals=language_totals, coverage_df=coverage_df,
                 health=health, control_center_url=control_center_url,
                 ecosystem_root=ecosystem_root,
                 registry_root=ecosystem_root / "data" / "local_registry" / "model_registry",
                 work_dir=work_dir, compose_path=Path(compose_path),
                 sentry_org=sentry_org, sentry_project_slugs=sentry_project_slugs)
    return out_html


def main() -> int:
    args = parse_args()
    if args.root:
        ecosystem_root = args.root
    else:
        # Derive root from script location: <root>/omnibioai-control-center/scripts/generate_report.py
        script_candidate = Path(__file__).resolve().parent.parent.parent  # /workspace
        if any((script_candidate / t).is_dir() for t in DEFAULT_TARGETS[:6]):
            ecosystem_root = script_candidate
        else:
            cwd = Path.cwd()
            ecosystem_root = cwd.parent if (cwd / "manage.py").exists() else cwd
    try:
        out = generate_report(
            ecosystem_root=ecosystem_root,
            targets=args.targets,
            out_relpath=args.out,
            title=args.title,
            control_center_url=args.control_center_url,
            skip_health=args.skip_health,
            skip_coverage=args.skip_coverage,
            compose_path=args.compose_path)
        print(f"\n✓ Report written: {out}")
        return 0
    except Exception as e:
        print(f"\n✗ {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
