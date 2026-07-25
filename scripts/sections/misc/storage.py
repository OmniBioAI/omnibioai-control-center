from __future__ import annotations

def storage_section_html(control_center_url: str) -> str:
    """Fetch disk/storage usage from control center."""
    import urllib.request, json
    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/storage", timeout=200
        ) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[report] storage_section_html failed: {type(e).__name__}: {e}", flush=True)

    if not data:
        return '<div class="tab-section"><h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Storage</h2><p style="color:var(--color-text-muted);font-size:13px">Unavailable</p></div>'

    disk = data.get("disk", {})
    total_gb = round(disk.get("total", 0) / 1e9, 1)
    used_gb  = round(disk.get("used",  0) / 1e9, 1)
    free_gb  = round(disk.get("free",  0) / 1e9, 1)
    pct_used = disk.get("pct_used", 0)
    pct_free = round(100 - pct_used, 1)

    categories = data.get("categories", {})
    ref_indexes = data.get("reference_indexes", {})

    def fmt_gb(b):
        gb = b / 1e9
        if gb >= 1:
            return f"{gb:.1f} GB"
        return f"{b/1e6:.0f} MB"

    bar_color = "#00e5a0" if pct_used < 80 else "#f59e0b" if pct_used < 90 else "#ef4444"

    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)

    CAT_COLORS = [
        "#00e5a0", "#a855f7", "#f59e0b", "#06b6d4",
        "#ef4444", "#8b5cf6", "#10b981", "#f97316"
    ]

    cat_cards = ""
    for i, (name, size) in enumerate(sorted_cats):
        color = CAT_COLORS[i % len(CAT_COLORS)]
        pct = round(size / disk.get("used", 1) * 100, 1)
        cat_cards += f"""
        <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
          border-radius:8px;padding:12px 16px;display:flex;align-items:center;
          justify-content:space-between;gap:12px">
          <div style="display:flex;align-items:center;gap:10px">
            <div style="width:10px;height:10px;border-radius:50%;
              background:{color};flex-shrink:0"></div>
            <span style="font-size:12px;font-weight:600;
              color:var(--color-text)">{name}</span>
          </div>
          <div style="text-align:right">
            <div style="font-size:13px;font-weight:700;
              color:{color}">{fmt_gb(size)}</div>
            <div style="font-size:10px;color:var(--color-text-muted)">{pct}%</div>
          </div>
        </div>"""

    sorted_orgs = sorted(ref_indexes.items(), key=lambda x: x[1], reverse=True)
    max_org_size = sorted_orgs[0][1] if sorted_orgs else 1

    ORG_ICONS = {
        "human": "🧬", "mouse": "🐭", "rat": "🐀",
        "zebrafish": "🐟", "drosophila": "🪰", "yeast": "🧫",
        "chimpanzee": "🐒", "macaque": "🐵", "celegans": "🪱",
        "arabidopsis": "🌿", "pig": "🐷", "chicken": "🐔",
    }
    org_bars = ""
    for org_key, size in sorted_orgs[:15]:
        org_name = org_key.split("_")[0]
        icon = ORG_ICONS.get(org_name, "🧬")
        pct_bar = round(size / max_org_size * 100)
        org_bars += f"""
        <div style="display:grid;grid-template-columns:140px 1fr 80px;
          gap:8px;align-items:center;margin-bottom:6px">
          <span style="font-size:11px;color:var(--color-text);
            font-family:var(--font-mono);overflow:hidden;
            text-overflow:ellipsis;white-space:nowrap">
            {icon} {org_key}
          </span>
          <div style="background:var(--color-border);border-radius:4px;height:8px">
            <div style="width:{pct_bar}%;height:100%;border-radius:4px;
              background:#a855f7"></div>
          </div>
          <span style="font-size:11px;color:var(--color-text-muted);
            text-align:right">{fmt_gb(size)}</span>
        </div>"""

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Storage</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    Disk usage · Reference data · Workflow outputs
  </p>

  <!-- Disk usage bar -->
  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;padding:20px;margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;
      align-items:baseline;margin-bottom:10px">
      <span style="font-weight:700;font-size:14px">NVMe Storage</span>
      <span style="font-size:12px;color:var(--color-text-muted)">
        {used_gb} GB used of {total_gb} GB
      </span>
    </div>
    <div style="background:var(--color-border);border-radius:6px;
      height:16px;overflow:hidden;margin-bottom:8px">
      <div style="width:{pct_used}%;height:100%;
        background:{bar_color};border-radius:6px;
        transition:width 0.3s ease"></div>
    </div>
    <div style="display:flex;justify-content:space-between">
      <span style="font-size:11px;color:{bar_color};font-weight:700">
        {pct_used}% used
      </span>
      <span style="font-size:11px;color:#00e5a0;font-weight:700">
        {free_gb} GB free ({pct_free}%)
      </span>
    </div>
  </div>

  <!-- Two column layout -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">

    <!-- Category breakdown -->
    <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
      border-radius:10px;overflow:hidden">
      <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
        <span style="font-weight:700;font-size:13px">Data Categories</span>
      </div>
      <div style="padding:12px;display:flex;flex-direction:column;gap:8px">
        {cat_cards if cat_cards else
          '<p style="color:var(--color-text-muted);font-size:12px;padding:8px">No data found</p>'}
      </div>
    </div>

    <!-- Reference index breakdown -->
    <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
      border-radius:10px;overflow:hidden">
      <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
        <span style="font-weight:700;font-size:13px">Reference Indexes by Organism</span>
      </div>
      <div style="padding:16px">
        {org_bars if org_bars else
          '<p style="color:var(--color-text-muted);font-size:12px">No indexes found</p>'}
      </div>
    </div>
  </div>
</div>"""
