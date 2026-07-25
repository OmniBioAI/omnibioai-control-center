from __future__ import annotations

from typing import List, Optional, Tuple

SHARED_CSS = """
<style id="shared">
:root {
  --color-bg:              #0d1117;
  --color-bg-surface:      #161b27;
  --color-bg-surface2:     #1e2435;
  --color-border:          #2a2d3e;
  --color-text:            #e2e8f0;
  --color-text-secondary:  #9ca3af;
  --color-text-muted:      #6b7280;
  --color-accent:          #00e5a0;
  --color-accent-dim:      rgba(0,229,160,0.10);
  --color-success:         #22c55e;
  --color-success-dim:     rgba(34,197,94,0.12);
  --color-success-border:  rgba(34,197,94,0.30);
  --color-danger:          #ef4444;
  --color-danger-dim:      rgba(239,68,68,0.12);
  --color-danger-border:   rgba(239,68,68,0.30);
  --color-warning:         #f59e0b;
  --color-warning-dim:     rgba(245,158,11,0.12);
  --color-warning-border:  rgba(245,158,11,0.30);
  --color-info:            #0094ff;
  --color-info-dim:        rgba(0,148,255,0.10);
  --radius-sm:             6px;
  --radius-lg:             12px;
  --radius-pill:           9999px;
  --font-sans:             'IBM Plex Sans', system-ui, sans-serif;
  --font-size-xs:          11px;
  --font-size-sm:          12px;
  --font-size-base:        13px;

  /* Architecture lane colors — kept unchanged, encode domain meaning */
  --c-teal:   #00e5a0; --c-teal-bg:   rgba(0,229,160,0.08); --c-teal-bd:   rgba(0,229,160,0.25);
  --c-blue:   #0094ff; --c-blue-bg:   rgba(0,148,255,0.08); --c-blue-bd:   rgba(0,148,255,0.25);
  --c-red:    #ef4444; --c-red-bg:    rgba(239,68,68,0.08);  --c-red-bd:    rgba(239,68,68,0.25);
  --c-amber:  #f59e0b; --c-amber-bg:  rgba(245,158,11,0.08); --c-amber-bd:  rgba(245,158,11,0.25);
  --c-purple: #a855f7; --c-purple-bg: rgba(168,85,247,0.08); --c-purple-bd: rgba(168,85,247,0.25);
  --c-gray:   #9ca3af; --c-gray-bg:   rgba(107,114,128,0.08);--c-gray-bd:   rgba(107,114,128,0.25);
  --c-green:  #22c55e; --c-green-bg:  rgba(34,197,94,0.08);  --c-green-bd:  rgba(34,197,94,0.25);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font-sans);background:transparent}
.tab-section{padding:20px 0}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:16px}
.kpi{background:var(--color-bg-surface);border-radius:8px;padding:12px 14px}
.kpi-label{font-size:11px;color:var(--color-text-muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.04em}
.kpi-val{font-size:20px;font-weight:600;color:var(--color-text)}
.kpi-sub{font-size:11px;color:var(--color-text-muted);margin-top:2px}
.section{background:var(--color-bg-surface);border:0.5px solid var(--color-border);border-radius:12px;padding:16px;margin-bottom:12px}
.sec-title{font-size:13px;font-weight:600;color:var(--color-text);margin-bottom:2px}
.sec-sub{font-size:11px;color:var(--color-text-muted);margin-bottom:14px}
.badge{font-size:10px;padding:2px 7px;border-radius:99px;font-weight:600;white-space:nowrap}
.tbl-wrap{border:0.5px solid var(--color-border);border-radius:12px;overflow:hidden;margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{padding:8px 12px;font-size:11px;font-weight:600;color:var(--color-text-muted);background:var(--color-bg-surface);
   border-bottom:0.5px solid var(--color-border);text-align:left;white-space:nowrap;
   cursor:pointer;user-select:none;text-transform:uppercase;letter-spacing:.04em}
th:hover{color:var(--color-text)}
th.r,td.r{text-align:right}
td{padding:7px 12px;border-bottom:0.5px solid var(--color-border);color:var(--color-text) !important;vertical-align:middle;background:var(--color-bg-surface) !important}
td.mono{font-family:monospace;font-size:11px;color:var(--color-text) !important;
        max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--color-bg-surface) !important}
.filter-row{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.search-inp{flex:1;min-width:140px;padding:6px 10px;font-size:12px;
            border:0.5px solid var(--color-border);border-radius:8px;background:var(--color-bg-surface);color:var(--color-text)}
.filter-sel{padding:6px 10px;font-size:12px;border:0.5px solid var(--color-border);
            border-radius:8px;background:var(--color-bg-surface);color:var(--color-text);cursor:pointer}
.result-count{font-size:11px;color:var(--color-text-muted);white-space:nowrap}
.pg-wrap{display:flex;align-items:center;gap:6px;justify-content:center;padding:4px 0}
.pg-btn{padding:5px 10px;font-size:12px;border:0.5px solid var(--color-border);border-radius:8px;
        background:var(--color-bg-surface);color:var(--color-text-muted);cursor:pointer;min-width:32px;text-align:center}
.pg-btn:hover:not(:disabled){background:var(--color-bg-surface);color:var(--color-text)}
.pg-btn:disabled{opacity:.4;cursor:not-allowed}
.pg-btn.active{background:var(--color-accent);color:#000;border-color:var(--color-accent)}
.pg-info{font-size:11px;color:var(--color-text-muted);margin:0 4px}
.per-pg{font-size:11px;color:var(--color-text-muted);display:flex;align-items:center;gap:6px;margin-left:auto}
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.bar-label{font-size:11px;color:var(--color-text-muted);text-align:right;flex-shrink:0;
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{flex:1;border-radius:3px;overflow:hidden;position:relative;background:var(--color-border)}
.bar-fill{height:100%;border-radius:3px;min-width:2px}
.bar-val{font-size:10px;font-weight:600;white-space:nowrap;
         position:absolute;right:6px;top:50%;transform:translateY(-50%)}
.share-bar{width:50px;height:4px;background:var(--color-border);border-radius:2px;
           overflow:hidden;display:inline-block;vertical-align:middle;margin-left:6px}
.share-fill{height:100%;border-radius:2px}
.donut-center{position:absolute;inset:0;display:flex;flex-direction:column;
              align-items:center;justify-content:center;pointer-events:none}
.donut-center-val{font-size:18px;font-weight:700;color:var(--color-text)}
.donut-center-lbl{font-size:10px;color:var(--color-text-muted)}
.legend-item{display:flex;align-items:center;gap:6px;padding:3px 0;
             font-size:11px;color:var(--color-text-muted)}
.legend-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0}
.legend-pct{margin-left:auto;font-size:11px;font-weight:600;color:var(--color-text)}
.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0}
.dot-up{background:var(--color-success)}.dot-down{background:var(--color-danger)}
.dot-warn{background:var(--color-warning)}.dot-loading{background:var(--color-text-muted)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.dot-loading{animation:pulse 1s ease-in-out infinite}
</style>
"""

