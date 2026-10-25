"""PostgreSQL job queue.

``FOR UPDATE SKIP LOCKED`` claims, leases, priorities, dedupe keys, exponential
backoff and a dead state after ``max_attempts``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

BACKOFF_BASE_SECONDS = 5.0
BACKOFF_CAP_SECONDS = 600.0

JOB_STATES = ("queued", "running", "done", "failed", "dead")


def backoff_seconds(attempts: int) -> float:
    """Exponential backoff after ``attempts`` failed attempts (deterministic, no jitter)."""
    return float(min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1))))


@dataclass(frozen=True)
class Job:
    id: UUID
    kind: str
    payload: dict[str, Any]
    priority: int
    attempts: int
    max_attempts: int
    dedupe_key: str | None
    run_after: datetime
    lease_until: datetime | None
    state: str
    last_error: str | None
    locked_by: str | None
    created_at: datetime


def _job(row: Any) -> Job:
    m = row._mapping
    payload = m["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return Job(
        id=m["id"],
        kind=m["kind"],
        payload=dict(payload or {}),
        priority=int(m["priority"]),
        attempts=int(m["attempts"]),
        max_attempts=int(m["max_attempts"]),
        dedupe_key=m["dedupe_key"],
        run_after=m["run_after"],
        lease_until=m["lease_until"],
        state=m["state"],
        last_error=m["last_error"],
        locked_by=m["locked_by"],
        created_at=m["created_at"],
    )


class JobQueue:
    def enqueue(
        self,
        conn: Connection,
        kind: str,
        payload: dict[str, Any],
        *,
        priority: int = 0,
        dedupe_key: str | None = None,
        run_after: datetime | None = None,
        max_attempts: int = 5,
    ) -> UUID | None:
        """Queue a job. Returns ``None`` when an active job with the same dedupe key exists."""
        row = conn.execute(
            text(
                "INSERT INTO hai_ops.jobs (kind, payload, priority, dedupe_key, run_after, max_attempts) "
                "VALUES (:kind, CAST(:payload AS jsonb), :priority, :dedupe_key, coalesce(:run_after, now()), :max_attempts) "  # noqa: E501
                "ON CONFLICT (dedupe_key) WHERE state IN ('queued', 'running') DO NOTHING RETURNING id"
            ),
            {
                "kind": kind,
                "payload": json.dumps(payload, default=str),
                "priority": priority,
                "dedupe_key": dedupe_key,
                "run_after": run_after,
                "max_attempts": max_attempts,
            },
        ).first()
        return row[0] if row else None

    def claim(
        self, conn: Connection, worker_id: str, *, kinds: list[str] | None = None, lease_seconds: int = 180
    ) -> Job | None:
        kind_filter = "AND kind = ANY(:kinds)" if kinds else ""
        row = conn.execute(
            text(
                "UPDATE hai_ops.jobs SET state = 'running', locked_by = :worker, attempts = attempts + 1, "
                "lease_until = now() + make_interval(secs => :lease), updated_at = now() "
                "WHERE id = (SELECT id FROM hai_ops.jobs WHERE state = 'queued' AND run_after <= now() "
                f"{kind_filter} ORDER BY priority DESC, run_after ASC, created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1) "
                "RETURNING *"
            ),
            {"worker": worker_id, "lease": lease_seconds, "kinds": kinds},
        ).first()
        return _job(row) if row else None

    def complete(self, conn: Connection, job_id: UUID, result: dict[str, Any] | None = None) -> None:
        conn.execute(
            text(
                "UPDATE hai_ops.jobs SET state = 'done', finished_at = now(), updated_at = now(), lease_until = NULL, "
                "result = CAST(:result AS jsonb) WHERE id = :id"
            ),
            {"id": job_id, "result": json.dumps(result or {}, default=str)},
        )

    def fail(self, conn: Connection, job_id: UUID, error: str, *, retry: bool = True) -> str:
        """Record a failure. Returns the new state: queued (retry), failed (no retry) or dead."""
        row = conn.execute(
            text("SELECT attempts, max_attempts FROM hai_ops.jobs WHERE id = :id FOR UPDATE"), {"id": job_id}
        ).first()
        if row is None:
            return "missing"
        attempts, max_attempts = int(row[0]), int(row[1])
        if not retry:
            state = "failed"
            run_after = None
        elif attempts >= max_attempts:
            state = "dead"
            run_after = None
        else:
            state = "queued"
            run_after = datetime.now(UTC) + timedelta(seconds=backoff_seconds(attempts))
        conn.execute(
            text(
                "UPDATE hai_ops.jobs SET state = :state, last_error = :error, lease_until = NULL, locked_by = NULL, "
                "run_after = coalesce(:run_after, run_after), updated_at = now(), "
                "finished_at = CASE WHEN :state IN ('failed', 'dead') THEN now() ELSE finished_at END WHERE id = :id"
            ),
            {"id": job_id, "state": state, "error": error[:4000], "run_after": run_after},
        )
        return state

    def extend_lease(self, conn: Connection, job_id: UUID, lease_seconds: int) -> None:
        conn.execute(
            text(
                "UPDATE hai_ops.jobs SET lease_until = now() + make_interval(secs => :lease) WHERE id = :id AND state = 'running'"  # noqa: E501
            ),
            {"id": job_id, "lease": lease_seconds},
        )

    def reap_expired(self, conn: Connection) -> int:
        """Requeue running jobs whose lease expired (the attempt already counted)."""
        result = conn.execute(
            text(
                "UPDATE hai_ops.jobs SET state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END, "
                "locked_by = NULL, lease_until = NULL, last_error = coalesce(last_error, 'lease expired'), updated_at = now() "  # noqa: E501
                "WHERE state = 'running' AND lease_until < now()"
            )
        )
        return int(result.rowcount or 0)

    def get(self, conn: Connection, job_id: UUID) -> Job | None:
        row = conn.execute(text("SELECT * FROM hai_ops.jobs WHERE id = :id"), {"id": job_id}).first()
        return _job(row) if row else None

    def find(
        self, conn: Connection, *, state: str | None = None, kind: str | None = None, limit: int = 100
    ) -> list[Job]:
        rows = conn.execute(
            text(
                "SELECT * FROM hai_ops.jobs WHERE (:state IS NULL OR state = :state) AND (:kind IS NULL OR kind = :kind) "  # noqa: E501
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"state": state, "kind": kind, "limit": limit},
        ).all()
        return [_job(r) for r in rows]

    def counts(self, conn: Connection) -> dict[str, int]:
        rows = conn.execute(text("SELECT state, count(*) FROM hai_ops.jobs GROUP BY state")).all()
        return {str(r[0]): int(r[1]) for r in rows}
