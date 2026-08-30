# backend/src/control_center/main.py

from __future__ import annotations

import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN", ""),
    integrations=[
        FastApiIntegration(),
        StarletteIntegration(),
    ],
    traces_sample_rate=0.1,
    environment=os.environ.get("SENTRY_ENVIRONMENT", "beta"),
    release=os.environ.get("SENTRY_RELEASE", "0.2.0-beta"),
    send_default_pii=False,
)
import json as _json_mod
import logging
import subprocess
import threading
import time as _time_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from control_center.api.routes_auth_proxy import router as auth_proxy_router
from control_center.api.routes_org_proxy import router as org_proxy_router
from control_center.api.routes_user_proxy import router as user_proxy_router
from control_center.api.routes_role_proxy import router as role_proxy_router
from control_center.api.routes_team_proxy import router as team_proxy_router
from control_center.api.routes_service_accounts_proxy import router as service_accounts_proxy_router
from control_center.api.routes_audit_proxy import router as audit_proxy_router
from control_center.api.routes_sessions_proxy import router as sessions_proxy_router
from control_center.api.routes_org_sso_proxy import router as org_sso_proxy_router
from control_center.api.routes_org_mfa_proxy import router as org_mfa_proxy_router
from control_center.api.routes_org_saml_proxy import router as org_saml_proxy_router
from control_center.api.routes_billing_proxy import router as billing_proxy_router
from control_center.api.routes_tes_proxy import router as tes_proxy_router
from control_center.api.routes_model_registry_proxy import router as model_registry_proxy_router
from control_center.api.routes_workflow_bundles_proxy import router as workflow_bundles_proxy_router
from control_center.api.routes_rag_proxy import router as rag_proxy_router
from control_center.api.routes_agent_orchestrator_proxy import router as agent_orchestrator_proxy_router
from control_center.api.routes_platform_config_proxy import router as platform_config_proxy_router
from control_center.api.routes_platform_interactions_proxy import router as platform_interactions_proxy_router
from control_center.analytics.router import router as analytics_router
from control_center.compliance.router import router as compliance_router
from control_center.api.routes_hipaa_compliance import router as hipaa_compliance_router
from control_center.api.routes_cloud import router as cloud_router
from control_center.api.routes_integrations import router as integrations_router
from control_center.api.routes_integration_health import router as integration_health_router
from control_center.core.auth import require_permission
from control_center.api.routes_config import router as config_router
from control_center.api.routes_cron import router as cron_router
from control_center.api.routes_dashboard import router as dashboard_router
from control_center.api.routes_deployment_health import router as deployment_health_router
from control_center.api.routes_docker import router as docker_router
from control_center.api.routes_health import router as health_router
from control_center.api.routes_infra import router as infra_router
from control_center.api.routes_known_issues import router as known_issues_router
from control_center.api.routes_llm import router as llm_router
from control_center.api.routes_reference import router as reference_router
from control_center.api.routes_regression_health import router as regression_health_router
from control_center.api.routes_report import router as report_router
from control_center.api.routes_services import router as services_router
from control_center.api.routes_storage import router_storage
from control_center.api.routes_summary import router as summary_router


# ── Structured JSON logger ────────────────────────────────────────────────────
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _json_mod.dumps({
            "ts":      self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
            "module":  record.module,
            **(record.__dict__.get("extra_fields", {})),
        })


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    return logging.getLogger("control_center")


log = _setup_logging()


app = FastAPI(
    title="OmniBioAI Control Center",
    version="0.1.0",
)

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# PR E (Admin Console Production Hardening): allow_origins=["*"] was a
# wildcard -- every other backend in this ecosystem that mounts
# CORSMiddleware (omnibioai-auth's app/core/config.py CORS_ALLOWED_
# ORIGINS, omnibioai-rag's ragbio/api/server.py _CORS_ORIGINS) uses an
# explicit, env-driven origin allowlist instead; this file was the one
# outlier, confirmed by reading all three directly. In the actual
# deployed topology (docker/nginx/control-center.conf) the browser only
# ever reaches this backend same-origin, through nginx's reverse
# proxy -- CORSMiddleware only matters for a browser calling this API
# directly, cross-origin, which the wildcard permitted from literally
# any site. Same CORS_ALLOWED_ORIGINS env var name/comma-separated
# format as omnibioai-auth's, for one ecosystem-wide convention;
# defaults cover both production domains (docs/admin-console-build.md)
# and this app's own local dev ports (5173 `npm run dev`, 5174 the
# nginx-fronted prod-like local build).
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174,"
        "https://admin.omnibioai.org,https://control.omnibioai.org",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
