from __future__ import annotations

def task_queue_section_html(control_center_url: str) -> str:
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/celery", timeout=10
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] task_queue_section_html failed: {type(e).__name__}: {e}", flush=True)

    workers = data.get("workers", []) if data else []
    recent_tasks = data.get("recent_tasks", []) if data else []

    if not workers and not recent_tasks:
        return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">task queue</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    /celery endpoint not implemented yet. Expected JSON shape:
    <pre style="font-size:11px;color:var(--color-text-muted);margin-top:8px;white-space:pre-wrap">{
  "workers": [{"name": str, "status": "online"|"offline", "active_tasks": int}, ...],
  "recent_tasks": [{"name": str, "state": str, "runtime_s": float}, ...]
}</pre>
  </div>
</div>
</div>"""

    _TASK_STATE_COLOR = {
        "SUCCESS": ("#EAF3DE", "#3B6D11"), "FAILURE": ("#FCEBEB", "#A32D2D"),
        "STARTED": ("#E6F1FB", "#185FA5"), "PENDING": ("#FAEEDA", "#854F0B"),
        "RETRY":   ("#FAEEDA", "#854F0B"),
    }

    def _worker_row(w):
        online = w.get("status") == "online"
        bg, color = ("#EAF3DE", "#3B6D11") if online else ("#FCEBEB", "#A32D2D")
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{w.get('name','')}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{w.get('status','unknown')}</span></td>
          <td class="r">{w.get('active_tasks',0)}</td>
        </tr>"""

    def _task_row(t):
        bg, color = _TASK_STATE_COLOR.get(t.get("state", ""), ("#F1EFE8", "#444441"))
        return f"""<tr>
          <td style="font-size:12px">{t.get('name','')}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{t.get('state','')}</span></td>
          <td class="r">{t.get('runtime_s','—')}s</td>
        </tr>"""

    worker_rows = "".join(_worker_row(w) for w in workers) or \
        '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px">no workers reported</td></tr>'
    task_rows = "".join(_task_row(t) for t in recent_tasks) or \
        '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px">no recent tasks</td></tr>'

    return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">workers</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>name</th><th>status</th><th class="r">active tasks</th></tr></thead>
      <tbody>{worker_rows}</tbody>
    </table>
  </div>
</div>
<div class="section">
  <div class="sec-title">recent tasks</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>task</th><th>state</th><th class="r">runtime</th></tr></thead>
      <tbody>{task_rows}</tbody>
    </table>
  </div>
</div>
</div>
"""
