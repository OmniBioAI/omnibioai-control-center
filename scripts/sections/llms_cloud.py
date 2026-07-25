from __future__ import annotations

def llm_section_html(control_center_url: str) -> str:
    """Fetch Ollama models and API key status from control center."""
    import urllib.request, json

    models = []
    api_keys = {}
    ollama_status = "unreachable"

    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/llms", timeout=5
        ) as r:
            data = json.loads(r.read())
            models = data.get("ollama", {}).get("models", [])
            ollama_status = data.get("ollama", {}).get("status", "unknown")
            api_keys = data.get("api_keys", {})
    except Exception:
        pass

    model_rows = ""
    for m in models:
        size = m.get("size_gb", 0)
        name = m.get("name", "")
        modified = m.get("modified", "")
        model_rows += f"""
          <tr>
            <td style="padding:10px 16px;font-family:monospace;color:#a855f7">{name}</td>
            <td style="padding:10px 16px;color:var(--color-text-soft)">{size} GB</td>
            <td style="padding:10px 16px;color:var(--color-text-muted)">{modified}</td>
          </tr>"""

    if not model_rows:
        model_rows = '<tr><td colspan="3" style="padding:20px 16px;color:var(--color-text-muted)">No models installed or Ollama unreachable</td></tr>'

    key_rows = ""
    for key, info in api_keys.items():
        configured = info.get("configured", False)
        label = info.get("label", key)
        badge_color = "#00e5a0" if configured else "#6b7280"
        badge_bg = "rgba(0,229,160,0.15)" if configured else "rgba(107,114,128,0.15)"
        badge_text = "CONFIGURED" if configured else "NOT SET"
        key_rows += f"""
          <tr>
            <td style="padding:10px 16px;color:var(--color-text)">{label}</td>
            <td style="padding:10px 16px">
              <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;
                background:{badge_bg};color:{badge_color};
                border:1px solid {badge_color}33">{badge_text}</span>
            </td>
          </tr>"""

    if not key_rows:
        key_rows = '<tr><td colspan="2" style="padding:20px 16px;color:var(--color-text-muted)">No API key data available</td></tr>'

    ollama_badge = "🟢 running" if ollama_status == "running" else "🔴 unreachable"

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Local LLMs</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    Ollama models installed on this machine · API key configuration status
  </p>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden;margin-bottom:20px">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border);
      display:flex;align-items:center;justify-content:space-between">
      <span style="font-weight:700;font-size:13px">Ollama — Local LLMs</span>
      <span style="font-size:12px;color:var(--color-text-muted)">{ollama_badge}</span>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="border-bottom:1px solid var(--color-border);
          background:rgba(255,255,255,0.02)">
          <th style="padding:8px 16px;text-align:left;font-size:10px;
            font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
            color:var(--color-text-muted)">Model</th>
          <th style="padding:8px 16px;text-align:left;font-size:10px;
            font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
            color:var(--color-text-muted)">Size</th>
          <th style="padding:8px 16px;text-align:left;font-size:10px;
            font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
            color:var(--color-text-muted)">Modified</th>
        </tr>
      </thead>
      <tbody>{model_rows}</tbody>
    </table>
  </div>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
      <span style="font-weight:700;font-size:13px">Cloud API Keys</span>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <tbody>{key_rows}</tbody>
    </table>
  </div>
</div>"""

def cloud_section_html(control_center_url: str) -> str:
    """Fetch cloud/HPC execution backend config from control center."""
    import urllib.request, json

    backends = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/cloud", timeout=5
        ) as r:
            backends = json.loads(r.read())
    except Exception:
        pass

    ICONS = {
        "local": "🖥", "slurm": "⚡", "aws": "☁️",
        "azure": "🔷", "gcp": "🟡", "kubernetes": "⎈"
    }

    cards = ""
    for key, info in backends.items():
        configured = info.get("configured", False)
        label = info.get("label", key)
        icon = ICONS.get(key, "🔧")
        border = "rgba(0,229,160,0.25)" if configured else "var(--color-border)"
        badge_color = "#00e5a0" if configured else "#6b7280"
        badge_bg = "rgba(0,229,160,0.15)" if configured else "rgba(107,114,128,0.15)"
        badge_text = "✓ CONFIGURED" if configured else "NOT CONFIGURED"

        details = ""
        for field in ["region", "project", "account", "queue", "host", "context", "note"]:
            val = info.get(field, "")
            if val:
                details += f"""<div style="display:flex;gap:8px;font-size:11px;margin-top:4px">
                  <span style="color:var(--color-text-muted);min-width:60px">{field}</span>
                  <span style="font-family:monospace;color:var(--color-text-soft)">{val}</span>
                </div>"""

        cards += f"""
          <div style="background:var(--color-bg-surface);
            border:1px solid {border};border-radius:10px;
            padding:16px 18px">
            <div style="display:flex;align-items:center;
              justify-content:space-between;margin-bottom:8px">
              <div style="display:flex;align-items:center;gap:8px">
                <span style="font-size:20px">{icon}</span>
                <span style="font-weight:700;font-size:14px">{label}</span>
              </div>
              <span style="font-size:10px;font-weight:700;padding:2px 8px;
                border-radius:99px;background:{badge_bg};color:{badge_color};
                border:1px solid {badge_color}33">{badge_text}</span>
            </div>
            {details}
          </div>"""

    if not cards:
        cards = '<p style="color:var(--color-text-muted)">Could not reach control center</p>'

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Execution Backends</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    Cloud and HPC execution backend configuration status
  </p>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px">
    {cards}
  </div>
</div>"""

def cost_tracking_placeholder_section_html() -> str:
    """"Coming soon" placeholder for the sidebar's Cost Tracking leaf.

    Cost tracking needs real AWS/GCP/Azure billing-API credentials tied to
    an active paying account -- separate IAM permissions from whatever's
    already used for compute/storage -- and this deployment doesn't have
    those yet (it runs primarily on local/Slurm backends today). Not wired
    to any endpoint; no JSON contract to document since none is planned
    until real billing access exists.
    """
    return """
<div class="tab-section">
<div class="section">
  <div class="sec-title">cost tracking</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    Coming soon. Cost tracking requires real AWS/GCP/Azure billing API credentials tied to an
    active paying account, which aren't in place for this deployment yet -- it currently runs
    primarily on local/Slurm backends. This view will be built once real cloud billing access
    is available.
  </div>
</div>
</div>"""