# summary/config/docker/services expose internal topology (hostnames, LAN
# IPs, container inventory, mount paths) -- control.omnibioai.org routes
# here directly, bypassing nginx-router's auth_request gate entirely (see
# /etc/cloudflared/config.yml), so these were reachable with no auth at
# all. Gate them the same way report_generate/coverage_generate already
# are below.
app.include_router(services_router, dependencies=[Depends(require_permission("platform.manage_infra"))])
app.include_router(summary_router, dependencies=[Depends(require_permission("platform.manage_infra"))])
app.include_router(regression_health_router, dependencies=[Depends(require_permission("platform.manage_infra"))])
app.include_router(deployment_health_router, dependencies=[Depends(require_permission("platform.manage_infra"))])
app.include_router(integration_health_router, dependencies=[Depends(require_permission("platform.manage_infra"))])
app.include_router(report_router)
app.include_router(config_router, dependencies=[Depends(require_permission("platform.manage_infra"))])
app.include_router(cron_router)
app.include_router(docker_router, dependencies=[Depends(require_permission("platform.manage_infra"))])
app.include_router(known_issues_router)
app.include_router(llm_router)
app.include_router(infra_router)
app.include_router(cloud_router)
# PR-B6: same ungated posture as cloud_router directly above -- see
# routes_integrations.py's own module comment for why (booleans/labels
# only, no internal topology, no credential values).
app.include_router(integrations_router)
app.include_router(reference_router)
app.include_router(router_storage)
app.include_router(auth_proxy_router)
app.include_router(org_proxy_router)
app.include_router(user_proxy_router)
app.include_router(role_proxy_router)
app.include_router(team_proxy_router)
app.include_router(service_accounts_proxy_router)
app.include_router(audit_proxy_router)
app.include_router(sessions_proxy_router)
app.include_router(org_sso_proxy_router)
app.include_router(org_mfa_proxy_router)
app.include_router(org_saml_proxy_router)
app.include_router(billing_proxy_router)
app.include_router(tes_proxy_router)
app.include_router(model_registry_proxy_router)
app.include_router(workflow_bundles_proxy_router)
app.include_router(rag_proxy_router)
# Agentic AI nav item (feature/agentic-ai-navbar): same "no blanket
# permission dependency" posture as model_registry_proxy_router/
# rag_proxy_router immediately above -- GET /api/agent/graphs/ has no
# auth requirement upstream (see routes_agent_orchestrator_proxy.py's own
# module comment).
app.include_router(agent_orchestrator_proxy_router)
app.include_router(platform_config_proxy_router)
app.include_router(platform_interactions_proxy_router)
# No blanket permission dependency here, unlike summary/docker/config/
# services above -- routes_dashboard.py's own docstring explains why:
# each section of its one response is authorized independently, either
# by forwarding the caller's token to the upstream service that owns
# that data, or (Infrastructure/Operations only) via its own in-process
# platform.manage_infra check.
app.include_router(dashboard_router)
# Usage Analytics v1: every route here is individually gated by its own
# Depends(require_analytics_scope) (401/403 per-request, platform_admin/
# org_admin/team_admin/deny) -- no blanket router-level permission
# dependency, same "each route owns its own authorization" posture
# dashboard_router immediately above already established, for the same
# reason: a single blanket permission here would either over- or
# under-restrict across the different roles analytics needs to serve.
app.include_router(analytics_router)
# HIPAA Basic Compliance Report v0.8.0: no blanket router-level permission
# dependency here either, same reasoning as analytics_router immediately
# above -- each route already requires manage_all_orgs individually
# (compliance/router.py's own _require_platform_admin).
app.include_router(compliance_router)
# Admin Console HIPAA Compliance Report (persistent change history): same
# posture as compliance_router immediately above -- each route already
# requires manage_all_orgs individually
# (routes_hipaa_compliance.py's own _require_platform_admin), not a
# generic proxy relay, so this is a normal in-process router like
# dashboard_router/analytics_router, not one of the routes_*_proxy.py
# routers above.
app.include_router(hipaa_compliance_router)


# ==============================================================================
# Report generation — background job state
# ==============================================================================

