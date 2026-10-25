"""Assessments: create, list, get, result, report, decisions, findings, trace, connector runs, cancel,
certification request, reassess."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import text

from hai_api.auth import require
from hai_api.deps import AppState, State, load_assessment
from hai_api.schemas import AssessmentCreate, AssessmentOut, DecisionOut, Page, ResultOut
from hai_core.assessments import AssessmentRequest, cancel, create_assessment, reassess, request_certification
from hai_core.auth import Principal, Scope
from hai_core.db.store import Store
from hai_core.errors import NotFoundError
from hai_core.generated.enums import LABELS
from hai_core.generated.models import Assessment, CriterionFinding
from hai_engine.reporting import build_report, coverage_wording

router = APIRouter(prefix="/v1/assessments", tags=["assessments"])

Reader = Annotated[Principal, Depends(require(Scope.ASSESSMENTS_READ))]
Writer = Annotated[Principal, Depends(require(Scope.ASSESSMENTS_WRITE))]


def _enum(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


def assessment_out(a: Assessment, base: str) -> AssessmentOut:
    aid = str(a.id)
    return AssessmentOut(
        id=a.id,
        org_id=a.org_id,
        parent_assessment_id=a.parent_assessment_id,
        requested_by=a.requested_by,
        submitted_domain=a.submitted_domain,
        direct_urls=list(a.direct_urls or []),
        stage_band=_enum(a.stage_band),
        size_band=_enum(a.size_band),
        lifecycle_state=_enum(a.lifecycle_state),
        lifecycle_label=LABELS["lifecycle_state"][_enum(a.lifecycle_state)],
        certification_requested=a.certification_requested,
        failure_reason=a.failure_reason,
        versions={
            "ontology": a.ontology_version,
            "methodology": a.methodology_version,
            "ruleset": a.ruleset_version,
            "prompt": a.prompt_version,
            "model": a.model_id,
        },
        created_at=a.created_at,
        started_at=a.started_at,
        finished_at=a.finished_at,
        links={
            "self": f"{base}/v1/assessments/{aid}",
            "result": f"{base}/v1/assessments/{aid}/result",
            "report": f"{base}/v1/assessments/{aid}/report",
            "decisions": f"{base}/v1/assessments/{aid}/decisions",
            "trace": f"{base}/v1/assessments/{aid}/trace",
            "connector_runs": f"{base}/v1/assessments/{aid}/connector-runs",
        },
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AssessmentOut, summary="Start an assessment")
def create(
    body: AssessmentCreate,
    st: State,
    principal: Writer,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> AssessmentOut:
    request = AssessmentRequest(
        organization_name=body.organization_name,
        website=body.website,
        stage=body.stage,
        size=body.size,
        industry=body.industry,
        direct_urls=body.direct_urls,
        certification_requested=body.certification_requested,
        legal_name=body.legal_name,
        aliases=body.aliases,
    )
    with st.tx(principal, "hai_api") as (conn, store):
        assessment, created = create_assessment(
            conn,
            store,
            request=request,
            principal=principal,
            settings=st.settings,
            manifest=st.manifest,
            idempotency_key=idempotency_key,
            queue=st.queue,
        )
    response.headers["Location"] = f"{st.settings.public_base_url}/v1/assessments/{assessment.id}"
    response.headers["X-Idempotent-Replay"] = "false" if created else "true"
    return assessment_out(assessment, st.settings.public_base_url)


@router.get("", response_model=Page[AssessmentOut], summary="List assessments")
def list_assessments(
    st: State,
    principal: Reader,
    org_id: UUID | None = None,
    state: str | None = Query(default=None, alias="lifecycle_state"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[AssessmentOut]:
    where: dict[str, Any] = {}
    if org_id:
        where["org_id"] = org_id
    if state:
        where["lifecycle_state"] = state
    with st.read(principal) as (_, store):
        rows = store.find(Assessment, where=where, order_by="created_at", descending=True, limit=limit, offset=offset)
        total = store.count(Assessment, where=where)
    return Page(
        items=[assessment_out(a, st.settings.public_base_url) for a in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{assessment_id}", response_model=AssessmentOut, summary="Lifecycle state and version pins")
def get_assessment(assessment_id: UUID, st: State, principal: Reader) -> AssessmentOut:
    with st.read(principal) as (_, store):
        return assessment_out(load_assessment(store, assessment_id), st.settings.public_base_url)


def result_out(st: AppState, store: Store, assessment_id: UUID) -> ResultOut:
    load_assessment(store, assessment_id)
    result = st.decisions.latest_result(store, assessment_id)
    if result is None:
        raise NotFoundError("no result yet; the assessment has not been decided")
    pillars = st.decisions.latest_pillars(store, assessment_id)
    return ResultOut(
        assessment_id=assessment_id,
        result_id=result.id,
        hai_score=float(result.hai_score) if result.hai_score is not None else None,
        confidence_pct=float(result.confidence_pct) if result.confidence_pct is not None else None,
        effectiveness=float(result.effectiveness) if result.effectiveness is not None else None,
        outcome_status=_enum(result.outcome_status),
        outcome_label=LABELS["outcome_status"][_enum(result.outcome_status)],
        gate_reasons=list(result.gate_reasons or []),
        review_triggers=list(result.review_triggers or []),
        caps_applied=list(result.caps_applied or []),
        score_before_caps=float(result.score_before_caps) if result.score_before_caps is not None else None,
        pillars=[
            {
                "code": _enum(p.pillar_code),
                "name": LABELS["pillar_code"][_enum(p.pillar_code)],
                "score": float(p.score),
                "confidence": float(p.confidence),
                "criteria_counted": p.criteria_counted,
                "criteria_excluded": p.criteria_excluded,
            }
            for p in pillars
        ],
        ruleset_version=result.ruleset_version,
        result_sha256=result.result_sha256,
        created_at=result.created_at,
    )


@router.get(
    "/{assessment_id}/result",
    response_model=ResultOut,
    summary="HAI Score, confidence, effectiveness and outcome status",
)
def get_result(assessment_id: UUID, st: State, principal: Reader) -> ResultOut:
    with st.read(principal) as (_, store):
        return result_out(st, store, assessment_id)


@router.get(
    "/{assessment_id}/report", summary="Full report: criteria, evidence, sources, coverage wording, execution notes"
)
def get_report(assessment_id: UUID, st: State, principal: Reader) -> dict[str, Any]:
    with st.read(principal) as (conn, store):
        load_assessment(store, assessment_id)
        return build_report(conn, store, st.manifest, assessment_id)


@router.get(
    "/{assessment_id}/decisions", response_model=Page[DecisionOut], summary="Criterion decisions (rules-engine output)"
)
def get_decisions(assessment_id: UUID, st: State, principal: Reader) -> Page[DecisionOut]:
    with st.read(principal) as (_, store):
        load_assessment(store, assessment_id)
        rows = st.decisions.latest_decisions(store, assessment_id)
    items = []
    order = {c.code: i for i, c in enumerate(st.manifest.criteria)}
    for d in sorted(rows, key=lambda d: order.get(_enum(d.criterion_code), 99)):
        code = _enum(d.criterion_code)
        crit = st.manifest.criterion(code)
        items.append(
            DecisionOut(
                id=d.id,
                criterion_code=code,
                criterion_name=crit.name,
                pillar=crit.pillar,
                level=d.level,
                coverage_state=_enum(d.coverage_state),
                coverage_wording=coverage_wording(_enum(d.coverage_state)),
                confidence=float(d.confidence),
                applied_rule_codes=list(d.applied_rule_codes),
                review_required=d.review_required,
                finding_id=d.finding_id,
                created_at=d.created_at,
            )
        )
    return Page(items=items, total=len(items), limit=len(items) or 1, offset=0)


@router.get("/{assessment_id}/findings", summary="LLM and heuristic findings (advisory; accepted and rejected)")
def get_findings(assessment_id: UUID, st: State, principal: Reader) -> dict[str, Any]:
    with st.read(principal) as (_, store):
        load_assessment(store, assessment_id)
        rows = store.find(CriterionFinding, where={"assessment_id": assessment_id}, order_by="created_at")
    items = [
        {
            "id": str(f.id),
            "criterion_code": _enum(f.criterion_code),
            "proposed_level": f.proposed_level,
            "evidence_link_ids": [str(x) for x in f.evidence_link_ids],
            "contradicting_link_ids": [str(x) for x in (f.contradicting_link_ids or [])],
            "uncertainty": float(f.uncertainty),
            "reasoning_summary": f.reasoning_summary,
            "provider": f.provider,
            "model_id": f.model_id,
            "prompt_version": f.prompt_version,
            "attempt": f.attempt,
            "role": f.role,
            "validation_status": _enum(f.validation_status),
            "validation_errors": f.validation_errors,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in rows
    ]
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}


def _trace_for(st: AppState, store: Store, assessment_id: UUID, criterion_code: str | None) -> dict[str, Any]:
    load_assessment(store, assessment_id)
    decisions = st.decisions.latest_decisions(store, assessment_id)
    result = st.decisions.latest_result(store, assessment_id)
    from hai_core.generated.models import EvidenceSnapshot

    snapshot = store.first(EvidenceSnapshot, where={"assessment_id": assessment_id})
    link_states = snapshot.link_states if snapshot else {}
    findings = {
        _enum(f.criterion_code): f
        for f in store.find(
            CriterionFinding,
            where={"assessment_id": assessment_id, "validation_status": "accepted"},
            order_by="created_at",
        )
    }  # hai-codes: ok
    out: list[dict[str, Any]] = []
    for d in decisions:
        code = _enum(d.criterion_code)
        if criterion_code and code != criterion_code:
            continue
        trace = d.trace if isinstance(d.trace, dict) else {"rules": d.trace}
        cited = set()
        f = findings.get(code)
        if f:
            cited = {str(x) for x in f.evidence_link_ids} | {str(x) for x in (f.contradicting_link_ids or [])}
        evidence = [
            {
                "link_id": lid,
                "cited_by_finding": lid in cited,
                **{
                    k: stt.get(k)
                    for k in (
                        "quote",
                        "polarity",
                        "admissibility",
                        "admissibility_reason",
                        "maturity_rung",
                        "execution_level",
                        "evidence_class",
                        "independence",
                        "source_tier",
                        "publisher_name",
                        "publisher_type",
                        "published_at",
                        "canonical_url",
                        "document_title",
                        "section_heading",
                        "document_id",
                        "span_id",
                        "char_start",
                        "char_end",
                        "connector_code",
                    )
                },
            }
            for lid, stt in link_states.items()
            if stt.get("criterion_code") == code
        ]
        out.append(
            {
                "criterion_code": code,
                "criterion_name": st.manifest.criterion(code).name,
                "decision_id": str(d.id),
                "level": d.level,
                "coverage_state": _enum(d.coverage_state),
                "confidence": float(d.confidence),
                "applied_rule_codes": list(d.applied_rule_codes),
                "rules": trace.get("rules", []),
                "inputs": trace.get("inputs", {}),
                "caps_applied": trace.get("caps_applied", []),
                "adjustments": trace.get("adjustments", []),
                "finding": {
                    "id": str(f.id),
                    "proposed_level": f.proposed_level,
                    "model_id": f.model_id,
                    "uncertainty": float(f.uncertainty),
                    "reasoning_summary": f.reasoning_summary,
                }
                if f
                else None,
                "evidence": evidence,
            }
        )
    if criterion_code and not out:
        raise NotFoundError(f"no decision for criterion {criterion_code}")
    payload: dict[str, Any] = {"assessment_id": str(assessment_id), "criteria": out}
    if not criterion_code:
        payload["result"] = {
            "hai_score": float(result.hai_score) if result and result.hai_score is not None else None,
            "outcome_status": _enum(result.outcome_status) if result else None,
            "rules": (result.trace or {}).get("rules", []) if result and isinstance(result.trace, dict) else [],
            "overlay": (result.trace or {}).get("overlay", {}) if result and isinstance(result.trace, dict) else {},
            "result_sha256": result.result_sha256 if result else None,
        }
        payload["snapshot"] = (
            {
                "id": str(snapshot.id),
                "frozen_at": snapshot.frozen_at.isoformat(),
                "sha256": snapshot.snapshot_sha256,
                "version_pins": snapshot.version_pins,
            }
            if snapshot
            else None
        )
    return payload


@router.get("/{assessment_id}/trace", summary="Every decision, rule and quote behind the score")
def get_trace(assessment_id: UUID, st: State, principal: Reader) -> dict[str, Any]:
    with st.read(principal) as (_, store):
        return _trace_for(st, store, assessment_id, None)


@router.get("/{assessment_id}/trace/{criterion_code}", summary="Trace for one criterion down to the exact quote")
def get_criterion_trace(assessment_id: UUID, criterion_code: str, st: State, principal: Reader) -> dict[str, Any]:
    alias = st.manifest.vocabularies["criterion_code"].resolve_alias(criterion_code)
    if alias is None:
        raise NotFoundError(f"unknown criterion {criterion_code}")
    with st.read(principal) as (_, store):
        return _trace_for(st, store, assessment_id, alias)


@router.get("/{assessment_id}/connector-runs", summary="What each source returned (IC-16)")
def get_connector_runs(assessment_id: UUID, st: State, principal: Reader) -> dict[str, Any]:
    with st.read(principal) as (conn, store):
        load_assessment(store, assessment_id)
        rows = (
            conn.execute(
                text(
                    "SELECT r.id, c.code, c.name, r.outcome::text, r.items_returned, r.error_code, r.started_at, r.finished_at, r.notes "
                    "FROM hai.connector_runs r JOIN hai.connectors c ON c.id = r.connector_id WHERE r.assessment_id = :a ORDER BY r.started_at"
                ),
                {"a": assessment_id},
            )
            .mappings()
            .all()
        )
    items = [
        {
            **dict(r),
            "id": str(r["id"]),
            "outcome_label": LABELS["connector_run_outcome"][r["outcome"]],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        }
        for r in rows
    ]
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}


@router.post("/{assessment_id}/cancel", response_model=AssessmentOut, summary="Cancel a queued or running assessment")
def cancel_assessment(assessment_id: UUID, st: State, principal: Writer) -> AssessmentOut:
    with st.tx(principal, "hai_api") as (_, store):
        updated = cancel(store, load_assessment(store, assessment_id), principal)
    return assessment_out(updated, st.settings.public_base_url)


@router.post(
    "/{assessment_id}/certification-request",
    response_model=AssessmentOut,
    summary="Ask a reviewer to decide on certification",
)
def certification_request(assessment_id: UUID, st: State, principal: Writer) -> AssessmentOut:
    with st.tx(principal, "hai_api") as (conn, store):
        updated = request_certification(conn, store, load_assessment(store, assessment_id), principal)
    return assessment_out(updated, st.settings.public_base_url)


@router.post(
    "/{assessment_id}/reassess",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AssessmentOut,
    summary="Start a new assessment of the same organization",
)
def reassess_assessment(assessment_id: UUID, st: State, principal: Writer, response: Response) -> AssessmentOut:
    with st.tx(principal, "hai_api") as (conn, store):
        new = reassess(
            conn,
            store,
            assessment=load_assessment(store, assessment_id),
            principal=principal,
            settings=st.settings,
            manifest=st.manifest,
            queue=st.queue,
        )
    response.headers["Location"] = f"{st.settings.public_base_url}/v1/assessments/{new.id}"
    return assessment_out(new, st.settings.public_base_url)
