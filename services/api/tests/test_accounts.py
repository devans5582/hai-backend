"""Console accounts against Postgres: first-run setup, sign-in, invitations, organization
visibility, team rules, sessions and account-owned API keys."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hai_api.deps import AppState
from hai_api.main import create_app
from hai_core.auth import Scope
from hai_core.db.engine import Database
from hai_core.settings import Settings
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration

OWNER = {"email": "owner@humaital.example", "name": "Olu Owner", "password": "owner-passphrase-2026"}
PASSWORD = "a-perfectly-fine-passphrase"


@pytest.fixture
def client(clean_db: Database, settings: Settings, manifest: Manifest) -> Iterator[TestClient]:
    app = create_app(settings=settings, manifest=manifest, state=AppState.build(settings, manifest))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def bootstrap(client: TestClient) -> dict[str, Any]:
    r = client.post("/v1/auth/bootstrap", json=OWNER)
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def login(client: TestClient, email: str, password: str, **extra: Any) -> dict[str, Any]:
    r = client.post("/v1/auth/login", json={"email": email, "password": password, **extra})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def invite(client: TestClient, token: str, **body: Any) -> dict[str, Any]:
    r = client.post("/v1/team/invitations", json=body, headers=bearer(token))
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out


def register(client: TestClient, invite_token: str, name: str = "New User", password: str = PASSWORD) -> dict[str, Any]:
    r = client.post("/v1/auth/register", json={"token": invite_token, "name": name, "password": password})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def start_assessment(client: TestClient, token: str, name: str, website: str, industry: str) -> dict[str, Any]:
    r = client.post(
        "/v1/assessments",
        json={"organization_name": name, "website": website, "stage": "growth", "size": "mid", "industry": industry},
        headers=bearer(token),
    )
    assert r.status_code == 202, r.text
    body: dict[str, Any] = r.json()
    return body


def test_first_run_bootstrap_then_sign_in_and_profile(client: TestClient) -> None:
    assert client.get("/v1/auth/status").json()["bootstrapped"] is False
    weak = client.post("/v1/auth/bootstrap", json={**OWNER, "password": "short"})
    assert weak.status_code == 422 and "password" in weak.json()["error"]["details"]["fields"]
    first = bootstrap(client)
    assert first["me"]["user"]["role"] == "owner" and first["me"]["account"]["kind"] == "platform"
    assert first["me"]["principal"]["is_platform_admin"] is True
    assert client.get("/v1/auth/status").json()["bootstrapped"] is True
    # bootstrap is a one-time door
    again = client.post("/v1/auth/bootstrap", json={**OWNER, "email": "second@humaital.example"})
    assert again.status_code == 409
    # password sign-in, case-insensitive email, wrong password refused without saying which part failed
    bad = client.post("/v1/auth/login", json={"email": OWNER["email"], "password": "nope-nope-nope"})
    assert bad.status_code == 401 and bad.json()["error"]["message"] == "invalid email or password"
    unknown = client.post("/v1/auth/login", json={"email": "nobody@humaital.example", "password": "nope-nope-nope"})
    assert unknown.status_code == 401 and unknown.json()["error"]["message"] == "invalid email or password"
    session = login(client, OWNER["email"].upper(), OWNER["password"])
    token = session["token"]
    me = client.get("/v1/auth/me", headers=bearer(token)).json()
    assert me["user"]["email"] == OWNER["email"] and me["session_id"] == session["me"]["session_id"]
    assert Scope.ADMIN in me["principal"]["scopes"]
    # the owner is a platform admin: full console access
    assert client.get("/v1/assessments", headers=bearer(token)).status_code == 200
    assert client.get("/v1/audit/verify", headers=bearer(token)).status_code == 200
    # profile and password
    renamed = client.patch("/v1/auth/me", json={"name": "Olu O."}, headers=bearer(token))
    assert renamed.status_code == 200 and renamed.json()["user"]["name"] == "Olu O."
    wrong = client.post(
        "/v1/auth/password",
        json={"current_password": "wrong", "new_password": "another-long-passphrase"},
        headers=bearer(token),
    )
    assert wrong.status_code == 401
    other = login(client, OWNER["email"], OWNER["password"])["token"]
    changed = client.post(
        "/v1/auth/password",
        json={"current_password": OWNER["password"], "new_password": "another-long-passphrase"},
        headers=bearer(token),
    )
    assert changed.status_code == 204
    # changing the password signs out every other session but keeps this one
    assert client.get("/v1/auth/me", headers=bearer(other)).status_code == 401
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 200
    assert client.get("/v1/auth/sessions", headers=bearer(token)).json()["total"] == 1
    assert (
        client.post("/v1/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}).status_code == 401
    )
    assert login(client, OWNER["email"], "another-long-passphrase")["me"]["user"]["name"] == "Olu O."
    # sign out revokes the session even though the JWT has not expired
    assert client.post("/v1/auth/logout", headers=bearer(token)).status_code == 204
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401


def test_login_lockout_after_repeated_failures(client: TestClient, settings: Settings) -> None:
    bootstrap(client)
    for _ in range(settings.login_max_failures):
        assert (
            client.post("/v1/auth/login", json={"email": OWNER["email"], "password": "wrong-wrong"}).status_code == 401
        )
    locked = client.post("/v1/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]})
    assert locked.status_code == 401 and "locked_until" in locked.json()["error"]["details"]


def test_invited_organization_users_see_only_their_reports(client: TestClient) -> None:
    owner = bootstrap(client)["token"]
    acme = start_assessment(client, owner, "Acme Corp", "https://www.acme.example", "Technology")
    other = start_assessment(client, owner, "Globex", "https://globex.example", "Financial Services")
    # an organization role needs an organization
    missing = client.post(
        "/v1/team/invitations", json={"email": "cfo@acme.example", "role": "org_admin"}, headers=bearer(owner)
    )
    assert missing.status_code == 422
    invitation = invite(client, owner, email="cfo@acme.example", role="org_admin", org_id=acme["org_id"])
    assert invitation["account"]["kind"] == "organization" and invitation["domain_match"] is True
    assert invitation["token"].startswith("hai_inv_") and invitation["invite_path"].startswith("/signup?token=")
    # the public lookup shows what is being accepted, without the token being guessable
    peek = client.get(f"/v1/auth/invitations/{invitation['token']}").json()
    assert peek["email"] == "cfo@acme.example" and peek["account"]["name"] == "Acme Corp"
    assert client.get("/v1/auth/invitations/hai_inv_nope").status_code == 404
    registered = register(client, invitation["token"], name="Chi Finance")
    org_admin = registered["token"]
    me = registered["me"]
    assert me["user"]["role"] == "org_admin" and me["account"]["org_id"] == acme["org_id"]
    assert me["principal"]["restricted_to_organizations"] == [acme["org_id"]]
    # the invitation is spent
    assert client.get(f"/v1/auth/invitations/{invitation['token']}").status_code == 409
    # visibility: only Acme's assessments and organization; Globex answers not found
    listing = client.get("/v1/assessments", headers=bearer(org_admin)).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == acme["id"]
    assert client.get(f"/v1/assessments/{acme['id']}", headers=bearer(org_admin)).status_code == 200
    assert client.get(f"/v1/assessments/{other['id']}", headers=bearer(org_admin)).status_code == 404
    assert client.get(f"/v1/assessments/{other['id']}/report", headers=bearer(org_admin)).status_code == 404
    assert client.get(f"/v1/assessments/{other['id']}/trace", headers=bearer(org_admin)).status_code == 404
    orgs = client.get("/v1/organizations", headers=bearer(org_admin)).json()
    assert orgs["total"] == 1 and orgs["items"][0]["id"] == acme["org_id"]
    assert client.get(f"/v1/organizations/{other['org_id']}", headers=bearer(org_admin)).status_code == 404
    assert client.get(f"/v1/organizations/{other['org_id']}/assessments", headers=bearer(org_admin)).status_code == 404
    assert client.get(f"/v1/organizations/{acme['org_id']}/assessments", headers=bearer(org_admin)).json()["total"] == 1
    # organization accounts cannot start assessments, review, sign or administer
    assert (
        client.post(
            "/v1/assessments",
            json={
                "organization_name": "Acme Corp",
                "website": "acme.example",
                "stage": "growth",
                "size": "mid",
                "industry": "Technology",
            },
            headers=bearer(org_admin),
        ).status_code
        == 403
    )
    assert client.get("/v1/team/accounts", headers=bearer(org_admin)).status_code == 403
    assert client.get("/v1/audit/verify", headers=bearer(org_admin)).status_code == 403
    # an organization admin invites colleagues into the same account with organization roles only
    bad_role = client.post(
        "/v1/team/invitations", json={"email": "x@acme.example", "role": "reviewer"}, headers=bearer(org_admin)
    )
    assert bad_role.status_code == 403
    colleague = invite(client, org_admin, email="analyst@acme.example", role="org_member")
    assert colleague["account"]["id"] == me["account"]["id"]
    member = register(client, colleague["token"], name="Ade Member")["token"]
    assert client.get("/v1/assessments", headers=bearer(member)).json()["total"] == 1
    assert client.get("/v1/team/users", headers=bearer(member)).status_code == 403
    team = client.get("/v1/team/users", headers=bearer(org_admin)).json()
    assert {u["email"] for u in team["items"]} == {"cfo@acme.example", "analyst@acme.example"}
    # the platform owner sees every account and user
    everyone = client.get("/v1/team/users", headers=bearer(owner)).json()
    assert everyone["total"] == 3
    accounts = client.get("/v1/team/accounts", headers=bearer(owner)).json()["items"]
    assert [a["kind"] for a in accounts] == ["platform", "organization"] and accounts[1]["active_users"] == 2
    # an organization-created API key is bound to the organization
    key = client.post("/v1/api-keys", json={"name": "acme-integration"}, headers=bearer(org_admin))
    assert key.status_code == 201 and Scope.ASSESSMENTS_WRITE not in key.json()["scopes"]
    plaintext = key.json()["api_key"]
    via_key = client.get("/v1/assessments", headers={"X-API-Key": plaintext}).json()
    assert via_key["total"] == 1 and via_key["items"][0]["id"] == acme["id"]
    assert client.get(f"/v1/assessments/{other['id']}", headers={"X-API-Key": plaintext}).status_code == 404
    # members see only their own keys; the org admin sees the account's keys; the owner sees all
    assert client.get("/v1/api-keys", headers=bearer(member)).json()["total"] == 0
    assert client.get("/v1/api-keys", headers=bearer(org_admin)).json()["total"] == 1
    assert client.get("/v1/api-keys", headers=bearer(owner)).json()["total"] == 1
    assert client.delete(f"/v1/api-keys/{key.json()['key_id']}", headers=bearer(member)).status_code == 404
    assert client.delete(f"/v1/api-keys/{key.json()['key_id']}", headers=bearer(org_admin)).status_code == 204
    assert client.get("/v1/assessments", headers={"X-API-Key": plaintext}).status_code == 401


def test_platform_roles_industries_and_team_rules(client: TestClient, settings: Settings) -> None:
    owner = bootstrap(client)["token"]
    software = start_assessment(client, owner, "Acme Corp", "https://www.acme.example", "Technology")
    finance = start_assessment(client, owner, "Globex", "https://globex.example", "Financial Services")
    # a reviewer limited to the software industry
    rev = invite(
        client, owner, email="rev@humaital.example", role="reviewer", industries=["Software"]
    )  # alias of technology
    assert rev["industries"] == ["technology"] and rev["account"]["kind"] == "platform"
    reviewer = register(client, rev["token"], name="Rae Reviewer")
    assert reviewer["me"]["principal"]["is_reviewer"] is True
    assert reviewer["me"]["principal"]["restricted_to_industries"] == ["technology"]
    rt = reviewer["token"]
    seen = client.get("/v1/assessments", headers=bearer(rt)).json()
    assert [a["id"] for a in seen["items"]] == [software["id"]]
    assert client.get(f"/v1/assessments/{finance['id']}", headers=bearer(rt)).status_code == 404
    assert client.get("/v1/organizations", headers=bearer(rt)).json()["total"] == 1
    assert client.get("/v1/reviews/tasks", headers=bearer(rt)).status_code == 200
    # the reviewer session is a JWT with a named subject, so signing is allowed in principle
    refused = client.post(
        f"/v1/assessments/{software['id']}/certification",
        json={"decision": "certified", "reason": "nothing to certify yet"},
        headers=bearer(rt),
    )
    assert refused.status_code == 409  # no result yet, not forbidden
    # an analyst with narrowed permissions cannot start assessments
    narrowed = invite(client, owner, email="viewer@humaital.example", role="analyst", scopes=[Scope.ASSESSMENTS_READ])
    assert sorted(narrowed["scopes"]) == sorted([Scope.ASSESSMENTS_READ, Scope.ONTOLOGY_READ])
    analyst = register(client, narrowed["token"], name="Ana Lyst")["token"]
    assert client.get("/v1/assessments", headers=bearer(analyst)).json()["total"] == 2
    assert (
        client.post(
            "/v1/assessments",
            json={
                "organization_name": "Initech",
                "website": "initech.example",
                "stage": "growth",
                "size": "mid",
                "industry": "Technology",
            },
            headers=bearer(analyst),
        ).status_code
        == 403
    )
    assert client.get("/v1/team/users", headers=bearer(analyst)).status_code == 403
    # scopes beyond the role are refused at invitation time
    too_much = client.post(
        "/v1/team/invitations",
        json={"email": "x@humaital.example", "role": "viewer", "scopes": [Scope.CERTIFICATION_SIGN]},
        headers=bearer(owner),
    )
    assert too_much.status_code == 422
    # team rules: owner cannot change own role; last owner cannot be disabled; admin cannot touch the owner
    users = {u["email"]: u for u in client.get("/v1/team/users", headers=bearer(owner)).json()["items"]}
    owner_id = users[OWNER["email"]]["id"]
    assert client.patch(f"/v1/team/users/{owner_id}", json={"role": "admin"}, headers=bearer(owner)).status_code == 403
    adm = invite(client, owner, email="adm@humaital.example", role="admin")
    admin = register(client, adm["token"], name="Ada Admin")["token"]
    assert (
        client.patch(f"/v1/team/users/{owner_id}", json={"status": "disabled"}, headers=bearer(admin)).status_code
        == 403
    )
    promoted = client.patch(
        f"/v1/team/users/{users['viewer@humaital.example']['id']}", json={"role": "viewer"}, headers=bearer(admin)
    )
    assert promoted.status_code == 200 and promoted.json()["role"] == "viewer"
    # only an owner grants owner
    assert (
        client.patch(
            f"/v1/team/users/{users['rev@humaital.example']['id']}", json={"role": "owner"}, headers=bearer(admin)
        ).status_code
        == 403
    )
    # disabling a user kills their sessions immediately
    disabled = client.patch(
        f"/v1/team/users/{users['rev@humaital.example']['id']}", json={"status": "disabled"}, headers=bearer(owner)
    )
    assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"
    assert client.get("/v1/auth/me", headers=bearer(rt)).status_code == 401
    assert (
        client.post("/v1/auth/login", json={"email": "rev@humaital.example", "password": PASSWORD}).status_code == 401
    )
    # a password reset link lets a user back in and revokes the old sessions
    users = {u["email"]: u for u in client.get("/v1/team/users", headers=bearer(owner)).json()["items"]}
    reset = client.post(f"/v1/team/users/{users['adm@humaital.example']['id']}/reset-link", headers=bearer(owner))
    assert reset.status_code == 200 and reset.json()["kind"] == "password_reset"
    back = client.post("/v1/auth/register", json={"token": reset.json()["token"], "password": "brand-new-passphrase"})
    assert back.status_code == 201 and back.json()["me"]["user"]["email"] == "adm@humaital.example"
    assert client.get("/v1/auth/me", headers=bearer(admin)).status_code == 401
    assert login(client, "adm@humaital.example", "brand-new-passphrase")["me"]["user"]["role"] == "admin"
    # invitations: pending list, revoke, duplicate email
    pending = invite(client, owner, email="later@humaital.example", role="viewer")
    assert client.get("/v1/team/invitations", headers=bearer(owner)).json()["total"] == 1
    assert client.delete(f"/v1/team/invitations/{pending['id']}", headers=bearer(owner)).status_code == 204
    assert client.get(f"/v1/auth/invitations/{pending['token']}").status_code == 409
    duplicate = client.post(
        "/v1/team/invitations", json={"email": OWNER["email"], "role": "viewer"}, headers=bearer(owner)
    )
    assert duplicate.status_code == 409
    # the console's role catalog narrows for organization admins
    assert {r["code"] for r in client.get("/v1/team/roles", headers=bearer(owner)).json()["roles"]} >= {
        "owner",
        "org_admin",
    }
    # the audit chain still verifies after all of this
    assert client.get("/v1/audit/verify", headers=bearer(owner)).json()["ok"] is True
    assert settings.session_ttl_minutes > 0


def test_access_requests_flow_into_invitations(client: TestClient) -> None:
    anonymous = client.post(
        "/v1/auth/access-requests",
        json={"email": "cto@newco.example", "name": "Nia", "organization_name": "Newco", "website": "newco.example"},
    )
    assert anonymous.status_code == 201 and anonymous.json()["status"] == "pending"
    repeat = client.post(
        "/v1/auth/access-requests", json={"email": "CTO@newco.example", "name": "Nia", "organization_name": "Newco"}
    )
    assert repeat.json()["id"] == anonymous.json()["id"]
    assert client.get("/v1/team/access-requests").status_code == 401
    owner = bootstrap(client)["token"]
    requests = client.get("/v1/team/access-requests", headers=bearer(owner)).json()
    assert requests["total"] == 1 and requests["items"][0]["organization_name"] == "Newco"
    # inviting the requester marks the request as invited
    invite(client, owner, email="cto@newco.example", role="viewer")
    assert client.get("/v1/team/access-requests", headers=bearer(owner)).json()["total"] == 0
    history = client.get("/v1/team/access-requests?status=all", headers=bearer(owner)).json()["items"]
    assert history[0]["status"] == "invited"
    second = client.post(
        "/v1/auth/access-requests", json={"email": "someone@else.example", "name": "S", "organization_name": "Else"}
    ).json()
    dismissed = client.post(f"/v1/team/access-requests/{second['id']}/dismiss", headers=bearer(owner))
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"


def test_legacy_credentials_still_work_alongside_accounts(
    client: TestClient, clean_db: Database, settings: Settings
) -> None:
    """Admin-minted reviewer tokens and partner keys keep working; they are not console users."""
    from hai_core.auth import create_api_key, mint_jwt

    with clean_db.transaction("pytest", "hai_admin") as conn:
        plaintext, _ = create_api_key(
            conn,
            settings.api_key_pepper.get_secret_value(),
            name="partner",
            scopes=Scope.PARTNER_DEFAULT,
            created_by="pytest",
        )
    minted = mint_jwt(
        settings.jwt_secret.get_secret_value(),
        subject="rev-1",
        name="Rev",
        role="reviewer",
        scopes=Scope.REVIEWER_DEFAULT,
    )
    key_me = client.get("/v1/auth/me", headers={"X-API-Key": plaintext}).json()
    assert key_me["user"] is None and key_me["principal"]["kind"] == "api_key"
    jwt_me = client.get("/v1/auth/me", headers=bearer(minted)).json()
    assert jwt_me["user"] is None and jwt_me["principal"]["is_reviewer"] is True
    # keys cannot create keys; a minted token has no profile to change
    assert client.post("/v1/api-keys", json={"name": "x"}, headers={"X-API-Key": plaintext}).status_code == 403
    assert client.patch("/v1/auth/me", json={"name": "x"}, headers=bearer(minted)).status_code == 403
    # a legacy key without an account is unrestricted
    with clean_db.engine.connect() as conn:
        assert conn.execute(text("SELECT account_id FROM hai_ops.api_keys WHERE name = 'partner'")).scalar_one() is None


def test_seeded_demo_owner_signs_in_outside_production_only(
    client: TestClient, clean_db: Database, settings: Settings, manifest: Manifest
) -> None:
    from hai_core.accounts import DEMO_USER_EMAIL, DEMO_USER_PASSWORD, seed_demo_user

    # not seeded yet: the sign-in page has nothing to offer
    assert client.get("/v1/auth/status").json()["demo_account"] is None
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert seed_demo_user(conn, is_production=False) == 1
        assert seed_demo_user(conn, is_production=False) == 1  # idempotent: password restored, no duplicate
    status = client.get("/v1/auth/status").json()
    assert status["bootstrapped"] is True
    assert status["demo_account"] == {"email": DEMO_USER_EMAIL, "password": DEMO_USER_PASSWORD}
    session = login(client, DEMO_USER_EMAIL, DEMO_USER_PASSWORD)
    assert session["me"]["user"]["role"] == "owner" and session["me"]["account"]["name"] == "Humaital"
    assert client.get("/v1/team/users", headers=bearer(session["token"])).json()["total"] == 1
    # a disabled demo user is not revived by seeding
    with clean_db.transaction("pytest", "hai_admin") as conn:
        conn.execute(
            text("UPDATE hai_ops.users SET status = 'disabled' WHERE lower(email) = :e"), {"e": DEMO_USER_EMAIL}
        )
        assert seed_demo_user(conn, is_production=False) == 0
    assert client.get("/v1/auth/status").json()["demo_account"] is None
    with clean_db.transaction("pytest", "hai_admin") as conn:
        conn.execute(text("UPDATE hai_ops.users SET status = 'active' WHERE lower(email) = :e"), {"e": DEMO_USER_EMAIL})
    # production: never seeded, never advertised, never signed in, even with the row present
    production = Settings(
        **(
            settings.model_dump()
            | {
                "env": "production",
                "api_key_pepper": "p" * 40,
                "jwt_secret": settings.jwt_secret.get_secret_value().replace("dev-", "prd-"),
                "cert_signing_key": "c" * 40,
                "webhook_signing_key": "w" * 40,
            }
        )
    )
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert seed_demo_user(conn, is_production=True) == 0
    app = create_app(settings=production, manifest=manifest, state=AppState.build(production, manifest))
    with TestClient(app) as prod:
        assert prod.get("/v1/auth/status").json()["demo_account"] is None
        refused = prod.post("/v1/auth/login", json={"email": DEMO_USER_EMAIL, "password": DEMO_USER_PASSWORD})
        assert refused.status_code == 401
