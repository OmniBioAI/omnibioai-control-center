from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # tools-count degrades gracefully if pyyaml missing

_SECRET_DEFAULT_RE = re.compile(r"\$\{([A-Z0-9_]+):-([^}]*)\}")

_SECRET_MARKERS = (
    "change-me", "changeme", "admin-secret", "secret-change-in-production",
    "omnibioai-secret", "omnibioai-studio-secret", "devtoken", "password", "insecure",
)

_SECRET_SAFE_KEYS = {
    "DEBUG", "DJANGO_DEBUG", "AUTH_ENABLED", "SENTRY_ENVIRONMENT", "REPORT_SCHEDULE_HOURS",
}

def _load_compose(compose_path: Path) -> Optional[Dict[str, Any]]:
    if yaml is None or not compose_path.exists():
        return None
    try:
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def _iter_service_env(env_block: Any):
    """Yield (key, raw_value) pairs from a compose `environment:` block --
    handles both dict-style (KEY: value) and list-style (- KEY=value)."""
    if isinstance(env_block, dict):
        for k, v in env_block.items():
            yield str(k), "" if v is None else str(v)
    elif isinstance(env_block, list):
        for item in env_block:
            item = str(item)
            if "=" in item:
                k, v = item.split("=", 1)
                yield k, v

def secrets_audit_section_html(compose_path: Path) -> str:
    compose = _load_compose(compose_path)
    if compose is None:
        reason = "PyYAML not installed -- cannot parse compose file" if yaml is None \
            else f"compose file not found at {compose_path}"
        return f"""
<div class="tab-section">
<div class="section"><div style="font-size:12px;color:var(--color-text-muted)">{reason}</div></div>
</div>"""

    services = compose.get("services") or {}
    flagged: List[Dict[str, str]] = []
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        for key, raw_value in _iter_service_env(svc.get("environment")):
            if key in _SECRET_SAFE_KEYS:
                continue
            m = _SECRET_DEFAULT_RE.search(raw_value)
            if not m:
                continue
            fallback = m.group(2)
            if fallback and any(marker in fallback.lower() for marker in _SECRET_MARKERS):
                flagged.append({"service": svc_name, "variable": key, "fallback": fallback})

    affected_services = len({f["service"] for f in flagged})
    kpi_color = "#A32D2D" if flagged else "#3B6D11"

    rows = "".join(f"""<tr>
          <td style="font-weight:600;font-size:12px">{f['service']}</td>
          <td class="mono">{f['variable']}</td>
          <td class="mono">{f['fallback']}</td>
          <td><span class="badge" style="background:#FCEBEB;color:#A32D2D">risky default</span></td>
        </tr>""" for f in flagged) or \
        '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px">no risky default fallback values found</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">flagged defaults</div><div class="kpi-val" style="color:{kpi_color}">{len(flagged)}</div></div>
  <div class="kpi"><div class="kpi-label">services affected</div><div class="kpi-val">{affected_services}</div></div>
</div>
<div class="section">
  <div class="sec-title">secrets audit</div>
  <div class="sec-sub">scans {compose_path.name} for ${{VAR:-default}} env fallbacks that look like placeholder secrets -- heuristic on the fallback text only, not proof the placeholder is actually deployed</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>service</th><th>variable</th><th>fallback value</th><th>flag</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
</div>
"""
