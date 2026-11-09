"""Console accounts: the platform account, participating organization accounts, users,
roles, sessions, invitations, password resets and access requests.

Passwords are hashed with scrypt from the standard library. Invitation and reset tokens
are random and stored as HMACs under the API key pepper. A login issues a session row and
a JWT that references it (``sid``); every request re-reads the session, the user and the
account so a disabled user or a changed role takes effect immediately.

Roles are fixed here, not in the ontology: they describe who may use the console, not
what is being scored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import jwt
from sqlalchemy import Connection, text

from hai_core.auth import AccountKind, Principal, PrincipalKind, Scope, hmac_secret
from hai_core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError, ValidationFailedError

UserStatus = Literal["active", "disabled"]
InvitationKind = Literal["invite", "password_reset"]

INVITE_TOKEN_PREFIX = "hai_inv_"  # noqa: S105 - a prefix, not a secret
SCRYPT_N_LOG2 = 14
SCRYPT_R = 8
SCRYPT_P = 1
MIN_PASSWORD_LENGTH = 10
MAX_INDUSTRIES = 20


# ---------------------------------------------------------------------- roles


@dataclass(frozen=True)
class RoleSpec:
    code: str
    label: str
    description: str
    account_kind: AccountKind
    kind: PrincipalKind
    scopes: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return Scope.ADMIN in self.scopes


_READ = frozenset({Scope.ASSESSMENTS_READ, Scope.ORGANIZATIONS_READ, Scope.ONTOLOGY_READ})

ROLES: dict[str, RoleSpec] = {
    "owner": RoleSpec(
        "owner",
        "Platform owner",
        "Full control of the platform, including other administrators.",
        "platform",
        "admin",
        Scope.ALL,
    ),
    "admin": RoleSpec(
        "admin",
        "Administrator",
        "Manages users, invitations, API keys and every assessment.",
        "platform",
        "admin",
        Scope.ALL,
    ),
    "reviewer": RoleSpec(
        "reviewer",
        "Reviewer",
        "Acts on the review queue and signs certification decisions under their own name.",
        "platform",
        "reviewer",
        Scope.REVIEWER_DEFAULT,
    ),
    "analyst": RoleSpec(
        "analyst",
        "Analyst",
        "Starts assessments, submits evidence and reads results.",
        "platform",
        "user",
        _READ | {Scope.ASSESSMENTS_WRITE, Scope.UPLOADS_WRITE},
    ),
    "viewer": RoleSpec("viewer", "Viewer", "Reads assessments, reports and organizations.", "platform", "user", _READ),
    "org_admin": RoleSpec(
        "org_admin",
        "Organization admin",
        "Sees the organization's reports, submits evidence and invites colleagues.",
        "organization",
        "user",
        _READ | {Scope.UPLOADS_WRITE},
    ),
    "org_member": RoleSpec(
        "org_member",
        "Organization member",
        "Sees the organization's reports.",
        "organization",
        "user",
        _READ,
    ),
}

SCOPE_LABELS: dict[str, tuple[str, str]] = {
    Scope.ASSESSMENTS_READ: ("View assessments", "Read assessments, results, reports and traces."),
    Scope.ASSESSMENTS_WRITE: ("Start assessments", "Create, cancel and reassess; request certification."),
    Scope.ORGANIZATIONS_READ: ("View organizations", "Read the organization directory and evidence ledger."),
    Scope.REVIEWS_WRITE: ("Review queue", "Act on review tasks with a reason."),
    Scope.CERTIFICATION_SIGN: ("Sign certifications", "Sign and revoke certification decisions."),
    Scope.UPLOADS_WRITE: ("Submit evidence", "Upload documents to the evidence portal."),
    Scope.WEBHOOKS_WRITE: ("Webhooks", "Subscribe to assessment and certification events."),
    Scope.AUDIT_READ: ("Audit log", "Read and verify the audit chain."),
    Scope.ONTOLOGY_READ: ("Methodology", "Read the ontology and methodology (public)."),
    Scope.ADMIN: ("Administration", "Everything, including team and API key management."),
}

ORGANIZATION_ROLES = frozenset(r for r, spec in ROLES.items() if spec.account_kind == "organization")
PLATFORM_ROLES = frozenset(r for r, spec in ROLES.items() if spec.account_kind == "platform")


def role_spec(role: str) -> RoleSpec:
    spec = ROLES.get(role)
    if spec is None:
        raise ValidationFailedError(f"unknown role {role!r}", details={"fields": {"role": "unknown role"}})
    return spec


def effective_scopes(role: str, requested: list[str] | None) -> frozenset[str]:
    """The role's scopes, narrowed to ``requested`` when given. Nothing beyond the role."""
    spec = role_spec(role)
    if requested is None:
        return spec.scopes
    wanted = frozenset(requested)
    unknown = sorted(wanted - Scope.ALL)
    if unknown:
        raise ValidationFailedError(f"unknown scopes {unknown}", details={"fields": {"scopes": "unknown scope"}})
    beyond = sorted(wanted - spec.scopes)
    if beyond:
        raise ValidationFailedError(
            f"scopes {beyond} are not available to the {spec.label} role",
            details={"fields": {"scopes": "beyond role"}, "allowed": sorted(spec.scopes)},
        )
    if spec.is_admin:
        return spec.scopes  # administrators are not narrowed
    return wanted | {Scope.ONTOLOGY_READ}


