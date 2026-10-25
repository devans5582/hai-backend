"""Job handlers: the assessment chain, webhook delivery and the monitoring tick.

acquire_evidence -> classify_links -> freeze_snapshot -> evaluate_criteria -> decide -> (reviews) -> finalize
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from hai_core.assessments import JOB_CHAIN, AssessmentRequest, create_assessment, fail_assessment, transition
from hai_core.auth import Principal
from hai_core.blobstore import BlobStore
from hai_core.db.engine import Database
from hai_core.db.store import Store
from hai_core.generated.enums import LifecycleState
from hai_core.generated.models import Assessment, Organization
from hai_core.manifest import role_codes
from hai_core.monitoring import due, mark_run
from hai_core.queue import Job, JobQueue
from hai_core.reviews import open_tasks_for, tasks_from_triggers
from hai_core.settings import Settings
from hai_core.webhooks import deliver, emit
from hai_engine.decision import DecisionService
from hai_engine.llm.base import Provider
from hai_engine.llm.registry import provider_from_settings, second_opinion_from_settings
from hai_engine.services import classify_links, evaluate_assessment
from hai_ontology.meta import Manifest
from hai_pipeline.acquire import AcquisitionService
from hai_pipeline.config import ConnectorsFile, load_connectors
from hai_pipeline.snapshot import build_snapshot

log = logging.getLogger("hai_worker")
SYSTEM = Principal("service", "worker", "hai-worker", frozenset())


class JobFailed(Exception):  # noqa: N818 - domain-named exception
    def __init__(self, message: str, *, retry: bool = True) -> None:
        super().__init__(message)
        self.retry = retry


@dataclass
class WorkerContext:
    settings: Settings
    manifest: Manifest
    db: Database
    blobs: BlobStore
    queue: JobQueue
    connectors: ConnectorsFile
    decisions: DecisionService
    provider: Provider
    second_opinion: Provider | None
    transport: httpx.AsyncBaseTransport | None = None
    webhook_transport: httpx.AsyncBaseTransport | None = None
    now: datetime | None = None

    @classmethod
    def build(
        cls,
        settings: Settings,
        manifest: Manifest,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        webhook_transport: httpx.AsyncBaseTransport | None = None,
        provider: Provider | None = None,
        now: datetime | None = None,
    ) -> WorkerContext:
        connectors_path = settings.connectors_config
        return cls(
            settings=settings,
            manifest=manifest,
            db=Database(
                settings.database_url, enforce_roles=settings.enforce_db_roles, allowed_roles=role_codes(manifest)
            ),
            blobs=BlobStore(settings.blob_store_url),
            queue=JobQueue(),
            connectors=load_connectors(connectors_path),
            decisions=DecisionService(manifest),
            provider=provider or provider_from_settings(settings, transport=transport),
            second_opinion=second_opinion_from_settings(settings, transport=transport),
            transport=transport,
            webhook_transport=webhook_transport,
            now=now,
        )

    def store(self, conn: Any, actor: str = SYSTEM.actor) -> Store:
        return Store(conn, actor=actor, manifest=self.manifest)


def _assessment_id(job: Job) -> UUID:
    try:
        return UUID(str(job.payload["assessment_id"]))
    except (KeyError, ValueError) as exc:
        raise JobFailed(f"job {job.id} has no assessment_id", retry=False) from exc


def _next(ctx: WorkerContext, conn: Any, kind: str, assessment_id: UUID) -> None:
    ctx.queue.enqueue(
        conn, kind, {"assessment_id": str(assessment_id)}, dedupe_key=f"{kind}:{assessment_id}", priority=5
    )


def _chain_after(kind: str) -> str | None:
    i = JOB_CHAIN.index(kind)
    return JOB_CHAIN[i + 1] if i + 1 < len(JOB_CHAIN) else None


async def acquire_evidence(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    aid = _assessment_id(job)
    with ctx.db.transaction(SYSTEM.actor, "hai_pipeline") as conn:
        store = ctx.store(conn)
        assessment = store.require(Assessment, aid)
        if assessment.lifecycle_state is LifecycleState.CANCELLED:
            return {"skipped": "cancelled"}
        if assessment.lifecycle_state is LifecycleState.QUEUED:
            transition(store, assessment, LifecycleState.ACQUIRING, reason="acquisition started")
    service = AcquisitionService(
        settings=ctx.settings,
        manifest=ctx.manifest,
        connectors=ctx.connectors,
        blobs=ctx.blobs,
        transport=ctx.transport,
        now=ctx.now,
    )
    with ctx.db.transaction(SYSTEM.actor, "hai_pipeline") as conn:
        store = ctx.store(conn)
        report = await service.acquire(conn, store, aid)
        _next(ctx, conn, "classify_links", aid)
    return {
        "runs": report.runs,
        "documents": report.documents,
        "spans": report.spans,
        "links": report.links,
        "incidents": report.incidents,
    }


async def classify_links_job(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    aid = _assessment_id(job)
    with ctx.db.transaction(SYSTEM.actor, "hai_engine") as conn:
        n = classify_links(conn, ctx.store(conn), ctx.manifest, aid)
        _next(ctx, conn, "freeze_snapshot", aid)
    return {"classified": n}


async def freeze_snapshot(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    aid = _assessment_id(job)
    with ctx.db.transaction(SYSTEM.actor, "hai_pipeline") as conn:
        store = ctx.store(conn)
        assessment = store.require(Assessment, aid)
        if assessment.lifecycle_state is LifecycleState.ACQUIRING:
            assessment = transition(store, assessment, LifecycleState.EVALUATING, reason="snapshot frozen")
        snapshot = build_snapshot(conn, store, assessment, ctx.manifest, frozen_at=ctx.now)
        _next(ctx, conn, "evaluate_criteria", aid)
    return {"snapshot_id": str(snapshot.id), "links": len(snapshot.link_ids), "sha256": snapshot.snapshot_sha256}


async def evaluate_criteria(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    aid = _assessment_id(job)
    with ctx.db.transaction(SYSTEM.actor, "hai_engine") as conn:
        summary = await evaluate_assessment(
            ctx.store(conn),
            ctx.manifest,
            aid,
            provider=ctx.provider,
            prompt_version=ctx.settings.prompt_version,
            second_opinion=ctx.second_opinion,
            blobs=ctx.blobs,
        )
        _next(ctx, conn, "decide", aid)
    return {
        "criteria": summary.criteria,
        "accepted": summary.accepted,
        "rejected": summary.rejected,
        "fell_back": summary.fell_back,
    }


async def decide(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    aid = _assessment_id(job)
    with ctx.db.transaction(SYSTEM.actor, "hai_engine") as conn:
        store = ctx.store(conn)
        decision = ctx.decisions.decide(conn, store, aid)
        assessment = store.require(Assessment, aid)
        by_code = {str(d.criterion_code.value): d.id for d in decision.decisions}
        tasks = tasks_from_triggers(
            conn,
            assessment_id=aid,
            triggers=decision.review_triggers,
            decisions_by_code=by_code,
            result_id=decision.result.id,
            opened_by=SYSTEM.actor,
        )
        if tasks:
            transition(store, assessment, LifecycleState.AWAITING_REVIEW, reason=f"{len(tasks)} review task(s)")
            emit(
                conn,
                "review.required",
                {
                    "assessment_id": str(aid),
                    "tasks": [t.as_dict() for t in tasks],
                    "outcome_status": decision.result.outcome_status.value,
                },
                queue=ctx.queue,
            )
        else:
            transition(store, assessment, LifecycleState.COMPLETED_UNVERIFIED, reason="no review triggers")
            emit(
                conn,
                "assessment.completed",
                _result_payload(aid, decision.result, LifecycleState.COMPLETED_UNVERIFIED.value),
                queue=ctx.queue,
            )
    return {
        "hai_score": float(decision.result.hai_score) if decision.result.hai_score is not None else None,
        "outcome_status": decision.result.outcome_status.value,
        "review_tasks": len(tasks),
    }


async def finalize(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    aid = _assessment_id(job)
    with ctx.db.transaction(SYSTEM.actor, "hai_engine") as conn:
        store = ctx.store(conn)
        assessment = store.require(Assessment, aid)
        if open_tasks_for(conn, aid) > 0:
            return {"skipped": "open review tasks remain"}
        previous = ctx.decisions.latest_result(store, aid)
        decision = ctx.decisions.finalize(conn, store, aid)
        signed = ctx.decisions.signed_certification_exists(conn, aid)
        if assessment.lifecycle_state is LifecycleState.AWAITING_REVIEW:
            target = LifecycleState.COMPLETED if signed else LifecycleState.COMPLETED_UNVERIFIED
            transition(store, assessment, target, reason="finalized after review")
        elif assessment.lifecycle_state is LifecycleState.COMPLETED_UNVERIFIED and signed:
            # certification requested and signed: move through awaiting_review to completed
            transition(
                store,
                transition(store, assessment, LifecycleState.AWAITING_REVIEW, reason="signed certification"),
                LifecycleState.COMPLETED,
                reason="finalized",
            )
        emit(
            conn,
            "assessment.completed",
            _result_payload(
                aid,
                decision.result,
                (LifecycleState.COMPLETED if signed else LifecycleState.COMPLETED_UNVERIFIED).value,
            ),
            queue=ctx.queue,
        )
        if previous is not None and (
            previous.hai_score != decision.result.hai_score or previous.outcome_status != decision.result.outcome_status
        ):
            emit(
                conn,
                "score.changed",
                {
                    "assessment_id": str(aid),
                    "previous": _result_payload(aid, previous, "")["result"],
                    "current": _result_payload(aid, decision.result, "")["result"],
                },
                queue=ctx.queue,
            )
    return {
        "hai_score": float(decision.result.hai_score) if decision.result.hai_score is not None else None,
        "outcome_status": decision.result.outcome_status.value,
    }


def _result_payload(aid: UUID, result: Any, lifecycle: str) -> dict[str, Any]:
    return {
        "assessment_id": str(aid),
        "lifecycle_state": lifecycle,
        "result": {
            "hai_score": float(result.hai_score) if result.hai_score is not None else None,
            "confidence_pct": float(result.confidence_pct) if result.confidence_pct is not None else None,
            "outcome_status": str(result.outcome_status.value),
            "result_id": str(result.id),
        },
    }


async def deliver_webhook(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    try:
        delivery_id = UUID(str(job.payload["delivery_id"]))
    except (KeyError, ValueError) as exc:
        raise JobFailed("job has no delivery_id", retry=False) from exc
    with ctx.db.transaction(SYSTEM.actor, "hai_api") as conn:
        ok, status, error = await deliver(conn, delivery_id, transport=ctx.webhook_transport)
    if not ok:
        raise JobFailed(f"webhook delivery failed: {error}")
    return {"status": status}


async def monitoring_tick(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    del job
    created: list[str] = []
    with ctx.db.transaction(SYSTEM.actor, "hai_api") as conn:
        store = ctx.store(conn)
        for sub in due(conn, ctx.now):
            org = store.require(Organization, sub.org_id)
            request = AssessmentRequest(
                organization_name=org.display_name,
                website=org.primary_domain,
                stage=str(org.stage_band.value if org.stage_band else "growth"),
                size=str(org.size_band.value if org.size_band else "mid"),
                industry=org.industry_code,
            )
            assessment, _ = create_assessment(
                conn,
                store,
                request=request,
                principal=SYSTEM,
                settings=ctx.settings,
                manifest=ctx.manifest,
                queue=ctx.queue,
            )
            mark_run(conn, sub, assessment.id, ctx.now)
            created.append(str(assessment.id))
    return {"assessments_created": created}


HANDLERS = {
    "acquire_evidence": acquire_evidence,
    "classify_links": classify_links_job,
    "freeze_snapshot": freeze_snapshot,
    "evaluate_criteria": evaluate_criteria,
    "decide": decide,
    "finalize": finalize,
    "deliver_webhook": deliver_webhook,
    "monitoring_tick": monitoring_tick,
}


def on_dead(ctx: WorkerContext, job: Job, error: str) -> None:
    """A dead pipeline job fails the assessment with a reason."""
    if job.kind not in JOB_CHAIN:
        return
    try:
        aid = _assessment_id(job)
    except JobFailed:
        return
    with ctx.db.transaction(SYSTEM.actor, "hai_pipeline") as conn:
        store = ctx.store(conn)
        assessment = store.get(Assessment, aid)
        if assessment is None or assessment.lifecycle_state in (
            LifecycleState.FAILED,
            LifecycleState.CANCELLED,
            LifecycleState.COMPLETED,
        ):
            return
        fail_assessment(store, assessment, f"{job.kind} failed after {job.attempts} attempt(s): {error}")
        emit(
            conn,
            "assessment.completed",
            {"assessment_id": str(aid), "lifecycle_state": "failed", "failure_reason": error[:500]},
            queue=ctx.queue,
        )
    log.error("assessment failed", extra={"assessment_id": str(aid), "job": job.kind, "error": error[:300]})


def utcnow() -> datetime:
    return datetime.now(UTC)
