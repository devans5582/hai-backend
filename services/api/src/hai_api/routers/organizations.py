"""Organizations, their assessments and evidence ledger, monitoring, uploads, benchmarks."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import text

from hai_api.auth import require
from hai_api.deps import State
from hai_api.routers.assessments import assessment_out
from hai_api.schemas import MonitoringCreate, OrganizationOut, Page
from hai_core.auth import Principal, Scope
from hai_core.errors import ValidationFailedError
from hai_core.generated.enums import LABELS
from hai_core.generated.models import Assessment, Organization
from hai_core.monitoring import list_subscriptions, register_upload, subscribe
from hai_core.visibility import require_visible_organization, restriction, visible_organization_ids

router = APIRouter(prefix="/v1", tags=["organizations"])

Reader = Annotated[Principal, Depends(require(Scope.ORGANIZATIONS_READ))]
Writer = Annotated[Principal, Depends(require(Scope.ASSESSMENTS_WRITE))]
Uploader = Annotated[Principal, Depends(require(Scope.UPLOADS_WRITE))]

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _enum(value: Any) -> str | None:
    if value is None:
        return None
    return str(value.value) if hasattr(value, "value") else str(value)


def org_out(o: Organization) -> OrganizationOut:
    return OrganizationOut(
        id=o.id,
        legal_name=o.legal_name,
        display_name=o.display_name,
        primary_domain=o.primary_domain,
        aliases=list(o.aliases or []),
        industry_code=o.industry_code,
        stage_band=_enum(o.stage_band),
        size_band=_enum(o.size_band),
        identifiers={"cik": o.cik, "lei": o.lei, "wikidata_qid": o.wikidata_qid, "github_handle": o.github_handle},
        identifiers_verified=o.identifiers_verified,
        entity_confidence=float(o.entity_confidence) if o.entity_confidence is not None else None,
        created_at=o.created_at,
    )


@router.get("/organizations", response_model=Page[OrganizationOut], summary="List organizations")
def list_organizations(
    st: State,
    principal: Reader,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[OrganizationOut]:
    with st.read(principal) as (conn, store):
        if principal.is_restricted:
            ids, total = visible_organization_ids(conn, principal, q=q, limit=limit, offset=offset)
            items = [org_out(store.require(Organization, i)) for i in ids]
        elif q:
            rows = conn.execute(
                text(
                    "SELECT id FROM hai.organizations WHERE display_name ILIKE :q OR legal_name ILIKE :q OR primary_domain ILIKE :q ORDER BY display_name LIMIT :l OFFSET :o"
                ),
                {"q": f"%{q}%", "l": limit, "o": offset},
            ).all()
            total = int(
                conn.execute(
                    text(
                        "SELECT count(*) FROM hai.organizations WHERE display_name ILIKE :q OR legal_name ILIKE :q OR primary_domain ILIKE :q"
                    ),
                    {"q": f"%{q}%"},
                ).scalar_one()
            )
            items = [org_out(store.require(Organization, r[0])) for r in rows]
        else:
            items = [org_out(o) for o in store.find(Organization, order_by="display_name", limit=limit, offset=offset)]
            total = store.count(Organization)
    return Page(items=items, total=total, limit=limit, offset=offset)


OVERVIEW_SQL = """
WITH visible AS (
    SELECT o.id FROM hai.organizations o WHERE {restriction}
      AND (CAST(:q AS text) IS NULL OR o.display_name ILIKE :q OR o.legal_name ILIKE :q OR o.primary_domain ILIKE :q)
),
runs AS (
    SELECT a.org_id, a.id, a.lifecycle_state::text AS lifecycle_state, a.created_at, a.finished_at,
           a.certification_requested,
           row_number() OVER (PARTITION BY a.org_id ORDER BY a.created_at, a.id) AS version,
           count(*) OVER (PARTITION BY a.org_id) AS versions
    FROM hai.assessments a WHERE a.org_id IN (SELECT id FROM visible)
),
latest AS (SELECT DISTINCT ON (org_id) * FROM runs ORDER BY org_id, created_at DESC, id DESC),
previous AS (SELECT DISTINCT ON (r.org_id) r.* FROM runs r JOIN latest l ON l.org_id = r.org_id AND r.id <> l.id ORDER BY r.org_id, r.created_at DESC, r.id DESC),
results AS (
    SELECT DISTINCT ON (res.assessment_id) res.assessment_id, res.hai_score, res.confidence_pct, res.outcome_status::text
    FROM hai.assessment_results res
    WHERE NOT EXISTS (SELECT 1 FROM hai.assessment_results later WHERE later.supersedes_id = res.id)
    ORDER BY res.assessment_id, res.created_at DESC
)
SELECT o.id AS org_id, o.display_name, o.legal_name, o.primary_domain, o.industry_code, o.stage_band::text, o.size_band::text,
       o.identifiers_verified, o.created_at AS org_created_at,
       l.id AS latest_id, l.lifecycle_state, l.created_at AS latest_created_at, l.finished_at AS latest_finished_at,
       l.version, l.versions, l.certification_requested,
       lr.hai_score, lr.confidence_pct, lr.outcome_status,
       p.id AS previous_id, p.created_at AS previous_created_at, pr.hai_score AS previous_score, pr.outcome_status AS previous_outcome
