"""Account building blocks that need no database: passwords, roles, scopes, principals."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from hai_core.accounts import (
    ORGANIZATION_ROLES,
    PLATFORM_ROLES,
    ROLES,
    Account,
    User,
    check_password_policy,
    effective_scopes,
    hash_password,
    normalize_email,
    normalize_industries,
    principal_for,
    roles_catalog,
    verify_password,
)
from hai_core.auth import Scope
from hai_core.errors import ValidationFailedError
from hai_core.visibility import restriction


def test_passwords_hash_with_a_fresh_salt_and_verify() -> None:
    first = hash_password("correct horse battery")
    second = hash_password("correct horse battery")
    assert first != second and first.startswith("scrypt$14$8$1$")
    assert verify_password("correct horse battery", first)
    assert verify_password("correct horse battery", second)
    assert not verify_password("wrong", first)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


def test_password_policy_rejects_short_common_and_email_passwords() -> None:
    with pytest.raises(ValidationFailedError):
        check_password_policy("short")
    with pytest.raises(ValidationFailedError):
        check_password_policy("password123")
    with pytest.raises(ValidationFailedError):
        check_password_policy("owner@acme.example", email="owner@acme.example")
    check_password_policy("a-long-enough-passphrase", email="owner@acme.example")


def test_roles_split_between_platform_and_organization_accounts() -> None:
    assert {"owner", "admin", "reviewer", "analyst", "viewer"} == PLATFORM_ROLES
    assert {"org_admin", "org_member"} == ORGANIZATION_ROLES
    assert ROLES["owner"].is_admin and ROLES["admin"].is_admin and not ROLES["reviewer"].is_admin
    assert ROLES["reviewer"].kind == "reviewer" and Scope.CERTIFICATION_SIGN in ROLES["reviewer"].scopes
    # organization roles can never review, sign or administer
    for role in ORGANIZATION_ROLES:
        assert not ROLES[role].scopes & {Scope.REVIEWS_WRITE, Scope.CERTIFICATION_SIGN, Scope.ADMIN}
    catalog = roles_catalog()
    assert {r["code"] for r in catalog["roles"]} == set(ROLES)
    assert {s["code"] for s in catalog["scopes"]} == set(Scope.ALL)


def test_scopes_can_be_narrowed_but_never_widened() -> None:
    assert effective_scopes("analyst", None) == ROLES["analyst"].scopes
    narrowed = effective_scopes("analyst", [Scope.ASSESSMENTS_READ])
    assert narrowed == {Scope.ASSESSMENTS_READ, Scope.ONTOLOGY_READ}
    with pytest.raises(ValidationFailedError):
        effective_scopes("analyst", [Scope.CERTIFICATION_SIGN])
    with pytest.raises(ValidationFailedError):
        effective_scopes("viewer", ["nope"])
    with pytest.raises(ValidationFailedError):
        effective_scopes("chief", None)
    # administrators keep everything whatever the request says
    assert effective_scopes("admin", [Scope.ASSESSMENTS_READ]) == Scope.ALL


def test_normalization_of_emails_and_industries() -> None:
    assert normalize_email("  Owner@Acme.Example ") == "owner@acme.example"
    with pytest.raises(ValidationFailedError):
        normalize_email("not an email")
    assert normalize_industries([" Software ", "technology", "Health  Care", "Financial Services", ""]) == [
        "technology",
        "healthcare",
        "financial_services",
    ]
    with pytest.raises(ValidationFailedError):
        normalize_industries(["Astrology"])


def _user(role: str, account: Account, industries: list[str] | None = None) -> User:
    return User(
        uuid4(),
        account.id,
        "u@acme.example",
        "User",
        role,
        sorted(ROLES[role].scopes),
        industries or [],
        "active",
        datetime.now(UTC),
        None,
        None,
    )


def test_principals_carry_account_restrictions() -> None:
    org_id = uuid4()
    org_account = Account(uuid4(), "organization", "Acme", org_id, "acme.example", datetime.now(UTC))
    platform = Account(uuid4(), "platform", "Humaital", None, "humaital.com", datetime.now(UTC))
    member = principal_for(_user("org_member", org_account), org_account)
    assert member.kind == "user" and member.org_ids == {str(org_id)} and member.is_restricted
    assert not member.is_reviewer and not member.manages_team
    org_admin = principal_for(_user("org_admin", org_account), org_account)
    assert org_admin.manages_team and not org_admin.is_platform_admin
    analyst = principal_for(_user("analyst", platform, ["software"]), platform)
    assert analyst.industries == {"software"} and analyst.is_restricted and not analyst.org_ids
    reviewer = principal_for(_user("reviewer", platform), platform)
    assert reviewer.kind == "reviewer" and reviewer.is_reviewer and not reviewer.is_restricted
    owner = principal_for(_user("owner", platform), platform)
    assert owner.kind == "admin" and owner.is_platform_admin and owner.manages_team
    clause, params = restriction(member)
    assert "a.org_id = ANY" in clause and params["vis_orgs"] == [org_id]
    clause, params = restriction(analyst)
    assert "industry_code" in clause and params["vis_industries"] == ["software"]
    assert restriction(owner) == ("TRUE", {})