def normalize_industries(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        cleaned = " ".join(v.strip().lower().split())
        if cleaned and cleaned not in out:
            out.append(cleaned)
    if len(out) > MAX_INDUSTRIES:
        raise ValidationFailedError("too many industries", details={"fields": {"industries": "at most 20"}})
    return out


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@") or " " in value:
        raise ValidationFailedError("invalid email address", details={"fields": {"email": "invalid email"}})
    return value


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[1]


# ------------------------------------------------------------------ passwords


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**SCRYPT_N_LOG2, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N_LOG2,
        SCRYPT_R,
        SCRYPT_P,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        # Hash anyway so a user without a password costs the same as a wrong password.
        hashlib.scrypt(password.encode("utf-8"), salt=b"0" * 16, n=2**SCRYPT_N_LOG2, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
        return False
    try:
        scheme, n_log2, r, p, salt, digest = encoded.split("$")
        if scheme != "scrypt":
            return False
        computed = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt), n=2 ** int(n_log2), r=int(r), p=int(p), dklen=32
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(computed, _unb64(digest))


def check_password_policy(password: str, *, email: str | None = None, min_length: int = MIN_PASSWORD_LENGTH) -> None:
    problems: dict[str, str] = {}
    if len(password) < min_length:
        problems["password"] = f"use at least {min_length} characters"
    elif email and password.strip().lower() == email.strip().lower():
        problems["password"] = "the password must not be the email address"  # noqa: S105
    elif password.strip().lower() in {"password", "password123", "0123456789", "1234567890", "qwertyuiop"}:
        problems["password"] = "that password is too common"  # noqa: S105
    if problems:
        raise ValidationFailedError("weak password", details={"fields": problems})


# -------------------------------------------------------------------- records


@dataclass(frozen=True)
class Account:
    id: UUID
    kind: AccountKind
    name: str
    org_id: UUID | None
    email_domain: str | None
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "name": self.name,
            "org_id": str(self.org_id) if self.org_id else None,
            "email_domain": self.email_domain,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class User:
    id: UUID
    account_id: UUID
    email: str
    name: str
    role: str
    scopes: list[str]
    industries: list[str]
    status: UserStatus
    created_at: datetime
    last_login_at: datetime | None
    invited_by: str | None
    password_hash: str | None = field(default=None, repr=False)
    failed_logins: int = 0
    locked_until: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        spec = ROLES.get(self.role)
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "role_label": spec.label if spec else self.role,
            "scopes": sorted(self.scopes),
            "industries": list(self.industries),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "invited_by": self.invited_by,
        }


@dataclass(frozen=True)
class Invitation:
    id: UUID
    kind: InvitationKind
    account_id: UUID
    user_id: UUID | None
    email: str
    role: str
    scopes: list[str]
    industries: list[str]
    invited_by: str
    invited_by_name: str | None
    message: str | None
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    @property
    def status(self) -> str:
        if self.accepted_at:
            return "accepted"
        if self.revoked_at:
            return "revoked"
        if self.expires_at < datetime.now(UTC):
            return "expired"
        return "pending"

    def as_dict(self) -> dict[str, Any]:
        spec = ROLES.get(self.role)
        return {
            "id": str(self.id),
            "kind": self.kind,
            "account_id": str(self.account_id),
            "user_id": str(self.user_id) if self.user_id else None,
            "email": self.email,
            "role": self.role,
            "role_label": spec.label if spec else self.role,
            "scopes": sorted(self.scopes),
            "industries": list(self.industries),
            "invited_by": self.invited_by,
            "invited_by_name": self.invited_by_name,
            "message": self.message,
            "status": self.status,
            "expires_at": self.expires_at.isoformat(),
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class Session:
    id: UUID
    user_id: UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None
    user_agent: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "user_agent": self.user_agent,
        }


@dataclass(frozen=True)
class AccessRequest:
    id: UUID
    email: str
    name: str
    organization_name: str
    website: str | None
    message: str | None
    status: str
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "email": self.email,
            "name": self.name,
            "organization_name": self.organization_name,
            "website": self.website,
            "message": self.message,
            "status": self.status,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat(),
        }


_ACCOUNT_COLS = "id, kind, name, org_id, email_domain, created_at"
_USER_COLS = (
    "id, account_id, email, name, role, scopes, industries, status, created_at, last_login_at, invited_by, "
    "password_hash, failed_logins, locked_until"
)
_INVITE_COLS = (
    "id, kind, account_id, user_id, email, role, scopes, industries, invited_by, invited_by_name, message, "
    "expires_at, accepted_at, revoked_at, created_at"
)
_SESSION_COLS = "id, user_id, created_at, expires_at, last_seen_at, revoked_at, user_agent"
_REQUEST_COLS = "id, email, name, organization_name, website, message, status, resolved_by, resolved_at, created_at"


def _account(row: Any) -> Account:
    return Account(row[0], cast(AccountKind, str(row[1])), str(row[2]), row[3], row[4], row[5])


