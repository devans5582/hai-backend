"""Assessment lifecycle services shared by the API and the worker.

Create (idempotent), reassess, cancel, request certification, and the job
chain that moves an assessment through its lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from hai_core.auth import Principal
from hai_core.db.store import Store
from hai_core.errors import ConflictError, InvalidTransitionError, ValidationFailedError
from hai_core.generated.enums import ATTRIBUTES, TRANSITIONS, LifecycleState, SizeBand, StageBand, resolve_alias
from hai_core.generated.models import Assessment, Organization
from hai_core.queue import JobQueue
from hai_core.settings import Settings
from hai_ontology.meta import Manifest

JOB_CHAIN: tuple[str, ...] = (
    "acquire_evidence",
    "classify_links",
    "freeze_snapshot",
    "evaluate_criteria",
    "decide",
    "finalize",
)


@dataclass
class AssessmentRequest:
    organization_name: str
    website: str
    stage: str
    size: str
    industry: str | None = None
    direct_urls: list[str] = field(default_factory=list)
    certification_requested: bool = False
    legal_name: str | None = None
    aliases: list[str] = field(default_factory=list)


def _registrable(website: str) -> str:
    from urllib.parse import urlsplit

    text = website.strip()
    if "://" not in text:
        text = "https://" + text
    host = (urlsplit(text).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if "." not in host:
        raise ValidationFailedError("website must be a domain or URL", details={"field": "website"})
    return host


def resolve_bands(stage: str, size: str) -> tuple[StageBand, SizeBand]:
    s = resolve_alias("stage_band", stage)
    z = resolve_alias("size_band", size)
    problems: dict[str, str] = {}
    if s is None:
        problems["stage"] = f"unknown stage {stage!r}; accepted values and aliases: " + ", ".join(
            sorted(ATTRIBUTES.get("stage_band", {}).keys() | set(StageBand))
        )
    if z is None:
        problems["size"] = f"unknown size {size!r}; accepted values include " + ", ".join(SizeBand)
    if problems:
        raise ValidationFailedError("invalid stage or size", details={"fields": problems})
    assert s is not None and z is not None
    return StageBand(s), SizeBand(z)


def find_or_create_organization(store: Store, request: AssessmentRequest) -> Organization:
    domain = _registrable(request.website)
    existing = store.first(Organization, where={"primary_domain": domain})
    if existing:
        changes: dict[str, Any] = {}
        if request.industry and existing.industry_code != request.industry:
            changes["industry_code"] = request.industry
        if changes:
            return store.update(Organization, existing.id, changes, reason="assessment request")
        return existing
    stage, size = resolve_bands(request.stage, request.size)
    return store.insert(
        Organization(
            legal_name=request.legal_name or request.organization_name,
            display_name=request.organization_name,
            primary_domain=domain,
            aliases=list(request.aliases),
            industry_code=request.industry,
            stage_band=stage,
            size_band=size,
        ),
        reason="assessment request",
    )


def create_assessment(
    conn: Connection,
    store: Store,
    *,
    request: AssessmentRequest,
    principal: Principal,
    settings: Settings,
    manifest: Manifest,
    idempotency_key: str | None = None,
    parent_assessment_id: UUID | None = None,
    queue: JobQueue | None = None,
) -> tuple[Assessment, bool]:
    """Create an assessment and queue acquisition. Returns (assessment, created)."""
    if idempotency_key:
        existing = store.first(Assessment, where={"idempotency_key": idempotency_key})
        if existing:
            if existing.requested_by != principal.actor:
                raise ConflictError("Idempotency-Key was used by a different principal")
            if existing.submitted_domain != _registrable(request.website):
                raise ConflictError("Idempotency-Key was used with a different request body")
            return existing, False
    stage, size = resolve_bands(request.stage, request.size)
    org = find_or_create_organization(store, request)
    assessment = store.insert(
        Assessment(
            org_id=org.id,
            parent_assessment_id=parent_assessment_id,
            requested_by=principal.actor,
            submitted_domain=org.primary_domain,
            direct_urls=[u.strip() for u in request.direct_urls if u.strip()],
            stage_band=stage,
            size_band=size,
            methodology_version=manifest.methodology_version,
            ruleset_version=manifest.ruleset.version,
            prompt_version=settings.prompt_version,
            model_id=f"{settings.llm_provider}:{settings.llm_model}",
            lifecycle_state=LifecycleState.QUEUED,
            idempotency_key=idempotency_key,
            certification_requested=request.certification_requested,
        ),
        reason="created",
    )
    (queue or JobQueue()).enqueue(
        conn,
        JOB_CHAIN[0],
        {"assessment_id": str(assessment.id)},
        dedupe_key=f"{JOB_CHAIN[0]}:{assessment.id}",
        priority=5,
    )
    return assessment, True


def reassess(
    conn: Connection,
    store: Store,
    *,
    assessment: Assessment,
    principal: Principal,
    settings: Settings,
    manifest: Manifest,
    queue: JobQueue | None = None,
) -> Assessment:
    org = store.require(Organization, assessment.org_id)
    request = AssessmentRequest(
        organization_name=org.display_name,
        website=org.primary_domain,
        stage=str(assessment.stage_band.value),
        size=str(assessment.size_band.value),
        industry=org.industry_code,
        direct_urls=list(assessment.direct_urls or []),
        certification_requested=assessment.certification_requested,
    )
    new, _ = create_assessment(
        conn,
        store,
        request=request,
        principal=principal,
        settings=settings,
        manifest=manifest,
        parent_assessment_id=assessment.id,
        queue=queue,
    )
    return new


def transition(
    store: Store, assessment: Assessment, target: LifecycleState, *, reason: str, extra: dict[str, Any] | None = None
) -> Assessment:
    """Move the lifecycle; the manifest's transitions table is checked here and again by the database trigger."""
    current = str(assessment.lifecycle_state.value)
    allowed = TRANSITIONS["lifecycle_state"].get(current, [])
    if target.value not in allowed:
        raise InvalidTransitionError(
            f"assessment cannot move from {current} to {target.value}", details={"allowed": allowed}
        )
    changes: dict[str, Any] = {"lifecycle_state": target, **(extra or {})}
    terminal = bool(ATTRIBUTES["lifecycle_state"][target.value]["terminal"])
    if terminal or target in (LifecycleState.COMPLETED_UNVERIFIED,):
        changes.setdefault("finished_at", datetime.now(UTC))
    if target is LifecycleState.ACQUIRING:
        changes.setdefault("started_at", datetime.now(UTC))
    return store.update(Assessment, assessment.id, changes, reason=reason)