FROM hai.organizations o
JOIN visible v ON v.id = o.id
LEFT JOIN latest l ON l.org_id = o.id
LEFT JOIN results lr ON lr.assessment_id = l.id
LEFT JOIN previous p ON p.org_id = o.id
LEFT JOIN results pr ON pr.assessment_id = p.id
WHERE (NOT CAST(:assessed_only AS boolean) OR l.id IS NOT NULL)
ORDER BY coalesce(l.created_at, o.created_at) DESC, o.display_name
LIMIT :l OFFSET :off
"""
OVERVIEW_COUNT_SQL = """
SELECT count(*) FROM hai.organizations o WHERE {restriction}
  AND (CAST(:q AS text) IS NULL OR o.display_name ILIKE :q OR o.legal_name ILIKE :q OR o.primary_domain ILIKE :q)
  AND (NOT CAST(:assessed_only AS boolean) OR EXISTS (SELECT 1 FROM hai.assessments a WHERE a.org_id = o.id))
"""

HISTORY_SQL = """
WITH runs AS (
    SELECT a.id, a.lifecycle_state::text AS lifecycle_state, a.created_at, a.finished_at, a.requested_by,
           a.methodology_version, a.ruleset_version, a.model_id, a.parent_assessment_id, a.certification_requested,
           row_number() OVER (ORDER BY a.created_at, a.id) AS version
    FROM hai.assessments a WHERE a.org_id = :o
),
results AS (
    SELECT DISTINCT ON (res.assessment_id) res.assessment_id, res.hai_score, res.confidence_pct, res.effectiveness,
           res.outcome_status::text
    FROM hai.assessment_results res
    WHERE NOT EXISTS (SELECT 1 FROM hai.assessment_results later WHERE later.supersedes_id = res.id)
    ORDER BY res.assessment_id, res.created_at DESC
)
SELECT r.*, res.hai_score, res.confidence_pct, res.effectiveness, res.outcome_status
FROM runs r LEFT JOIN results res ON res.assessment_id = r.id
ORDER BY r.version DESC
"""


def _result_summary(row: Any) -> dict[str, Any] | None:
    if row["outcome_status"] is None:
        return None
    return {
        "hai_score": float(row["hai_score"]) if row["hai_score"] is not None else None,
        "confidence_pct": float(row["confidence_pct"]) if row["confidence_pct"] is not None else None,
        "outcome_status": row["outcome_status"],
        "outcome_label": LABELS["outcome_status"][row["outcome_status"]],
    }


def _history_result(row: Any) -> dict[str, Any] | None:
    summary = _result_summary(row)
    if summary is None:
        return None
    if row["effectiveness"] is not None:
        summary["effectiveness"] = float(row["effectiveness"])
    return summary


@router.get(
    "/organizations/overview",
    summary="One row per organization: the latest assessment version, its result, the version count and the previous score",
)
def organizations_overview(
    st: State,
    principal: Reader,
    q: str | None = None,
    assessed_only: bool = Query(default=True, description="hide organizations that were never assessed"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    clause, vis_params = restriction(principal, assessment="", organization="o")
    params: dict[str, Any] = {
        **vis_params,
        "q": f"%{q}%" if q else None,
        "assessed_only": assessed_only,
        "l": limit,
        "off": offset,
    }
    with st.read(principal) as (conn, _):
        rows = conn.execute(text(OVERVIEW_SQL.format(restriction=clause)), params).mappings().all()
        total = int(conn.execute(text(OVERVIEW_COUNT_SQL.format(restriction=clause)), params).scalar_one())
    items = []
    for r in rows:
        latest = (
            {
                "id": str(r["latest_id"]),
                "version": int(r["version"]),
                "lifecycle_state": r["lifecycle_state"],
                "lifecycle_label": LABELS["lifecycle_state"][r["lifecycle_state"]],
                "certification_requested": bool(r["certification_requested"]),
                "created_at": r["latest_created_at"].isoformat() if r["latest_created_at"] else None,
                "finished_at": r["latest_finished_at"].isoformat() if r["latest_finished_at"] else None,
            }
            if r["latest_id"]
            else None
        )
        previous = (
            {
                "id": str(r["previous_id"]),
                "created_at": r["previous_created_at"].isoformat() if r["previous_created_at"] else None,
                "hai_score": float(r["previous_score"]) if r["previous_score"] is not None else None,
                "outcome_status": r["previous_outcome"],
            }
            if r["previous_id"]
            else None
        )
        score = float(r["hai_score"]) if r["hai_score"] is not None else None
        prev_score = previous["hai_score"] if previous else None
        items.append(
            {
                "organization": {
                    "id": str(r["org_id"]),
                    "display_name": r["display_name"],
                    "legal_name": r["legal_name"],
                    "primary_domain": r["primary_domain"],
                    "industry_code": r["industry_code"],
                    "industry_label": LABELS["industry"].get(r["industry_code"], r["industry_code"])
                    if r["industry_code"]
                    else None,
                    "stage_band": r["stage_band"],
                    "size_band": r["size_band"],
                    "identifiers_verified": bool(r["identifiers_verified"]),
                },
                "versions": int(r["versions"]) if r["versions"] is not None else 0,
                "latest": latest,
                "result": _result_summary(r),
                "previous": previous,
                "score_delta": round(score - prev_score, 1) if score is not None and prev_score is not None else None,
            }
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/organizations/{org_id}/history", summary="Every assessment of an organization as numbered versions, newest first"
)
def organization_history(org_id: UUID, st: State, principal: Reader) -> dict[str, Any]:
    with st.read(principal) as (conn, store):
        require_visible_organization(store, principal, org_id)
        rows = conn.execute(text(HISTORY_SQL), {"o": org_id}).mappings().all()
    items = [
        {
            "version": int(r["version"]),
            "is_latest": i == 0,
            "assessment": {
                "id": str(r["id"]),
                "lifecycle_state": r["lifecycle_state"],
                "lifecycle_label": LABELS["lifecycle_state"][r["lifecycle_state"]],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
                "requested_by": r["requested_by"],
                "methodology_version": r["methodology_version"],
                "ruleset_version": r["ruleset_version"],
                "model_id": r["model_id"],
                "parent_assessment_id": str(r["parent_assessment_id"]) if r["parent_assessment_id"] else None,
                "certification_requested": bool(r["certification_requested"]),
            },
            "result": _history_result(r),
        }
        for i, r in enumerate(rows)
    ]
    return {
        "organization_id": str(org_id),
        "latest_id": str(rows[0]["id"]) if rows else None,
        "items": items,
        "total": len(items),
        "limit": len(items) or 1,
        "offset": 0,
    }


@router.get("/organizations/{org_id}", response_model=OrganizationOut)
def get_organization(org_id: UUID, st: State, principal: Reader) -> OrganizationOut:
    with st.read(principal) as (_, store):
        org = require_visible_organization(store, principal, org_id)
    return org_out(org)


@router.get("/organizations/{org_id}/assessments", summary="Assessments of an organization, newest first")
def org_assessments(
    org_id: UUID,
    st: State,
    principal: Reader,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with st.read(principal) as (_, store):
        require_visible_organization(store, principal, org_id)
        rows = store.find(
            Assessment, where={"org_id": org_id}, order_by="created_at", descending=True, limit=limit, offset=offset
        )
        total = store.count(Assessment, where={"org_id": org_id})
    return {
        "items": [assessment_out(a, st.settings.public_base_url).model_dump(mode="json") for a in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


EVIDENCE_SQL = """
SELECT l.id AS link_id, l.criterion_code::text, l.polarity::text, l.admissibility::text, l.maturity_rung::text, l.execution_level::text,
       l.evidence_class::text, l.independence::text, l.source_tier::text, l.proposer, l.relevance, l.created_at,
       s.id AS span_id, s.quote, s.char_start, s.char_end, s.section_heading,
       d.id AS document_id, d.canonical_url, d.title, d.published_at, d.retrieved_at, d.sha256,
       p.name AS publisher, p.publisher_type::text, c.code AS connector, r.assessment_id
