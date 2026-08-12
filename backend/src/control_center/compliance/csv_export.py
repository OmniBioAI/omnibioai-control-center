"""HIPAA Basic Compliance Report v0.8.0: renders the same report context
pdf.py consumes into a single CSV -- one section per block, separated by
a blank row and a "## Section Name" marker row, the same shape a reader
opening this in a spreadsheet app or a plain text editor can both follow
without a header line lying about how many columns the rest of the file
has (Section 1 is a 2-column metric/value table; Sections 2-4 are wider).
No new csv-writing convention invented -- csv.writer + io.StringIO is the
exact mechanism analytics/router.py's own /analytics/export already uses.
"""
from __future__ import annotations

import csv
import io
from typing import Any


def render_report_csv(context: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["HIPAA Basic Compliance Report"])
    writer.writerow(["Organization", f"{context['organization_name']} (org #{context['organization_id']})"])
    writer.writerow(["Period", f"{context['from_date']} to {context['to_date']}"])
    writer.writerow(["Generated", f"{context['generated_at']} by {context['generated_by']}"])
    writer.writerow([])

    writer.writerow(["## Section 1: Executive Summary"])
    writer.writerow(["Metric", "Value"])
    summary = context["summary"]
    writer.writerow(["Total Users", summary["total_users"]])
    writer.writerow(["Active Users In Period", summary["active_users"]])
    writer.writerow(["RAG Queries", summary["total_rag_queries"]])
    writer.writerow(["Security Incidents", summary["security_incidents"]])
    writer.writerow([])

    writer.writerow(["## Section 2: User Access Log"])
    writer.writerow(["User", "Login Count", "Last Login", "Failed Attempts"])
    for row in context["user_access"]:
        writer.writerow([row["user_label"], row["login_count"], row["last_login"], row["failed_attempts"]])
    writer.writerow([])

    writer.writerow(["## Section 3: RAG Query Log"])
    writer.writerow(["Timestamp", "User", "Trace ID"])
    for row in context["rag_queries"]:
        writer.writerow([row["timestamp"], row["user_label"], row["trace_id"] or ""])
    writer.writerow([])

    writer.writerow(["## Section 4: Security Events"])
    writer.writerow(["Timestamp", "Event", "Actor", "Outcome"])
    for row in context["security_events"]:
        writer.writerow([row["timestamp"], row["label"], row["actor_label"], row["outcome"]])

    return buffer.getvalue()
