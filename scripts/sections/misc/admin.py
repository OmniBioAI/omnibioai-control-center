from __future__ import annotations

# ==============================================================================
# Admin tab -- Actions / Scheduled Jobs / Known Issues
#
# Unlike most other tabs, this one can't be baked at report-generation time:
# admin state (are you logged in? are you an admin?) and the underlying data
# (job status, issue list) both change independently of when the report was
# last regenerated. So this follows the same "static skeleton + client-side
# fetch" pattern already established for the Docker Images tab
# (sections/docker_images.py's _DOCKER_IMAGES_SCRIPT) rather than the
# baked-once pattern most other misc sub-tabs use.
#
# Auth: reads the JWT from the same localStorage key
# ("omnibioai_access_token") omnibioai-studio's session.js already uses --
# since this report and the Studio SPA share an origin, an existing Studio
# login is recognized here automatically. Login posts directly to
# /auth/login (same-origin passthrough via nginx) -- no auth logic is
# reimplemented client-side. Every admin-action fetch goes through
# admFetch(), which clears the stored token and re-renders the login form
# on a 401 rather than failing silently.
# ==============================================================================

ADMIN_STYLE = """
<style>
.adm-btn-primary{font-size:12px;font-weight:600;padding:8px 16px;border-radius:8px;border:none;background:var(--color-accent);color:#04120c;cursor:pointer;font-family:inherit}
.adm-btn-primary:disabled{opacity:0.5;cursor:not-allowed}
.adm-btn-sm{font-size:11px;font-weight:600;padding:4px 10px;border-radius:6px;border:0.5px solid var(--color-border);background:var(--color-bg-surface2);color:var(--color-text);cursor:pointer;font-family:inherit}
.adm-input{padding:6px 10px;font-size:12px;border-radius:6px;border:0.5px solid var(--color-border);background:var(--color-bg-surface2);color:var(--color-text);font-family:inherit}
.adm-input:focus{outline:none;border-color:var(--color-accent);box-shadow:0 0 0 3px var(--color-accent-dim)}
.adm-login-card{max-width:360px}
.adm-brand{display:flex;align-items:center;gap:8px;margin-bottom:16px}
.adm-brand-label{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:12px;font-weight:600;color:var(--color-accent);letter-spacing:0.04em}
.adm-field{display:flex;flex-direction:column;gap:8px;max-width:320px}
.adm-label{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10px;font-weight:600;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;display:block}
</style>
"""


def admin_auth_header_html() -> str:
    """Rendered once above all three Admin sub-tabs (misc_section_html's
    header_html) -- login state applies across the whole group, not to a
    single sub-tab."""
    return ADMIN_STYLE + """
<div class="section adm-login-card" id="adm-login-section" style="display:none">
  <div class="adm-brand">
    <svg width="20" height="20" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M20 2 L36 11 V29 L20 38 L4 29 V11 Z" stroke="var(--color-accent)" stroke-width="2.5" fill="var(--color-accent-dim)"/>
      <path d="M20 12 L28 16.5 V25.5 L20 30 L12 25.5 V16.5 Z" fill="var(--color-accent)" opacity="0.85"/>
    </svg>
    <span class="adm-brand-label">OmniBioAI Admin</span>
  </div>
  <div class="sec-title">Sign in</div>
  <div class="sec-sub">Admin access is required to make changes on this tab -- everything here is still visible without signing in.</div>
  <div id="adm-login-error" style="color:var(--color-danger);font-size:12px;margin-bottom:8px;display:none"></div>
  <div class="adm-field">
    <div>
      <label class="adm-label" for="adm-login-email">Email</label>
      <input type="email" id="adm-login-email" placeholder="you@omnibioai.org" class="adm-input" style="width:100%">
    </div>
    <div>
      <label class="adm-label" for="adm-login-password">Password</label>
      <input type="password" id="adm-login-password" placeholder="••••••••" class="adm-input" style="width:100%" onkeydown="if(event.key==='Enter')admLogin()">
    </div>
    <button onclick="admLogin()" class="adm-btn-primary" style="margin-top:2px">Sign in</button>
  </div>
</div>
<div class="section" id="adm-readonly-banner" style="display:none">
  <div style="color:var(--color-warning);font-size:12px">Signed in, but admin access is required to make changes here -- everything below is read-only for your account.</div>
</div>
"""


