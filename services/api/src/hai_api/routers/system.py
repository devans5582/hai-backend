"""Health, readiness, tokens, webhooks and the audit log."""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import text

from hai_api.auth import Admin, require
from hai_api.deps import State
from hai_api.schemas import TokenOut, TokenRequest, WebhookCreate
from hai_core.audit import list_events, verify_chain
from hai_core.auth import Principal, Scope, mint_jwt
from hai_core.db.migrate import schema_version
from hai_core.errors import NotFoundError, UnavailableError, ValidationFailedError
from hai_core.webhooks import EVENTS, deactivate, list_subscriptions, subscribe

router = APIRouter(tags=["system"])

AuditReader = Annotated[Principal, Depends(require(Scope.AUDIT_READ))]
WebhookWriter = Annotated[Principal, Depends(require(Scope.WEBHOOKS_WRITE))]


@router.get("/health", summary="Liveness")
def health(st: State) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "hai-api",
        "ontology_version": st.manifest.ontology_version,
        "methodology_version": st.manifest.methodology_version,
    }


@router.get("/ready", summary="Readiness: database reachable and migrated to this ontology version")
def ready(st: State, response: Response) -> dict[str, Any]:
    if not st.db.ping():
        raise UnavailableError("database unreachable")
    sv = schema_version(st.db)
    if sv is None:
        raise UnavailableError("database not migrated")
    ontology_version, methodology_version, manifest_hash = sv
    ok = ontology_version == st.manifest.ontology_version and manifest_hash == st.manifest.hash
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ok else "schema_mismatch",
        "database": {
            "ontology_version": ontology_version,
            "methodology_version": methodology_version,
            "manifest_hash": manifest_hash,
        },
        "service": {
            "ontology_version": st.manifest.ontology_version,
            "methodology_version": st.manifest.methodology_version,
            "manifest_hash": st.manifest.hash,
        },
    }


@router.post("/v1/auth/token", response_model=TokenOut, summary="Mint a reviewer or admin JWT (admin only)")
def mint_token(body: TokenRequest, st: State, principal: Admin) -> TokenOut:
    scopes = (
        frozenset(body.scopes)
        if body.scopes is not None
        else (Scope.REVIEWER_DEFAULT if body.role == "reviewer" else Scope.ALL)
    )
    unknown = sorted(scopes - Scope.ALL)
    if unknown:
        raise ValidationFailedError(f"unknown scopes {unknown}", details={"scopes": sorted(Scope.ALL)})
    ttl = body.ttl_minutes or st.settings.jwt_ttl_minutes
    token = mint_jwt(
        st.settings.jwt_secret.get_secret_value(),
        subject=body.subject,
        name=body.name,
        role=cast(Literal["reviewer", "admin"], body.role),
        scopes=scopes,
        issuer=st.settings.jwt_issuer,
        ttl_minutes=ttl,
    )
    with st.tx(principal, "hai_api") as (_, store):
        store.record_action(
            "token_minted",
            "Principal",
            None,
            reason=f"{body.role} token for {body.subject}",
            after={"subject": body.subject, "role": body.role, "scopes": sorted(scopes)},
        )
    return TokenOut(
        token=token, role=cast(Literal["reviewer", "admin"], body.role), scopes=sorted(scopes), expires_in_minutes=ttl
    )


@router.post(
    "/v1/webhooks", status_code=status.HTTP_201_CREATED, summary="Subscribe to events (HMAC-signed deliveries)"
)
def create_webhook(body: WebhookCreate, st: State, principal: WebhookWriter) -> dict[str, Any]:
    with st.tx(principal, "hai_api") as (conn, _):
        sub = subscribe(conn, owner=principal.actor, url=body.url, events=body.events, secret=body.secret)
    return {**sub.as_dict(), "events_available": list(EVENTS)}


@router.get("/v1/webhooks", summary="Your webhook subscriptions")
def get_webhooks(st: State, principal: WebhookWriter) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        subs = list_subscriptions(conn, owner=None if principal.has(Scope.ADMIN) else principal.actor)
    return {"items": [s.as_dict() for s in subs], "total": len(subs), "limit": len(subs) or 1, "offset": 0}


@router.delete(
    "/v1/webhooks/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate a subscription"
)
def delete_webhook(subscription_id: UUID, st: State, principal: WebhookWriter) -> Response:
    with st.tx(principal, "hai_api") as (conn, _):
        ok = deactivate(conn, subscription_id, owner=None if principal.has(Scope.ADMIN) else principal.actor)
    if not ok:
        raise NotFoundError("no active subscription with that id")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/audit/verify", summary="Recompute the audit hash chain (AT-15)")
def audit_verify(st: State, principal: AuditReader) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        result = verify_chain(conn)
    return {"ok": result.ok, "events": result.events, "first_bad_seq": result.first_bad_seq, "message": result.message}


@router.get("/v1/audit/events", summary="Audit events, newest first")
def audit_events(
    st: State,
    principal: AuditReader,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        rows = list_events(conn, limit=limit, offset=offset)
        total = int(conn.execute(text("SELECT count(*) FROM hai.audit_events")).scalar_one())
    items = [
        {
            **r,
            "id": str(r["id"]),
            "subject_id": str(r["subject_id"]) if r["subject_id"] else None,
            "at": r["at"].isoformat(),
        }
        for r in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}