def _user(row: Any) -> User:
    return User(
        row[0],
        row[1],
        str(row[2]),
        str(row[3]),
        str(row[4]),
        [str(s) for s in row[5]],
        [str(s) for s in row[6]],
        cast(UserStatus, str(row[7])),
        row[8],
        row[9],
        row[10],
        row[11],
        int(row[12]),
        row[13],
    )


def _invitation(row: Any) -> Invitation:
    return Invitation(
        row[0],
        cast(InvitationKind, str(row[1])),
        row[2],
        row[3],
        str(row[4]),
        str(row[5]),
        [str(s) for s in row[6]],
        [str(s) for s in row[7]],
        str(row[8]),
        row[9],
        row[10],
        row[11],
        row[12],
        row[13],
        row[14],
    )


def _session(row: Any) -> Session:
    return Session(row[0], row[1], row[2], row[3], row[4], row[5], row[6])


def _request(row: Any) -> AccessRequest:
    return AccessRequest(
        row[0], str(row[1]), str(row[2]), str(row[3]), row[4], row[5], str(row[6]), row[7], row[8], row[9]
    )


# ------------------------------------------------------------------- accounts


def count_users(conn: Connection) -> int:
    return int(conn.execute(text("SELECT count(*) FROM hai_ops.users")).scalar_one())


def is_bootstrapped(conn: Connection) -> bool:
    return count_users(conn) > 0


def platform_account(conn: Connection) -> Account | None:
    row = conn.execute(text(f"SELECT {_ACCOUNT_COLS} FROM hai_ops.accounts WHERE kind = 'platform'")).first()
    return _account(row) if row else None


def get_account(conn: Connection, account_id: UUID | str) -> Account | None:
    row = conn.execute(
        text(f"SELECT {_ACCOUNT_COLS} FROM hai_ops.accounts WHERE id = :id"), {"id": UUID(str(account_id))}
    ).first()
    return _account(row) if row else None


def list_accounts(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            f"SELECT {_ACCOUNT_COLS}, "
            "(SELECT count(*) FROM hai_ops.users u WHERE u.account_id = a.id AND u.status = 'active') AS active_users, "
            "(SELECT count(*) FROM hai_ops.invitations i WHERE i.account_id = a.id AND i.kind = 'invite' "
            " AND i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now()) AS pending_invitations, "
            "(SELECT count(*) FROM hai_ops.api_keys k WHERE k.account_id = a.id AND k.revoked_at IS NULL) AS api_keys "
            "FROM hai_ops.accounts a ORDER BY (kind = 'platform') DESC, name"
        )
    ).all()
    return [
        {
            **_account(r).as_dict(),
            "active_users": int(r[6]),
            "pending_invitations": int(r[7]),
            "api_keys": int(r[8]),
        }
        for r in rows
    ]


def ensure_organization_account(conn: Connection, org_id: UUID, *, created_by: str) -> Account:
    """The account of a participating organization, created on first invitation."""
    row = conn.execute(text(f"SELECT {_ACCOUNT_COLS} FROM hai_ops.accounts WHERE org_id = :o"), {"o": org_id}).first()
    if row:
        return _account(row)
    org = conn.execute(
        text("SELECT display_name, legal_name, primary_domain FROM hai.organizations WHERE id = :o"), {"o": org_id}
    ).first()
    if org is None:
        raise NotFoundError(f"organization {org_id} not found")
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.accounts (kind, name, org_id, email_domain, created_by) "
            f"VALUES ('organization', :name, :org, :domain, :by) RETURNING {_ACCOUNT_COLS}"
        ),
        {"name": str(org[0] or org[1]), "org": org_id, "domain": str(org[2]).lower(), "by": created_by},
    ).first()
    assert row is not None
    return _account(row)


# ---------------------------------------------------------------------- users


def get_user(conn: Connection, user_id: UUID | str) -> User | None:
    row = conn.execute(
        text(f"SELECT {_USER_COLS} FROM hai_ops.users WHERE id = :id"), {"id": UUID(str(user_id))}
    ).first()
    return _user(row) if row else None


def find_user_by_email(conn: Connection, email: str) -> User | None:
    row = conn.execute(
        text(f"SELECT {_USER_COLS} FROM hai_ops.users WHERE lower(email) = :e"), {"e": email.strip().lower()}
    ).first()
    return _user(row) if row else None


def list_users(conn: Connection, *, account_id: UUID | str | None = None) -> list[tuple[User, Account]]:
    clause = "WHERE u.account_id = :a" if account_id else ""
    rows = conn.execute(
        text(
            f"SELECT {', '.join('u.' + c.strip() for c in _USER_COLS.split(','))}, "
            f"{', '.join('a.' + c.strip() for c in _ACCOUNT_COLS.split(','))} "
            f"FROM hai_ops.users u JOIN hai_ops.accounts a ON a.id = u.account_id {clause} "
            "ORDER BY (a.kind = 'platform') DESC, a.name, u.created_at"
        ),
        {"a": UUID(str(account_id)) if account_id else None},
    ).all()
    n = len(_USER_COLS.split(","))
    return [(_user(r[:n]), _account(r[n:])) for r in rows]


