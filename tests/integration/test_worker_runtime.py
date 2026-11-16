"""Long-running jobs keep their leases and stale attempts cannot finish newer claims."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from hai_core.assessments import AssessmentRequest, create_assessment
from hai_core.db.engine import Database
from hai_core.generated.enums import LifecycleState
from hai_core.generated.models import Assessment
from hai_core.queue import Job, JobQueue
from hai_core.settings import Settings
from hai_ontology.meta import Manifest
from hai_worker.jobs import HANDLERS, SYSTEM, WorkerContext
from hai_worker.main import Worker

pytestmark = pytest.mark.integration


async def test_expired_final_attempt_fails_assessment(
    clean_db: Database, settings: Settings, manifest: Manifest
) -> None:
    worker = Worker(settings, manifest, kinds=["unused"])
    try:
        with clean_db.transaction("pytest", "hai_api") as conn:
            assessment, _ = create_assessment(
                conn,
                worker.ctx.store(conn),
                request=AssessmentRequest("Example", "example.test", "growth", "mid"),
                principal=SYSTEM,
                settings=settings,
                manifest=manifest,
            )
            job = worker.ctx.queue.claim(conn, "crashed-worker")
            assert job is not None
            conn.execute(
                text(
                    "UPDATE hai_ops.jobs SET attempts = max_attempts, "
                    "lease_until = now() - interval '1 second' WHERE id = :id"
                ),
                {"id": job.id},
            )
        assert await worker.run_once() is None
        with clean_db.transaction("pytest", "hai_api") as conn:
            updated = worker.ctx.store(conn).require(Assessment, assessment.id)
            assert updated.lifecycle_state is LifecycleState.FAILED
            assert updated.failure_reason is not None and "lease expired" in updated.failure_reason
    finally:
        worker.ctx.db.dispose()


def test_stale_attempt_cannot_modify_reclaimed_job(clean_db: Database) -> None:
    queue = JobQueue()
    with clean_db.transaction("pytest", "hai_engine") as conn:
        job_id = queue.enqueue(conn, "test", {}, max_attempts=2)
        assert job_id is not None
        first = queue.claim(conn, "same-worker-id")
        assert first is not None
        conn.execute(
            text("UPDATE hai_ops.jobs SET lease_until = now() - interval '1 second' WHERE id = :id"), {"id": job_id}
        )
        assert queue.reap_expired(conn) == 1
        second = queue.claim(conn, "same-worker-id")
        assert second is not None and second.attempts == 2
        assert not queue.extend_lease(conn, job_id, 180, claim=first)
        assert not queue.complete(conn, job_id, {"stale": True}, claim=first)
        assert queue.fail(conn, job_id, "stale failure", claim=first) == "missing"
        current = queue.get(conn, job_id)
        assert current is not None and current.state == "running" and current.last_error == "lease expired"
        conn.execute(
            text("UPDATE hai_ops.jobs SET lease_until = now() - interval '1 second' WHERE id = :id"), {"id": job_id}
        )
        expired = queue.reap_expired_jobs(conn)
        assert len(expired) == 1 and expired[0].state == "dead"
        assert not queue.complete(conn, job_id, claim=second)
        assert conn.execute(text("SELECT finished_at FROM hai_ops.jobs WHERE id = :id"), {"id": job_id}).scalar_one()


async def test_long_handler_renews_lease(
    clean_db: Database, settings: Settings, manifest: Manifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = asyncio.Event(), asyncio.Event()

    async def wait_for_release(ctx: WorkerContext, job: Job) -> dict[str, Any]:
        started.set()
        await release.wait()
        return {"ok": True}

    monkeypatch.setitem(HANDLERS, "test_wait", wait_for_release)
    worker = Worker(settings.model_copy(update={"worker_lease_seconds": 1}), manifest, kinds=["test_wait"])
    other = Worker(settings, manifest, kinds=["test_wait"])
    with clean_db.transaction("pytest", "hai_engine") as conn:
        job_id = worker.ctx.queue.enqueue(conn, "test_wait", {})
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        await asyncio.sleep(1.25)
        assert await other.run_once() is None
        release.set()
        await asyncio.wait_for(task, timeout=2)
        with clean_db.transaction("pytest", "hai_engine") as conn:
            assert job_id is not None
            job = worker.ctx.queue.get(conn, job_id)
            assert job is not None and job.state == "done" and job.attempts == 1
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        worker.ctx.db.dispose()
        other.ctx.db.dispose()


async def test_lost_claim_cancels_handler_and_rolls_back(
    clean_db: Database, settings: Settings, manifest: Manifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def waiting_handler(ctx: WorkerContext, job: Job) -> dict[str, Any]:
        with ctx.db.transaction("pytest", "hai_engine") as conn:
            ctx.queue.enqueue(conn, "must_roll_back", {})
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return {}

    monkeypatch.setitem(HANDLERS, "test_wait", waiting_handler)
    worker = Worker(settings.model_copy(update={"worker_lease_seconds": 1}), manifest, kinds=["test_wait"])
    with clean_db.transaction("pytest", "hai_engine") as conn:
        worker.ctx.queue.enqueue(conn, "test_wait", {})
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        with clean_db.transaction("pytest", "hai_engine") as conn:
            conn.execute(
                text("UPDATE hai_ops.jobs SET lease_until = now() - interval '1 second' WHERE kind = 'test_wait'")
            )
            worker.ctx.queue.reap_expired(conn)
            newer = worker.ctx.queue.claim(conn, settings.worker_id, kinds=["test_wait"])
            assert newer is not None and newer.attempts == 2
        await asyncio.wait_for(task, timeout=2)
        assert cancelled.is_set()
        with clean_db.transaction("pytest", "hai_engine") as conn:
            assert worker.ctx.queue.find(conn, kind="must_roll_back") == []
            current = worker.ctx.queue.get(conn, newer.id)
            assert current is not None and current.state == "running" and current.attempts == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        worker.ctx.db.dispose()
