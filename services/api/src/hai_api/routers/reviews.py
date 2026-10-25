"""Reviews (JWT reviewers only), certification signing and public verification."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from hai_api.auth import Anyone, require
from hai_api.deps import State, load_assessment
from hai_api.schemas import CertificationCreate, ReviewCreate
from hai_core.assessments import transition
from hai_core.auth import Principal, Scope
from hai_core.errors import ConflictError, NotFoundError
from hai_core.generated.enums import LifecycleState, OutcomeStatus, ReviewSubjectType
from hai_core.generated.models import Assessment
from hai_core.reviews import act, close_task, list_tasks, open_tasks_for
from hai_core.webhooks import emit

router = APIRouter(prefix="/v1", tags=["reviews"])

ReviewWriter = Annotated[Principal, Depends(require(Scope.REVIEWS_WRITE, reviewer=True))]
Signer = Annotated[Principal, Depends(require(Scope.CERTIFICATION_SIGN, reviewer=True))]
Reader = Annotated[Principal, Depends(require(Scope.ASSESSMENTS_READ))]


@router.get("/reviews/tasks", summary="The review queue")
def tasks(
    st: State,
    principal: Reader,
    status_filter: str | None = Query(default="open", alias="status"),
    assessment_id: UUID | None = None,
    subject_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        rows, total = list_tasks(
            conn,
            status=status_filter,
            assessment_id=assessment_id,
            subject_type=subject_type,
            limit=limit,
            offset=offset,
        )
    return {"items": [t.as_dict() for t in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/reviews", status_code=status.HTTP_201_CREATED, summary="Act on a review task (always with a reason)")
def review(body: ReviewCreate, st: State, principal: ReviewWriter) -> dict[str, Any]:
    with st.tx(principal, "hai_reviewer") as (conn, store):
        row, task = act(conn, store, task_id=body.task_id, principal=principal, action=body.action, reason=body.reason)
        queued_finalize = False
        if task.status == "closed" and task.assessment_id and open_tasks_for(conn, task.assessment_id) == 0:
            a = store.get(Assessment, task.assessment_id)
            if a is not None and a.lifecycle_state is LifecycleState.AWAITING_REVIEW:
                st.queue.enqueue(
                    conn, "finalize", {"assessment_id": str(a.id)}, dedupe_key=f"finalize:{a.id}:{row.id}", priority=3
                )
                queued_finalize = True
    return {
        "review": {
            "id": str(row.id),
            "subject_type": str(row.subject_type.value),
            "subject_id": str(row.subject_id),
            "assessment_id": str(row.assessment_id) if row.assessment_id else None,
            "reviewer_id": row.reviewer_id,
            "action": str(row.action.value),
            "reason": row.reason,
            "decided_at": row.decided_at.isoformat(),
        },
        "task": task.as_dict(),
        "finalize_queued": queued_finalize,
    }


@router.post(
    "/assessments/{assessment_id}/certification",
    status_code=status.HTTP_201_CREATED,
    tags=["certification"],
    summary="Sign a certification decision (reviewer JWT only)",
)
def sign_certification(assessment_id: UUID, body: CertificationCreate, st: State, principal: Signer) -> dict[str, Any]:
    with st.tx(principal, "hai_reviewer") as (conn, store):
        assessment = load_assessment(store, assessment_id)
        result = st.decisions.latest_result(store, assessment_id)
        if result is None:
            raise ConflictError("the assessment has no result to certify yet")
        rows, _ = list_tasks(
            conn, status="open", assessment_id=assessment_id, subject_type=ReviewSubjectType.CERTIFICATION.value
        )
        for t in rows:
            if t.opened_by == principal.actor:
                from hai_core.errors import ForbiddenError

                raise ForbiddenError("four eyes: the reviewer who requested certification cannot sign it")
            if principal.id in t.excluded_reviewers:
                from hai_core.errors import ForbiddenError

                raise ForbiddenError("this certification task was escalated away from you")
        decision = st.certification.sign(
            store, assessment=assessment, result=result, principal=principal, decision=body.decision, reason=body.reason
        )
        for t in rows:
            close_task(conn, t.id, closed_by=principal.id)
        if assessment.lifecycle_state is LifecycleState.AWAITING_REVIEW and open_tasks_for(conn, assessment_id) == 0:
            st.queue.enqueue(
                conn,
                "finalize",
                {"assessment_id": str(assessment_id)},
                dedupe_key=f"finalize:{assessment_id}:{decision.id}",
                priority=3,
            )
        emit(
            conn,
            "certification.signed",
            {
                "assessment_id": str(assessment_id),
                "decision": body.decision,
                "certificate_number": decision.certificate_number,
                "reviewer_id": principal.id,
            },
            queue=st.queue,
        )
    return {
        "id": str(decision.id),
        "assessment_id": str(assessment_id),
        "decision": str(decision.decision.value),
        "certificate_number": decision.certificate_number,
        "reviewer_id": decision.reviewer_id,
        "signed_at": decision.signed_at.isoformat(),
        "expires_at": decision.expires_at.isoformat() if decision.expires_at else None,
        "threshold_applied": float(decision.threshold_applied),
        "gate_reasons": list(decision.gate_reasons or []),
        "verify_url": f"{st.settings.public_base_url}/v1/certifications/{decision.certificate_number}/verify"
        if decision.certificate_number
        else None,
    }


@router.delete(
    "/assessments/{assessment_id}/certification",
    tags=["certification"],
    summary="Revoke a certification (reviewer JWT only)",
)
def revoke_certification(
    assessment_id: UUID, st: State, principal: Signer, reason: str = Query(min_length=3, max_length=2000)
) -> dict[str, Any]:
    with st.tx(principal, "hai_reviewer") as (conn, store):
        current = st.certification.require_current(store, assessment_id)
        revoked = st.certification.revoke(store, current=current, principal=principal, reason=reason)
        assessment = load_assessment(store, assessment_id)
        result = st.decisions.latest_result(store, assessment_id)
        if result is not None and result.outcome_status is OutcomeStatus.HAI_CERTIFIED:
            st.queue.enqueue(
                conn,
                "decide",
                {"assessment_id": str(assessment_id)},
                dedupe_key=f"decide:{assessment_id}:{revoked.id}",
                priority=3,
            )
        if assessment.lifecycle_state is LifecycleState.COMPLETED:
            pass  # completed is terminal; the new result row records the revocation
        emit(
            conn,
            "certification.signed",
            {"assessment_id": str(assessment_id), "decision": "revoked", "reviewer_id": principal.id},
            queue=st.queue,
        )
    return {"id": str(revoked.id), "decision": "revoked", "supersedes_id": str(revoked.supersedes_id), "reason": reason}


@router.get(
    "/certifications/{certificate_number}/verify", tags=["certification"], summary="Public certificate verification"
)
def verify_certificate(certificate_number: str, st: State, principal: Anyone) -> dict[str, Any]:
    with st.read(principal) as (_, store):
        verification = st.certification.verify(store, certificate_number)
    if verification.status == "not_found":
        raise NotFoundError("no certificate with that number")
    return verification.as_dict()


_ = transition