_CHARTJS = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/'
    'Chart.js/4.4.1/chart.umd.js"></script>'
)

def misc_section_html(sub_tabs: List[Tuple[str, str, str]], group_id: str = "misc",
                       render_nav: bool = True, header_html: str = "") -> str:
    """
    sub_tabs: list of (id, label, html_content) tuples. Renders a sub-nav
    plus one panel per sub-tab; first sub-tab is active by default.

    group_id namespaces the DOM ids/JS scope for this instance -- if this
    function is called more than once on the same page (e.g. one call for
    Misc, another for a combined LLMs & Cloud tab), each call's panel ids
    and sub-tab toggling must stay independent. Panel ids are namespaced
    as "misc-panel-{group_id}-{sid}" and miscSub() only ever queries
    within this instance's own wrapper div (id "misc-wrap-{group_id}"),
    so two instances never hide/show each other's panels.

    render_nav=False skips the inline sub-nav button row (panels + the
    miscSub() toggle function are unchanged) -- used when an external
    navigation UI (the sidebar) already lists these sub-tabs and drives
    miscSub() itself, so the inline row would just be a redundant second
    nav for the same choice.

    header_html renders once, above the nav row/panels, and is never
    hidden by the sub-tab switch -- for content that applies across all
    of a group's sub-tabs (e.g. a KPI strip fed by one shared fetch).
    """
    if not sub_tabs:
        return '<div class="tab-section"><div style="font-size:12px;color:var(--color-text-muted)">No misc sections configured yet.</div></div>'

    nav_buttons = ""
    panels = ""
    for i, (sid, label, content) in enumerate(sub_tabs):
        active = i == 0
        color = "#00e5a0" if active else "#6b7280"
        weight = "600" if active else "400"
        border = "#00e5a0" if active else "transparent"
        panel_id = f"misc-panel-{group_id}-{sid}"
        if render_nav:
            nav_buttons += (
                f'<button class="misc-sub" data-sub="{panel_id}" '
                f'onclick="miscSub(\'{group_id}\',\'{panel_id}\')" '
                f'style="padding:10px 16px;font-size:13px;color:{color};font-weight:{weight};'
                f'background:none;border:none;border-bottom:2px solid {border};cursor:pointer;'
                f'white-space:nowrap;margin-bottom:-1px;font-family:inherit">{label}</button>'
            )
        display = "" if active else "display:none"
        panels += f'<div id="{panel_id}" style="{display}">{content}</div>'

    nav_row = (
        f'<div style="display:flex;border-bottom:1px solid #2a2d3e;margin-bottom:16px">\n  {nav_buttons}\n</div>\n'
        if render_nav else ""
    )

    return f"""
<div class="tab-section">
<div id="misc-wrap-{group_id}">
{header_html}{nav_row}{panels}
</div>
</div>

<script>
function miscSub(groupId, id){{
  var wrap=document.getElementById('misc-wrap-'+groupId);
  if(!wrap) return;
  wrap.querySelectorAll('[id^="misc-panel-'+groupId+'-"]').forEach(function(p){{p.style.display='none';}});
  var target=document.getElementById(id);
  if(target)target.style.display='';
  wrap.querySelectorAll('.misc-sub').forEach(function(b){{
    var a=b.dataset.sub===id;
    b.style.color=a?'#00e5a0':'#6b7280';
    b.style.fontWeight=a?'600':'400';
    b.style.borderBottomColor=a?'#00e5a0':'transparent';
  }});
}}
</script>
"""

