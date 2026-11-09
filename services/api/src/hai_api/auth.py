"""Authentication and per-route scopes.

``X-API-Key`` for partners and services (HMAC-stored keys), ``Authorization:
Bearer <jwt>`` for people. A bearer token is either a console session (login
issues it; its ``sid`` claim is checked against the session row on every
request, so a disabled user or a changed role takes effect immediately) or an
admin-minted reviewer or admin token. Public routes accept the anonymous
principal. ``HAI_AUTH_DISABLED`` grants an admin principal in development only
(production refuses the setting).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from hai_core.accounts import verify_session
from hai_core.auth import ANONYMOUS, Principal, Scope, decode_token, verify_api_key, verify_jwt
from hai_core.errors import ForbiddenError, UnauthorizedError

__all__ = ["Admin", "Anyone", "Principal", "Reviewer", "Scope", "TeamManager", "current_principal", "require"]


def current_principal(request: Request) -> Principal:
    state = request.app.state.hai
    settings = state.settings
    api_key = request.headers.get("x-api-key")
    auth = request.headers.get("authorization", "")
    if api_key:
        with state.db.transaction("auth", "hai_api") as conn:
            principal = verify_api_key(
                conn, settings.api_key_pepper.get_secret_value(), api_key, allow_demo=not settings.is_production
            )
        if principal is None:
            raise UnauthorizedError("invalid or revoked API key")
        return principal
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        secret = settings.jwt_secret.get_secret_value()
        claims = decode_token(secret, token, issuer=settings.jwt_issuer)
        if "sid" in claims:
            with state.db.transaction("auth", "hai_api") as conn:
                return verify_session(conn, claims)
        return verify_jwt(secret, token, issuer=settings.jwt_issuer)
    if settings.auth_disabled and not settings.is_production:
        return Principal("admin", "dev-admin", "Development admin", frozenset({Scope.ADMIN}))
    return ANONYMOUS


Anyone = Annotated[Principal, Depends(current_principal)]


def require(*scopes: str, reviewer: bool = False, team: bool = False) -> Callable[[Principal], Principal]:
    def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if principal.kind == "anonymous":
            raise UnauthorizedError("authentication required")
        if reviewer and not principal.is_reviewer:
            raise ForbiddenError("this action needs a named reviewer (JWT), not an API key")
        if team and not principal.manages_team:
            raise ForbiddenError("this action needs a platform administrator or an organization admin")
        missing = [s for s in scopes if not principal.has(s)]
        if missing:
            raise ForbiddenError("missing scope: " + ", ".join(missing), details={"required": list(scopes)})
        return principal

    return dependency


Reviewer = Annotated[Principal, Depends(require(reviewer=True))]
Admin = Annotated[Principal, Depends(require(Scope.ADMIN))]
TeamManager = Annotated[Principal, Depends(require(team=True))]
