"""Webhooks: subscriptions, HMAC-signed deliveries, retried through the job queue."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Connection, text

from hai_core.queue import JobQueue

EVENTS = ("assessment.completed", "review.required", "score.changed", "certification.signed")
SIGNATURE_HEADER = "X-HAI-Signature"
EVENT_HEADER = "X-HAI-Event"
DELIVERY_HEADER = "X-HAI-Delivery"


@dataclass(frozen=True)
class Subscription:
    id: UUID
    owner: str
    url: str
    events: list[str]
    active: bool
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "owner": self.owner,
            "url": self.url,
            "events": list(self.events),
            "active": self.active,
            "created_at": self.created_at.isoformat(),
        }


def _sub(row: Any) -> Subscription:
    m = row._mapping
    return Subscription(m["id"], m["owner"], m["url"], list(m["events"]), bool(m["active"]), m["created_at"])


def sign_body(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def subscribe(conn: Connection, *, owner: str, url: str, events: list[str], secret: str) -> Subscription:
    unknown = sorted(set(events) - set(EVENTS))
    if unknown:
        from hai_core.errors import ValidationFailedError

        raise ValidationFailedError(f"unknown events {unknown}", details={"events": list(EVENTS)})
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.webhook_subscriptions (owner, url, secret, events) VALUES (:o, :u, :s, :e) RETURNING *"
        ),
        {"o": owner, "u": url, "s": secret, "e": events},
    ).first()
    assert row is not None
    return _sub(row)


def list_subscriptions(conn: Connection, *, owner: str | None = None) -> list[Subscription]:
    if owner is None:
        rows = conn.execute(text("SELECT * FROM hai_ops.webhook_subscriptions ORDER BY created_at")).all()
    else:
        rows = conn.execute(
            text("SELECT * FROM hai_ops.webhook_subscriptions WHERE owner = :o ORDER BY created_at"), {"o": owner}
        ).all()
    return [_sub(r) for r in rows]


def deactivate(conn: Connection, subscription_id: UUID, *, owner: str | None = None) -> bool:
    result = conn.execute(
        text(
            "UPDATE hai_ops.webhook_subscriptions SET active = false WHERE id = :id AND (CAST(:o AS text) IS NULL OR owner = :o) AND active"
        ),
        {"id": subscription_id, "o": owner},
    )
    return bool(result.rowcount)


def emit(conn: Connection, event: str, payload: dict[str, Any], *, queue: JobQueue | None = None) -> int:
    """Create a delivery per active subscription for ``event`` and queue the delivery jobs."""
    rows = conn.execute(
        text("SELECT id FROM hai_ops.webhook_subscriptions WHERE active AND :e = ANY(events)"), {"e": event}
    ).all()
    q = queue or JobQueue()
    n = 0
    body = {"event": event, "emitted_at": datetime.now(UTC).isoformat(), "data": payload}
    for (sub_id,) in rows:
        delivery = conn.execute(
            text(
                "INSERT INTO hai_ops.webhook_deliveries (subscription_id, event, payload) VALUES (:s, :e, CAST(:p AS jsonb)) RETURNING id"
            ),
            {"s": sub_id, "e": event, "p": json.dumps(body, default=str)},
        ).scalar_one()
        q.enqueue(
            conn,
            "deliver_webhook",
            {"delivery_id": str(delivery)},
            dedupe_key=f"deliver_webhook:{delivery}",
            max_attempts=6,
        )
        n += 1
    return n


async def deliver(
    conn: Connection, delivery_id: UUID, *, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0
) -> tuple[bool, int | None, str | None]:
    row = conn.execute(
        text(
            "SELECT d.id, d.event, d.payload, s.url, s.secret, s.active FROM hai_ops.webhook_deliveries d "
            "JOIN hai_ops.webhook_subscriptions s ON s.id = d.subscription_id WHERE d.id = :id"
        ),
        {"id": delivery_id},
    ).first()
    if row is None:
        return False, None, "delivery not found"
    _, event, payload, url, secret, active = row
    if not active:
        conn.execute(
            text(
                "UPDATE hai_ops.webhook_deliveries SET last_error = 'subscription inactive', attempts = attempts + 1 WHERE id = :id"
            ),
            {"id": delivery_id},
        )
        return True, None, "subscription inactive"
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        EVENT_HEADER: str(event),
        DELIVERY_HEADER: str(delivery_id),
        SIGNATURE_HEADER: sign_body(str(secret), body),
    }
    status: int | None = None
    error: str | None = None
    try:
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(timeout)) as client:
            resp = await client.post(str(url), content=body, headers=headers)
        status = resp.status_code
        ok = 200 <= resp.status_code < 300
        if not ok:
            error = f"HTTP {resp.status_code}"
    except httpx.HTTPError as exc:
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    conn.execute(
        text(
            "UPDATE hai_ops.webhook_deliveries SET attempts = attempts + 1, last_status = :st, last_error = :err, "
            "delivered_at = CASE WHEN :ok THEN now() ELSE delivered_at END WHERE id = :id"
        ),
        {"st": status, "err": error, "ok": ok, "id": delivery_id},
    )
    return ok, status, error


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_body(secret, body), signature)
