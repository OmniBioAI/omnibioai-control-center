"""Idempotent seed of the initial HIPAA compliance history -- V1 ships
with no automatic producer (see api/routes_hipaa_compliance.py's own
module docstring), so the already-completed HIPAA audit-integrity
changes are seeded here by hand, once. Called from
db.py::_ensure_initialized on first real database access (production),
skipped entirely by the test suite (tests override the `get_db`
dependency and never reach this module through it).

Every field below was verified directly against GitHub (`git show`/
`gh pr view`/`gh run list` against the real omnibioai-security-audit and
omnibioai-control-center repos) at the time this module was written, not
recalled from memory or assumed. Nothing here is fabricated:

- SECURITY-AUDIT-PR8, SECURITY-AUDIT-PR9: merged, omnibioai-security-audit.
- CC-PR45, CC-PR46: merged, omnibioai-control-center. CC-PR46 (HIPAA
  PR3d) merged *while this feature was being built* -- it was still OPEN
  when this file was first drafted, and was deliberately not marked
  "released" until re-verified as merged (mergeCommit 3b86b64, CI
  success) -- see this repo's own PR description for the full timeline.

None of these four had a recorded GitHub PR review (`reviews: []` on
every one, self-authored and self-merged by the same account) -- reviewer
is left None rather than inventing an approver.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from control_center.hipaa_compliance.models import HipaaComplianceChange

_SELF_MERGED_NOTE = (
    "Self-authored and self-merged by man4ish; no formal GitHub PR review "
    "recorded (reviews: [])."
)

SEED_CHANGES: list[dict] = [
    {
        "change_id": "SECURITY-AUDIT-PR8",
        "title": "Sign this service's own native audit:events payloads (HIPAA PR3b)",
        "change_date": date(2026, 8, 14),
        "repository": "omnibioai-security-audit",
        "branch": "security/hipaa-audit-producer-signing",
        "commit_sha": "ab2790f8f4045c21a40f1a2a757b234a90555f56",
        "pr_number": 8,
        "description": (
            "AuditLogger.log() -- this service's own native audit:events producer -- "
            "was the sixth and last of six real producers found unsigned by the HIPAA "
            "audit-integrity assessment. Now signs the exact wire `data` string with "
            "AuditConfig.EVENT_SIGNING_SECRET before publishing, importing "
            "audit.signing.sign_audit_event directly (same repo, no hand-port/drift risk "
            "unlike the other five producers)."
        ),
        "control_category": "audit_event_signing",
        "affected_component": "audit/logger.py (AuditLogger.log)",
        "status": "released",
        "verification_result": (
            "All 10 pre-existing tests/test_logger.py tests pass unmodified; 7 new tests "
            "in tests/test_logger_signing.py. Full suite: 249 passed (242 baseline + 7 "
            "new), 0 regressions."
        ),
        "reviewer": None,
        "evidence": [
            {
                "type": "github_pr",
                "label": "omnibioai-security-audit#8",
                "url": "https://github.com/OmniBioAI/omnibioai-security-audit/pull/8",
                "identifier": None,
            },
            {
                "type": "commit",
                "label": "ab2790f",
                "url": "https://github.com/OmniBioAI/omnibioai-security-audit/commit/ab2790f8f4045c21a40f1a2a757b234a90555f56",
                "identifier": None,
            },
            {
                "type": "ci_run",
                "label": "CI run 31834489454 -- success",
                "url": "https://github.com/OmniBioAI/omnibioai-security-audit/actions/runs/31834489454",
                "identifier": None,
            },
            {
                "type": "test_suite",
                "label": "249 passed (242 baseline + 7 new), 0 regressions",
                "url": None,
                "identifier": None,
            },
        ],
        "notes": (
            "Sixth and final PR closing producer-side signing platform-wide -- companion "
            "PRs already merged in omnibioai-api-gateway#10, omnibioai-tes#23, "
            "omnibioai-workflow-bundles#25, omnibioai-control-center#43, omnibioai-rag#21. "
            + _SELF_MERGED_NOTE
        ),
    },
    {
        "change_id": "SECURITY-AUDIT-PR9",
        "title": "Surface integrity_status through GET /audit/events",
        "change_date": date(2026, 8, 15),
        "repository": "omnibioai-security-audit",
        "branch": "feature/audit-events-integrity-status-read-api",
        "commit_sha": "71a2593d80ba9d535362d3a5b689442deee013c5",
        "pr_number": 9,
        "description": (
            "audit_events.integrity_status has been classified by the worker for every "
            "event since PR3a's deployment, but was never visible through this service's "
            "own GET /audit/events API. Adds the field to AuditEventOut (never Optional, "
            "matches the NOT NULL DB column) plus a matching integrity_status query filter "
            "in list_audit_events and its route."
        ),
        "control_category": "audit_event_verification",
        "affected_component": "api/routes_audit_events.py, schemas/audit.py, services/audit_query_service.py",
        "status": "released",
        "verification_result": (
            "Updated the one existing exact-field-set assertion to include the new field; "
            "added 2 query-service filter tests + 1 HTTP-level filter test. 252 passed "
            "(249 baseline + 3 new), 0 regressions."
        ),
        "reviewer": None,
        "evidence": [
            {
                "type": "github_pr",
                "label": "omnibioai-security-audit#9",
                "url": "https://github.com/OmniBioAI/omnibioai-security-audit/pull/9",
                "identifier": None,
            },
            {
                "type": "commit",
                "label": "71a2593",
                "url": "https://github.com/OmniBioAI/omnibioai-security-audit/commit/71a2593d80ba9d535362d3a5b689442deee013c5",
                "identifier": None,
            },
            {
                "type": "ci_run",
                "label": "CI run 31860393227 -- success",
                "url": "https://github.com/OmniBioAI/omnibioai-security-audit/actions/runs/31860393227",
                "identifier": None,
            },
            {
                "type": "test_suite",
                "label": "252 passed (249 baseline + 3 new), 0 regressions",
                "url": None,
                "identifier": None,
            },
        ],
        "notes": (
            "Lets a platform_admin see whether any audit event was ever verified, or "
            "isolate events that failed verification, directly from this service's own "
            "read API. " + _SELF_MERGED_NOTE
        ),
    },
    {
        "change_id": "CC-PR45",
        "title": "HIPAA PR3c: verify audit event integrity in Control Center",
        "change_date": date(2026, 8, 15),
        "repository": "omnibioai-control-center",
        "branch": "feat/hipaa-pr3c-audit-integrity",
        "commit_sha": "80ea65081408cd1166d6a13738efe893405ded93",
        "pr_number": 45,
        "description": (
            "Control Center's own human-facing audit trail (checks/audit_trail.py, "
            "GET /audit-trail) previously ignored the sig field entirely. Now verifies "
            "each audit:events entry's HMAC-SHA256 signature locally (byte-exact against "
            "the raw Redis `data` string, fail-closed on malformed/adversarial input), "
            "classifying every event valid/invalid/unsigned -- purely additive, does not "
            "alter pagination, filtering, or any existing aggregate."
        ),
        "control_category": "audit_event_verification",
        "affected_component": "backend/src/control_center/checks/audit_trail.py",
        "status": "released",
        "verification_result": (
            "backend/tests/test_check_audit_trail.py: 25/25 passed (9 pre-existing + 16 "
            "new). test_public_dashboard_no_leak.py + test_routes_infra.py: 24/24 passed, "
            "unmodified. Full Control Center backend suite: 1323/1323 passed, 0 "
            "regressions. Also live-verified against the real running stack: 25/25 recent "
            "audit:events Redis entries, classified locally, agreed exactly with "
            "security-audit's own independently-persisted classification (read-only, no "
            "writes)."
        ),
        "reviewer": None,
        "evidence": [
            {
                "type": "github_pr",
                "label": "omnibioai-control-center#45",
                "url": "https://github.com/OmniBioAI/omnibioai-control-center/pull/45",
                "identifier": None,
            },
            {
                "type": "commit",
                "label": "80ea650",
                "url": "https://github.com/OmniBioAI/omnibioai-control-center/commit/80ea65081408cd1166d6a13738efe893405ded93",
                "identifier": None,
            },
            {
                "type": "ci_run",
                "label": "CI run 31859704385 -- success",
                "url": "https://github.com/OmniBioAI/omnibioai-control-center/actions/runs/31859704385",
                "identifier": None,
            },
            {
                "type": "test_suite",
                "label": "1323/1323 passed, 0 regressions",
                "url": None,
                "identifier": None,
            },
        ],
        "notes": (
            "Closes the last human-facing gap in the HIPAA PR3b rollout. "
            "checks/gateway_traffic.py and analytics/consumer.py (Control Center's other "
            "two raw audit:events readers) were deliberately deferred to PR3d -- see "
            "CC-PR46. " + _SELF_MERGED_NOTE
        ),
    },
    {
        "change_id": "CC-PR46",
        "title": "HIPAA PR3d: verify audit integrity in remaining consumers",
        "change_date": date(2026, 8, 15),
        "repository": "omnibioai-control-center",
        "branch": "feat/hipaa-pr3d-audit-consumer-integrity",
        "commit_sha": "3b86b64f4e9ea2d65cb9e6680534e4954f189b75",
        "pr_number": 46,
        "description": (
            "Closes the remaining two raw audit:events consumer gaps left after PR3c: "
            "checks/gateway_traffic.py now verifies each event's signature before it "
            "contributes to any numeric aggregate, and analytics/consumer.py verifies "
            "before an event reaches the durable Redis aggregator. Both import "
            "classify_event_integrity directly from checks.audit_trail (PR3c) -- no "
            "fourth hand-port of the signing contract. Also fixed a real gap found while "
            "building this: control-center-analytics-worker's compose definition had no "
            "JWT_SECRET, which would have misclassified every genuinely valid signed "
            "event as invalid."
        ),
        "control_category": "audit_event_verification",
        "affected_component": (
            "backend/src/control_center/checks/gateway_traffic.py, "
            "backend/src/control_center/analytics/consumer.py"
        ),
        "status": "released",
        "verification_result": (
            "test_check_gateway_traffic.py: 16/16 passed (9 pre-existing + 7 new). "
            "test_analytics_consumer.py: 36/36 passed (30 pre-existing + 6 new). Full "
            "Control Center backend suite: 1335/1335 passed, 0 regressions. GitHub "
            "Actions Lint & Test: pass."
        ),
        "reviewer": None,
        "evidence": [
            {
                "type": "github_pr",
                "label": "omnibioai-control-center#46",
                "url": "https://github.com/OmniBioAI/omnibioai-control-center/pull/46",
                "identifier": None,
            },
            {
                "type": "commit",
                "label": "3b86b64 (merge)",
                "url": "https://github.com/OmniBioAI/omnibioai-control-center/commit/3b86b64f4e9ea2d65cb9e6680534e4954f189b75",
                "identifier": None,
            },
            {
                "type": "ci_run",
                "label": "CI run 31861565476 -- success",
                "url": "https://github.com/OmniBioAI/omnibioai-control-center/actions/runs/31861565476",
                "identifier": None,
            },
            {
                "type": "test_suite",
                "label": "1335/1335 passed, 0 regressions",
                "url": None,
                "identifier": None,
            },
        ],
        "notes": (
            "Closes the HIPAA PR3b audit-integrity rollout's last consumer gap -- every "
            "raw audit:events reader in this ecosystem now verifies signatures. "
            + _SELF_MERGED_NOTE
        ),
    },
]


def seed_initial_data(db: Session) -> int:
    """Inserts any SEED_CHANGES row whose change_id isn't already
    present. Idempotent by design (checked per-row, not a single bulk
    INSERT) -- safe to call on every process start, and safe if a
    platform_admin has since edited or deleted one of these rows via the
    API (their edit is never overwritten by a later restart). Returns
    the number of rows actually inserted."""
    existing_ids = {
        row_id for (row_id,) in db.query(HipaaComplianceChange.change_id).all()
    }
    inserted = 0
    for change in SEED_CHANGES:
        if change["change_id"] in existing_ids:
            continue
        db.add(HipaaComplianceChange(**change))
        inserted += 1
    if inserted:
        db.commit()
    return inserted
