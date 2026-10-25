"""Authentication and per-route scopes.

``X-API-Key`` for partners and services (HMAC-stored keys), ``Authorization:
Bearer <jwt>`` for named reviewers and admins. Public routes accept the
anonymous principal. ``HAI_AUTH_DISABLED`` grants an admin principal in
development only (production refuses the setting).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from hai_core.auth import ANONYMOUS, Principal, Scope, verify_api_key, verify_jwt
from hai_core.errors import ForbiddenError, UnauthorizedError

__all__ = ["Admin", "Anyone", "Principal", "Reviewer", "Scope", "current_principal", "require"]


def current_principal(request: Request) -> Principal:
    state = request.app.state.hai
    settings = state.settings
    api_key = request.headers.get("x-api-key")
    auth = request.headers.get("authorization", "")
    if api_key:
        with state.db.transaction("auth", "hai_api") as conn:
            principal = verify_api_key(conn, settings.api_key_pepper.get_secret_value(), api_key)
        if principal is None:
            raise UnauthorizedError("invalid or revoked API key")
        return principal
    if auth.lower().startswith("bearer "):
        return verify_jwt(settings.jwt_secret.get_secret_value(), auth[7:].strip(), issuer=settings.jwt_issuer)
    if settings.auth_disabled and not settings.is_production:
        return Principal("admin", "dev-admin", "Development admin", frozenset({Scope.ADMIN}))
    return ANONYMOUS


Anyone = Annotated[Principal, Depends(current_principal)]


def require(*scopes: str, reviewer: bool = False) -> Callable[[Principal], Principal]:
    def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if principal.kind == "anonymous":
            raise UnauthorizedError("authentication required")
        if reviewer and not principal.is_reviewer:
            raise ForbiddenError("this action needs a named reviewer (JWT), not an API key")
        missing = [s for s in scopes if not principal.has(s)]
        if missing:
            raise ForbiddenError("missing scope: " + ", ".join(missing), details={"required": list(scopes)})
        return principal

    return dependency


Reviewer = Annotated[Principal, Depends(require(reviewer=True))]
Admin = Annotated[Principal, Depends(require(Scope.ADMIN))]