def admin_actions_section_html() -> str:
    return """
<div class="section" id="adm-actions-section" style="display:none">
  <div class="sec-title">Report &amp; Coverage</div>
  <div class="sec-sub">Regenerate the ecosystem report, or refresh control-center's own test coverage on demand. Full ecosystem coverage still runs nightly via the scheduled job (see Scheduled Jobs).</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap">
    <button id="adm-btn-regen" onclick="admRegenerate()" class="adm-btn-primary">&#8635; Regenerate Report</button>
    <button id="adm-btn-cov" onclick="admRefreshCoverage()" class="adm-btn-primary">&#8635; Refresh Coverage</button>
  </div>
  <div id="adm-actions-msg" style="font-size:12px;color:var(--color-text-muted);margin-top:10px"></div>
</div>
<div id="adm-actions-locked" style="font-size:12px;color:var(--color-text-muted)">Sign in as an admin (above) to trigger a report regeneration or coverage refresh.</div>
"""


def admin_jobs_section_html() -> str:
    return """
<div class="tbl-wrap">
  <table>
    <thead><tr><th>Job</th><th>Schedule</th><th>State</th><th>Last Run</th><th>Last Run At</th><th>Log</th><th></th></tr></thead>
    <tbody id="adm-jobs-tbody"><tr><td colspan="7" style="text-align:center;color:var(--color-text-muted);padding:24px 12px">loading…</td></tr></tbody>
  </table>
</div>
"""


def admin_issues_section_html() -> str:
    return """
<div class="section" id="adm-issue-new-form" style="display:none;margin-bottom:12px">
  <div class="sec-title">New issue</div>
  <div style="display:flex;flex-direction:column;gap:8px;max-width:520px">
    <input type="text" id="adm-issue-new-title" placeholder="title" class="adm-input">
    <textarea id="adm-issue-new-description" placeholder="description" rows="3" class="adm-input"></textarea>
    <div style="display:flex;gap:8px">
      <input type="text" id="adm-issue-new-area" placeholder="area (e.g. GPU / Infra)" class="adm-input" style="flex:1">
      <select id="adm-issue-new-severity" class="adm-input">
        <option value="low">low</option>
        <option value="medium" selected>medium</option>
        <option value="high">high</option>
      </select>
    </div>
    <button onclick="admCreateIssue()" class="adm-btn-primary" style="align-self:flex-start">Add issue</button>
  </div>
</div>
<div id="adm-issues-list"><div style="font-size:12px;color:var(--color-text-muted)">loading…</div></div>
"""


