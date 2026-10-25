"""The background worker: claims jobs from the Postgres queue and runs the handlers."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from hai_core.logging import configure_logging
from hai_core.manifest import get_manifest, verify_generated_code
from hai_core.queue import Job
from hai_core.settings import Settings, get_settings
from hai_engine.llm.base import Provider
from hai_engine.rules import resolve
from hai_ontology.meta import Manifest
from hai_worker.jobs import HANDLERS, SYSTEM, JobFailed, WorkerContext, on_dead

log = logging.getLogger("hai_worker")


class Worker:
    def __init__(
        self,
        settings: Settings,
        manifest: Manifest,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        webhook_transport: httpx.AsyncBaseTransport | None = None,
        provider: Provider | None = None,
        now: datetime | None = None,
        kinds: list[str] | None = None,
    ) -> None:
        verify_generated_code(manifest)
        resolve(manifest)
        self.ctx = WorkerContext.build(
            settings, manifest, transport=transport, webhook_transport=webhook_transport, provider=provider, now=now
        )
        self.kinds = kinds
        self.worker_id = settings.worker_id
        self._stop = False
        self._last_tick = 0.0

    async def run_once(self) -> Job | None:
        """Claim and run one job. Returns the job, or None when the queue is idle."""
        with self.ctx.db.transaction(SYSTEM.actor, "hai_engine") as conn:
            self.ctx.queue.reap_expired(conn)
            job = self.ctx.queue.claim(
                conn, self.worker_id, kinds=self.kinds, lease_seconds=self.ctx.settings.worker_lease_seconds
            )
        if job is None:
            return None
        handler = HANDLERS.get(job.kind)
        started = time.monotonic()
        try:
            if handler is None:
                raise JobFailed(f"unknown job kind {job.kind}", retry=False)
            result = await handler(self.ctx, job)
        except JobFailed as exc:
            self._fail(job, str(exc), retry=exc.retry)
            return job
        except Exception as exc:
            log.exception("job crashed", extra={"job": job.kind, "job_id": str(job.id)})
            self._fail(job, f"{type(exc).__name__}: {exc}", retry=True)
            return job
        with self.ctx.db.transaction(SYSTEM.actor, "hai_engine") as conn:
            self.ctx.queue.complete(conn, job.id, result)
        log.info(
            "job done",
            extra={
                "job": job.kind,
                "job_id": str(job.id),
                "ms": int((time.monotonic() - started) * 1000),
                **_loggable(result),
            },
        )
        return job

    def _fail(self, job: Job, error: str, *, retry: bool) -> None:
        with self.ctx.db.transaction(SYSTEM.actor, "hai_engine") as conn:
            state = self.ctx.queue.fail(conn, job.id, error, retry=retry)
        log.warning("job failed", extra={"job": job.kind, "job_id": str(job.id), "state": state, "error": error[:300]})
        if state in ("dead", "failed"):
            on_dead(self.ctx, job, error)

    async def drain(self, max_jobs: int = 200) -> int:
        """Run jobs until the queue is idle (tests and one-shot runs)."""
        n = 0
        while n < max_jobs:
            job = await self.run_once()
            if job is None:
                break
            n += 1
        return n

    def schedule_monitoring_tick(self) -> None:
        now = time.monotonic()
        interval = self.ctx.settings.monitoring_tick_minutes * 60
        if now - self._last_tick < interval:
            return
        self._last_tick = now
        bucket = datetime.now(UTC).strftime("%Y%m%d%H%M")
        with self.ctx.db.transaction(SYSTEM.actor, "hai_api") as conn:
            self.ctx.queue.enqueue(conn, "monitoring_tick", {}, dedupe_key=f"monitoring_tick:{bucket}", priority=-5)

    async def run_forever(self) -> None:
        log.info("hai-worker started", extra={"worker_id": self.worker_id, "provider": self.ctx.provider.model_id})
        while not self._stop:
            self.schedule_monitoring_tick()
            job = await self.run_once()
            if job is None:
                await asyncio.sleep(self.ctx.settings.worker_poll_seconds)
        self.ctx.db.dispose()

    def stop(self) -> None:
        self._stop = True


def _loggable(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if isinstance(v, str | int | float | bool)}


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, "hai-worker", settings.log_json)
    worker = Worker(settings, get_manifest(settings.ontology_dir))
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)
    loop.run_until_complete(worker.run_forever())