def _insert_user(
    conn: Connection,
    *,
    account_id: UUID,
    email: str,
    name: str,
    role: str,
    scopes: frozenset[str],
    industries: list[str],
    password_hash: str | None,
    invited_by: str | None,
) -> User:
    if find_user_by_email(conn, email) is not None:
        raise ConflictError("a user with this email already exists", details={"fields": {"email": "already in use"}})
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.users (account_id, email, name, role, scopes, industries, password_hash, invited_by) "
            f"VALUES (:a, :e, :n, :r, :s, :i, :p, :by) RETURNING {_USER_COLS}"
        ),
        {
            "a": account_id,
            "e": email,
            "n": name.strip(),
            "r": role,
            "s": sorted(scopes),
            "i": industries,
            "p": password_hash,
            "by": invited_by,
        },
    ).first()
    assert row is not None
    return _user(row)


def bootstrap_owner(
    conn: Connection, *, email: str, name: str, password: str, platform_name: str = "Humaital", created_by: str
) -> User:
    """Create the platform account and its first owner. Only when no user exists yet."""
    if is_bootstrapped(conn):
        raise ConflictError("the platform already has users; ask an administrator for an invitation")
    email = normalize_email(email)
    if not name.strip():
        raise ValidationFailedError("name is required", details={"fields": {"name": "required"}})
    check_password_policy(password, email=email)
    account = platform_account(conn)
    if account is None:
        row = conn.execute(
            text(
                "INSERT INTO hai_ops.accounts (kind, name, email_domain, created_by) "
                f"VALUES ('platform', :name, :domain, :by) RETURNING {_ACCOUNT_COLS}"
            ),
            {"name": platform_name.strip() or "Humaital", "domain": email_domain(email), "by": created_by},
        ).first()
        assert row is not None
        account = _account(row)
    return _insert_user(
        conn,
        account_id=account.id,
        email=email,
        name=name,
        role="owner",
        scopes=ROLES["owner"].scopes,
        industries=[],
        password_hash=hash_password(password),
        invited_by=None,
    )


def create_user_directly(
    conn: Connection,
    *,
    account_id: UUID,
    email: str,
    name: str,
    role: str,
    password: str,
    industries: list[str] | None = None,
    created_by: str,
) -> User:
    """An active user with a known password (operators and tests). Role must fit the account."""
    account = get_account(conn, account_id)
    if account is None:
        raise NotFoundError("account not found")
    spec = role_spec(role)
    if spec.account_kind != account.kind:
        raise ValidationFailedError(f"role {role} does not belong to a {account.kind} account")
    email = normalize_email(email)
    check_password_policy(password, email=email)
    return _insert_user(
        conn,
        account_id=account.id,
        email=email,
        name=name,
        role=role,
        scopes=spec.scopes,
        industries=normalize_industries(industries),
        password_hash=hash_password(password),
        invited_by=created_by,
    )


def _active_owners(conn: Connection, excluding: UUID | None = None) -> int:
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM hai_ops.users WHERE role = 'owner' AND status = 'active' "
                "AND (CAST(:x AS uuid) IS NULL OR id <> :x)"
            ),
            {"x": excluding},
        ).scalar_one()
    )


def update_user(
    conn: Connection,
    *,
    actor: Principal,
    user_id: UUID,
    name: str | None = None,
    role: str | None = None,
    scopes: list[str] | None = None,
    industries: list[str] | None = None,
    status: UserStatus | None = None,
) -> User:
    """Change a user's role, scopes, industries or status under the team rules."""
    user = get_user(conn, user_id)
    if user is None:
        raise NotFoundError("user not found")
    assert_can_manage(actor, user)
    if str(user.id) == actor.id and (role is not None or status is not None):
        raise ForbiddenError("you cannot change your own role or status")
    if user.role == "owner" and actor.account_role != "owner":
        raise ForbiddenError("only a platform owner can change another owner")
    new_role = role or user.role
    spec = role_spec(new_role)
    account = get_account(conn, user.account_id)
    assert account is not None
    if spec.account_kind != account.kind:
        raise ValidationFailedError(f"role {new_role} does not belong to a {account.kind} account")
    if new_role == "owner" and actor.account_role != "owner":
        raise ForbiddenError("only a platform owner can grant the owner role")
    if actor.account_role == "org_admin" and new_role not in ORGANIZATION_ROLES:
        raise ForbiddenError("organization admins manage organization roles only")
    if scopes is not None:
        new_scopes = effective_scopes(new_role, scopes)
    elif role is not None:
        new_scopes = spec.scopes  # a new role starts from its defaults
    else:
        new_scopes = frozenset(user.scopes)
    new_industries = normalize_industries(industries) if industries is not None else user.industries
    if account.kind == "organization":
        new_industries = []
    new_status = status or user.status
    loses_owner = (new_status == "disabled" or new_role != "owner") and user.role == "owner" and user.status == "active"
    if loses_owner and _active_owners(conn, excluding=user.id) == 0:
        raise ConflictError("the platform must keep at least one active owner")
    row = conn.execute(
        text(
            "UPDATE hai_ops.users SET name = :n, role = :r, scopes = :s, industries = :i, status = :st, "
            f"updated_at = now() WHERE id = :id RETURNING {_USER_COLS}"
        ),
        {
            "n": (name or user.name).strip(),
            "r": new_role,
            "s": sorted(new_scopes),
            "i": new_industries,
            "st": new_status,
            "id": user.id,
        },
    ).first()
    assert row is not None
    if new_status == "disabled":
        revoke_sessions(conn, user_id=user.id)
    return _user(row)