FROM hai.evidence_links l
JOIN hai.evidence_spans s ON s.id = l.span_id
JOIN hai.source_documents d ON d.id = s.source_document_id
JOIN hai.publishers p ON p.id = d.publisher_id
JOIN hai.connector_runs r ON r.id = d.connector_run_id
JOIN hai.connectors c ON c.id = r.connector_id
JOIN hai.assessments a ON a.id = r.assessment_id
WHERE a.org_id = :o
  AND (CAST(:crit AS text) IS NULL OR l.criterion_code::text = :crit)
  AND (CAST(:adm AS text) IS NULL OR l.admissibility::text = :adm)
  AND NOT EXISTS (SELECT 1 FROM hai.evidence_links newer WHERE newer.supersedes_id = l.id)
ORDER BY l.created_at DESC, l.id
LIMIT :l OFFSET :off
"""
EVIDENCE_COUNT_SQL = """
SELECT count(*) FROM hai.evidence_links l
JOIN hai.evidence_spans s ON s.id = l.span_id
JOIN hai.source_documents d ON d.id = s.source_document_id
JOIN hai.connector_runs r ON r.id = d.connector_run_id
JOIN hai.assessments a ON a.id = r.assessment_id
WHERE a.org_id = :o AND (CAST(:crit AS text) IS NULL OR l.criterion_code::text = :crit) AND (CAST(:adm AS text) IS NULL OR l.admissibility::text = :adm)
  AND NOT EXISTS (SELECT 1 FROM hai.evidence_links newer WHERE newer.supersedes_id = l.id)