def cancel(store: Store, assessment: Assessment, principal: Principal) -> Assessment:
    return transition(store, assessment, LifecycleState.CANCELLED, reason=f"cancelled by {principal.actor}")


def request_certification(conn: Connection, store: Store, assessment: Assessment, principal: Principal) -> Assessment:
    updated = store.update(
        Assessment,
        assessment.id,
        {"certification_requested": True},
        reason=f"certification requested by {principal.actor}",
    )
    if updated.lifecycle_state is LifecycleState.COMPLETED_UNVERIFIED:
        updated = transition(store, updated, LifecycleState.AWAITING_REVIEW, reason="certification requested")
        from hai_core.reviews import create_task

        create_task(
            conn,
            assessment_id=updated.id,
            subject_type="certification",
            subject_id=updated.id,
            reason="certification requested",
            opened_by=principal.actor,
        )  # hai-codes: ok
    return updated


def fail_assessment(store: Store, assessment: Assessment, reason: str) -> Assessment:
    current = assessment.lifecycle_state
    if current in (LifecycleState.ACQUIRING, LifecycleState.EVALUATING):
        return transition(
            store, assessment, LifecycleState.FAILED, reason=reason, extra={"failure_reason": reason[:2000]}
        )
    if current is LifecycleState.QUEUED:
        store.update(Assessment, assessment.id, {"lifecycle_state": LifecycleState.ACQUIRING}, reason="failing")
        return transition(
            store,
            store.require(Assessment, assessment.id),
            LifecycleState.FAILED,
            reason=reason,
            extra={"failure_reason": reason[:2000]},
        )
    return store.update(Assessment, assessment.id, {"failure_reason": reason[:2000]}, reason=reason)
