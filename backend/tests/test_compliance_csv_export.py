"""Unit tests for control_center.compliance.csv_export."""
import csv
import io

from control_center.compliance.csv_export import render_report_csv

_CONTEXT = {
    "organization_name": "KUMC Research",
    "organization_id": 1,
    "from_date": "2026-08-01",
    "to_date": "2026-08-31",
    "generated_at": "2026-08-11T12:00:00Z",
    "generated_by": "admin@omnibioai.org",
    "summary": {"total_users": 2, "active_users": 1, "total_rag_queries": 1, "security_incidents": 1},
    "user_access": [
        {"user_label": "alice@kumc.edu", "login_count": 5, "last_login": "2026-08-20T10:00:00", "failed_attempts": 0},
    ],
    "rag_queries": [
        {"timestamp": "2026-08-10T09:00:00", "user_label": "alice@kumc.edu", "trace_id": "trace-1"},
    ],
    "security_events": [
        {"timestamp": "2026-08-13T10:00:00", "label": "Role Assignment Denied", "actor_label": "bob@kumc.edu", "outcome": "deny"},
    ],
}


def test_includes_org_and_period_header():
    text = render_report_csv(_CONTEXT)
    assert "KUMC Research" in text
    assert "2026-08-01" in text
    assert "2026-08-31" in text


def test_includes_all_four_section_markers():
    text = render_report_csv(_CONTEXT)
    assert "## Section 1: Executive Summary" in text
    assert "## Section 2: User Access Log" in text
    assert "## Section 3: RAG Query Log" in text
    assert "## Section 4: Security Events" in text


def test_is_parseable_as_csv():
    text = render_report_csv(_CONTEXT)
    rows = list(csv.reader(io.StringIO(text)))
    assert any(row == ["alice@kumc.edu", "5", "2026-08-20T10:00:00", "0"] for row in rows)
    assert any(row == ["2026-08-10T09:00:00", "alice@kumc.edu", "trace-1"] for row in rows)
    assert any(row == ["2026-08-13T10:00:00", "Role Assignment Denied", "bob@kumc.edu", "deny"] for row in rows)


def test_handles_empty_sections():
    context = {**_CONTEXT, "user_access": [], "rag_queries": [], "security_events": []}
    text = render_report_csv(context)
    assert "## Section 4: Security Events" in text  # doesn't blow up on empty lists


def test_missing_trace_id_renders_as_empty_string():
    context = {**_CONTEXT, "rag_queries": [{"timestamp": "2026-08-10T09:00:00", "user_label": "alice@kumc.edu", "trace_id": None}]}
    text = render_report_csv(context)
    rows = list(csv.reader(io.StringIO(text)))
    assert any(row == ["2026-08-10T09:00:00", "alice@kumc.edu", ""] for row in rows)
