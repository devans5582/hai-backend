"""Hash-chained, append-only audit log (AT-15).

Each event's hash is SHA-256 over the previous hash and the canonical JSON of
the event. Appends are serialised with an advisory lock so the chain never
forks. ``verify`` recomputes every hash in sequence order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.generated.enums import ONTOLOGY_VERSION

GENESIS_HASH = "0" * 64
_LOCK_KEY = 7_412_903_117  # arbitrary constant for pg_advisory_xact_lock


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def event_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical(payload)).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value", None), str):
        return value.value
    return str(value)


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    actor: str
    action: str
    subject_type: str
    subject_id: UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    at: datetime
    prev_hash: str
    hash: str

    def payload(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "actor": self.actor,
            "action": self.action,
            "subject_type": self.subject_type,
            "subject_id": str(self.subject_id) if self.subject_id else None,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "at": self.at.isoformat(),
        }


def append_event(
    conn: Connection,
    *,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    at: datetime | None = None,
) -> AuditRecord:
    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    last = conn.execute(text("SELECT seq, hash FROM hai.audit_events ORDER BY seq DESC LIMIT 1")).first()
    seq = int(last[0]) + 1 if last else 1
    prev_hash = str(last[1]) if last else GENESIS_HASH
    when = at or datetime.now(UTC)
    record = AuditRecord(
        seq=seq,
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        before=_jsonable(before) if before is not None else None,
        after=_jsonable(after) if after is not None else None,
        reason=reason,
        at=when,
        prev_hash=prev_hash,
        hash="",
    )
    digest = event_hash(prev_hash, record.payload())
    record = AuditRecord(**{**record.__dict__, "hash": digest})
    conn.execute(
        text(
            "INSERT INTO hai.audit_events (ontology_version, seq, actor, action, subject_type, subject_id, "
            "before, after, reason, at, prev_hash, hash) VALUES (:ov, :seq, :actor, :action, :st, :sid, "
            "CAST(:before AS jsonb), CAST(:after AS jsonb), :reason, :at, :prev, :hash)"
        ),
        {
            "ov": ONTOLOGY_VERSION,
            "seq": seq,
            "actor": actor,
            "action": action,
            "st": subject_type,
            "sid": subject_id,
            "before": json.dumps(record.before) if record.before is not None else None,
            "after": json.dumps(record.after) if record.after is not None else None,
            "reason": reason,
            "at": when,
            "prev": prev_hash,
            "hash": digest,
        },
    )
    return record


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    events: int
    first_bad_seq: int | None
    message: str


def verify_chain(conn: Connection) -> VerifyResult:
    rows = conn.execute(
        text(
            "SELECT seq, actor, action, subject_type, subject_id, before, after, reason, at, prev_hash, hash "
            "FROM hai.audit_events ORDER BY seq"
        )
    ).all()
    prev = GENESIS_HASH
    expected_seq = 1
    for r in rows:
        seq = int(r[0])
        if seq != expected_seq:
            return VerifyResult(False, len(rows), seq, f"sequence gap: expected {expected_seq}, found {seq}")
        if str(r[9]) != prev:
            return VerifyResult(False, len(rows), seq, f"prev_hash mismatch at seq {seq}")
        at: datetime = r[8]
        payload = {
            "seq": seq,
            "actor": r[1],
            "action": r[2],
            "subject_type": r[3],
            "subject_id": str(r[4]) if r[4] else None,
            "before": r[5],
            "after": r[6],
            "reason": r[7],
            "at": at.astimezone(UTC).isoformat(),
        }
        if event_hash(prev, payload) != str(r[10]):
            return VerifyResult(False, len(rows), seq, f"hash mismatch at seq {seq}: event was altered")
        prev = str(r[10])
        expected_seq += 1
    return VerifyResult(True, len(rows), None, "audit chain verified")


def list_events(conn: Connection, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, seq, actor, action, subject_type, subject_id, before, after, reason, at, prev_hash, hash "
            "FROM hai.audit_events ORDER BY seq DESC LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    ).mappings()
    return [dict(r) for r in rows]
