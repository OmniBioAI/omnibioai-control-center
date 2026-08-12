"""Tests for control_center.compliance.pdf -- the Jinja2/WeasyPrint render
layer. No FastAPI/HTTP involved (that's test_compliance_router.py, a later
step); this file only proves the template renders and produces a real PDF.
"""
from control_center.compliance.pdf import render_report_html, render_report_pdf

_MINIMAL_CONTEXT = {
    "organization_name": "KUMC Research",
    "organization_id": 42,
    "from_date": "2026-08-01",
    "to_date": "2026-08-31",
    "generated_at": "2026-08-11T12:00:00Z",
    "generated_by": "admin@omnibioai.org",
    "summary": {
        "total_users": 12,
        "active_users": 7,
        "total_rag_queries": 340,
        "security_incidents": 2,
    },
    "user_access": [
        {"user_label": "alice@kumc.edu", "login_count": 14, "last_login": "2026-08-30T09:12:00Z", "failed_attempts": 0},
        {"user_label": "bob@kumc.edu", "login_count": 3, "last_login": "2026-08-28T17:45:00Z", "failed_attempts": 2},
    ],
    "rag_queries": [
        {"timestamp": "2026-08-30T09:15:00Z", "user_label": "alice@kumc.edu", "trace_id": "trace-abc123"},
    ],
    "security_events": [
        {"timestamp": "2026-08-29T02:00:00Z", "label": "login_failure", "actor_label": "bob@kumc.edu", "outcome": "failure"},
        {"timestamp": "2026-08-30T09:00:00Z", "label": "login_success", "actor_label": "alice@kumc.edu", "outcome": "success"},
    ],
}

_EMPTY_CONTEXT = {
    **{k: v for k, v in _MINIMAL_CONTEXT.items() if k not in ("user_access", "rag_queries", "security_events", "summary")},
    "summary": {"total_users": 0, "active_users": 0, "total_rag_queries": 0, "security_incidents": 0},
    "user_access": [],
    "rag_queries": [],
    "security_events": [],
}


def test_render_report_html_includes_org_and_period():
    html = render_report_html(_MINIMAL_CONTEXT)
    assert "KUMC Research" in html
    assert "2026-08-01" in html
    assert "2026-08-31" in html
    assert "alice@kumc.edu" in html


def test_render_report_html_includes_omnibioai_logo_mark():
    html = render_report_html(_MINIMAL_CONTEXT)
    # The inline SVG hexagon mark shared with main.py's own header/AdminLogo.tsx.
    assert "<svg" in html
    assert "polygon points=\"16,2 28,8 28,22 16,28 4,22 4,8\"" in html


def test_render_report_html_escapes_user_supplied_values():
    context = {**_MINIMAL_CONTEXT, "organization_name": "<script>alert(1)</script>"}
    html = render_report_html(context)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_report_html_shows_empty_state_notes():
    html = render_report_html(_EMPTY_CONTEXT)
    assert "No login activity recorded in this period." in html
    assert "No RAG queries recorded in this period." in html
    assert "No security events recorded in this period." in html


def test_render_report_html_shows_not_tracked_notes():
    html = render_report_html(_MINIMAL_CONTEXT)
    assert "Session duration is not included in this report" in html
    assert "Dataset views/downloads and data uploads are not tracked" in html


def test_render_report_pdf_produces_valid_pdf_bytes():
    pdf_bytes = render_report_pdf(_MINIMAL_CONTEXT)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000


def test_render_report_pdf_handles_empty_sections():
    pdf_bytes = render_report_pdf(_EMPTY_CONTEXT)
    assert pdf_bytes.startswith(b"%PDF-")
