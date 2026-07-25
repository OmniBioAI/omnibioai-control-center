from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:
    yaml = None  # tools-count degrades gracefully if pyyaml missing

from sections.misc.secrets_audit import _load_compose, _SECRET_DEFAULT_RE

def _parse_port_mapping(mapping: str) -> Dict[str, Any]:
    s = str(mapping).strip()
    m = _SECRET_DEFAULT_RE.match(s)
    if m and s.startswith(m.group(0)):
        bind = m.group(2) or "0.0.0.0"
        rest = s[len(m.group(0)):]
        if rest.startswith(":"):
            rest = rest[1:]
        parts = rest.split(":")
    else:
        parts = s.split(":")
        if len(parts) >= 3:
            bind = parts[0]
            parts = parts[1:]
        else:
            bind = "0.0.0.0"
    host_port = parts[0] if parts else ""
    container_port = parts[1] if len(parts) > 1 else host_port
    external = bind not in ("127.0.0.1", "localhost")
    return {"raw": s, "bind": bind, "host_port": host_port,
            "container_port": container_port, "external": external}

def exposed_ports_section_html(compose_path: Path) -> str:
    compose = _load_compose(compose_path)
    if compose is None:
        reason = "PyYAML not installed -- cannot parse compose file" if yaml is None \
            else f"compose file not found at {compose_path}"
        return f"""
<div class="tab-section">
<div class="section"><div style="font-size:12px;color:var(--color-text-muted)">{reason}</div></div>
</div>"""

    services = compose.get("services") or {}
    mappings: List[Dict[str, Any]] = []
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        for p in (svc.get("ports") or []):
            parsed = _parse_port_mapping(p)
            parsed["service"] = svc_name
            mappings.append(parsed)

    mappings.sort(key=lambda m: (not m["external"], m["service"]))
    external_count = sum(1 for m in mappings if m["external"])
    localhost_count = len(mappings) - external_count

    def _row(m: Dict[str, Any]) -> str:
        if m["external"]:
            badge = '<span class="badge" style="background:#FCEBEB;color:#A32D2D">external</span>'
        else:
            badge = '<span class="badge" style="background:#EAF3DE;color:#3B6D11">localhost-only</span>'
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{m['service']}</td>
          <td class="mono">{m['raw']}</td>
          <td class="mono">{m['bind']}:{m['host_port']} -> {m['container_port']}</td>
          <td>{badge}</td>
        </tr>"""

    rows = "".join(_row(m) for m in mappings) or \
        '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px">no port mappings found</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">total mappings</div><div class="kpi-val">{len(mappings)}</div></div>
  <div class="kpi"><div class="kpi-label">external</div><div class="kpi-val" style="color:#A32D2D">{external_count}</div></div>
  <div class="kpi"><div class="kpi-label">localhost-only</div><div class="kpi-val" style="color:#3B6D11">{localhost_count}</div></div>
</div>
<div class="section">
  <div class="sec-title">exposed ports</div>
  <div class="sec-sub">port mappings parsed from {compose_path.name} · sorted external-first</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>service</th><th>raw mapping</th><th>bind:host -> container</th><th>exposure</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
</div>
"""