_ADMIN_SCRIPT = """
<script>
(function() {
  var ADM_TOKEN_KEY = 'omnibioai_access_token';
  var admState = {token: null, roles: [], isAdmin: false};
  var admJobs = [];
  var admIssues = [];
  var admLogState = {}; // job id -> {expanded, loading, lines, error}

  var _SEV = {
    high:   ['var(--color-danger)',  'var(--color-danger-dim)'],
    medium: ['var(--color-warning)', 'var(--color-warning-dim)'],
    low:    ['var(--color-info)',    'var(--color-info-dim)']
  };
  var _STA = {
    open:         ['var(--color-danger)',  'var(--color-danger-dim)'],
    acknowledged: ['var(--color-warning)', 'var(--color-warning-dim)'],
    resolved:     ['var(--color-success)', 'var(--color-success-dim)']
  };

  function admEsc(s) {
    return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // Absolute-path fetches (leading '/') resolve against the origin root, not
  // the current page path -- when this report is loaded through nginx at
  // /_svc/control/ (vs. directly on control-center's own port), a bare
  // fetch('/cron/jobs') misses nginx's /_svc/control/* location entirely and
  // falls through to its catch-all (the web-ui SPA). Preserve whatever
  // prefix the page was actually loaded under. Does not apply to /auth/*
  // calls -- those are a separate top-level nginx location, not nested
  // under /_svc/control.
  function admApi(path) {
    var p = window.location.pathname;
    var prefix = p.indexOf('/_svc/control') === 0 ? '/_svc/control' : '';
    return prefix + path;
  }

  // ── Session ──────────────────────────────────────────────────────────────
  function admGetToken() { return localStorage.getItem(ADM_TOKEN_KEY); }
  function admSetToken(t) { localStorage.setItem(ADM_TOKEN_KEY, t); }
  function admClearToken() { localStorage.removeItem(ADM_TOKEN_KEY); }

  async function admFetch(url, opts) {
    opts = opts || {};
    var token = admGetToken();
    opts.headers = Object.assign({}, opts.headers || {}, token ? {'Authorization': 'Bearer ' + token} : {});
    var res = await fetch(url, opts);
    if (res.status === 401) {
      admClearToken();
      admState.token = null; admState.isAdmin = false; admState.roles = [];
      admRender();
      throw new Error('Session expired -- please sign in again');
    }
    return res;
  }
  window.admFetch = admFetch;

  async function admCheckAuth() {
    var token = admGetToken();
    if (!token) {
      admState.token = null; admState.isAdmin = false; admState.roles = [];
      admRender();
      return;
    }
    try {
      var res = await fetch('/auth/validate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: token}),
      });
      var data = await res.json();
      if (!data.valid) {
        admClearToken();
        admState.token = null; admState.isAdmin = false; admState.roles = [];
      } else {
        admState.token = token;
        admState.roles = data.roles || [];
        admState.isAdmin = admState.roles.indexOf('admin') >= 0;
      }
    } catch (e) {
      admState.token = null; admState.isAdmin = false; admState.roles = [];
    }
    admRender();
  }

  async function admLogin() {
    var email = document.getElementById('adm-login-email').value;
    var password = document.getElementById('adm-login-password').value;
    var errEl = document.getElementById('adm-login-error');
    errEl.style.display = 'none';
    try {
      var res = await fetch('/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email: email, password: password}),
      });
      if (!res.ok) {
        errEl.textContent = res.status === 401 ? 'Invalid email or password' : 'Login failed';
        errEl.style.display = 'block';
        return;
      }
      var data = await res.json();
      admSetToken(data.access_token);
      await admCheckAuth();
    } catch (e) {
      errEl.textContent = 'Login failed: ' + e;
      errEl.style.display = 'block';
    }
  }
  window.admLogin = admLogin;

  function admRender() {
    var loginSec = document.getElementById('adm-login-section');
    var readonlyBanner = document.getElementById('adm-readonly-banner');
    var actionsSec = document.getElementById('adm-actions-section');
    var actionsLocked = document.getElementById('adm-actions-locked');

    if (!admState.token) {
      loginSec.style.display = 'block';
      readonlyBanner.style.display = 'none';
    } else if (!admState.isAdmin) {
      loginSec.style.display = 'none';
      readonlyBanner.style.display = 'block';
    } else {
      loginSec.style.display = 'none';
      readonlyBanner.style.display = 'none';
    }

    if (actionsSec) actionsSec.style.display = admState.isAdmin ? 'block' : 'none';
    if (actionsLocked) actionsLocked.style.display = admState.isAdmin ? 'none' : 'block';

    admRenderJobs();
    admRenderIssues();
  }

  // ── Scheduled Jobs ───────────────────────────────────────────────────────
  function admLoadJobs() {
    fetch(admApi('/cron/jobs')).then(function(r) { return r.json(); }).then(function(d) {
      admJobs = d.jobs || [];
      admRenderJobs();
    }).catch(function() {
      var tb = document.getElementById('adm-jobs-tbody');
      if (tb) tb.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--color-danger);padding:24px 12px">Control center unreachable</td></tr>';
    });
  }

  function admLoadJobLog(id) {
    admLogState[id] = Object.assign({}, admLogState[id], {expanded: true, loading: true, error: null});
    admRenderJobs();
    fetch(admApi('/cron/jobs/' + id + '/log?lines=100')).then(function(r) { return r.json(); }).then(function(d) {
      admLogState[id] = {expanded: true, loading: false, lines: d.lines || [], error: null};
      admRenderJobs();
    }).catch(function(e) {
      admLogState[id] = {expanded: true, loading: false, lines: [], error: 'Failed to load log: ' + e.message};
      admRenderJobs();
    });
  }
  window.admLoadJobLog = admLoadJobLog;

  function admToggleLog(id) {
    var st = admLogState[id];
    if (st && st.expanded) {
      admLogState[id] = Object.assign({}, st, {expanded: false});
      admRenderJobs();
    } else {
      admLoadJobLog(id);
    }
  }
  window.admToggleLog = admToggleLog;

  function admRenderJobs() {
    var tbody = document.getElementById('adm-jobs-tbody');
    if (!tbody) return;
    if (!admJobs.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--color-text-muted);padding:24px 12px">loading…</td></tr>';
      return;
    }
    tbody.innerHTML = admJobs.map(function(j) {
      var statusColor = j.last_status === 'error' ? 'var(--color-danger)'
        : j.last_status === 'ok' ? 'var(--color-success)' : 'var(--color-text-muted)';
      var pausedBadge = j.paused === null
        ? '<span class="badge" style="background:var(--color-bg-surface2);color:var(--color-text-muted)">unknown</span>'
        : j.paused
          ? '<span class="badge" style="background:var(--color-warning-dim);color:var(--color-warning)">paused</span>'
          : '<span class="badge" style="background:var(--color-success-dim);color:var(--color-success)">active</span>';
      var lastRunAt = j.last_run_at ? new Date(j.last_run_at).toLocaleString() : 'never';
      var controls = '';
      if (admState.isAdmin) {
        controls =
          '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">' +
          '<input type="text" value="' + admEsc(j.schedule) + '" id="adm-sched-' + j.id + '" class="adm-input" style="width:100px;font-family:monospace;font-size:11px;padding:3px 6px">' +
          '<button onclick="admSaveSchedule(\\'' + j.id + '\\')" class="adm-btn-sm">Save</button>' +
          (j.paused
            ? '<button onclick="admResumeJob(\\'' + j.id + '\\')" class="adm-btn-sm">Resume</button>'
            : '<button onclick="admPauseJob(\\'' + j.id + '\\')" class="adm-btn-sm">Pause</button>') +
          '</div>';
      }
      var logSt = admLogState[j.id] || {};
      var logBtn = '<button onclick="admToggleLog(\\'' + j.id + '\\')" class="adm-btn-sm">' + (logSt.expanded ? 'Hide' : 'View') + '</button>';
      var row = '<tr>' +
        '<td style="font-weight:600">' + admEsc(j.name) + '</td>' +
        '<td class="mono">' + admEsc(j.schedule) + '</td>' +
        '<td>' + pausedBadge + '</td>' +
        '<td style="color:' + statusColor + '">' + admEsc(j.last_status) + '</td>' +
        '<td style="font-size:11px;color:var(--color-text-muted)">' + lastRunAt + '</td>' +
        '<td>' + logBtn + '</td>' +
        '<td>' + controls + '</td>' +
        '</tr>';
      if (logSt.expanded) {
        var body;
        if (logSt.loading) {
          body = '<div style="font-size:11px;color:var(--color-text-muted)">loading log…</div>';
        } else if (logSt.error) {
          body = '<div style="font-size:11px;color:var(--color-danger)">' + admEsc(logSt.error) + '</div>';
        } else if (!logSt.lines || !logSt.lines.length) {
          body = '<div style="font-size:11px;color:var(--color-text-muted)">Log is empty.</div>';
        } else {
          body = '<pre style="margin:0;padding:8px 10px;background:var(--color-bg-surface2);border-radius:6px;font-family:monospace;font-size:11px;line-height:1.5;max-height:280px;overflow:auto;white-space:pre-wrap;word-break:break-all">' +
            logSt.lines.map(admEsc).join('\\n') + '</pre>';
        }
        row += '<tr><td colspan="7" style="padding:6px 12px 14px">' + body + '</td></tr>';
      }
      return row;
    }).join('');
  }

  async function admPauseJob(id) { await admJobAction(id, 'pause'); }
  async function admResumeJob(id) { await admJobAction(id, 'resume'); }
  window.admPauseJob = admPauseJob;
  window.admResumeJob = admResumeJob;

  async function admJobAction(id, action) {
    try {
      await admFetch(admApi('/cron/jobs/' + id + '/' + action), {method: 'POST'});
      admLoadJobs();
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  }

  async function admSaveSchedule(id) {
    var input = document.getElementById('adm-sched-' + id);
    try {
      var res = await admFetch(admApi('/cron/jobs/' + id + '/schedule'), {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({schedule: input.value}),
      });
      if (!res.ok) {
        var body = await res.json();
        alert('Failed to update schedule: ' + (body.error || res.status));
        return;
      }
      admLoadJobs();
    } catch (e) {
      alert('Failed to update schedule: ' + e.message);
    }
  }
  window.admSaveSchedule = admSaveSchedule;

  // ── Known Issues ─────────────────────────────────────────────────────────
  function admLoadIssues() {
    fetch(admApi('/known-issues')).then(function(r) { return r.json(); }).then(function(d) {
      admIssues = d.issues || [];
      admRenderIssues();
    }).catch(function() {
      var el = document.getElementById('adm-issues-list');
      if (el) el.innerHTML = '<div style="font-size:12px;color:var(--color-danger)">Control center unreachable</div>';
    });
  }

  function admRenderIssues() {
    var el = document.getElementById('adm-issues-list');
    if (!el) return;
    var newForm = document.getElementById('adm-issue-new-form');
    if (newForm) newForm.style.display = admState.isAdmin ? 'block' : 'none';

    if (!admIssues.length) {
      el.innerHTML = '<div style="font-size:12px;color:var(--color-text-muted)">No known issues logged.</div>';
      return;
    }
    el.innerHTML = admIssues.map(function(i) {
      var sev = _SEV[i.severity] || ['var(--color-text-muted)', 'var(--color-bg-surface2)'];
      var sta = _STA[i.status] || ['var(--color-text-muted)', 'var(--color-bg-surface2)'];
      var adminBtns = '';
      if (admState.isAdmin) {
        var options = ['open', 'acknowledged', 'resolved'].map(function(s) {
          return '<option value="' + s + '"' + (s === i.status ? ' selected' : '') + '>' + s + '</option>';
        }).join('');
        adminBtns =
          '<div style="display:flex;gap:6px;margin-top:8px">' +
          '<select id="adm-issue-status-' + i.id + '" class="adm-input" style="font-size:11px;padding:3px 6px" onchange="admUpdateIssueStatus(\\'' + i.id + '\\',this.value)">' + options + '</select>' +
          '<button onclick="admDeleteIssue(\\'' + i.id + '\\')" class="adm-btn-sm" style="color:var(--color-danger)">Delete</button>' +
          '</div>';
      }
      return '<div class="section" style="margin-bottom:8px">' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:4px">' +
        '<span style="font-size:13px;font-weight:600">' + admEsc(i.title) + '</span>' +
        '<div style="display:flex;gap:6px;flex-shrink:0">' +
        '<span class="badge" style="background:' + sev[1] + ';color:' + sev[0] + '">' + admEsc(i.severity) + '</span>' +
        '<span class="badge" style="background:' + sta[1] + ';color:' + sta[0] + '">' + admEsc(i.status) + '</span>' +
        '</div></div>' +
        '<div style="font-size:12px;color:var(--color-text-muted);margin-bottom:4px">' + admEsc(i.description) + '</div>' +
        '<div style="font-size:10px;color:var(--color-text-muted)">' + admEsc(i.area) + ' · opened ' + admEsc(i.opened_at) + '</div>' +
        adminBtns +
        '</div>';
    }).join('');
  }

  async function admCreateIssue() {
    var title = document.getElementById('adm-issue-new-title').value;
    var description = document.getElementById('adm-issue-new-description').value;
    var area = document.getElementById('adm-issue-new-area').value;
    var severity = document.getElementById('adm-issue-new-severity').value;
    if (!title.trim()) { alert('Title is required'); return; }
    try {
      var res = await admFetch(admApi('/known-issues'), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title: title, description: description, area: area, severity: severity}),
      });
      if (!res.ok) {
        var body = await res.json();
        alert('Failed to create issue: ' + (body.error || res.status));
        return;
      }
      document.getElementById('adm-issue-new-title').value = '';
      document.getElementById('adm-issue-new-description').value = '';
      document.getElementById('adm-issue-new-area').value = '';
      admLoadIssues();
    } catch (e) {
      alert('Failed to create issue: ' + e.message);
    }
  }
  window.admCreateIssue = admCreateIssue;

  async function admUpdateIssueStatus(id, status) {
    try {
      await admFetch(admApi('/known-issues/' + id), {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({status: status}),
      });
      admLoadIssues();
    } catch (e) {
      alert('Failed to update issue: ' + e.message);
    }
  }
  window.admUpdateIssueStatus = admUpdateIssueStatus;

  async function admDeleteIssue(id) {
    if (!confirm('Delete this issue?')) return;
    try {
      await admFetch(admApi('/known-issues/' + id), {method: 'DELETE'});
      admLoadIssues();
    } catch (e) {
      alert('Failed to delete issue: ' + e.message);
    }
  }
  window.admDeleteIssue = admDeleteIssue;

  // ── Report / Coverage actions ────────────────────────────────────────────
  async function admRegenerate() {
    var btn = document.getElementById('adm-btn-regen');
    var msg = document.getElementById('adm-actions-msg');
    btn.disabled = true;
    msg.textContent = 'Generating report… this takes 2–5 minutes';
    try {
      await admFetch(admApi('/report/generate'), {method: 'POST'});
      admPollReportStatus();
    } catch (e) {
      msg.textContent = 'Failed to start: ' + e.message;
      btn.disabled = false;
    }
  }
  window.admRegenerate = admRegenerate;

  function admPollReportStatus() {
    fetch(admApi('/report/status')).then(function(r) { return r.json(); }).then(function(s) {
      var btn = document.getElementById('adm-btn-regen');
      var msg = document.getElementById('adm-actions-msg');
      if (s.status === 'running') {
        msg.textContent = 'Generating…';
        setTimeout(admPollReportStatus, 2000);
      } else if (s.status === 'done') {
        btn.disabled = false;
        msg.textContent = 'Done -- reload the page to see the new report.';
      } else if (s.status === 'error') {
        btn.disabled = false;
        msg.textContent = 'Error: ' + (s.message || 'unknown');
      } else {
        btn.disabled = false;
      }
    });
  }

  async function admRefreshCoverage() {
    var btn = document.getElementById('adm-btn-cov');
    var msg = document.getElementById('adm-actions-msg');
    btn.disabled = true;
    msg.textContent = 'Running coverage for control-center…';
    try {
      await admFetch(admApi('/coverage/generate'), {method: 'POST'});
      admPollCoverageStatus();
    } catch (e) {
      msg.textContent = 'Failed to start: ' + e.message;
      btn.disabled = false;
    }
  }
  window.admRefreshCoverage = admRefreshCoverage;

  function admPollCoverageStatus() {
    fetch(admApi('/coverage/status')).then(function(r) { return r.json(); }).then(function(s) {
      var btn = document.getElementById('adm-btn-cov');
      var msg = document.getElementById('adm-actions-msg');
      if (s.status === 'running') {
        msg.textContent = 'Running coverage…';
        setTimeout(admPollCoverageStatus, 2000);
      } else if (s.status === 'done') {
        btn.disabled = false;
        msg.textContent = 'Coverage refreshed: ' + (s.message || '');
      } else if (s.status === 'error') {
        btn.disabled = false;
        msg.textContent = 'Error: ' + (s.message || 'unknown');
      } else {
        btn.disabled = false;
      }
    });
  }

  admLoadJobs();
  admLoadIssues();
  admCheckAuth();
})();
</script>
"""