class _JobState:
    """Thread-safe state for the background report generation job."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.status: str = "idle"       # idle | running | done | error
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.message: str = ""

    def start(self) -> None:
        with self._lock:
            self.status = "running"
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.finished_at = None
            self.message = ""

    def finish(self, message: str = "") -> None:
        with self._lock:
            self.status = "done"
            self.finished_at = datetime.now(timezone.utc).isoformat()
            self.message = message

    def fail(self, message: str) -> None:
        with self._lock:
            self.status = "error"
            self.finished_at = datetime.now(timezone.utc).isoformat()
            self.message = message

    def as_dict(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "message": self.message,
            }


_job = _JobState()


# ==============================================================================
# Docker tab injection — appended to the sticky bar on the / ecosystem report
# Raw Python string (r-prefix) so \' stays as JS escape and / regex chars are unambiguous.
# ==============================================================================

_DOCKER_INJECT_JS = r"""<style>
#tab-docker { padding: 20px 0; }
.omni-d-subnav { display:flex; border-bottom:1px solid #e5e7eb; margin-bottom:16px; }
.omni-d-subbtn { padding:9px 16px; font-size:12px; font-weight:400; color:#6b7280; background:none; border:none; border-bottom:2px solid transparent; cursor:pointer; font-family:inherit; margin-bottom:-1px; white-space:nowrap; transition:color .1s; }
.omni-d-subbtn:hover { color:#374151; }
.omni-d-subbtn.active { font-weight:600; color:#2563eb; border-bottom-color:#2563eb; }
.omni-d-pills { display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; }
.omni-d-pill { font-size:12px; font-weight:600; padding:4px 12px; border-radius:99px; background:#f3f4f6; border:1px solid #e5e7eb; color:#374151; white-space:nowrap; }
.omni-d-card { background:white; border:1px solid #e5e7eb; border-radius:10px; overflow:hidden; margin-bottom:16px; }
.omni-d-table { width:100%; border-collapse:collapse; }
.omni-d-table th { font-size:10px; font-weight:700; color:#6b7280; text-transform:uppercase; letter-spacing:.07em; padding:9px 14px; border-bottom:1px solid #e5e7eb; text-align:left; background:#f9fafb; white-space:nowrap; }
.omni-d-table td { font-size:12px; color:#374151; padding:10px 14px; border-bottom:1px solid #f3f4f6; vertical-align:middle; }
.omni-d-table tr:last-child td { border-bottom:none; }
.omni-d-table tr:hover td { background:#f9fafb; }
.omni-d-loading { text-align:center; padding:28px; color:#9ca3af; font-size:12px; }
.omni-d-pager { display:none; align-items:center; gap:8px; justify-content:center; padding:10px 14px; border-top:1px solid #f3f4f6; background:white; }
.omni-d-pager-btn { padding:5px 14px; border-radius:6px; border:1px solid #d1d5db; background:white; color:#374151; font-size:12px; cursor:pointer; font-family:inherit; transition:opacity .12s; }
.omni-d-pager-btn:disabled { opacity:0.4; cursor:default; }
.omni-d-pager-info { font-size:12px; color:#6b7280; min-width:160px; text-align:center; }
.omni-d-sif-wrap { display:flex; gap:16px; align-items:flex-start; }
.omni-d-sidebar { width:164px; flex-shrink:0; }
.omni-d-sidebar-lbl { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:#9ca3af; margin-bottom:8px; }
.omni-d-catbtn { width:100%; text-align:left; padding:6px 10px; border-radius:6px; font-size:12px; background:transparent; color:#374151; border:1px solid transparent; cursor:pointer; font-family:inherit; display:flex; justify-content:space-between; align-items:center; margin-bottom:2px; }
.omni-d-catbtn:hover { background:#f9fafb; }
.omni-d-catbtn.active { background:#eff6ff; color:#2563eb; border-color:#bfdbfe; font-weight:600; }
.omni-d-cnt { background:#e5e7eb; color:#374151; border-radius:99px; font-size:10px; font-weight:700; padding:1px 6px; margin-left:4px; flex-shrink:0; }
.omni-d-main { flex:1; min-width:0; }
.omni-d-search { width:100%; max-width:300px; padding:7px 11px; font-size:13px; border:1px solid #d1d5db; border-radius:8px; font-family:inherit; outline:none; display:block; margin-bottom:10px; color:#374151; background:white; }
.omni-d-search:focus { border-color:#2563eb; box-shadow:0 0 0 2px rgba(37,99,235,.15); }
</style>
<script>
(function() {
  var _dLoaded = false, _dActive = 'ct';
  var _ctData = [], _ctPage = 0, _CT_PP = 25;
  var _sifData = [], _sifCat = null, _sifPage = 0, _SIF_PP = 25;
  var _plData = [], _plPage = 0, _PL_PP = 25;

  function omniEsc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // /docker/* now requires require_permission("platform.manage_infra")
  // (core/auth.py) -- same omnibioai_access_token localStorage key the
  // Admin tab's login sets.
  function omniAuthHeader() {
    var t = localStorage.getItem('omnibioai_access_token');
    return t ? {'Authorization': 'Bearer ' + t} : {};
  }

  function omniPagerHtml(pId, navFn) {
    return '<div id="' + pId + '" class="omni-d-pager">' +
      '<button class="omni-d-pager-btn" id="' + pId + '-prev" onclick="' + navFn + '(-1)">&#8592; Prev</button>' +
      '<span class="omni-d-pager-info" id="' + pId + '-info"></span>' +
      '<button class="omni-d-pager-btn" id="' + pId + '-next" onclick="' + navFn + '(1)">Next &#8594;</button>' +
      '</div>';
  }

  function omniUpdatePager(pId, page, pages, total, unit) {
    var el = document.getElementById(pId);
    if (!el) return;
    if (pages > 1) {
      el.style.display = 'flex';
      document.getElementById(pId + '-info').textContent = 'Page ' + (page + 1) + ' of ' + pages + ' (' + total + ' ' + unit + ')';
      var pb = document.getElementById(pId + '-prev'), nb = document.getElementById(pId + '-next');
      pb.disabled = page === 0; nb.disabled = page >= pages - 1;
    } else {
      el.style.display = 'none';
    }
  }

  function buildDockerPanel() {
    var el = document.createElement('div');
    el.id = 'tab-docker';
    el.className = 'tab-panel';
    el.innerHTML =
      '<nav class="omni-d-subnav">' +
        '<button class="omni-d-subbtn active" id="omni-subbtn-ct" onclick="omniDockSub(\'ct\')">Platform Containers</button>' +
        '<button class="omni-d-subbtn" id="omni-subbtn-sif" onclick="omniDockSub(\'sif\')">Tool SIF Images</button>' +
        '<button class="omni-d-subbtn" id="omni-subbtn-pl" onclick="omniDockSub(\'pl\')">Plugin Docker Images</button>' +
      '</nav>' +
      '<div id="omni-d-ct">' +
        '<div id="omni-d-ct-pills" class="omni-d-pills"></div>' +
        '<div class="omni-d-card">' +
          '<table class="omni-d-table"><thead><tr><th>Container</th><th>Image</th><th>Status</th><th>Uptime</th><th>Ports</th></tr></thead>' +
          '<tbody id="omni-d-ct-tbody"><tr><td colspan="5" class="omni-d-loading">Loading…</td></tr></tbody></table>' +
          omniPagerHtml('omni-d-ct-pager', 'omniCtNav') +
        '</div>' +
      '</div>' +
      '<div id="omni-d-sif" style="display:none">' +
        '<div id="omni-d-sif-pills" class="omni-d-pills"></div>' +
        '<div class="omni-d-sif-wrap">' +
          '<div class="omni-d-sidebar"><div class="omni-d-sidebar-lbl">Categories</div><div id="omni-d-catlist"></div></div>' +
          '<div class="omni-d-main">' +
            '<input class="omni-d-search" id="omni-d-search" type="search" placeholder="Search tools…" oninput="omniSifSearch()">' +
            '<div class="omni-d-card">' +
              '<table class="omni-d-table"><thead><tr><th>Tool</th><th>Category</th><th>Status</th><th>Size</th></tr></thead>' +
              '<tbody id="omni-d-sif-tbody"><tr><td colspan="4" class="omni-d-loading">Loading…</td></tr></tbody></table>' +
              omniPagerHtml('omni-d-sif-pager', 'omniSifNav') +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div id="omni-d-pl" style="display:none">' +
        '<div id="omni-d-pl-pills" class="omni-d-pills"></div>' +
        '<div class="omni-d-card">' +
          '<table class="omni-d-table"><thead><tr><th>Plugin</th><th>Category</th><th>Image</th><th>Local Status</th><th>Size</th></tr></thead>' +
          '<tbody id="omni-d-pl-tbody"><tr><td colspan="5" class="omni-d-loading">Scanning plugin images…</td></tr></tbody></table>' +
          omniPagerHtml('omni-d-pl-pager', 'omniPlNav') +
        '</div>' +
      '</div>';
    return el;
  }

  function injectDockerTab() {
    var tabNav = document.querySelector('.tab-nav');
    if (!tabNav) return;
    var btn = document.createElement('button');
    btn.className = 'tab-btn';
    btn.textContent = 'Docker Images';
    btn.id = 'omni-docker-btn';
    btn.addEventListener('click', function() {
      openTab('tab-docker', btn);
      if (!_dLoaded) { _dLoaded = true; omniLoadCt(); omniLoadSif(); omniLoadPl(); }
    });
    // Insert before whatever is currently the last tab (Miscellaneous) so
    // Docker Images lands second-to-last, not after it.
    var lastBtn = tabNav.lastElementChild;
    if (lastBtn) { tabNav.insertBefore(btn, lastBtn); } else { tabNav.appendChild(btn); }
    var panel = buildDockerPanel();
    var existingPanels = document.querySelectorAll('.tab-panel');
    if (existingPanels.length > 0) {
      var lastPanel = existingPanels[existingPanels.length - 1];
      lastPanel.parentNode.insertBefore(panel, lastPanel);
    } else {
      tabNav.parentNode.appendChild(panel);
    }
  }

  window.omniDockSub = function(sub) {
    _dActive = sub;
    ['ct','sif','pl'].forEach(function(s) {
      var p = document.getElementById('omni-d-' + s);
      var b = document.getElementById('omni-subbtn-' + s);
      if (p) p.style.display = s === sub ? '' : 'none';
      if (b) b.classList.toggle('active', s === sub);
    });
  };

  var CAT_COLORS = {
    'alignment':['#2563eb','#fff'],'assembly':['#059669','#fff'],
    'variant-calling':['#9333ea','#fff'],'rna-seq':['#ea580c','#fff'],
    'single-cell':['#0284c7','#fff'],'epigenomics':['#b45309','#fff'],
    'protein-structure':['#7c3aed','#fff'],'proteomics':['#be123c','#fff'],
    'population-genetics':['#16a34a','#fff'],'annotation':['#92400e','#fff'],
    'metagenomics':['#0e7490','#fff'],'qc':['#475569','#fff'],
    'imaging':['#be185d','#fff'],'genomics':['#1d4ed8','#fff']
  };
  function omniCatChip(cat) {
    var cc = CAT_COLORS[cat] || ['#64748b', '#fff'];
    return '<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:99px;background:' + cc[0] + ';color:' + cc[1] + ';white-space:nowrap">' + omniEsc(cat) + '</span>';
  }

  /* ── CT ── */
  window.omniCtNav = function(dir) { _ctPage += dir; omniRenderCt(); };
  function omniRenderCt() {
    var total = _ctData.length, pages = Math.ceil(total / _CT_PP);
    if (_ctPage >= pages) _ctPage = Math.max(0, pages - 1);
    var start = _ctPage * _CT_PP, end = Math.min(start + _CT_PP, total);
    var rows = '';
    for (var i = start; i < end; i++) {
      var c = _ctData[i], name = (c.Names || '').replace(/^\//, '') || '—';
      var st = (c.State || '').toLowerCase();
      var run = st === 'running' || (c.Status || '').indexOf('Up ') === 0;
      var rst = st === 'restarting' || (c.Status || '').toLowerCase().indexOf('restart') >= 0;
      var bbg = run ? '#dcfce7' : rst ? '#fef3c7' : '#fee2e2';
      var bcol = run ? '#15803d' : rst ? '#92400e' : '#b91c1c';
      var blbl = run ? 'running' : rst ? 'restarting' : 'stopped';
      rows += '<tr>' +
        '<td style="font-weight:600;font-size:13px;color:#111827;padding:10px 14px">' + omniEsc(name) + '</td>' +
        '<td style="font-size:11px;color:#6b7280;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:10px 14px">' + omniEsc(c.Image || '—') + '</td>' +
        '<td style="padding:10px 14px"><span style="font-size:10px;font-weight:700;padding:3px 9px;border-radius:99px;background:' + bbg + ';color:' + bcol + '">' + blbl + '</span></td>' +
        '<td style="font-size:11px;color:#6b7280;white-space:nowrap;padding:10px 14px">' + omniEsc(c.RunningFor || '—') + '</td>' +
        '<td style="font-size:11px;color:#374151;font-family:monospace;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:10px 14px">' + omniEsc(c.Ports || '—') + '</td>' +
        '</tr>';
    }
    document.getElementById('omni-d-ct-tbody').innerHTML = rows || '<tr><td colspan="5" class="omni-d-loading">No containers</td></tr>';
    omniUpdatePager('omni-d-ct-pager', _ctPage, pages, total, 'containers');
  }
  async function omniLoadCt() {
    document.getElementById('omni-d-ct-tbody').innerHTML = '<tr><td colspan="5" class="omni-d-loading">Loading…</td></tr>';
    try {
      var res = await fetch('/docker/containers', {headers: omniAuthHeader()});
      if (res.status === 401) {
        document.getElementById('omni-d-ct-tbody').innerHTML = '<tr><td colspan="5" class="omni-d-loading">Sign in on the Admin tab to view this</td></tr>';
        return;
      }
      var d = await res.json();
      var pills = '';
      if (d.running != null) pills += '<span class="omni-d-pill" style="color:#059669">' + d.running + ' running</span>';
      if (d.stopped != null) pills += '<span class="omni-d-pill" style="color:#dc2626">' + d.stopped + ' stopped</span>';
      document.getElementById('omni-d-ct-pills').innerHTML = pills;
      _ctData = d.containers || []; _ctPage = 0;
      if (!_ctData.length) {
        document.getElementById('omni-d-ct-tbody').innerHTML = '<tr><td colspan="5" class="omni-d-loading">' + (d.error ? 'Error: ' + omniEsc(d.error) : 'No containers found — is Docker running?') + '</td></tr>';
        return;
      }
      omniRenderCt();
    } catch(e) {
      document.getElementById('omni-d-ct-tbody').innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:#dc2626;font-size:12px">' + omniEsc(String(e)) + '</td></tr>';
    }
  }

  /* ── SIF ── */
  window.omniSifNav = function(dir) { _sifPage += dir; omniRenderSif(); };
  window.omniSifSearch = function() { _sifPage = 0; omniRenderSif(); };
  window.omniSetCat = function(cat) { _sifCat = cat; _sifPage = 0; omniRebuildCats(); omniRenderSif(); };

  function omniRebuildCats() {
    var counts = {};
    for (var i = 0; i < _sifData.length; i++) { var cat = _sifData[i].category; counts[cat] = (counts[cat] || 0) + 1; }
    var cats = Object.entries(counts).sort(function(a, b) { return b[1] - a[1]; });
    var html = '<button class="omni-d-catbtn' + (_sifCat === null ? ' active' : '') + '" onclick="omniSetCat(null)">' +
      '<span>All</span><span class="omni-d-cnt">' + _sifData.length + '</span></button>';
    for (var j = 0; j < cats.length; j++) {
      var cat2 = cats[j][0], cnt = cats[j][1], act = _sifCat === cat2 ? ' active' : '';
      html += '<button class="omni-d-catbtn' + act + '" onclick="omniSetCat(\'' + omniEsc(cat2) + '\')">' +
        '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + omniEsc(cat2) + '</span>' +
        '<span class="omni-d-cnt">' + cnt + '</span></button>';
    }
    document.getElementById('omni-d-catlist').innerHTML = html;
  }

  window.omniRenderSif = function() {
    var q = (document.getElementById('omni-d-search').value || '').toLowerCase();
    var filtered = _sifData.filter(function(img) {
      return (!q || img.tool.toLowerCase().indexOf(q) >= 0) && (!_sifCat || img.category === _sifCat);
    });
    if (!filtered.length) {
      document.getElementById('omni-d-sif-tbody').innerHTML = '<tr><td colspan="4" class="omni-d-loading">No SIF images found</td></tr>';
      document.getElementById('omni-d-sif-pager').style.display = 'none';
      return;
    }
    var total = filtered.length, pages = Math.ceil(total / _SIF_PP);
    if (_sifPage >= pages) _sifPage = Math.max(0, pages - 1);
    var start = _sifPage * _SIF_PP, end = Math.min(start + _SIF_PP, total);
    var rows = '';
    for (var i = start; i < end; i++) {
      var img = filtered[i];
      var sbg = img.exists ? '#dcfce7' : '#fee2e2', scol = img.exists ? '#15803d' : '#b91c1c', slbl = img.exists ? 'built' : 'missing';
      var sizeHtml = '—';
      if (img.exists) {
        var pct = Math.min(100, (img.size_mb / 5120) * 100).toFixed(1);
        var szlbl = img.size_mb >= 1024 ? (img.size_mb / 1024).toFixed(1) + ' GB' : img.size_mb + ' MB';
        sizeHtml = '<div style="display:flex;align-items:center;gap:8px">' +
          '<div style="width:60px;height:4px;background:#e5e7eb;border-radius:99px;overflow:hidden">' +
          '<div style="height:100%;width:' + pct + '%;background:#2563eb;border-radius:99px"></div></div>' +
          '<span style="font-size:11px;color:#6b7280;white-space:nowrap;font-family:monospace">' + szlbl + '</span></div>';
      }
      rows += '<tr>' +
        '<td style="font-weight:600;font-size:13px;color:#111827;padding:10px 14px">' + omniEsc(img.tool) + '</td>' +
        '<td style="padding:10px 14px">' + omniCatChip(img.category) + '</td>' +
        '<td style="padding:10px 14px"><span style="font-size:10px;font-weight:700;padding:3px 9px;border-radius:99px;background:' + sbg + ';color:' + scol + '">' + slbl + '</span></td>' +
        '<td style="padding:10px 14px;min-width:130px">' + sizeHtml + '</td>' +
        '</tr>';
    }
    document.getElementById('omni-d-sif-tbody').innerHTML = rows;
    omniUpdatePager('omni-d-sif-pager', _sifPage, pages, total, 'tools');
  };

  async function omniLoadSif() {
    document.getElementById('omni-d-sif-tbody').innerHTML = '<tr><td colspan="4" class="omni-d-loading">Scanning SIF images…</td></tr>';
    try {
      var res = await fetch('/docker/sif-images', {headers: omniAuthHeader()});
      if (res.status === 401) {
        document.getElementById('omni-d-sif-tbody').innerHTML = '<tr><td colspan="4" class="omni-d-loading">Sign in on the Admin tab to view this</td></tr>';
        return;
      }
      var d = await res.json();
      _sifData = d.images || []; _sifPage = 0;
      var pills = '';
      if (d.built != null) pills += '<span class="omni-d-pill" style="color:#059669">' + d.built + ' built</span>';
      if (d.missing != null) pills += '<span class="omni-d-pill" style="color:#dc2626">' + d.missing + ' missing</span>';
      if (d.total_gb != null) pills += '<span class="omni-d-pill" style="color:#2563eb">' + d.total_gb + ' GB total</span>';
      document.getElementById('omni-d-sif-pills').innerHTML = pills;
      omniRebuildCats(); omniRenderSif();
    } catch(e) {
      document.getElementById('omni-d-sif-tbody').innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:#dc2626;font-size:12px">' + omniEsc(String(e)) + '</td></tr>';
    }
  }

  /* ── Plugins ── */
  window.omniPlNav = function(dir) { _plPage += dir; omniRenderPl(); };
  function omniRenderPl() {
    var total = _plData.length, pages = Math.ceil(total / _PL_PP);
    if (_plPage >= pages) _plPage = Math.max(0, pages - 1);
    var start = _plPage * _PL_PP, end = Math.min(start + _PL_PP, total);
    var rows = '';
    for (var i = start; i < end; i++) {
      var p = _plData[i], st = p.local_status || 'unknown';
      var pbg = st === 'present' ? '#dcfce7' : '#fee2e2';
      var pcol = st === 'present' ? '#15803d' : '#b91c1c';
      var szHtml = '—';
      if (st === 'present' && p.size_mb > 0) { szHtml = p.size_mb >= 1024 ? (p.size_mb / 1024).toFixed(1) + ' GB' : p.size_mb + ' MB'; }
      rows += '<tr>' +
        '<td style="font-weight:600;color:#111827;padding:10px 14px;white-space:nowrap">' + omniEsc(p.name || p.plugin || '—') + '</td>' +
        '<td style="padding:10px 14px">' + omniCatChip(p.category || 'general') + '</td>' +
        '<td style="font-size:11px;color:#6b7280;padding:10px 14px;font-family:monospace;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + omniEsc(p.image || '—') + '</td>' +
        '<td style="padding:10px 14px"><span style="font-size:10px;font-weight:700;padding:3px 9px;border-radius:99px;background:' + pbg + ';color:' + pcol + '">' + st + '</span></td>' +
        '<td style="font-size:11px;color:#6b7280;padding:10px 14px;font-family:monospace;white-space:nowrap">' + szHtml + '</td>' +
        '</tr>';
    }
    document.getElementById('omni-d-pl-tbody').innerHTML = rows || '<tr><td colspan="5" class="omni-d-loading">No plugins</td></tr>';
    omniUpdatePager('omni-d-pl-pager', _plPage, pages, total, 'plugins');
  }
  async function omniLoadPl() {
    document.getElementById('omni-d-pl-tbody').innerHTML = '<tr><td colspan="5" class="omni-d-loading">Scanning plugin images…</td></tr>';
    try {
      var res = await fetch('/docker/plugin-images', {headers: omniAuthHeader()});
      if (res.status === 401) {
        document.getElementById('omni-d-pl-tbody').innerHTML = '<tr><td colspan="5" class="omni-d-loading">Sign in on the Admin tab to view this</td></tr>';
        return;
      }
      var d = await res.json();
      _plData = d.plugins || []; _plPage = 0;
      var pills = '';
      if (d.present != null) pills += '<span class="omni-d-pill">' + _plData.length + ' plugins</span>';
      if (d.present != null) pills += '<span class="omni-d-pill" style="color:#059669">' + d.present + ' present</span>';
      if (d.missing != null) pills += '<span class="omni-d-pill" style="color:#dc2626">' + d.missing + ' missing</span>';
      document.getElementById('omni-d-pl-pills').innerHTML = pills;
      if (!_plData.length) {
        document.getElementById('omni-d-pl-tbody').innerHTML = '<tr><td colspan="5" class="omni-d-loading">No plugins found</td></tr>';
        return;
      }
      omniRenderPl();
    } catch(e) {
      document.getElementById('omni-d-pl-tbody').innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:#dc2626;font-size:12px">' + omniEsc(String(e)) + '</td></tr>';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectDockerTab);
  } else {
    injectDockerTab();
  }
})();
</script>"""


def _workspace_root() -> Path:
    return Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))


def _reset_job_to_idle(job: "_JobState" = None, delay_s: int = 5) -> None:
    """Reset job status to idle after a short delay so reloaded pages see 'idle'."""
    job = job if job is not None else _job
    import time as _time
    _time.sleep(delay_s)
    with job._lock:
        if job.status in ("done", "error"):
            job.status = "idle"


def _run_report_job() -> None:
    workspace = _workspace_root()
    log.info("report_job_started", extra={"extra_fields": {"workspace": str(workspace)}})
    script = workspace / "omnibioai-control-center" / "scripts" / "generate_report.py"

    if not script.exists():
        msg = f"Report script not found: {script}"
        _job.fail(msg)
        log.error("report_job_failed", extra={"extra_fields": {"error": msg}})
        threading.Thread(target=_reset_job_to_idle, daemon=True).start()
        return

    cmd = [
        "python3", str(script),
        "--root", str(workspace),
        "--health-url", f"http://127.0.0.1:{os.environ.get('CONTROL_CENTER_PORT', '7070')}",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode == 0:
            last_line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "Done"
            _job.finish(last_line)
            log.info("report_job_finished", extra={"extra_fields": {"output": last_line}})
        else:
            msg = proc.stderr.strip() or proc.stdout.strip() or "Unknown error"
            _job.fail(msg)
            log.error("report_job_failed", extra={"extra_fields": {"error": msg}})
    except subprocess.TimeoutExpired:
        _job.fail("Report generation timed out after 10 minutes")
        log.error("report_job_timeout")
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        _job.fail(msg)
        log.error("report_job_failed", extra={"extra_fields": {"error": msg}})

    # Reset to idle after 30s so subsequent page loads don't see 'done'
    # and trigger another reload loop.
    threading.Thread(target=_reset_job_to_idle, daemon=True).start()


@app.post("/report/generate")
def report_generate(_admin: dict = Depends(require_permission("platform.manage_content"))) -> JSONResponse:
    """Trigger background report generation. Returns 409 if already running.

    Admin-gated at the application level -- nginx's auth_request already
    requires a valid JWT for this path, but only checks authentication, not
    role. This is the independent, defense-in-depth check that still holds
    even if nginx is misconfigured or bypassed."""
    # AUDIT_EVENT integration point: PR3D leaves this a comment, not a
    # call -- IAM's persistent audit ledger (PR9) has no client library
    # this repo can import yet. Once one exists, emit here with
    # actor=_admin["sub"], action="report.generate".
    log.info("report_generate_requested")
    if _job.as_dict()["status"] == "running":
        return JSONResponse({"error": "Report generation already in progress"}, status_code=409)
    _job.start()
    thread = threading.Thread(target=_run_report_job, daemon=True)
    thread.start()
    return JSONResponse({"status": "started"})


@app.get("/report/status")
def report_status() -> JSONResponse:
    """Poll job state. Frontend polls this every 2s while running."""
    state = _job.as_dict()
    report_path = _workspace_root() / "work" / "out" / "reports" / "omnibioai_ecosystem_report.html"
    state["report_exists"] = report_path.exists()
    if report_path.exists():
        mtime = datetime.fromtimestamp(report_path.stat().st_mtime, tz=timezone.utc)
        state["report_generated_at"] = mtime.isoformat()
    else:
        state["report_generated_at"] = None
    return JSONResponse(state)


# ==============================================================================
# Coverage collection — background job state (mirrors the report job above)
# ==============================================================================
#
# Scoped to omnibioai-control-center only. run_coverage_host.py's own
# docstring says it must run "on the developer machine... so each repo's
# dependencies are already installed" -- confirmed live: none of the other
# ~17 repos' service containers have pytest installed (they're production
# runtime images), and the script invokes `sys.executable -m pytest`, i.e.
# whatever interpreter runs it, not a per-repo venv. control-center's own
# container does have pytest/pytest-cov (installed via this service's own
# startup command) and can self-test, so that's the one repo this endpoint
# can honestly run on demand. The other ~17 repos still get fresh coverage
# from the existing nightly host cron job (see /cron/jobs).

_coverage_job = _JobState()
_COVERAGE_REPO = "omnibioai-control-center"


def _run_coverage_job() -> None:
    workspace = _workspace_root()
    log.info("coverage_job_started", extra={"extra_fields": {"repo": _COVERAGE_REPO}})
    script = workspace / "omnibioai-control-center" / "scripts" / "run_coverage_host.py"

    if not script.exists():
        msg = f"Coverage script not found: {script}"
        _coverage_job.fail(msg)
        log.error("coverage_job_failed", extra={"extra_fields": {"error": msg}})
        threading.Thread(target=_reset_job_to_idle, args=(_coverage_job,), daemon=True).start()
        return

    cmd = [
        "python3", str(script),
        "--root", str(workspace),
        "--repos", _COVERAGE_REPO,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode == 0:
            last_line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "Done"
            _coverage_job.finish(last_line)
            log.info("coverage_job_finished", extra={"extra_fields": {"output": last_line}})
        else:
            msg = proc.stderr.strip() or proc.stdout.strip() or "Unknown error"
            _coverage_job.fail(msg)
            log.error("coverage_job_failed", extra={"extra_fields": {"error": msg}})
    except subprocess.TimeoutExpired:
        _coverage_job.fail("Coverage collection timed out after 10 minutes")
        log.error("coverage_job_timeout")
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        _coverage_job.fail(msg)
        log.error("coverage_job_failed", extra={"extra_fields": {"error": msg}})

    threading.Thread(target=_reset_job_to_idle, args=(_coverage_job,), daemon=True).start()


@app.post("/coverage/generate")
def coverage_generate(_admin: dict = Depends(require_permission("platform.manage_content"))) -> JSONResponse:
    """Trigger background coverage collection for omnibioai-control-center
    only (see module comment above for why the other repos aren't included).
    Returns 409 if already running. Admin-gated, same as /report/generate."""
    # AUDIT_EVENT integration point: see report_generate above --
    # actor=_admin["sub"], action="coverage.generate".
    log.info("coverage_generate_requested")
    if _coverage_job.as_dict()["status"] == "running":
        return JSONResponse({"error": "Coverage collection already in progress"}, status_code=409)
    _coverage_job.start()
    thread = threading.Thread(target=_run_coverage_job, daemon=True)
    thread.start()
    return JSONResponse({"status": "started"})


@app.get("/coverage/status")
def coverage_status() -> JSONResponse:
    """Poll coverage job state. Same shape as /report/status."""
    state = _coverage_job.as_dict()
    result_path = _workspace_root() / "omnibioai-work" / "out" / "coverage" / f"{_COVERAGE_REPO}.json"
    state["result_exists"] = result_path.exists()
    if result_path.exists():
        mtime = datetime.fromtimestamp(result_path.stat().st_mtime, tz=timezone.utc)
        state["result_generated_at"] = mtime.isoformat()
    else:
        state["result_generated_at"] = None
    return JSONResponse(state)


@app.get("/report/data")
def report_data() -> JSONResponse:
    """Return structured JSON data for the React frontend (projects, languages, coverage)."""
    data_path = _workspace_root() / "work" / "out" / "reports" / "report_data.json"
    if not data_path.exists():
        return JSONResponse({"error": "No report data yet. Generate the report first."}, status_code=404)
    try:
        import json as _json
        return JSONResponse(_json.loads(data_path.read_text(encoding="utf-8")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ==============================================================================
# Scheduled report generation
# ==============================================================================

REPORT_SCHEDULE_HOURS = float(os.environ.get("REPORT_SCHEDULE_HOURS", "6"))


def _scheduler_loop() -> None:
    """Background thread — triggers report generation every N hours.
    First run is delayed by REPORT_SCHEDULE_HOURS so startup is clean.
    Skips if a job is already running.
    """
    log.info("report_scheduler_started", extra={"extra_fields": {
        "interval_hours": REPORT_SCHEDULE_HOURS,
        "first_run_in_hours": REPORT_SCHEDULE_HOURS,
    }})
    _time_mod.sleep(REPORT_SCHEDULE_HOURS * 3600)
    while True:
        try:
            if _job.as_dict()["status"] != "running":
                log.info("report_scheduler_triggering")
                _job.start()
                thread = threading.Thread(target=_run_report_job, daemon=True)
                thread.start()
            else:
                log.info("report_scheduler_skipped_already_running")
        except Exception as e:
            log.error("report_scheduler_error", extra={"extra_fields": {"error": str(e)}})
        _time_mod.sleep(REPORT_SCHEDULE_HOURS * 3600)


@app.on_event("startup")
async def on_startup() -> None:
    log.info("control_center_started", extra={"extra_fields": {
        "workspace": str(_workspace_root()),
        "port": os.environ.get("CONTROL_CENTER_PORT", "7070"),
        "report_schedule_hours": REPORT_SCHEDULE_HOURS,
    }})
    scheduler = threading.Thread(target=_scheduler_loop, daemon=True)
    scheduler.start()


# ==============================================================================
# Dashboard UI
# ==============================================================================


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    report_path = _workspace_root() / "work" / "out" / "reports" / "omnibioai_ecosystem_report.html"

    if report_path.exists():
        report_html = report_path.read_text(encoding="utf-8")
        port = os.environ.get("CONTROL_CENTER_PORT", "7070")
        sticky_bar = f"""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  body {{ padding-top: 62px !important; }}
  #omni-header {{
    position:fixed;top:0;left:0;right:0;z-index:9999;
    display:flex;align-items:center;justify-content:space-between;
    padding:10px 28px;
    background:white;
    box-shadow:0 2px 8px rgba(0,0,0,.1);
    font-family:'Inter','Segoe UI',system-ui,sans-serif;
    gap:12px;
  }}
  #omni-header .logo {{ display:flex;align-items:center;gap:10px; }}
  #omni-header .logo-text {{ font-size:18px;font-weight:700;color:#2563eb;letter-spacing:-.01em; }}
  #omni-header .logo-text span {{ font-weight:400; }}
  #omni-header .logo-sub {{ font-size:11px;color:#9ca3af;margin-top:1px; }}
  #omni-header .hdr-right {{ display:flex;align-items:center;gap:10px;flex-wrap:wrap; }}
  #omni-header .status-chip {{ font-size:12px;font-weight:600;padding:5px 13px;border-radius:99px;display:inline-flex;align-items:center;gap:6px; }}
  #omni-header .chip-green {{ background:#ecfdf5;color:#059669;border:1px solid #a7f3d0; }}
  #omni-header .chip-amber {{ background:#fffbeb;color:#d97706;border:1px solid #fde68a; }}
  #omni-header .chip-red {{ background:#fef2f2;color:#dc2626;border:1px solid #fecaca; }}
  #omni-header .chip-dot {{ width:7px;height:7px;border-radius:50%;background:#10b981; }}
</style>
<header id="omni-header">
  <div class="logo">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 34" width="36" height="36">
      <polygon points="16,2 28,8 28,22 16,28 4,22 4,8" fill="none" stroke="#2563eb" stroke-width="1.8"/>
      <path d="M11 9 C16 13,14 17,20 20 M20 9 C15 13,17 17,11 20" stroke="#2563eb" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <circle cx="16" cy="15" r="2.2" fill="#2563eb"/>
    </svg>
    <div>
      <div class="logo-text">Omni<span>BioAI</span></div>
      <div class="logo-sub">Ecosystem Report</div>
    </div>
  </div>
  <div class="hdr-right">
    <div class="status-chip chip-green" id="omni-svc-badge" style="display:none;"></div>
  </div>
</header>
<script>
(function() {{
  // Regenerate/coverage-refresh controls now live in the Admin Console
  // (admin-gated there, both client-side and server-side) rather than
  // this always-visible header -- this script now only drives the live
  // service-status chip. /summary itself moved behind
  // require_permission("platform.manage_infra") (it leaks internal
  // hostnames/LAN IPs, not just up/down counts) --
  // attach the token if the visitor happens to already be signed in via
  // the Admin Console; anonymous visitors just see no chip (badge stays
  // hidden), same as any other unreachable-state failure below.
  async function omniLoadStatus() {{
    try {{
      var _t = localStorage.getItem('omnibioai_access_token');
      var res = await fetch('/summary', {{headers: _t ? {{'Authorization': 'Bearer ' + _t}} : {{}}}});
      if (res.status === 401) return;
      var data = await res.json();
      var svcs = data.services || [];
      var up = svcs.filter(function(s){{return s.status==='UP';}}).length;
      var badge = document.getElementById('omni-svc-badge');
      var dot = '<div class="chip-dot" style="background:' + (up===svcs.length?'#10b981':'#f59e0b') + ';"></div>';
      badge.innerHTML = dot + up + '/' + svcs.length + ' UP';
      badge.style.display = 'inline-flex';
      badge.className = 'status-chip ' + (up===svcs.length?'chip-green':'chip-amber');
    }} catch(e) {{}}
  }}

  omniLoadStatus();
  setInterval(omniLoadStatus, 15000);
}})();
</script>
"""
        inject = sticky_bar + _DOCKER_INJECT_JS
        if '<body>' in report_html:
            report_html = report_html.replace('<body>', '<body>' + inject, 1)
        else:
            report_html = inject + report_html

        return HTMLResponse(content=report_html)

    # No report yet — show landing page
    return HTMLResponse(content="""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>OmniBioAI — Generate Report</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
    body{font-family:'Inter',system-ui,sans-serif;background:#f9fafb;display:flex;align-items:center;justify-content:center;min-height:100vh;}
    .card{background:white;border:1px solid #e5e7eb;border-radius:14px;padding:48px;max-width:480px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.06);}
    .logo{font-size:22px;font-weight:700;color:#2563eb;margin-bottom:8px;}
    .sub{font-size:14px;color:#9ca3af;margin-bottom:32px;}
    .btn{font-size:14px;font-weight:600;padding:12px 28px;border-radius:9px;cursor:pointer;border:none;background:#2563eb;color:white;font-family:inherit;display:inline-flex;align-items:center;gap:8px;}
    .btn:disabled{background:#93c5fd;cursor:not-allowed;}
    .msg{font-size:12px;color:#6b7280;margin-top:16px;}
    .spin{width:16px;height:16px;border:2px solid rgba(255,255,255,.4);border-top-color:white;border-radius:50%;animation:spin .8s linear infinite;display:none;}
    @keyframes spin{to{transform:rotate(360deg);}}
    .login-field{width:100%;padding:9px 12px;font-size:13px;border-radius:8px;border:1px solid #d1d5db;font-family:inherit;margin-bottom:8px;}
    .login-err{color:#dc2626;font-size:12px;margin-bottom:8px;display:none;}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">OmniBioAI</div>
    <div class="sub">No ecosystem report found. Generate one to get started.</div>

    <div id="gen-locked">
      <div class="msg" style="margin-top:0;margin-bottom:16px;">Admin sign-in required to generate the initial report.</div>
      <div id="login-err" class="login-err"></div>
      <input type="email" id="login-email" class="login-field" placeholder="email">
      <input type="password" id="login-password" class="login-field" placeholder="password" onkeydown="if(event.key==='Enter')doLogin()">
      <button class="btn" onclick="doLogin()" style="width:100%;justify-content:center;">Sign in</button>
    </div>

    <div id="gen-readonly" style="display:none;">
      <div class="msg" style="margin-top:0;color:#d97706;">Signed in, but admin access is required to generate the report.</div>
    </div>

    <div id="gen-unlocked" style="display:none;">
      <button class="btn" id="btn" onclick="generate()">
        <span class="spin" id="spin"></span>
        &#128196; Generate Report
      </button>
    </div>

    <div class="msg" id="msg"></div>
  </div>
<script>
  var TOKEN_KEY = 'omnibioai_access_token';
  function apiPath(p) {
    var prefix = window.location.pathname.indexOf('/_svc/control') === 0 ? '/_svc/control' : '';
    return prefix + p;
  }

  async function checkAuth() {
    var token = localStorage.getItem(TOKEN_KEY);
    var locked = document.getElementById('gen-locked');
    var readonly = document.getElementById('gen-readonly');
    var unlocked = document.getElementById('gen-unlocked');
    if (!token) { locked.style.display='block'; readonly.style.display='none'; unlocked.style.display='none'; return; }
    try {
      var res = await fetch('/auth/validate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({token: token})});
      var data = await res.json();
      var isAdmin = data.valid && (data.roles || []).indexOf('admin') >= 0;
      if (!data.valid) { localStorage.removeItem(TOKEN_KEY); locked.style.display='block'; readonly.style.display='none'; unlocked.style.display='none'; }
      else if (!isAdmin) { locked.style.display='none'; readonly.style.display='block'; unlocked.style.display='none'; }
      else { locked.style.display='none'; readonly.style.display='none'; unlocked.style.display='block'; }
    } catch (e) {
      locked.style.display='block'; readonly.style.display='none'; unlocked.style.display='none';
    }
  }

  async function doLogin() {
    var email = document.getElementById('login-email').value;
    var password = document.getElementById('login-password').value;
    var err = document.getElementById('login-err');
    err.style.display = 'none';
    try {
      var res = await fetch('/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email:email, password:password})});
      if (!res.ok) { err.textContent = res.status===401 ? 'Invalid email or password' : 'Login failed'; err.style.display='block'; return; }
      var data = await res.json();
      localStorage.setItem(TOKEN_KEY, data.access_token);
      checkAuth();
    } catch (e) { err.textContent = 'Login failed: ' + e; err.style.display='block'; }
  }

  async function generate() {
    var btn=document.getElementById('btn'),spin=document.getElementById('spin'),msg=document.getElementById('msg');
    btn.disabled=true;spin.style.display='inline-block';msg.textContent='Generating report… this takes 2–5 minutes';
    try{
      var token = localStorage.getItem(TOKEN_KEY);
      var res = await fetch(apiPath('/report/generate'), {method:'POST', headers: token ? {'Authorization':'Bearer '+token} : {}});
      if (res.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        msg.textContent = 'Session expired -- please sign in again';
        btn.disabled=false; spin.style.display='none';
        checkAuth();
        return;
      }
      poll();
    }catch(e){msg.textContent='Error: '+e;btn.disabled=false;spin.style.display='none';}
  }
  async function poll(){
    try{
      var res=await fetch(apiPath('/report/status')),state=await res.json();
      if(state.status==='done'){window.location.reload();}
      else if(state.status==='error'){
        document.getElementById('msg').textContent='Error: '+(state.message||'unknown');
        document.getElementById('btn').disabled=false;
        document.getElementById('spin').style.display='none';
      }else{setTimeout(poll,2000);}
    }catch(e){setTimeout(poll,3000);}
  }

  checkAuth();
</script>
</body>
</html>
""")



@app.get("/dashboard")
def dashboard() -> RedirectResponse:
    """/dashboard is retired -- its live per-service status cards and
    report-generation controls are now covered by / (service status chip
    in the header) and the Admin Console (Actions page), respectively.
    Kept as a redirect rather than a 404 for any old bookmarks/links."""
    return RedirectResponse(url="/", status_code=302)