def assert_can_manage(actor: Principal, target: User | Account) -> None:
    """Platform admins manage everyone; organization admins manage their own account."""
    if actor.is_platform_admin:
        return
    account_id = target.account_id if isinstance(target, User) else target.id
    if actor.account_role == "org_admin" and actor.account_id == str(account_id):
        return
    raise ForbiddenError("you do not manage this account")


# ------------------------------------------------------------------- sessions


def _issue_session(
    conn: Connection,
    *,
    user: User,
    account: Account,
    secret: str,
    issuer: str,
    ttl: timedelta,
    user_agent: str | None,
) -> tuple[str, Session]:
    now = datetime.now(UTC)
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.sessions (user_id, expires_at, last_seen_at, user_agent) "
            f"VALUES (:u, :exp, :now, :ua) RETURNING {_SESSION_COLS}"
        ),
        {"u": user.id, "exp": now + ttl, "now": now, "ua": (user_agent or "")[:300] or None},
    ).first()
    assert row is not None
    session = _session(row)
    spec = role_spec(user.role)
    payload: dict[str, Any] = {
        "iss": issuer,
        "sub": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": spec.kind,
        "account_role": user.role,
        "account": str(account.id),
        "account_kind": account.kind,
        "scopes": sorted(user.scopes),
        "sid": str(session.id),
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid4().hex,
    }
    conn.execute(
        text("UPDATE hai_ops.users SET last_login_at = now(), failed_logins = 0 WHERE id = :id"), {"id": user.id}
    )
    return jwt.encode(payload, secret, algorithm="HS256"), session


@dataclass(frozen=True)
class LoginResult:
    """Success carries the session; failure carries a message. Failures are returned, not raised,
    so the caller's transaction commits the failed-attempt counter and the lockout."""

    token: str | None = None
    session: Session | None = None
    user: User | None = None
    account: Account | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.token is not None

    def unwrap(self) -> tuple[str, Session, User, Account]:
        if self.token is None or self.session is None or self.user is None or self.account is None:
            raise UnauthorizedError(self.error or "invalid email or password", details=self.details)
        return self.token, self.session, self.user, self.account


def login(
    conn: Connection,
    *,
    email: str,
    password: str,
    secret: str,
    issuer: str,
    ttl: timedelta,
    user_agent: str | None = None,
    max_failures: int = 10,
    lockout: timedelta = timedelta(minutes=15),
) -> LoginResult:
    """Verify email and password, apply the lockout, issue a session. Errors do not say which part failed."""
    user = find_user_by_email(conn, email) if "@" in email else None
    if user is None:
        verify_password(password, None)
        return LoginResult(error="invalid email or password")
    now = datetime.now(UTC)
    if user.locked_until and user.locked_until > now:
        return LoginResult(
            error="too many failed sign-in attempts; try again later",
            details={"locked_until": user.locked_until.isoformat()},
        )
    if not verify_password(password, user.password_hash):
        failures = user.failed_logins + 1
        lock = now + lockout if failures >= max_failures else None
        conn.execute(
            text("UPDATE hai_ops.users SET failed_logins = :f, locked_until = :l WHERE id = :id"),
            {"f": failures, "l": lock, "id": user.id},
        )
        return LoginResult(error="invalid email or password")
    if user.status != "active":
        return LoginResult(error="this account is disabled; contact your administrator")
    account = get_account(conn, user.account_id)
    assert account is not None
    conn.execute(text("UPDATE hai_ops.users SET locked_until = NULL WHERE id = :id"), {"id": user.id})
    token, session = _issue_session(
        conn, user=user, account=account, secret=secret, issuer=issuer, ttl=ttl, user_agent=user_agent
    )
    return LoginResult(token=token, session=session, user=user, account=account)


def principal_for(user: User, account: Account, session_id: UUID | None = None) -> Principal:
    spec = role_spec(user.role)
    return Principal(
        spec.kind,
        str(user.id),
        user.name,
        frozenset(user.scopes),
        account_id=str(account.id),
        account_kind=account.kind,
        account_name=account.name,
        account_role=user.role,
        email=user.email,
        session_id=str(session_id) if session_id else None,
        org_ids=frozenset({str(account.org_id)}) if account.kind == "organization" and account.org_id else frozenset(),
        industries=frozenset(user.industries) if account.kind == "platform" else frozenset(),
    )


