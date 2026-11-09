"""API keys, reviewer JWTs and the principal every route sees.

API keys look like ``hai_<key id>.<secret>``. Only an HMAC-SHA256 of the secret
under a server pepper is stored; the plaintext is shown once at creation.
The seeded development key ``demo`` requires explicit opt-in when verifying.
Reviewers and admins use HS256 JWTs: either minted by an admin (stateless) or
issued at login for a console user (``sid`` claim, checked against the session
row by ``hai_core.accounts``). Every principal carries scopes; routes declare
which scope they need. A principal may also be restricted to organizations
or industries; ``hai_core.visibility`` applies that restriction.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import jwt
from sqlalchemy import Connection, text

from hai_core.errors import UnauthorizedError

PrincipalKind = Literal["api_key", "reviewer", "admin", "user", "service", "anonymous"]
AccountKind = Literal["platform", "organization"]
DEMO_API_KEY = "demo"  # Intentional development credential; rejected in production.


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
    # Console users and account-bound API keys carry their account; both may be restricted.
    account_id: str | None = None
    account_kind: AccountKind | None = None
    account_name: str | None = None
    account_role: str | None = None
    email: str | None = None
    session_id: str | None = None
    org_ids: frozenset[str] = field(default_factory=frozenset)  # non-empty: only these organizations
    industries: frozenset[str] = field(default_factory=frozenset)  # non-empty: only these industries (lowercase)

    @property
    def actor(self) -> str:
        return f"{self.kind}:{self.id}"

    @property
    def is_reviewer(self) -> bool:
        return self.kind in ("reviewer", "admin")

    @property
    def is_restricted(self) -> bool:
        return bool(self.org_ids or self.industries)

    @property
    def is_platform_admin(self) -> bool:
        return self.has(Scope.ADMIN)

    @property
    def manages_team(self) -> bool:
        return self.is_platform_admin or self.account_role == "org_admin"

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
    created_by: str = ""
    account_id: UUID | None = None


_KEY_COLUMNS = "id, key_id, name, scopes, created_at, revoked_at, last_used_at, created_by, account_id"


def create_api_key(
    conn: Connection,
    pepper: str,
    *,
    name: str,
    scopes: frozenset[str],
    created_by: str,
    account_id: UUID | str | None = None,
) -> tuple[str, ApiKeyRecord]:
    key_id, secret, plaintext = new_plaintext_key()
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.api_keys (key_id, name, key_hmac, scopes, created_by, account_id) "
            f"VALUES (:key_id, :name, :hmac, :scopes, :created_by, :account_id) RETURNING {_KEY_COLUMNS}"
        ),
        {
            "key_id": key_id,
            "name": name,
            "hmac": hmac_secret(pepper, secret),
            "scopes": sorted(scopes),
            "created_by": created_by,
            "account_id": UUID(str(account_id)) if account_id else None,
        },
    ).first()
    assert row is not None
    return plaintext, _record(row)


def _record(row: Any) -> ApiKeyRecord:
    return ApiKeyRecord(row[0], row[1], row[2], list(row[3]), row[4], row[5], row[6], str(row[7] or ""), row[8])


def verify_api_key(conn: Connection, pepper: str, plaintext: str, *, allow_demo: bool = False) -> Principal | None:
    value = plaintext.strip()
    parsed = (DEMO_API_KEY, DEMO_API_KEY) if value == DEMO_API_KEY else parse_plaintext_key(value)
    if parsed is None:
        return None
    key_id, secret = parsed
    # Check the reserved ID too: hai_demo.demo must not bypass the environment guard.
    if key_id == DEMO_API_KEY and not allow_demo:
        return None
    row = conn.execute(
        text(
            "SELECT k.id, k.key_id, k.name, k.scopes, k.revoked_at, k.key_hmac, k.account_id, a.kind, a.name, a.org_id "
            "FROM hai_ops.api_keys k LEFT JOIN hai_ops.accounts a ON a.id = k.account_id WHERE k.key_id = :k"
        ),
        {"k": key_id},
    ).first()
    if row is None:
        # Compare anyway so timing does not reveal whether the id exists.
        hmac.compare_digest(hmac_secret(pepper, secret), hmac_secret(pepper, "x"))
        return None
    if not hmac.compare_digest(hmac_secret(pepper, secret), str(row[5])):
        return None
    if row[4] is not None:
        return None
    conn.execute(text("UPDATE hai_ops.api_keys SET last_used_at = now() WHERE id = :id"), {"id": row[0]})
    account_kind = cast(AccountKind, str(row[7])) if row[7] else None
    # A key owned by an organization account sees only that organization, whatever its scopes say.
    org_ids = frozenset({str(row[9])}) if account_kind == "organization" and row[9] else frozenset()
    return Principal(
        "api_key",
        str(row[1]),
        str(row[2]),
        frozenset(str(s) for s in row[3]),
        account_id=str(row[6]) if row[6] else None,
        account_kind=account_kind,
        account_name=str(row[8]) if row[8] else None,
        org_ids=org_ids,
    )


def revoke_api_key(conn: Connection, key_id: str, *, account_id: UUID | str | None = None) -> bool:
    """Revoke a key; when ``account_id`` is given, only a key of that account."""
    clause = " AND account_id = :account" if account_id else ""
    result = conn.execute(
        text(f"UPDATE hai_ops.api_keys SET revoked_at = now() WHERE key_id = :k AND revoked_at IS NULL{clause}"),
        {"k": key_id, "account": UUID(str(account_id)) if account_id else None},
    )
    return bool(result.rowcount)


def list_api_keys(
    conn: Connection, *, account_id: UUID | str | None = None, created_by: str | None = None
) -> list[ApiKeyRecord]:
    """All keys, or the keys of one account, optionally narrowed to one creator."""
    where = ["1=1"]
    params: dict[str, Any] = {}
    if account_id:
        where.append("account_id = :account")
        params["account"] = UUID(str(account_id))
    if created_by:
        where.append("created_by = :creator")
        params["creator"] = created_by
    rows = conn.execute(
        text(f"SELECT {_KEY_COLUMNS} FROM hai_ops.api_keys WHERE {' AND '.join(where)} ORDER BY created_at"), params
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


def decode_token(secret: str, token: str, *, issuer: str = "hai") -> dict[str, Any]:
    """Verify signature, issuer and expiry; return the claims. Session tokens carry ``sid``."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, secret, algorithms=["HS256"], issuer=issuer, options={"require": ["exp", "sub", "iss"]}
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError(f"invalid token: {exc}") from exc
    return payload


def verify_jwt(secret: str, token: str, *, issuer: str = "hai") -> Principal:
    """An admin-minted reviewer or admin token (no session row)."""
    payload = decode_token(secret, token, issuer=issuer)
    role = payload.get("role")
    if role not in ("reviewer", "admin"):
        raise UnauthorizedError("token role must be reviewer or admin")
    scopes = frozenset(str(s) for s in payload.get("scopes", []))
    if role == "admin":
        scopes = scopes | {Scope.ADMIN}
    return Principal(role, str(payload["sub"]), str(payload.get("name") or payload["sub"]), scopes)
