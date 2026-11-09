"""What a restricted principal may see.

An organization account sees only its own organization. A platform user whose
invitation named industries sees only organizations in those industries. The
restriction is applied in SQL for lists and as a check for single resources;
a hidden resource answers "not found", never "forbidden", so existence is not
revealed. Unrestricted principals pass through untouched.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.auth import Principal
from hai_core.db.store import Store
from hai_core.errors import NotFoundError
from hai_core.generated.models import Assessment, Organization


def restriction(principal: Principal, *, assessment: str = "a", organization: str = "o") -> tuple[str, dict[str, Any]]:
    """A SQL fragment (always true for unrestricted principals) and its parameters.

    ``assessment`` and ``organization`` are the table aliases in the caller's query;
    pass ``assessment=None``-style empty strings when only organizations are queried.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if principal.org_ids:
        column = f"{assessment}.org_id" if assessment else f"{organization}.id"
        clauses.append(f"{column} = ANY(CAST(:vis_orgs AS uuid[]))")
        params["vis_orgs"] = [UUID(x) for x in sorted(principal.org_ids)]
    if principal.industries:
        clauses.append(f"lower(coalesce({organization}.industry_code, '')) = ANY(CAST(:vis_industries AS text[]))")
        params["vis_industries"] = sorted(principal.industries)
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def organization_visible(principal: Principal, org: Organization) -> bool:
    if principal.org_ids and str(org.id) not in principal.org_ids:
        return False
    return not (principal.industries and (org.industry_code or "").strip().lower() not in principal.industries)


def require_visible_organization(store: Store, principal: Principal, org_id: UUID) -> Organization:
    org = store.get(Organization, org_id)
    if org is None or not organization_visible(principal, org):
        raise NotFoundError(f"organization {org_id} not found")
    return org


def require_visible_assessment(store: Store, principal: Principal, assessment: Assessment) -> Assessment:
    if not principal.is_restricted:
        return assessment
    org = store.get(Organization, assessment.org_id)
    if org is None or not organization_visible(principal, org):
        raise NotFoundError(f"assessment {assessment.id} not found")
    return assessment


def visible_assessment_ids(
    conn: Connection,
    principal: Principal,
    *,
    org_id: UUID | None = None,
    lifecycle_state: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[UUID], int]:
    """Newest-first assessment ids the principal may see, with the total."""
    clause, params = restriction(principal)
    where = [clause]
    if org_id is not None:
        where.append("a.org_id = :org_id")
        params["org_id"] = org_id
    if lifecycle_state:
        where.append("a.lifecycle_state::text = :state")
        params["state"] = lifecycle_state
    sql_where = " AND ".join(where)
    base = "FROM hai.assessments a JOIN hai.organizations o ON o.id = a.org_id WHERE " + sql_where
    total = int(conn.execute(text("SELECT count(*) " + base), params).scalar_one())
    rows = conn.execute(
        text(f"SELECT a.id {base} ORDER BY a.created_at DESC, a.id LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    ).all()
    return [r[0] for r in rows], total


def visible_organization_ids(
    conn: Connection, principal: Principal, *, q: str | None = None, limit: int, offset: int
) -> tuple[list[UUID], int]:
    """Organization ids the principal may see, by display name, with the total."""
    clause, params = restriction(principal, assessment="")
    where = [clause]
    if q:
        where.append("(o.display_name ILIKE :q OR o.legal_name ILIKE :q OR o.primary_domain ILIKE :q)")
        params["q"] = f"%{q}%"
    base = "FROM hai.organizations o WHERE " + " AND ".join(where)
    total = int(conn.execute(text("SELECT count(*) " + base), params).scalar_one())
    rows = conn.execute(
        text(f"SELECT o.id {base} ORDER BY o.display_name, o.id LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    ).all()
    return [r[0] for r in rows], total