def verify_session(conn: Connection, claims: dict[str, Any]) -> Principal:
    """Resolve a session JWT's claims against the live session, user and account rows."""
    sid = claims.get("sid")
    try:
        session_id = UUID(str(sid))
    except ValueError as exc:
        raise UnauthorizedError("invalid session token") from exc
    row = conn.execute(
        text(
            f"SELECT {', '.join('s.' + c.strip() for c in _SESSION_COLS.split(','))}, "
            f"{', '.join('u.' + c.strip() for c in _USER_COLS.split(','))}, "
            f"{', '.join('a.' + c.strip() for c in _ACCOUNT_COLS.split(','))} "
            "FROM hai_ops.sessions s JOIN hai_ops.users u ON u.id = s.user_id "
            "JOIN hai_ops.accounts a ON a.id = u.account_id WHERE s.id = :sid"
        ),
        {"sid": session_id},
    ).first()
    if row is None:
        raise UnauthorizedError("session not found; sign in again")
    ns, nu = len(_SESSION_COLS.split(",")), len(_USER_COLS.split(","))
    session, user, account = _session(row[:ns]), _user(row[ns : ns + nu]), _account(row[ns + nu :])
    now = datetime.now(UTC)
    if session.revoked_at is not None or session.expires_at <= now:
        raise UnauthorizedError("session expired or signed out; sign in again")
    if user.status != "active":
        raise UnauthorizedError("this account is disabled; contact your administrator")
    if str(user.id) != str(claims.get("sub")):
        raise UnauthorizedError("session does not match the token")
    conn.execute(
        text(
            "UPDATE hai_ops.sessions SET last_seen_at = now() WHERE id = :sid "
            "AND (last_seen_at IS NULL OR last_seen_at < now() - interval '60 seconds')"
        ),
        {"sid": session.id},
    )
    return principal_for(user, account, session.id)


def list_sessions(conn: Connection, *, user_id: UUID | str) -> list[Session]:
    rows = conn.execute(
        text(
            f"SELECT {_SESSION_COLS} FROM hai_ops.sessions WHERE user_id = :u AND revoked_at IS NULL "
            "AND expires_at > now() ORDER BY created_at DESC"
        ),
        {"u": UUID(str(user_id))},
    ).all()
    return [_session(r) for r in rows]


def revoke_sessions(conn: Connection, *, user_id: UUID | str, except_session: UUID | str | None = None) -> int:
    result = conn.execute(
        text(
            "UPDATE hai_ops.sessions SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL "
            "AND (CAST(:keep AS uuid) IS NULL OR id <> :keep)"
        ),
        {"u": UUID(str(user_id)), "keep": UUID(str(except_session)) if except_session else None},
    )
    return int(result.rowcount)


def revoke_session(conn: Connection, session_id: UUID | str) -> bool:
    result = conn.execute(
        text("UPDATE hai_ops.sessions SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"),
        {"id": UUID(str(session_id))},
    )
    return bool(result.rowcount)


def change_password(conn: Connection, *, user: User, current: str, new: str, keep_session: UUID | str | None) -> None:
    if not verify_password(current, user.password_hash):
        raise UnauthorizedError("the current password is incorrect")
    check_password_policy(new, email=user.email)
    conn.execute(
        text("UPDATE hai_ops.users SET password_hash = :p, updated_at = now() WHERE id = :id"),
        {"p": hash_password(new), "id": user.id},
    )
    revoke_sessions(conn, user_id=user.id, except_session=keep_session)


def update_profile(conn: Connection, *, user_id: UUID | str, name: str) -> User:
    if not name.strip():
        raise ValidationFailedError("name is required", details={"fields": {"name": "required"}})
    row = conn.execute(
        text(f"UPDATE hai_ops.users SET name = :n, updated_at = now() WHERE id = :id RETURNING {_USER_COLS}"),
        {"n": name.strip()[:200], "id": UUID(str(user_id))},
    ).first()
    if row is None:
        raise NotFoundError("user not found")
    return _user(row)


# ---------------------------------------------------------------- invitations


def new_invite_token() -> str:
    return INVITE_TOKEN_PREFIX + secrets.token_urlsafe(32)


def _token_hmac(pepper: str, token: str) -> str:
    return hmac_secret(pepper, token.strip())


def create_invitation(
    conn: Connection,
    pepper: str,
    *,
    actor: Principal,
    email: str,
    role: str,
    org_id: UUID | None = None,
    industries: list[str] | None = None,
    scopes: list[str] | None = None,
    message: str | None = None,
    ttl: timedelta = timedelta(days=7),
) -> tuple[str, Invitation, Account, bool]:
    """Invite a user into the platform account or an organization account.

    Returns the plaintext token (shown once), the invitation, the target account and
    whether the invited email's domain matches the organization's domain.
    """
    email = normalize_email(email)
    spec = role_spec(role)
    if spec.account_kind == "platform":
        if not actor.is_platform_admin:
            raise ForbiddenError("only platform administrators invite platform users")
        if role == "owner" and actor.account_role != "owner":
            raise ForbiddenError("only a platform owner can invite another owner")
        account = platform_account(conn)
        if account is None:
            raise ConflictError("the platform account does not exist yet")
    else:
        if actor.is_platform_admin:
            if org_id is None:
                raise ValidationFailedError(
                    "an organization is required for organization roles", details={"fields": {"org_id": "required"}}
                )
            account = ensure_organization_account(conn, org_id, created_by=actor.actor)
        elif actor.account_role == "org_admin" and actor.account_id:
            found = get_account(conn, actor.account_id)
            if found is None or found.kind != "organization":
                raise ForbiddenError("your account cannot invite users")
            account = found
        else:
            raise ForbiddenError("you cannot invite users")
    if find_user_by_email(conn, email) is not None:
        raise ConflictError("a user with this email already exists", details={"fields": {"email": "already in use"}})
    final_scopes = effective_scopes(role, scopes)
    final_industries = normalize_industries(industries) if spec.account_kind == "platform" else []
    # A new invitation for the same email replaces pending ones.
    conn.execute(
        text(
            "UPDATE hai_ops.invitations SET revoked_at = now() WHERE lower(email) = :e AND kind = 'invite' "
            "AND accepted_at IS NULL AND revoked_at IS NULL"
        ),
        {"e": email},
    )
    token = new_invite_token()
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.invitations (kind, account_id, email, role, scopes, industries, token_hmac, "
            "invited_by, invited_by_name, message, expires_at) VALUES ('invite', :a, :e, :r, :s, :i, :h, :by, :byname, "
            f":m, :exp) RETURNING {_INVITE_COLS}"
        ),
        {
            "a": account.id,
            "e": email,
            "r": role,
            "s": sorted(final_scopes),
            "i": final_industries,
            "h": _token_hmac(pepper, token),
            "by": actor.actor,
            "byname": actor.name,
            "m": (message or "").strip()[:2000] or None,
            "exp": datetime.now(UTC) + ttl,
        },
    ).first()
    assert row is not None
    conn.execute(
        text(
            "UPDATE hai_ops.access_requests SET status = 'invited', resolved_by = :by, resolved_at = now() "
            "WHERE lower(email) = :e AND status = 'pending'"
        ),
        {"by": actor.actor, "e": email},
    )
    domain_match = account.kind != "organization" or _domain_matches(conn, account, email_domain(email))
    return token, _invitation(row), account, domain_match


