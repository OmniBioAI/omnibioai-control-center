from __future__ import annotations

from sqlalchemy.orm import Session

from control_center.hipaa_compliance.models import HipaaComplianceChange
from control_center.hipaa_compliance.schemas import (
    CONTROL_CATEGORY_LABELS,
    PENDING_STATUSES,
    VERIFIED_STATUSES,
    ComplianceControlCategory,
    ComplianceStatus,
    ControlCategorySummary,
    HipaaComplianceChangeCreate,
    HipaaComplianceChangeUpdate,
    HipaaComplianceSummaryOut,
)


class ChangeAlreadyExistsError(Exception):
    """Raised when creating a change_id that already exists -- change_id
    is the primary key (models.py), so this is a real conflict, not a
    generic DB error the route should mask as a 500."""


class ChangeNotFoundError(Exception):
    """Raised by get/update for a change_id with no matching row."""


def list_changes(
    db: Session,
    page: int,
    page_size: int,
    status: str | None = None,
    control_category: str | None = None,
    repository: str | None = None,
) -> tuple[list[HipaaComplianceChange], int]:
    """Returns (page of rows, total matching rows). Filter-in-SQL,
    count-before-paginate -- the same shape omnibioai-security-audit's
    audit_query_service.list_audit_events already established for this
    ecosystem's other paginated platform-admin endpoint. Ordered newest-
    first by change_date, change_id as a tiebreaker so same-day records
    still sort deterministically across pages."""
    query = db.query(HipaaComplianceChange)

    if status is not None:
        query = query.filter(HipaaComplianceChange.status == status)
    if control_category is not None:
        query = query.filter(HipaaComplianceChange.control_category == control_category)
    if repository is not None:
        query = query.filter(HipaaComplianceChange.repository == repository)

    total = query.count()

    rows = (
        query.order_by(
            HipaaComplianceChange.change_date.desc(), HipaaComplianceChange.change_id.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return rows, total


def get_change(db: Session, change_id: str) -> HipaaComplianceChange:
    row = db.get(HipaaComplianceChange, change_id)
    if row is None:
        raise ChangeNotFoundError(change_id)
    return row


def create_change(db: Session, payload: HipaaComplianceChangeCreate) -> HipaaComplianceChange:
    if db.get(HipaaComplianceChange, payload.change_id) is not None:
        raise ChangeAlreadyExistsError(payload.change_id)

    row = HipaaComplianceChange(
        change_id=payload.change_id,
        title=payload.title,
        change_date=payload.change_date,
        repository=payload.repository,
        branch=payload.branch,
        commit_sha=payload.commit_sha,
        pr_number=payload.pr_number,
        description=payload.description,
        control_category=payload.control_category.value,
        affected_component=payload.affected_component,
        status=payload.status.value,
        verification_result=payload.verification_result,
        reviewer=payload.reviewer,
        evidence=[e.model_dump(mode="json") for e in payload.evidence],
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_change(
    db: Session, change_id: str, payload: HipaaComplianceChangeUpdate
) -> HipaaComplianceChange:
    row = get_change(db, change_id)

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "control_category" and value is not None:
            value = ComplianceControlCategory(value).value
        elif field == "status" and value is not None:
            value = ComplianceStatus(value).value
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return row


def build_summary(db: Session) -> HipaaComplianceSummaryOut:
    """Compliance Overview: every number here is derived live from
    hipaa_compliance_changes, never a separately-maintained counter that
    could drift from the underlying rows."""
    rows = db.query(HipaaComplianceChange).all()

    verified_count = sum(1 for r in rows if r.status in VERIFIED_STATUSES)
    pending_count = sum(1 for r in rows if r.status in PENDING_STATUSES)
    exception_count = sum(1 for r in rows if r.status == ComplianceStatus.EXCEPTION.value)

    categories_present = {r.control_category for r in rows}

    if not rows:
        overall_status = "no_data"
    elif exception_count > 0:
        overall_status = "attention_needed"
    elif pending_count > 0:
        overall_status = "in_progress"
    else:
        overall_status = "on_track"

    latest = max(rows, key=lambda r: (r.change_date, r.change_id), default=None)

    return HipaaComplianceSummaryOut(
        overall_status=overall_status,
        total_controls_tracked=len(categories_present),
        verified_count=verified_count,
        pending_count=pending_count,
        exception_count=exception_count,
        latest_change_id=latest.change_id if latest else None,
        latest_change_title=latest.title if latest else None,
        latest_change_date=latest.change_date if latest else None,
        controls=build_control_summaries(rows),
    )


def build_control_summaries(rows: list[HipaaComplianceChange]) -> list[ControlCategorySummary]:
    """Every taxonomy category appears here, even with zero changes --
    an admin scanning Compliance Controls should see "Access Control: 0
    tracked" as a real, visible gap, not have that category silently
    absent from the list."""
    by_category: dict[str, list[HipaaComplianceChange]] = {c.value: [] for c in ComplianceControlCategory}
    for row in rows:
        by_category.setdefault(row.control_category, []).append(row)

    summaries = []
    for category in ComplianceControlCategory:
        entries = by_category.get(category.value, [])
        summaries.append(
            ControlCategorySummary(
                category=category,
                label=CONTROL_CATEGORY_LABELS[category],
                total=len(entries),
                verified=sum(1 for e in entries if e.status in VERIFIED_STATUSES),
                pending=sum(1 for e in entries if e.status in PENDING_STATUSES),
                exceptions=sum(1 for e in entries if e.status == ComplianceStatus.EXCEPTION.value),
            )
        )
    return summaries
