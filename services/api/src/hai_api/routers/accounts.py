"""Console accounts: sign-in, registration by invitation, first-run setup, profile, team
management (users, invitations, access requests) and API keys owned by an account."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from hai_api.auth import Admin, Anyone, TeamManager, require
from hai_api.deps import State
from hai_api.schemas import (
    AccessRequestCreate,
    ApiKeyCreate,
    BootstrapRequest,
    InvitationCreate,
    LoginRequest,
    PasswordChange,
    ProfileUpdate,
    RegisterRequest,
    UserUpdate,
)
from hai_core import accounts
from hai_core.auth import Principal, Scope, create_api_key, list_api_keys, revoke_api_key
from hai_core.db.store import Store
from hai_core.errors import ForbiddenError, NotFoundError, UnauthorizedError, ValidationFailedError

router = APIRouter(prefix="/v1", tags=["accounts"])

Authenticated = Annotated[Principal, Depends(require())]


def _session_ttl(st: State, remember: bool) -> timedelta:
    if remember:
        return timedelta(days=st.settings.session_remember_days)
    return timedelta(minutes=st.settings.session_ttl_minutes)


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _me(principal: Principal, user: accounts.User | None, account: accounts.Account | None) -> dict[str, Any]:
    """Who is signed in, what they may do, and (for console users) their profile and account."""
    return {
        "principal": {
            "kind": principal.kind,
            "id": principal.id,
            "name": principal.name,
            "actor": principal.actor,
            "scopes": sorted(principal.scopes | ({Scope.ADMIN} if principal.is_platform_admin else set())),
            "is_reviewer": principal.is_reviewer,
            "is_platform_admin": principal.is_platform_admin,
            "manages_team": principal.manages_team,
            "restricted_to_organizations": sorted(principal.org_ids),
            "restricted_to_industries": sorted(principal.industries),
        },
        "user": user.as_dict() if user else None,
        "account": account.as_dict() if account else None,
        "session_id": principal.session_id,
        "roles": accounts.roles_catalog(),
    }


def _login_response(
    token: str, session: accounts.Session, user: accounts.User, account: accounts.Account
) -> dict[str, Any]:
    principal = accounts.principal_for(user, account, session.id)
    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": session.expires_at.isoformat(),
        "me": _me(principal, user, account),
    }


def _record(
    store: Store, action: str, subject_id: UUID | None, *, reason: str, after: dict[str, Any] | None = None
) -> None:
    store.record_action(action, "Principal", subject_id, reason=reason, after=after or {})


def _current_user(st: State, principal: Principal) -> tuple[accounts.User, accounts.Account]:
    if principal.session_id is None:
        raise ForbiddenError("this action needs a console sign-in, not an API key or minted token")
    with st.read(principal) as (conn, _):
        user = accounts.get_user(conn, principal.id)
        account = accounts.get_account(conn, principal.account_id) if principal.account_id else None
    if user is None or account is None:
        raise NotFoundError("user not found")
    return user, account


# ------------------------------------------------------------------ sign in


@router.get("/auth/status", summary="Whether the platform has an owner yet (public)")
def auth_status(st: State) -> dict[str, Any]:
    with st.db.connect() as conn:
        bootstrapped = accounts.is_bootstrapped(conn)
        demo = accounts.demo_user_available(conn, is_production=st.settings.is_production)
    return {
        "bootstrapped": bootstrapped,
        "signup": "invitation",
        "platform_name": "Humaital",
        # Development only: the seeded demo owner, so the sign-in page can offer it in one click.
        "demo_account": {"email": accounts.DEMO_USER_EMAIL, "password": accounts.DEMO_USER_PASSWORD} if demo else None,
    }


@router.post("/auth/bootstrap", status_code=status.HTTP_201_CREATED, summary="Create the first platform owner")
def bootstrap(body: BootstrapRequest, st: State, request: Request) -> dict[str, Any]:
    with st.db.transaction("bootstrap", "hai_api") as conn:
        user = accounts.bootstrap_owner(
            conn,
            email=body.email,
            name=body.name,
            password=body.password,
            platform_name=body.platform_name,
            created_by="bootstrap",
        )
        token, session, user, account = accounts.login(
            conn,
            email=user.email,
            password=body.password,
            secret=st.settings.jwt_secret.get_secret_value(),
            issuer=st.settings.jwt_issuer,
            ttl=_session_ttl(st, False),
            user_agent=_user_agent(request),
        ).unwrap()
        Store(conn, actor=f"user:{user.id}", manifest=st.manifest).record_action(
            "platform_bootstrapped", "Principal", user.id, reason="first owner created", after={"email": user.email}
        )
    return _login_response(token, session, user, account)


@router.post("/auth/login", summary="Sign in with email and password")
def login(body: LoginRequest, st: State, request: Request) -> dict[str, Any]:
    # The demo owner is a development credential; production refuses it even if the row was carried over.
    if st.settings.is_production and accounts.is_demo_user_email(body.email):
        raise UnauthorizedError("invalid email or password")
    with st.db.transaction("login", "hai_api") as conn:
        outcome = accounts.login(
            conn,
            email=body.email,
            password=body.password,
            secret=st.settings.jwt_secret.get_secret_value(),
            issuer=st.settings.jwt_issuer,
            ttl=_session_ttl(st, body.remember_me),
            user_agent=_user_agent(request),
            max_failures=st.settings.login_max_failures,
            lockout=timedelta(minutes=st.settings.login_lockout_minutes),
        )
    # Outside the transaction: a failed attempt and its lockout are committed before the refusal.
    token, session, user, account = outcome.unwrap()
    return _login_response(token, session, user, account)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out this session or every session")
def logout(st: State, principal: Authenticated, everywhere: bool = False) -> Response:
    if principal.session_id is not None:
        with st.tx(principal, "hai_api") as (conn, _):
            if everywhere:
                accounts.revoke_sessions(conn, user_id=principal.id)
            else:
                accounts.revoke_session(conn, principal.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", summary="The signed-in principal, profile, account and permissions")
def me(st: State, principal: Authenticated) -> dict[str, Any]:
    user = account = None
    if principal.session_id is not None:
        with st.read(principal) as (conn, _):
            user = accounts.get_user(conn, principal.id)
            account = accounts.get_account(conn, principal.account_id) if principal.account_id else None
    return _me(principal, user, account)


@router.patch("/auth/me", summary="Update your profile")
def update_me(body: ProfileUpdate, st: State, principal: Authenticated) -> dict[str, Any]:
    _current_user(st, principal)
    with st.tx(principal, "hai_api") as (conn, _):
        user = accounts.update_profile(conn, user_id=principal.id, name=body.name)
        account = accounts.get_account(conn, user.account_id)
    return _me(
        accounts.principal_for(user, cast(accounts.Account, account), UUID(cast(str, principal.session_id))),
        user,
        account,
    )


@router.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change your password")
def change_password(body: PasswordChange, st: State, principal: Authenticated) -> Response:
    user, _ = _current_user(st, principal)
    with st.tx(principal, "hai_api") as (conn, store):
        accounts.change_password(
            conn, user=user, current=body.current_password, new=body.new_password, keep_session=principal.session_id
        )
        _record(store, "password_changed", user.id, reason="password changed by the user")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/sessions", summary="Your active sessions")
def my_sessions(st: State, principal: Authenticated) -> dict[str, Any]:
    _current_user(st, principal)
    with st.read(principal) as (conn, _):
        rows = accounts.list_sessions(conn, user_id=principal.id)
    items = [{**s.as_dict(), "current": str(s.id) == principal.session_id} for s in rows]
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}


# ------------------------------------------------------- invitations (public)


@router.get("/auth/invitations/{token}", summary="Look up an invitation or password reset by its token (public)")
def invitation_by_token(token: str, st: State) -> dict[str, Any]:
    with st.db.connect() as conn:
        invitation, account = accounts.find_invitation(conn, st.settings.api_key_pepper.get_secret_value(), token)
    return {**invitation.as_dict(), "account": account.as_dict()}


@router.post("/auth/register", status_code=status.HTTP_201_CREATED, summary="Accept an invitation or reset a password")
def register(body: RegisterRequest, st: State, request: Request) -> dict[str, Any]:
    with st.db.transaction("register", "hai_api") as conn:
        token, session, user, account = accounts.accept_invitation(
            conn,
            st.settings.api_key_pepper.get_secret_value(),
            token=body.token,
            name=body.name,
            password=body.password,
            secret=st.settings.jwt_secret.get_secret_value(),
            issuer=st.settings.jwt_issuer,
            ttl=_session_ttl(st, False),
            user_agent=_user_agent(request),
        )
        Store(conn, actor=f"user:{user.id}", manifest=st.manifest).record_action(
            "invitation_accepted", "Principal", user.id, reason="user registered", after={"role": user.role}
        )
    return _login_response(token, session, user, account)


@router.post("/auth/access-requests", status_code=status.HTTP_201_CREATED, summary="Ask for access (public)")
def request_access(body: AccessRequestCreate, st: State) -> dict[str, Any]:
    with st.db.transaction("access-request", "hai_api") as conn:
        req = accounts.create_access_request(
            conn,
            email=body.email,
            name=body.name,
            organization_name=body.organization_name,
            website=body.website,
            message=body.message,
        )
    return {"id": str(req.id), "status": req.status, "created_at": req.created_at.isoformat()}


# ----------------------------------------------------------------------- team


@router.get("/team/roles", summary="Roles and permissions the console can assign")
def team_roles(principal: Authenticated) -> dict[str, Any]:
    catalog = accounts.roles_catalog()
    if not principal.is_platform_admin:
        catalog["roles"] = [r for r in catalog["roles"] if r["account_kind"] == "organization"]
    return catalog


@router.get("/team/users", summary="Users you manage")
def team_users(st: State, principal: TeamManager) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        rows = accounts.list_users(conn, account_id=None if principal.is_platform_admin else principal.account_id)
    items = [{**u.as_dict(), "account": a.as_dict()} for u, a in rows]
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}


@router.patch("/team/users/{user_id}", summary="Change a user's name, role, permissions, industries or status")
def team_update_user(user_id: UUID, update: UserUpdate, st: State, principal: TeamManager) -> dict[str, Any]:
    with st.tx(principal, "hai_api") as (conn, store):
        user = accounts.update_user(
            conn,
            actor=principal,
            user_id=user_id,
            name=update.name,
            role=update.role,
            scopes=update.scopes,
            industries=update.industries,
            status=cast(Literal["active", "disabled"] | None, update.status),
        )
        _record(
            store,
            "user_updated",
            user.id,
            reason=f"user {user.email} updated by {principal.actor}",
            after=update.model_dump(exclude_none=True),
        )
        account = accounts.get_account(conn, user.account_id)
    return {**user.as_dict(), "account": account.as_dict() if account else None}


@router.post("/team/users/{user_id}/reset-link", summary="Create a one-time password reset link")
def team_reset_link(user_id: UUID, st: State, principal: Authenticated) -> dict[str, Any]:
    if str(user_id) != principal.id and not principal.manages_team:
        raise ForbiddenError("this action needs a platform administrator or an organization admin")
    with st.tx(principal, "hai_api") as (conn, store):
        token, invitation = accounts.create_password_reset(
            conn,
            st.settings.api_key_pepper.get_secret_value(),
            actor=principal,
            user_id=user_id,
            ttl=timedelta(hours=st.settings.password_reset_ttl_hours),
        )
        _record(store, "password_reset_issued", user_id, reason=f"reset link issued by {principal.actor}")
    return _with_link(st, token, invitation)


def _with_link(st: State, token: str, invitation: accounts.Invitation) -> dict[str, Any]:
    path = f"/signup?token={token}"
    return {
        **invitation.as_dict(),
        "token": token,
        "invite_path": path,
        "invite_url": st.settings.console_base_url.rstrip("/") + path,
    }


@router.get("/team/invitations", summary="Pending invitations you manage")
def team_invitations(
    st: State, principal: TeamManager, pending: bool = Query(default=True, description="only pending ones")
) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        rows = accounts.list_invitations(
            conn, account_id=None if principal.is_platform_admin else principal.account_id, pending_only=pending
        )
    items = [{**i.as_dict(), "account": a.as_dict()} for i, a in rows]
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}


@router.post("/team/invitations", status_code=status.HTTP_201_CREATED, summary="Invite a user (link shown once)")
def team_invite(body: InvitationCreate, st: State, principal: TeamManager) -> dict[str, Any]:
    with st.tx(principal, "hai_api") as (conn, store):
        token, invitation, account, domain_match = accounts.create_invitation(
            conn,
            st.settings.api_key_pepper.get_secret_value(),
            actor=principal,
            email=body.email,
            role=body.role,
            org_id=body.org_id,
            industries=body.industries,
            scopes=body.scopes,
            message=body.message,
            ttl=timedelta(hours=st.settings.invitation_ttl_hours),
        )
        _record(
            store,
            "invitation_created",
            invitation.id,
            reason=f"{body.role} invited by {principal.actor}",
            after={"email": invitation.email, "role": invitation.role, "account": str(account.id)},
        )
    return {**_with_link(st, token, invitation), "account": account.as_dict(), "domain_match": domain_match}


@router.delete(
    "/team/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an invitation"
)
def team_revoke_invitation(invitation_id: UUID, st: State, principal: TeamManager) -> Response:
    with st.tx(principal, "hai_api") as (conn, store):
        ok = accounts.revoke_invitation(conn, actor=principal, invitation_id=invitation_id)
        if not ok:
            raise NotFoundError("no pending invitation with that id")
        _record(store, "invitation_revoked", invitation_id, reason=f"revoked by {principal.actor}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/team/accounts", summary="The platform account and every participating organization account")
def team_accounts(st: State, principal: Admin) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        items = accounts.list_accounts(conn)
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}


@router.get("/team/access-requests", summary="Access requests from people without an invitation")
def team_access_requests(
    st: State, principal: Admin, status_filter: str | None = Query(default="pending", alias="status")
) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        rows = accounts.list_access_requests(conn, status=None if status_filter == "all" else status_filter)
    items = [r.as_dict() for r in rows]
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}


@router.post("/team/access-requests/{request_id}/dismiss", summary="Dismiss an access request")
def team_dismiss_request(request_id: UUID, st: State, principal: Admin) -> dict[str, Any]:
    with st.tx(principal, "hai_api") as (conn, store):
        req = accounts.dismiss_access_request(conn, actor=principal, request_id=request_id)
        _record(store, "access_request_dismissed", req.id, reason=f"dismissed by {principal.actor}")
    return req.as_dict()


# ------------------------------------------------------------------- API keys


def _key_out(rec: Any) -> dict[str, Any]:
    return {
        "id": str(rec.id),
        "key_id": rec.key_id,
        "name": rec.name,
        "scopes": list(rec.scopes),
        "created_by": rec.created_by,
        "account_id": str(rec.account_id) if rec.account_id else None,
        "created_at": rec.created_at.isoformat(),
        "revoked_at": rec.revoked_at.isoformat() if rec.revoked_at else None,
        "last_used_at": rec.last_used_at.isoformat() if rec.last_used_at else None,
        "status": "revoked" if rec.revoked_at else "active",
    }


@router.get("/api-keys", summary="API keys of your account (platform administrators see every key)")
def api_keys(st: State, principal: Authenticated) -> dict[str, Any]:
    with st.read(principal) as (conn, _):
        if principal.is_platform_admin:
            rows = list_api_keys(conn)
        elif principal.manages_team:
            rows = list_api_keys(conn, account_id=principal.account_id)
        else:
            rows = list_api_keys(conn, account_id=principal.account_id, created_by=principal.actor)
    items = [_key_out(r) for r in rows]
    return {"items": items, "total": len(items), "limit": len(items) or 1, "offset": 0}


@router.post("/api-keys", status_code=status.HTTP_201_CREATED, summary="Create an API key (plaintext shown once)")
def create_key(body: ApiKeyCreate, st: State, principal: Authenticated) -> dict[str, Any]:
    if principal.kind == "api_key":
        raise ForbiddenError("sign in to the console to create API keys")
    requested = frozenset(body.scopes) if body.scopes is not None else principal.scopes - {Scope.ADMIN}
    unknown = sorted(requested - Scope.ALL)
    if unknown:
        raise ValidationFailedError(f"unknown scopes {unknown}", details={"fields": {"scopes": "unknown scope"}})
    if not principal.is_platform_admin:
        beyond = sorted(requested - principal.scopes)
        if beyond:
            raise ForbiddenError(f"you cannot grant scopes you do not hold: {beyond}", details={"beyond": beyond})
    if Scope.ADMIN in requested and principal.account_role != "owner":
        raise ForbiddenError("only a platform owner can create an admin API key")
    with st.tx(principal, "hai_admin") as (conn, store):
        plaintext, rec = create_api_key(
            conn,
            st.settings.api_key_pepper.get_secret_value(),
            name=body.name,
            scopes=requested,
            created_by=principal.actor,
            account_id=principal.account_id,
        )
        _record(
            store,
            "api_key_created",
            rec.id,
            reason=f"API key {rec.name} created by {principal.actor}",
            after={"key_id": rec.key_id, "scopes": sorted(requested)},
        )
    return {**_key_out(rec), "api_key": plaintext}


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an API key")
def revoke_key(key_id: str, st: State, principal: Authenticated) -> Response:
    with st.tx(principal, "hai_admin") as (conn, store):
        if principal.is_platform_admin:
            ok = revoke_api_key(conn, key_id)
        elif principal.manages_team:
            ok = revoke_api_key(conn, key_id, account_id=principal.account_id)
        else:
            mine = {k.key_id for k in list_api_keys(conn, account_id=principal.account_id, created_by=principal.actor)}
            ok = key_id in mine and revoke_api_key(conn, key_id, account_id=principal.account_id)
        if not ok:
            raise NotFoundError("no active API key with that id")
        _record(store, "api_key_revoked", None, reason=f"API key {key_id} revoked by {principal.actor}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_ = Anyone
