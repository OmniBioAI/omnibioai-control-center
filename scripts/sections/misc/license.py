"""
OmniBioAI scripts.sections.misc.license.

Purpose:
    Builds report HTML through license_section_html for the control center.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import urllib.error

from shared.health_fetch import _admin_header, ReportAuthenticationError


def _unavailable_html(message: str) -> str:
    return f"""
<div class="tab-section">
<div class="section">
  <div class="sec-title">license</div>
  <div style="font-size:12px;color:var(--color-text-muted)">
    {message}
  </div>
</div>
</div>"""

def license_section_html(control_center_url: str) -> str:
    import urllib.request, json
    # Local report generation is useful without IAM. Do not prompt for a
    # username/password or contact the protected endpoint unless the caller
    # explicitly supplied a short-lived token through the environment.
    if not _admin_header():
        return _unavailable_html(
            "Protected license data skipped. Set CONTROL_CENTER_ACCESS_TOKEN "
            "to include it."
        )
    data: dict = {}
    unavailable = "/license returned no data."
    try:
        request = urllib.request.Request(
            f"{control_center_url.rstrip('/')}/license",
            headers={"User-Agent": "omnibioai-report/1.0", **_admin_header()},
        )
        with urllib.request.urlopen(request, timeout=10) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        # Never include response bodies, URLs, or exception text in diagnostics.
        if e.code == 401:
            raise ReportAuthenticationError(
                "/license: HTTP 401 authentication failure. Supply a valid, unexpired "
                "short-lived IAM-issued operator access token through CONTROL_CENTER_ACCESS_TOKEN."
            ) from None
        if e.code == 403:
            raise ReportAuthenticationError(
                "/license: HTTP 403 insufficient permission. The user corresponding to "
                "CONTROL_CENTER_ACCESS_TOKEN must be authorized for platform.manage_infra."
            ) from None
        if e.code in (404, 501):
            unavailable = f"/license endpoint unavailable or not implemented (HTTP {e.code})."
        else:
            unavailable = f"/license endpoint unavailable (HTTP {e.code})."
    except (urllib.error.URLError, TimeoutError):
        unavailable = "/license endpoint unavailable (connection failed or timed out)."
    except Exception:
        unavailable = "/license response could not be read."

    if not data:
        print(f"[report] {unavailable}", flush=True)
        return _unavailable_html(unavailable)

    seats_used = data.get("seats_used", 0)
    seats_total = data.get("seats_total", 0)
    util_pct = round(100 * seats_used / seats_total, 1) if seats_total else 0
    licenses = data.get("licenses", [])

    _LICENSE_STATUS_COLOR = {
        "active":   ("#EAF3DE", "#3B6D11"),
        "expired":  ("#FCEBEB", "#A32D2D"),
        "expiring": ("#FAEEDA", "#854F0B"),
    }

    def _lic_row(l):
        bg, color = _LICENSE_STATUS_COLOR.get(l.get("status", ""), ("#F1EFE8", "#444441"))
        return f"""<tr>
          <td style="font-weight:600;font-size:12px">{l.get('org','')}</td>
          <td class="mono">{l.get('expires_at','')}</td>
          <td><span class="badge" style="background:{bg};color:{color}">{l.get('status','')}</span></td>
        </tr>"""

    rows = "".join(_lic_row(l) for l in licenses) or \
        '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px">no license records</td></tr>'

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">seats used</div><div class="kpi-val">{seats_used}/{seats_total}</div><div class="kpi-sub">{util_pct}% utilization</div></div>
</div>
<div class="section">
  <div class="sec-title">licenses</div>
  <div class="tbl-wrap">
    <table>
      <thead><tr><th>org</th><th>expires</th><th>status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
</div>
"""
