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
from hai_core.errors import NotFoundError, ValidationFailedError
from hai_core.generated.models import Assessment, Organization
from hai_core.monitoring import list_subscriptions, register_upload, subscribe

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
        if q:
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


@router.get("/organizations/{org_id}", response_model=OrganizationOut)
def get_organization(org_id: UUID, st: State, principal: Reader) -> OrganizationOut:
    with st.read(principal) as (_, store):
        org = store.get(Organization, org_id)
    if org is None:
        raise NotFoundError(f"organization {org_id} not found")
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
        if store.get(Organization, org_id) is None:
            raise NotFoundError(f"organization {org_id} not found")
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
        if store.get(Organization, org_id) is None:
            raise NotFoundError(f"organization {org_id} not found")
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
        if store.get(Organization, org_id) is None:
            raise NotFoundError(f"organization {org_id} not found")
        sub = subscribe(conn, org_id=org_id, interval_days=body.interval_days, requested_by=principal.actor)
    return sub.as_dict()


@router.get("/organizations/{org_id}/monitoring", summary="Monitoring subscriptions of an organization")
def get_monitoring(org_id: UUID, st: State, principal: Reader) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
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
        if store.get(Organization, org_id) is None:
            raise NotFoundError(f"organization {org_id} not found")
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
