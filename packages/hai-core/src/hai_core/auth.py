"""API keys and reviewer JWTs.

API keys look like ``hai_<key id>.<secret>``. Only an HMAC-SHA256 of the secret
under a server pepper is stored; the plaintext is shown once at creation.
Reviewers and admins use HS256 JWTs minted by an admin. Every principal
carries scopes; routes declare which scope they need.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import jwt
from sqlalchemy import Connection, text

from hai_core.errors import UnauthorizedError

PrincipalKind = Literal["api_key", "reviewer", "admin", "service", "anonymous"]


class Scope:
    ASSESSMENTS_READ = "assessments:read"
    ASSESSMENTS_WRITE = "assessments:write"
    ORGANIZATIONS_READ = "organizations:read"
    REVIEWS_WRITE = "reviews:write"
    CERTIFICATION_SIGN = "certification:sign"
    UPLOADS_WRITE = "uploads:write"
    WEBHOOKS_WRITE = "webhooks:write"
    AUDIT_READ = "audit:read"
    ONTOLOGY_READ = "ontology:read"
    ADMIN = "admin"

    ALL: frozenset[str] = frozenset(
        {
            "assessments:read",
            "assessments:write",
            "organizations:read",
            "reviews:write",
            "certification:sign",
            "uploads:write",
            "webhooks:write",
            "audit:read",
            "ontology:read",
            "admin",
        }
    )
    PARTNER_DEFAULT: frozenset[str] = frozenset(
        {
            "assessments:read",
            "assessments:write",
            "organizations:read",
            "uploads:write",
            "webhooks:write",
            "ontology:read",
        }
    )
    REVIEWER_DEFAULT: frozenset[str] = frozenset(
        {"assessments:read", "organizations:read", "reviews:write", "certification:sign", "ontology:read", "audit:read"}
    )


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    id: str
    name: str
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def actor(self) -> str:
        return f"{self.kind}:{self.id}"

    @property
    def is_reviewer(self) -> bool:
        return self.kind in ("reviewer", "admin")

    def has(self, scope: str) -> bool:
        return Scope.ADMIN in self.scopes or scope in self.scopes


ANONYMOUS = Principal("anonymous", "anonymous", "anonymous", frozenset({Scope.ONTOLOGY_READ}))


# ------------------------------------------------------------------- API keys


def hmac_secret(pepper: str, secret: str) -> str:
    return hmac.new(pepper.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def new_plaintext_key() -> tuple[str, str, str]:
    """Returns (key_id, secret, plaintext)."""
    key_id = uuid4().hex[:12]
    secret = secrets.token_urlsafe(32)
    return key_id, secret, f"hai_{key_id}.{secret}"


def parse_plaintext_key(value: str) -> tuple[str, str] | None:
    if not value.startswith("hai_") or "." not in value:
        return None
    key_id, _, secret = value[4:].partition(".")
    if not key_id or not secret:
        return None
    return key_id, secret


@dataclass(frozen=True)
class ApiKeyRecord:
    id: UUID
    key_id: str
    name: str
    scopes: list[str]
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


def create_api_key(
    conn: Connection, pepper: str, *, name: str, scopes: frozenset[str], created_by: str
) -> tuple[str, ApiKeyRecord]:
    key_id, secret, plaintext = new_plaintext_key()
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.api_keys (key_id, name, key_hmac, scopes, created_by) "
            "VALUES (:key_id, :name, :hmac, :scopes, :created_by) RETURNING id, key_id, name, scopes, created_at, revoked_at, last_used_at"  # noqa: E501
        ),
        {
            "key_id": key_id,
            "name": name,
            "hmac": hmac_secret(pepper, secret),
            "scopes": sorted(scopes),
            "created_by": created_by,
        },
    ).first()
    assert row is not None
    return plaintext, _record(row)


def _record(row: Any) -> ApiKeyRecord:
    return ApiKeyRecord(row[0], row[1], row[2], list(row[3]), row[4], row[5], row[6])


def verify_api_key(conn: Connection, pepper: str, plaintext: str) -> Principal | None:
    parsed = parse_plaintext_key(plaintext.strip())
    if parsed is None:
        return None
    key_id, secret = parsed
    row = conn.execute(
        text(
            "SELECT id, key_id, name, scopes, created_at, revoked_at, last_used_at, key_hmac FROM hai_ops.api_keys WHERE key_id = :k"  # noqa: E501
        ),
        {"k": key_id},
    ).first()
    if row is None:
        # Compare anyway so timing does not reveal whether the id exists.
        hmac.compare_digest(hmac_secret(pepper, secret), hmac_secret(pepper, "x"))
        return None
    if not hmac.compare_digest(hmac_secret(pepper, secret), str(row[7])):
        return None
    if row[5] is not None:
        return None
    conn.execute(text("UPDATE hai_ops.api_keys SET last_used_at = now() WHERE id = :id"), {"id": row[0]})
    return Principal("api_key", str(row[1]), str(row[2]), frozenset(str(s) for s in row[3]))


def revoke_api_key(conn: Connection, key_id: str) -> bool:
    result = conn.execute(
        text("UPDATE hai_ops.api_keys SET revoked_at = now() WHERE key_id = :k AND revoked_at IS NULL"), {"k": key_id}
    )
    return bool(result.rowcount)


def list_api_keys(conn: Connection) -> list[ApiKeyRecord]:
    rows = conn.execute(
        text(
            "SELECT id, key_id, name, scopes, created_at, revoked_at, last_used_at FROM hai_ops.api_keys ORDER BY created_at"  # noqa: E501
        )
    ).all()
    return [_record(r) for r in rows]


# ----------------------------------------------------------------------- JWTs


def mint_jwt(
    secret: str,
    *,
    subject: str,
    name: str,
    role: Literal["reviewer", "admin"],
    scopes: frozenset[str],
    issuer: str = "hai",
    ttl_minutes: int = 480,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "iss": issuer,
        "sub": subject,
        "name": name,
        "role": role,
        "scopes": sorted(scopes),
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=ttl_minutes)).timestamp()),
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_jwt(secret: str, token: str, *, issuer: str = "hai") -> Principal:
    try:
        payload = jwt.decode(
            token, secret, algorithms=["HS256"], issuer=issuer, options={"require": ["exp", "sub", "iss"]}
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError(f"invalid token: {exc}") from exc
    role = payload.get("role")
    if role not in ("reviewer", "admin"):
        raise UnauthorizedError("token role must be reviewer or admin")
    scopes = frozenset(str(s) for s in payload.get("scopes", []))
    if role == "admin":
        scopes = scopes | {Scope.ADMIN}
    return Principal(role, str(payload["sub"]), str(payload.get("name") or payload["sub"]), scopes)