def _domain_matches(conn: Connection, account: Account, domain: str) -> bool:
    if account.email_domain and (domain == account.email_domain or domain.endswith("." + account.email_domain)):
        return True
    if account.org_id is None:
        return False
    row = conn.execute(text("SELECT aliases FROM hai.organizations WHERE id = :o"), {"o": account.org_id}).first()
    aliases = [str(a).lower() for a in (row[0] or [])] if row else []
    return any(domain == a or domain.endswith("." + a) for a in aliases)


def create_password_reset(
    conn: Connection, pepper: str, *, actor: Principal, user_id: UUID, ttl: timedelta = timedelta(hours=24)
) -> tuple[str, Invitation]:
    user = get_user(conn, user_id)
    if user is None:
        raise NotFoundError("user not found")
    if str(user.id) != actor.id:
        assert_can_manage(actor, user)
        if user.role == "owner" and actor.account_role != "owner":
            raise ForbiddenError("only a platform owner can reset another owner's password")
    conn.execute(
        text(
            "UPDATE hai_ops.invitations SET revoked_at = now() WHERE user_id = :u AND kind = 'password_reset' "
            "AND accepted_at IS NULL AND revoked_at IS NULL"
        ),
        {"u": user.id},
    )
    token = new_invite_token()
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.invitations (kind, account_id, user_id, email, role, scopes, industries, token_hmac, "
            "invited_by, invited_by_name, expires_at) VALUES ('password_reset', :a, :u, :e, :r, :s, :i, :h, :by, "
            f":byname, :exp) RETURNING {_INVITE_COLS}"
        ),
        {
            "a": user.account_id,
            "u": user.id,
            "e": user.email,
            "r": user.role,
            "s": sorted(user.scopes),
            "i": user.industries,
            "h": _token_hmac(pepper, token),
            "by": actor.actor,
            "byname": actor.name,
            "exp": datetime.now(UTC) + ttl,
        },
    ).first()
    assert row is not None
    return token, _invitation(row)


def find_invitation(conn: Connection, pepper: str, token: str) -> tuple[Invitation, Account]:
    """A pending, unexpired invitation or reset for a plaintext token."""
    if not token.startswith(INVITE_TOKEN_PREFIX):
        raise NotFoundError("invitation not found")
    row = conn.execute(
        text(f"SELECT {_INVITE_COLS} FROM hai_ops.invitations WHERE token_hmac = :h"), {"h": _token_hmac(pepper, token)}
    ).first()
    if row is None:
        raise NotFoundError("invitation not found")
    invitation = _invitation(row)
    if invitation.status != "pending":
        raise ConflictError(f"this invitation is {invitation.status}", details={"status": invitation.status})
    account = get_account(conn, invitation.account_id)
    assert account is not None
    return invitation, account


def accept_invitation(
    conn: Connection,
    pepper: str,
    *,
    token: str,
    name: str,
    password: str,
    secret: str,
    issuer: str,
    ttl: timedelta,
    user_agent: str | None = None,
) -> tuple[str, Session, User, Account]:
    """Create the user (or reset the password) and sign them in."""
    invitation, account = find_invitation(conn, pepper, token)
    check_password_policy(password, email=invitation.email)
    if invitation.kind == "password_reset":
        assert invitation.user_id is not None
        user = get_user(conn, invitation.user_id)
        if user is None or user.status != "active":
            raise ConflictError("this account can no longer be reset")
        conn.execute(
            text(
                "UPDATE hai_ops.users SET password_hash = :p, failed_logins = 0, locked_until = NULL, "
                "updated_at = now() WHERE id = :id"
            ),
            {"p": hash_password(password), "id": user.id},
        )
        revoke_sessions(conn, user_id=user.id)
    else:
        if not name.strip():
            raise ValidationFailedError("name is required", details={"fields": {"name": "required"}})
        user = _insert_user(
            conn,
            account_id=account.id,
            email=invitation.email,
            name=name,
            role=invitation.role,
            scopes=frozenset(invitation.scopes),
            industries=invitation.industries,
            password_hash=hash_password(password),
            invited_by=invitation.invited_by,
        )
    conn.execute(text("UPDATE hai_ops.invitations SET accepted_at = now() WHERE id = :id"), {"id": invitation.id})
    user = get_user(conn, user.id) or user
    jwt_token, session = _issue_session(
        conn, user=user, account=account, secret=secret, issuer=issuer, ttl=ttl, user_agent=user_agent
    )
    return jwt_token, session, user, account


