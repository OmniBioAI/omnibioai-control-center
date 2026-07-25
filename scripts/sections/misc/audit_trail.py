from __future__ import annotations

def _health_audit_trail_section_html() -> str:
    return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">audit trail</div>
  <div class="sec-sub">gateway request/access log · not a compliance-grade audit trail</div>
  <div style="font-size:11px;color:var(--color-text-muted);background:var(--color-bg-surface2);border-radius:8px;padding:10px 12px;margin-bottom:12px">
    This is a gateway request/access log, not a full audit trail in the compliance sense.
    Identity (user_id) is present on only ~1.4% of events -- most traffic (health checks,
    unauthenticated requests) has no associated actor. No application-level audit events
    (e.g. LIMS record access, model registry changes) are currently captured here -- only
    HTTP-gateway-level request/auth/policy/HPC decisions.
  </div>
</div>

<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">events (7d window)</div><div class="kpi-val" id="at-k-total">—</div></div>
  <div class="kpi"><div class="kpi-label">health-check pings</div><div class="kpi-val" id="at-k-health">—</div><div class="kpi-sub" id="at-k-health-pct"></div></div>
  <div class="kpi"><div class="kpi-label">denied</div><div class="kpi-val" style="color:#A32D2D" id="at-k-deny">—</div></div>
  <div class="kpi"><div class="kpi-label">distinct actors</div><div class="kpi-val" id="at-k-actors">—</div></div>
</div>

<div class="section">
  <div class="filter-row">
    <label style="font-size:12px;color:var(--color-text-muted);display:flex;align-items:center;gap:5px;cursor:pointer">
      <input type="checkbox" id="at-hide-health" checked onchange="atApply()"> Hide health-check noise
    </label>
    <select class="filter-sel" id="at-f-type" onchange="atApply()"><option value="">all event types</option></select>
    <select class="filter-sel" id="at-f-decision" onchange="atApply()">
      <option value="">all decisions</option><option value="allow">allow</option><option value="deny">deny</option>
    </select>
    <select class="filter-sel" id="at-f-status" onchange="atApply()"><option value="">all status codes</option></select>
    <select class="filter-sel" id="at-f-reason" onchange="atApply()"><option value="">all reasons</option></select>
  </div>
  <div class="filter-row">
    <label style="font-size:11px;color:var(--color-text-muted)">from <input type="date" id="at-f-from" onchange="atApply()" style="font-family:inherit;font-size:12px;padding:4px 6px;border:0.5px solid var(--color-border);border-radius:6px;background:var(--color-bg-surface);color:var(--color-text)"></label>
    <label style="font-size:11px;color:var(--color-text-muted)">to <input type="date" id="at-f-to" onchange="atApply()" style="font-family:inherit;font-size:12px;padding:4px 6px;border:0.5px solid var(--color-border);border-radius:6px;background:var(--color-bg-surface);color:var(--color-text)"></label>
    <input class="search-inp" type="text" id="at-search" placeholder="search action / endpoint / trace id..." oninput="atApply()">
    <span class="result-count" id="at-count">— items</span>
    <div class="per-pg">per page <select class="filter-sel" onchange="atPerPage(this.value)"><option value="15" selected>15</option><option value="30">30</option><option value="50">50</option></select></div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th onclick="atSort('timestamp')">time</th>
        <th onclick="atSort('event_type')">event type</th>
        <th onclick="atSort('action')">action</th>
        <th onclick="atSort('decision')">decision</th>
        <th class="r" onclick="atSort('status_code')">status</th>
        <th onclick="atSort('reason')">reason</th>
        <th onclick="atSort('user_id')">actor</th>
        <th>trace id</th>
      </tr></thead>
      <tbody id="at-tbody"></tbody>
    </table>
  </div>
  <div class="pg-wrap" id="at-pg"></div>
</div>
</div>
"""
