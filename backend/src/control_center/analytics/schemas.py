"""The normalized internal analytics event contract (task brief Section
2), and the mapping from the one real wire shape that feeds it today --
omnibioai-auth's `InteractionEvent` (app/schemas/interaction.py), read off
`interactions:events`.

Deliberately narrower than the brief's example event contract:
`team_id`/`duration_ms`/`request_id` are real fields on AnalyticsEvent
(so the internal contract and any future response/consumer code can
already use them), but the one real producer today has no `team_id` or
`duration_ms` on the wire at all -- adding those to omnibioai-auth's
InteractionEvent/RAG's producer would mean modifying two unrelated
services for this control-center-only phase, which the task brief
explicitly says not to do unless required to expose an
already-existing event. `request_id` maps from `trace_id`, the closest
existing analog already on the wire.

API response models live in service.py/router.py (a later PR), not
here -- this module only defines the one thing every future consumer
needs: what an analytics event *is*, once normalized.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AnalyticsEvent(BaseModel):
    event_id: str
    event_type: str
    timestamp: datetime

    org_id: Optional[int] = None
    team_id: Optional[int] = None
    user_id: Optional[int] = None

    service: str
    action: str = ""
    status: Optional[str] = None

    duration_ms: Optional[float] = None
    request_id: Optional[str] = None

    metadata: dict[str, Any] = Field(default_factory=dict)


# Status values the one real producer (ragbio/api/server.py) actually
# emits today: "success", "error", "timeout". Treated as a closed-ish
# "did this fail" classification -- a few plausible synonyms are
# included defensively for whatever the next producer turns out to use,
# without assuming any of them will actually appear yet.
_FAILURE_STATUSES = {"error", "timeout", "failed", "denied", "cancelled"}


def _derive_event_type(interaction_type: str, status: Optional[str]) -> str:
    """`{interaction_type}.{completed|failed}` -- e.g. RAG's
    interaction_type="query" becomes query.completed/query.failed,
    matching the brief's own query.completed/query.failed vocabulary
    exactly. A not-yet-seen interaction_type (e.g. a future "workflow"
    producer) falls into the same `{type}.completed`/`{type}.failed`
    shape automatically, so this function needs no change when a new
    producer shows up -- only QUERY_EVENT_TYPES/WORKFLOW_EVENT_TYPES
    below would need a new entry if a caller wants to filter on it
    specifically.
    """
    failed = (status or "").lower() in _FAILURE_STATUSES
    kind = interaction_type or "event"
    return f"{kind}.{'failed' if failed else 'completed'}"


def normalize_interaction_event(payload: dict) -> AnalyticsEvent:
    """Builds one AnalyticsEvent from a raw `interactions:events` payload
    (already `json.loads`-ed). Raises KeyError/ValueError/pydantic's
    ValidationError on a payload missing a required field
    (interaction_id/timestamp/organization_id/service) -- the caller
    (consumer.py) decides what a malformed payload means, this function
    only normalizes a well-formed one.
    """
    interaction_type = payload.get("interaction_type", "") or ""
    status = payload.get("status")
    return AnalyticsEvent(
        event_id=payload["interaction_id"],
        event_type=_derive_event_type(interaction_type, status),
        timestamp=payload["timestamp"],
        org_id=payload["organization_id"],
        team_id=None,
        user_id=payload.get("user_id"),
        service=payload.get("service") or "unknown",
        action=payload.get("action") or interaction_type,
        status=status,
        duration_ms=None,
        request_id=payload.get("trace_id"),
        metadata=payload.get("metadata") or {},
    )


QUERY_EVENT_TYPES = frozenset({"query.completed", "query.failed"})
WORKFLOW_EVENT_TYPES = frozenset({"workflow.completed", "workflow.failed"})


def is_failure(event_type: str) -> bool:
    return event_type.endswith(".failed")