def list_invitations(
    conn: Connection, *, account_id: UUID | str | None = None, pending_only: bool = True
) -> list[tuple[Invitation, Account]]:
    where = ["i.kind = 'invite'"]
    params: dict[str, Any] = {}
    if account_id:
        where.append("i.account_id = :a")
        params["a"] = UUID(str(account_id))
    if pending_only:
        where.append("i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now()")
    rows = conn.execute(
        text(
            f"SELECT {', '.join('i.' + c.strip() for c in _INVITE_COLS.split(','))}, "
            f"{', '.join('a.' + c.strip() for c in _ACCOUNT_COLS.split(','))} "
            f"FROM hai_ops.invitations i JOIN hai_ops.accounts a ON a.id = i.account_id WHERE {' AND '.join(where)} "
            "ORDER BY i.created_at DESC"
        ),
        params,
    ).all()
    n = len(_INVITE_COLS.split(","))
    return [(_invitation(r[:n]), _account(r[n:])) for r in rows]


def revoke_invitation(conn: Connection, *, actor: Principal, invitation_id: UUID) -> bool:
    row = conn.execute(
        text(f"SELECT {_INVITE_COLS} FROM hai_ops.invitations WHERE id = :id"), {"id": invitation_id}
    ).first()
    if row is None:
        raise NotFoundError("invitation not found")
    invitation = _invitation(row)
    account = get_account(conn, invitation.account_id)
    assert account is not None
    assert_can_manage(actor, account)
    result = conn.execute(
        text(
            "UPDATE hai_ops.invitations SET revoked_at = now() "
            "WHERE id = :id AND accepted_at IS NULL AND revoked_at IS NULL"
        ),
        {"id": invitation_id},
    )
    return bool(result.rowcount)


# ------------------------------------------------------------ access requests


def create_access_request(
    conn: Connection, *, email: str, name: str, organization_name: str, website: str | None, message: str | None
) -> AccessRequest:
    """Record a request from someone without an invitation. One pending request per email."""
    email = normalize_email(email)
    if not name.strip() or not organization_name.strip():
        raise ValidationFailedError(
            "name and organization are required",
            details={
                "fields": {
                    k: "required"
                    for k, v in (("name", name), ("organization_name", organization_name))
                    if not v.strip()
                }
            },
        )
    existing = conn.execute(
        text(f"SELECT {_REQUEST_COLS} FROM hai_ops.access_requests WHERE lower(email) = :e AND status = 'pending'"),
        {"e": email},
    ).first()
    if existing:
        return _request(existing)
    row = conn.execute(
        text(
            "INSERT INTO hai_ops.access_requests (email, name, organization_name, website, message) "
            f"VALUES (:e, :n, :o, :w, :m) RETURNING {_REQUEST_COLS}"
        ),
        {
            "e": email,
            "n": name.strip()[:200],
            "o": organization_name.strip()[:200],
            "w": (website or "").strip()[:500] or None,
            "m": (message or "").strip()[:2000] or None,
        },
    ).first()
    assert row is not None
    return _request(row)


def list_access_requests(conn: Connection, *, status: str | None = "pending") -> list[AccessRequest]:
    clause = "WHERE status = :s" if status else ""
    rows = conn.execute(
        text(f"SELECT {_REQUEST_COLS} FROM hai_ops.access_requests {clause} ORDER BY created_at DESC"), {"s": status}
    ).all()
    return [_request(r) for r in rows]


def dismiss_access_request(conn: Connection, *, actor: Principal, request_id: UUID) -> AccessRequest:
    row = conn.execute(
        text(
            "UPDATE hai_ops.access_requests SET status = 'dismissed', resolved_by = :by, resolved_at = now() "
            f"WHERE id = :id AND status = 'pending' RETURNING {_REQUEST_COLS}"
        ),
        {"by": actor.actor, "id": request_id},
    ).first()
    if row is None:
        raise NotFoundError("no pending access request with that id")
    return _request(row)


def roles_catalog() -> dict[str, Any]:
    """Roles and scopes with labels, for the console's invitation form."""
    return {
        "roles": [
            {
                "code": spec.code,
                "label": spec.label,
                "description": spec.description,
                "account_kind": spec.account_kind,
                "scopes": sorted(spec.scopes),
                "narrowable": not spec.is_admin,
            }
            for spec in ROLES.values()
        ],
        "scopes": [
            {"code": code, "label": label, "description": description}
            for code, (label, description) in SCOPE_LABELS.items()
        ],
    }