def sidebar_nav_html(spec: List[Tuple[str, str, Optional[List[Tuple[str, str]]]]]) -> str:
    """Renders the left sidebar nav markup from SIDEBAR_NAV_SPEC.

    Group labels toggle their own child list (sbnavToggleGroup) rather than
    navigating; leaves (top-level or child) select a panel directly
    (sbnavSelectTop / sbnavSelectChild). URL-hash read/write is layered on
    top of these same two functions separately, not handled here.
    """
    items = ""
    for i, (top_id, label, children) in enumerate(spec):
        is_default_active = i == 0
        if children:
            child_buttons = "".join(
                f'<button class="sbnav-item sbnav-child" data-top="{top_id}" data-child="{cid}" '
                f'onclick="sbnavSelectChild(\'{top_id}\',\'{cid}\')">{clabel}</button>'
                for cid, clabel in children
            )
            items += f"""
<div class="sbnav-group" data-top="{top_id}">
  <button class="sbnav-item sbnav-group-label" data-top="{top_id}" onclick="sbnavToggleGroup('{top_id}')">
    <span class="sbnav-caret">&#9656;</span>{label}
  </button>
  <div class="sbnav-children" id="sbnav-children-{top_id}">{child_buttons}</div>
</div>"""
        else:
            active_cls = " active" if is_default_active else ""
            items += (
                f'\n<button class="sbnav-item sbnav-leaf{active_cls}" data-top="{top_id}" '
                f'onclick="sbnavSelectTop(\'{top_id}\')">{label}</button>'
            )
    return items
