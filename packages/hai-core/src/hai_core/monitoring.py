"""Continuous monitoring subscriptions and evidence portal uploads (beyond-v1 extension points built cheaply)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.blobstore import BlobStore
from hai_core.generated.enums import ClaimScopeType


@dataclass(frozen=True)
class MonitoringSubscription:
    id: UUID
    org_id: UUID
    interval_days: int
    active: bool
    requested_by: str
    next_run_at: datetime
    last_assessment_id: UUID | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "interval_days": self.interval_days,
            "active": self.active,
            "requested_by": self.requested_by,
            "next_run_at": self.next_run_at.isoformat(),
            "last_assessment_id": str(self.last_assessment_id) if self.last_assessment_id else None,
        }


def _sub(row: Any) -> MonitoringSubscription:
    m = row._mapping
    return MonitoringSubscription(
        m["id"],
        m["org_id"],
        int(m["interval_days"]),
        bool(m["active"]),
        m["requested_by"],
        m["next_run_at"],
        m["last_assessment_id"],
    )


def subscribe(
    conn: Connection, *, org_id: UUID, interval_days: int, requested_by: str, first_run_at: datetime | None = None
) -> MonitoringSubscription:
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.monitoring_subscriptions (org_id, interval_days, requested_by, next_run_at) "
            "VALUES (:o, :i, :r, coalesce(:n, now() + make_interval(days => :i))) RETURNING *"
        ),
        {"o": org_id, "i": interval_days, "r": requested_by, "n": first_run_at},
    ).first()
    assert row is not None
    return _sub(row)


def list_subscriptions(conn: Connection, *, org_id: UUID | None = None) -> list[MonitoringSubscription]:
    rows = conn.execute(
        text(
            "SELECT * FROM hai_ops.monitoring_subscriptions WHERE (CAST(:o AS uuid) IS NULL OR org_id = :o) ORDER BY created_at"
        ),
        {"o": org_id},
    ).all()
    return [_sub(r) for r in rows]


def due(conn: Connection, now: datetime | None = None) -> list[MonitoringSubscription]:
    rows = conn.execute(
        text(
            "SELECT * FROM hai_ops.monitoring_subscriptions WHERE active AND next_run_at <= :now ORDER BY next_run_at FOR UPDATE SKIP LOCKED"
        ),
        {"now": now or datetime.now(UTC)},
    ).all()
    return [_sub(r) for r in rows]


def mark_run(
    conn: Connection, subscription: MonitoringSubscription, assessment_id: UUID, now: datetime | None = None
) -> None:
    when = now or datetime.now(UTC)
    conn.execute(
        text("UPDATE hai_ops.monitoring_subscriptions SET last_assessment_id = :a, next_run_at = :n WHERE id = :id"),
        {"a": assessment_id, "n": when + timedelta(days=subscription.interval_days), "id": subscription.id},
    )


# ------------------------------------------------------------------------ uploads


@dataclass(frozen=True)
class Upload:
    id: UUID
    org_id: UUID
    filename: str
    content_type: str
    sha256: str
    blob_uri: str
    assertion_text: str
    claim_scope: str
    submitted_by: str
    status: str
    source_document_id: UUID | None
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "filename": self.filename,
            "content_type": self.content_type,
            "sha256": self.sha256,
            "assertion_text": self.assertion_text,
            "claim_scope": self.claim_scope,
            "submitted_by": self.submitted_by,
            "status": self.status,
            "source_document_id": str(self.source_document_id) if self.source_document_id else None,
            "created_at": self.created_at.isoformat(),
        }


def _upload(row: Any) -> Upload:
    m = row._mapping
    return Upload(
        m["id"],
        m["org_id"],
        m["filename"],
        m["content_type"],
        m["sha256"],
        m["blob_uri"],
        m["assertion_text"],
        str(m["claim_scope"]),
        m["submitted_by"],
        m["status"],
        m["source_document_id"],
        m["created_at"],
    )


def register_upload(
    conn: Connection,
    blobs: BlobStore,
    *,
    org_id: UUID,
    filename: str,
    content_type: str,
    content: bytes,
    assertion_text: str,
    submitted_by: str,
    claim_scope: ClaimScopeType = ClaimScopeType.ORGANIZATION,
) -> Upload:
    ref = blobs.put(content)
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.uploads (org_id, filename, content_type, sha256, blob_uri, assertion_text, claim_scope, submitted_by) "
            "VALUES (:o, :f, :c, :h, :u, :a, :s, :b) RETURNING *"
        ),
        {
            "o": org_id,
            "f": filename,
            "c": content_type,
            "h": ref.sha256,
            "u": ref.uri,
            "a": assertion_text,
            "s": claim_scope.value,
            "b": submitted_by,
        },
    ).first()
    assert row is not None
    return _upload(row)


def list_uploads(conn: Connection, *, org_id: UUID | None = None, status: str | None = None) -> list[Upload]:
    rows = conn.execute(
        text(
            "SELECT * FROM hai_ops.uploads WHERE (CAST(:o AS uuid) IS NULL OR org_id = :o) AND (CAST(:s AS text) IS NULL OR status = :s) ORDER BY created_at"
        ),
        {"o": org_id, "s": status},
    ).all()
    return [_upload(r) for r in rows]