"""


@router.get(
    "/organizations/{org_id}/evidence",
    summary="The evidence ledger: links with their spans and sources (paginated with totals)",
)
def org_evidence(
    org_id: UUID,
    st: State,
    principal: Reader,
    criterion: str | None = None,
    admissibility: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    crit = st.manifest.vocabularies["criterion_code"].resolve_alias(criterion) if criterion else None
    if criterion and crit is None:
        raise ValidationFailedError(f"unknown criterion {criterion}", details={"field": "criterion"})
    params = {"o": org_id, "crit": crit, "adm": admissibility, "l": limit, "off": offset}
    with st.read(principal) as (conn, store):
        require_visible_organization(store, principal, org_id)
        rows = conn.execute(text(EVIDENCE_SQL), params).mappings().all()
        total = int(conn.execute(text(EVIDENCE_COUNT_SQL), params).scalar_one())
    items = []
    for r in rows:
        item = dict(r)
        for k in ("link_id", "span_id", "document_id", "assessment_id"):
            item[k] = str(item[k])
        for k in ("created_at", "published_at", "retrieved_at"):
            item[k] = item[k].isoformat() if item[k] else None
        item["relevance"] = float(item["relevance"]) if item["relevance"] is not None else None
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post(
    "/organizations/{org_id}/monitoring",
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe an organization to continuous monitoring",
)
def add_monitoring(org_id: UUID, body: MonitoringCreate, st: State, principal: Writer) -> dict[str, Any]:
    with st.tx(principal, "hai_api") as (conn, store):
        require_visible_organization(store, principal, org_id)
        sub = subscribe(conn, org_id=org_id, interval_days=body.interval_days, requested_by=principal.actor)
    return sub.as_dict()


@router.get("/organizations/{org_id}/monitoring", summary="Monitoring subscriptions of an organization")
def get_monitoring(org_id: UUID, st: State, principal: Reader) -> dict[str, Any]:
    with st.read(principal) as (conn, store):
        require_visible_organization(store, principal, org_id)
        subs = list_subscriptions(conn, org_id=org_id)
    return {"items": [s.as_dict() for s in subs], "total": len(subs), "limit": len(subs) or 1, "offset": 0}


@router.post(
    "/evidence/uploads",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a document through the evidence portal (enters as a claim)",
)
async def upload_evidence(
    st: State,
    principal: Uploader,
    org_id: Annotated[UUID, Form()],
    assertion_text: Annotated[str, Form(min_length=3, max_length=2000)],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    content = await file.read()
    if not content:
        raise ValidationFailedError("the uploaded file is empty", details={"field": "file"})
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValidationFailedError("the uploaded file is larger than 20 MB", details={"field": "file"})
    with st.tx(principal, "hai_api") as (conn, store):
        require_visible_organization(store, principal, org_id)
        up = register_upload(
            conn,
            st.blobs,
            org_id=org_id,
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            assertion_text=assertion_text,
            submitted_by=principal.actor,
        )
    return up.as_dict()


@router.get(
    "/benchmarks/industries",
    tags=["benchmarks"],
    summary="Peers by industry, stage band and size band (access-limited runs excluded)",
)
def benchmarks(st: State, principal: Reader, industry: str | None = None) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        rows = (
            conn.execute(
                text(
                    "SELECT industry, stage_band::text, size_band::text, organizations, average_score, average_confidence FROM hai_ops.v_industry_benchmarks WHERE (CAST(:i AS text) IS NULL OR industry = :i) ORDER BY industry, stage_band, size_band"
                ),
                {"i": industry},
            )
            .mappings()
            .all()
        )
    items = [
        {
            **dict(r),
            "average_score": float(r["average_score"]) if r["average_score"] is not None else None,
            "average_confidence": float(r["average_confidence"]) if r["average_confidence"] is not None else None,
        }
        for r in rows
    ]
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}
