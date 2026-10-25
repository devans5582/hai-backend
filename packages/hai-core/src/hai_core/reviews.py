"""Review queue: tasks, allowed actions per subject type, mandatory reasons, escalation and four eyes.

A review always carries a reason (database CHECK). Escalation keeps the task
open and excludes the escalating reviewer from acting on it again. A reviewer
who opened a certification task cannot be the one who signs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.auth import Principal
from hai_core.db.store import Store
from hai_core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from hai_core.generated.enums import ATTRIBUTES, Admissibility, IncidentStatus, ReviewAction, ReviewSubjectType
from hai_core.generated.models import EvidenceLink, Incident, Review


@dataclass(frozen=True)
class ReviewTask:
    id: UUID
    assessment_id: UUID | None
    subject_type: str
    subject_id: UUID
    reason: str
    status: str
    opened_by: str
    excluded_reviewers: list[str]
    closed_by: str | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def allowed_actions(self) -> list[str]:
        return [str(a) for a in ATTRIBUTES["review_subject_type"][self.subject_type]["allowed_actions"]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "assessment_id": str(self.assessment_id) if self.assessment_id else None,
            "subject_type": self.subject_type,
            "subject_id": str(self.subject_id),
            "reason": self.reason,
            "status": self.status,
            "opened_by": self.opened_by,
            "excluded_reviewers": list(self.excluded_reviewers),
            "allowed_actions": self.allowed_actions,
            "closed_by": self.closed_by,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def _task(row: Any) -> ReviewTask:
    m = row._mapping
    return ReviewTask(
        id=m["id"],
        assessment_id=m["assessment_id"],
        subject_type=str(m["subject_type"]),
        subject_id=m["subject_id"],
        reason=m["reason"],
        status=m["status"],
        opened_by=m["opened_by"],
        excluded_reviewers=list(m["excluded_reviewers"] or []),
        closed_by=m["closed_by"],
        closed_at=m["closed_at"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


def create_task(
    conn: Connection, *, assessment_id: UUID | None, subject_type: str, subject_id: UUID, reason: str, opened_by: str
) -> ReviewTask:
    """Open a task unless an open one already exists for the same subject."""
    existing = conn.execute(
        text(
            "SELECT * FROM hai_ops.review_tasks WHERE subject_type = :t AND subject_id = :s AND status IN ('open', 'escalated')"
        ),
        {"t": subject_type, "s": subject_id},
    ).first()
    if existing:
        return _task(existing)
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.review_tasks (assessment_id, subject_type, subject_id, reason, opened_by) "
            "VALUES (:a, :t, :s, :r, :o) RETURNING *"
        ),
        {"a": assessment_id, "t": subject_type, "s": subject_id, "r": reason, "o": opened_by},
    ).first()
    assert row is not None
    return _task(row)


def get_task(conn: Connection, task_id: UUID) -> ReviewTask:
    row = conn.execute(text("SELECT * FROM hai_ops.review_tasks WHERE id = :id"), {"id": task_id}).first()
    if row is None:
        raise NotFoundError(f"review task {task_id} not found")
    return _task(row)


def list_tasks(
    conn: Connection,
    *,
    status: str | None = "open",
    assessment_id: UUID | None = None,
    subject_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ReviewTask], int]:
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status == "open":
        where.append("status IN ('open', 'escalated')")
    elif status:
        where.append("status = :status")
        params["status"] = status
    if assessment_id:
        where.append("assessment_id = :a")
        params["a"] = assessment_id
    if subject_type:
        where.append("subject_type = :t")
        params["t"] = subject_type
    clause = " AND ".join(where)
    total = int(conn.execute(text(f"SELECT count(*) FROM hai_ops.review_tasks WHERE {clause}"), params).scalar_one())
    rows = conn.execute(
        text(f"SELECT * FROM hai_ops.review_tasks WHERE {clause} ORDER BY created_at LIMIT :limit OFFSET :offset"),
        params,
    ).all()
    return [_task(r) for r in rows], total


def open_tasks_for(conn: Connection, assessment_id: UUID) -> int:
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM hai_ops.review_tasks WHERE assessment_id = :a AND status IN ('open', 'escalated')"
            ),
            {"a": assessment_id},
        ).scalar_one()
    )


def act(
    conn: Connection, store: Store, *, task_id: UUID, principal: Principal, action: str, reason: str
) -> tuple[Review, ReviewTask]:
    """Record a review on a task and apply its effect. Returns the review row and the updated task."""
    if not principal.is_reviewer:
        raise ForbiddenError("only a named reviewer can review")
    if not reason or not reason.strip():
        raise ValidationFailedError("a review always carries a reason", details={"field": "reason"})
    task = get_task(conn, task_id)
    if task.status == "closed":
        raise ConflictError("this review task is closed")
    if principal.id in task.excluded_reviewers:
        raise ForbiddenError("this task was escalated away from you; a different reviewer must act on it")
    if action not in task.allowed_actions:
        raise ValidationFailedError(
            f"action {action!r} is not allowed for a {task.subject_type} review",
            details={"allowed_actions": task.allowed_actions},
        )
    if (
        task.subject_type == ReviewSubjectType.CERTIFICATION.value
        and action == ReviewAction.SIGN.value
        and task.opened_by == principal.actor
    ):
        raise ForbiddenError("four eyes: the reviewer who requested certification cannot sign it")
    review = store.insert(
        Review(
            subject_type=ReviewSubjectType(task.subject_type),
            subject_id=task.subject_id,
            assessment_id=task.assessment_id,
            reviewer_id=principal.id,
            action=ReviewAction(action),
            reason=reason.strip(),
            decided_at=datetime.now(UTC),
        ),
        reason=reason.strip(),
    )
    _apply_effect(store, task, ReviewAction(action), principal)
    keeps_open = bool(ATTRIBUTES["review_action"][action]["keeps_task_open"])
    if keeps_open:
        conn.execute(
            text(
                "UPDATE hai_ops.review_tasks SET status = 'escalated', excluded_reviewers = array_append(excluded_reviewers, :r), updated_at = now() WHERE id = :id"
            ),
            {"r": principal.id, "id": task.id},
        )
    else:
        conn.execute(
            text(
                "UPDATE hai_ops.review_tasks SET status = 'closed', closed_by = :r, closed_at = now(), closing_review_id = :rid, updated_at = now() WHERE id = :id"
            ),
            {"r": principal.id, "rid": review.id, "id": task.id},
        )
    return review, get_task(conn, task.id)


def _apply_effect(store: Store, task: ReviewTask, action: ReviewAction, principal: Principal) -> None:
    st = task.subject_type
    if st == ReviewSubjectType.INCIDENT.value:
        if action is ReviewAction.SUBSTANTIATE:
            store.update(
                Incident,
                task.subject_id,
                {"status": IncidentStatus.SUBSTANTIATED},
                reason=f"substantiated by {principal.id}",
            )
        elif action is ReviewAction.DISMISS:
            store.update(
                Incident, task.subject_id, {"status": IncidentStatus.DISMISSED}, reason=f"dismissed by {principal.id}"
            )
    elif st == ReviewSubjectType.LINK.value:
        if action is ReviewAction.APPROVE:
            store.update(
                EvidenceLink,
                task.subject_id,
                {
                    "admissibility": Admissibility.ADMISSIBLE,
                    "reviewer_id": principal.id,
                    "admissibility_reason": "approved in review",
                },
                reason=f"approved by {principal.id}",
            )
        elif action is ReviewAction.REJECT:
            store.update(
                EvidenceLink,
                task.subject_id,
                {
                    "admissibility": Admissibility.INADMISSIBLE_IRRELEVANT,
                    "reviewer_id": principal.id,
                    "admissibility_reason": "rejected in review",
                },
                reason=f"rejected by {principal.id}",
            )
    # contradiction, confidence, finding, appeal and applicability reviews are recorded; finalize reads them.


def close_task(conn: Connection, task_id: UUID, *, closed_by: str, review_id: UUID | None = None) -> None:
    conn.execute(
        text(
            "UPDATE hai_ops.review_tasks SET status = 'closed', closed_by = :r, closed_at = now(), closing_review_id = :rid, updated_at = now() WHERE id = :id AND status <> 'closed'"
        ),
        {"r": closed_by, "rid": review_id, "id": task_id},
    )


def tasks_from_triggers(
    conn: Connection,
    *,
    assessment_id: UUID,
    triggers: list[str],
    decisions_by_code: dict[str, UUID],
    result_id: UUID,
    opened_by: str,
) -> list[ReviewTask]:
    """Open one task per review trigger produced by the rules engine."""
    out: list[ReviewTask] = []
    for trigger in triggers:
        kind, _, ref = trigger.partition(":")
        if kind == "contradiction" and ref in decisions_by_code:
            out.append(
                create_task(
                    conn,
                    assessment_id=assessment_id,
                    subject_type=ReviewSubjectType.CONTRADICTION.value,
                    subject_id=decisions_by_code[ref],
                    reason=f"contradictory evidence on {ref}",
                    opened_by=opened_by,
                )
            )
        elif kind == "incident":
            try:
                incident_id = UUID(ref)
            except ValueError:
                continue
            out.append(
                create_task(
                    conn,
                    assessment_id=assessment_id,
                    subject_type=ReviewSubjectType.INCIDENT.value,
                    subject_id=incident_id,
                    reason="unverified incident",
                    opened_by=opened_by,
                )
            )
        elif kind == "finding" and ref in decisions_by_code:
            out.append(
                create_task(
                    conn,
                    assessment_id=assessment_id,
                    subject_type=ReviewSubjectType.FINDING.value,
                    subject_id=decisions_by_code[ref],
                    reason=f"finding needs review on {ref}",
                    opened_by=opened_by,
                )
            )
        elif kind == "applicability" and ref in decisions_by_code:
            out.append(
                create_task(
                    conn,
                    assessment_id=assessment_id,
                    subject_type=ReviewSubjectType.APPLICABILITY.value,
                    subject_id=decisions_by_code[ref],
                    reason=f"applicability condition on {ref}",
                    opened_by=opened_by,
                )
            )
        elif kind == "confidence":
            out.append(
                create_task(
                    conn,
                    assessment_id=assessment_id,
                    subject_type=ReviewSubjectType.CONFIDENCE.value,
                    subject_id=result_id,
                    reason=f"borderline confidence {ref}",
                    opened_by=opened_by,
                )
            )
        elif kind == "certification":
            out.append(
                create_task(
                    conn,
                    assessment_id=assessment_id,
                    subject_type=ReviewSubjectType.CERTIFICATION.value,
                    subject_id=assessment_id,
                    reason="certification requested",
                    opened_by=opened_by,
                )
            )
    return out
