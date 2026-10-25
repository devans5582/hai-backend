"""API contract tests against Postgres: auth, envelopes, idempotency, reviews, certification, ontology."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from hai_api.deps import AppState
from hai_api.main import create_app
from hai_core.auth import Scope, create_api_key, mint_jwt
from hai_core.db.engine import Database
from hai_core.settings import Settings
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration


@pytest.fixture
def client(clean_db: Database, settings: Settings, manifest: Manifest) -> Iterator[TestClient]:
    app = create_app(settings=settings, manifest=manifest, state=AppState.build(settings, manifest))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def api_key(clean_db: Database, settings: Settings) -> str:
    with clean_db.transaction("pytest", "hai_admin") as conn:
        plaintext, _ = create_api_key(
            conn,
            settings.api_key_pepper.get_secret_value(),
            name="partner",
            scopes=Scope.PARTNER_DEFAULT,
            created_by="pytest",
        )
    return plaintext


def reviewer_token(settings: Settings, subject: str = "rev-1", role: Literal["reviewer", "admin"] = "reviewer") -> str:
    scopes = Scope.REVIEWER_DEFAULT if role == "reviewer" else Scope.ALL
    return mint_jwt(
        settings.jwt_secret.get_secret_value(),
        subject=subject,
        name=subject,
        role=role,
        scopes=scopes,
        issuer=settings.jwt_issuer,
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


BODY: dict[str, Any] = {
    "organization_name": "Acme Corp",
    "website": "https://www.acme.example",
    "stage": "startup",
    "size": "11-50",
    "industry": "Software",
}


def test_public_endpoints_and_auth(client: TestClient, api_key: str, settings: Settings) -> None:
    assert client.get("/health").status_code == 200
    ready = client.get("/ready").json()
    assert ready["status"] == "ready" and ready["database"]["manifest_hash"] == ready["service"]["manifest_hash"]
    assert client.get("/v1/ontology").status_code == 200
    assert client.get("/v1/certifications/HAI-NOPE/verify").status_code == 404
    unauth = client.get("/v1/assessments")
    assert unauth.status_code == 401 and unauth.json()["error"]["code"] == "unauthorized"
    assert client.get("/v1/assessments", headers={"X-API-Key": "hai_bad.key"}).status_code == 401
    assert client.get("/v1/assessments", headers={"X-API-Key": api_key}).status_code == 200
    assert client.get("/v1/assessments", headers=bearer(reviewer_token(settings))).status_code == 200
    # scopes: a partner key cannot read the audit log or mint tokens
    assert client.get("/v1/audit/verify", headers={"X-API-Key": api_key}).status_code == 403
    assert (
        client.post("/v1/auth/token", json={"subject": "x", "name": "x"}, headers={"X-API-Key": api_key}).status_code
        == 403
    )
    minted = client.post(
        "/v1/auth/token",
        json={"subject": "rev-9", "name": "Nine"},
        headers=bearer(reviewer_token(settings, "adm", "admin")),
    )
    assert minted.status_code == 200 and minted.json()["role"] == "reviewer"
    assert client.get("/v1/reviews/tasks", headers=bearer(minted.json()["token"])).status_code == 200
    assert "X-Request-Id" in client.get("/health").headers


def test_validation_errors_use_the_error_envelope(client: TestClient, api_key: str) -> None:
    r = client.post("/v1/assessments", json={**BODY, "stage": "galactic"}, headers={"X-API-Key": api_key})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_failed" and "stage" in body["details"]["fields"]
    r2 = client.post("/v1/assessments", json={"organization_name": "x"}, headers={"X-API-Key": api_key})
    assert r2.status_code == 422 and "website" in r2.json()["error"]["details"]["fields"]
    r3 = client.post("/v1/assessments", json={**BODY, "unknown": 1}, headers={"X-API-Key": api_key})
    assert r3.status_code == 422
    assert client.get("/v1/assessments/not-a-uuid", headers={"X-API-Key": api_key}).status_code == 422
    missing = client.get("/v1/assessments/00000000-0000-4000-8000-000000000000", headers={"X-API-Key": api_key})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def test_idempotent_start_and_aliases(client: TestClient, api_key: str) -> None:
    headers = {"X-API-Key": api_key, "Idempotency-Key": "k-1"}
    first = client.post("/v1/assessments", json=BODY, headers=headers)
    assert first.status_code == 202 and first.headers["X-Idempotent-Replay"] == "false"
    second = client.post("/v1/assessments", json=BODY, headers=headers)
    assert (
        second.status_code == 202
        and second.json()["id"] == first.json()["id"]
        and second.headers["X-Idempotent-Replay"] == "true"
    )
    a = first.json()
    assert a["lifecycle_state"] == "queued" and a["stage_band"] == "early" and a["size_band"] == "small"
    assert a["submitted_domain"] == "acme.example" and a["versions"]["model"] == "heuristic:ladder-1"
    conflict = client.post("/v1/assessments", json={**BODY, "website": "other.example"}, headers=headers)
    assert conflict.status_code == 409
    listing = client.get("/v1/assessments", headers={"X-API-Key": api_key}).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == a["id"]
    assert client.get(f"/v1/assessments/{a['id']}/result", headers={"X-API-Key": api_key}).status_code == 404
    orgs = client.get("/v1/organizations", headers={"X-API-Key": api_key}).json()
    assert orgs["total"] == 1 and orgs["items"][0]["primary_domain"] == "acme.example"
    org_id = orgs["items"][0]["id"]
    assert client.get(f"/v1/organizations/{org_id}/assessments", headers={"X-API-Key": api_key}).json()["total"] == 1
    ev = client.get(f"/v1/organizations/{org_id}/evidence", headers={"X-API-Key": api_key}).json()
    assert ev == {"items": [], "total": 0, "limit": 50, "offset": 0}
    cancelled = client.post(f"/v1/assessments/{a['id']}/cancel", headers={"X-API-Key": api_key})
    assert cancelled.status_code == 200 and cancelled.json()["lifecycle_state"] == "cancelled"
    again = client.post(f"/v1/assessments/{a['id']}/cancel", headers={"X-API-Key": api_key})
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition"
    re = client.post(f"/v1/assessments/{a['id']}/reassess", headers={"X-API-Key": api_key})
    assert re.status_code == 202 and re.json()["parent_assessment_id"] == a["id"]


def test_review_requires_reason_and_api_keys_cannot_sign(client: TestClient, api_key: str, settings: Settings) -> None:
    created = client.post("/v1/assessments", json=BODY, headers={"X-API-Key": api_key}).json()
    aid = created["id"]
    # reviews need a reviewer JWT and a reason
    assert (
        client.post(
            "/v1/reviews",
            json={"task_id": aid, "action": "approve", "reason": "because"},
            headers={"X-API-Key": api_key},
        ).status_code
        == 403
    )
    short = client.post(
        "/v1/reviews",
        json={"task_id": aid, "action": "approve", "reason": ""},
        headers=bearer(reviewer_token(settings)),
    )
    assert short.status_code == 422
    assert (
        client.post(
            "/v1/reviews",
            json={"task_id": aid, "action": "approve", "reason": "a real reason"},
            headers=bearer(reviewer_token(settings)),
        ).status_code
        == 404
    )
    # signing needs a reviewer; an API key is refused even with the right path
    refused = client.post(
        f"/v1/assessments/{aid}/certification",
        json={"decision": "certified", "reason": "please"},
        headers={"X-API-Key": api_key},
    )
    assert refused.status_code == 403 and "reviewer" in refused.json()["error"]["message"]
    no_result = client.post(
        f"/v1/assessments/{aid}/certification",
        json={"decision": "certified", "reason": "please"},
        headers=bearer(reviewer_token(settings)),
    )
    assert no_result.status_code == 409


def test_webhooks_uploads_monitoring_and_benchmarks(client: TestClient, api_key: str) -> None:
    h = {"X-API-Key": api_key}
    bad = client.post(
        "/v1/webhooks", json={"url": "https://hook.example/x", "events": ["nope"], "secret": "s" * 20}, headers=h
    )
    assert bad.status_code == 422
    sub = client.post(
        "/v1/webhooks",
        json={"url": "https://hook.example/x", "events": ["assessment.completed"], "secret": "s" * 20},
        headers=h,
    )
    assert sub.status_code == 201 and client.get("/v1/webhooks", headers=h).json()["total"] == 1
    assert client.delete(f"/v1/webhooks/{sub.json()['id']}", headers=h).status_code == 204
    assert client.delete(f"/v1/webhooks/{sub.json()['id']}", headers=h).status_code == 404
    created = client.post("/v1/assessments", json=BODY, headers=h).json()
    org_id = created["org_id"]
    up = client.post(
        "/v1/evidence/uploads",
        data={"org_id": org_id, "assertion_text": "Our AI policy, signed by the board."},
        files={"file": ("policy.txt", b"We are committed to responsible AI. " * 20, "text/plain")},
        headers=h,
    )
    assert up.status_code == 201 and up.json()["status"] == "pending" and up.json()["sha256"]
    mon = client.post(f"/v1/organizations/{org_id}/monitoring", json={"interval_days": 30}, headers=h)
    assert (
        mon.status_code == 201 and client.get(f"/v1/organizations/{org_id}/monitoring", headers=h).json()["total"] == 1
    )
    assert client.get("/v1/benchmarks/industries", headers=h).json()["items"] == []


def test_ontology_endpoints(client: TestClient, manifest: Manifest) -> None:
    summary = client.get("/v1/ontology").json()
    assert (
        summary["manifest_hash"] == manifest.hash and len(summary["entities"]) == 30 and len(summary["criteria"]) == 20
    )
    assert client.get("/v1/ontology/entities/EvidenceLink").json()["table"] == "evidence_links"
    assert client.get("/v1/ontology/entities/Nope").status_code == 404
    voc = client.get("/v1/ontology/vocabularies/coverage_state").json()
    assert next(v["code"] for v in voc["values"]) == "observed"
    assert client.get("/v1/ontology/export/jsonld").json()["@context"]["skos"]
    assert "coverage_wording" in client.get("/v1/ontology/labels").json()
    assert (
        client.get(f"/v1/ontology/{manifest.ontology_version}").json()["ontology"]["ontology"]["version"]
        == manifest.ontology_version
    )
    assert client.get("/v1/ontology/9.9.9").status_code == 404
    crits = client.get("/v1/methodology/criteria").json()
    assert (
        crits["total"] == 20
        and client.get("/v1/methodology/criteria/safety_risk_mitigation").json()["code"] == "SAF-01"
    )
    assert client.get("/v1/methodology/pillars").json()["total"] == 6
    rules = client.get("/v1/methodology/rules").json()
    assert rules["total"] == 16 and all(r["implementation"] for r in rules["items"])
    assert client.get("/v1/methodology/decisions").json()["total"] == 10
    assert client.get("/v1/methodology/scoring").json()["scoring"]["score_cap"] == 85
    ics = client.get("/v1/ontology/integrity-constraints").json()
    assert ics["total"] == 18


def test_cors_denies_unknown_origins(client: TestClient) -> None:
    ok = client.options(
        "/health", headers={"Origin": "https://www.humaital.com", "Access-Control-Request-Method": "GET"}
    )
    assert ok.headers.get("access-control-allow-origin") == "https://www.humaital.com"
    sub = client.options(
        "/health", headers={"Origin": "https://app.humaital.com", "Access-Control-Request-Method": "GET"}
    )
    assert sub.headers.get("access-control-allow-origin") == "https://app.humaital.com"
    bad = client.options("/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
    plain = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in plain.headers
