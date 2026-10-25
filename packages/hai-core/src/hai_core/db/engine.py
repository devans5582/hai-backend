"""Engine and transactions.

Every transaction sets the acting principal (``hai.actor``) so ``created_by``
and the audit log know who wrote. When roles are enforced, ``SET LOCAL ROLE``
switches to the component's NOLOGIN role so table grants enforce writer
separation (IC-12). Integrity errors raised by generated triggers and
constraints are translated into typed errors.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from hai_core.errors import (
    AppendOnlyError,
    CertificationRequiredError,
    ConflictError,
    ForbiddenError,
    HaiError,
    ImmutableFieldError,
    IntegrityViolationError,
    InvalidTransitionError,
)

_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


class Database:
    def __init__(self, url: str, *, enforce_roles: bool = False, allowed_roles: frozenset[str] = frozenset()) -> None:
        self.url = url
        self.engine: Engine = create_engine(_sqlalchemy_url(url), pool_pre_ping=True, pool_size=5, max_overflow=10)
        self.enforce_roles = enforce_roles
        self.allowed_roles = allowed_roles

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def transaction(self, actor: str, role: str | None = None) -> Iterator[Connection]:
        """A transaction acting as ``actor``, optionally under ``role`` (when enforced)."""
        if role is not None and (not _ROLE_RE.match(role) or (self.allowed_roles and role not in self.allowed_roles)):
            raise ValueError(f"unknown database role {role!r}")
        try:
            with self.engine.begin() as conn:
                conn.execute(text("SELECT set_config('hai.actor', :actor, true)"), {"actor": actor})
                if self.enforce_roles and role:
                    conn.execute(text(f"SET LOCAL ROLE {role}"))
                yield conn
        except (IntegrityError, ProgrammingError, DBAPIError) as exc:
            raise translate_db_error(exc) from exc

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            yield conn

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except DBAPIError:
            return False


def translate_db_error(exc: BaseException) -> HaiError | BaseException:
    """Map driver errors from generated triggers and constraints to typed errors."""
    message = str(getattr(exc, "orig", exc))
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    if "HAI_APPEND_ONLY" in message:
        return AppendOnlyError(_first_line(message), details={"sqlstate": sqlstate})
    if "HAI_IMMUTABLE" in message:
        return ImmutableFieldError(_first_line(message), details={"sqlstate": sqlstate})
    if "HAI_TRANSITION" in message:
        return InvalidTransitionError(_first_line(message), details={"sqlstate": sqlstate})
    if "HAI_CERTIFICATION" in message:
        return CertificationRequiredError(_first_line(message), details={"sqlstate": sqlstate})
    if sqlstate == "42501" or "permission denied" in message:
        return ForbiddenError(_first_line(message), details={"sqlstate": sqlstate})
    if isinstance(exc, IntegrityError):
        if sqlstate == "23505" or "duplicate key" in message:
            return ConflictError(_first_line(message), details={"sqlstate": sqlstate})
        constraint = _constraint_name(message)
        return IntegrityViolationError(_first_line(message), details={"sqlstate": sqlstate, "constraint": constraint})
    return exc


def _first_line(message: str) -> str:
    return message.strip().splitlines()[0] if message.strip() else "database error"


def _constraint_name(message: str) -> str | None:
    m = re.search(r'constraint "([^"]+)"', message)
    return m.group(1) if m else None
