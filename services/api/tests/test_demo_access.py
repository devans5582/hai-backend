"""Demo access works through normal API auth and never grants reviewer or production access."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hai_api.deps import AppState
from hai_api.main import create_app
from hai_core.auth import DEMO_API_KEY
from hai_core.db.engine import Database
from hai_core.seed import seed_demo_api_key
from hai_core.settings import Settings
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration


def test_seeded_demo_can_read_and_create_assessments_but_cannot_review_or_administer(
    clean_db: Database, settings: Settings, manifest: Manifest
) -> None:
    with clean_db.transaction("pytest", "hai_admin") as conn:
        seed_demo_api_key(conn, settings)
    app = create_app(settings=settings, manifest=manifest, state=AppState.build(settings, manifest))
    headers = {"X-API-Key": DEMO_API_KEY}
    with TestClient(app) as client:
        assert client.get("/v1/assessments").status_code == 401
        assert client.get("/v1/assessments", headers={"X-API-Key": "demo-wrong"}).status_code == 401
        assert client.get("/v1/assessments", headers=headers).status_code == 200
        assert client.get("/v1/organizations", headers=headers).status_code == 200
        assert client.get("/v1/reviews/tasks", headers=headers).status_code == 200
        created = client.post(
            "/v1/assessments",
            json={
                "organization_name": "Demo Organization",
                "website": "demo.example",
                "stage": "growth",
                "size": "mid",
            },
            headers=headers,
        )
        assert created.status_code == 202
        assessment_id = created.json()["id"]
        assert created.json()["requested_by"] == "api_key:demo"
        assert client.get(f"/v1/assessments/{assessment_id}", headers=headers).status_code == 200
        assert client.get("/v1/assessments", headers={"X-API-Key": "hai_demo.demo"}).status_code == 200
        assert client.get("/v1/audit/verify", headers=headers).status_code == 403
        assert client.post("/v1/auth/token", json={"subject": "demo-reviewer"}, headers=headers).status_code == 403
        assert (
            client.post(
                "/v1/reviews",
                json={"task_id": assessment_id, "action": "approve", "reason": "Demo review attempt"},
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/v1/assessments/{assessment_id}/certification",
                json={"decision": "certified", "reason": "Demo certification attempt"},
                headers=headers,
            ).status_code
            == 403
        )


def test_production_api_rejects_every_demo_spelling_even_when_the_database_has_a_matching_row(
    clean_db: Database, settings: Settings, manifest: Manifest
) -> None:
    production = Settings(
        **(
            settings.model_dump()
            | {
                "env": "production",
                "api_key_pepper": "p" * 40,
                "jwt_secret": "j" * 40,
                "cert_signing_key": "c" * 40,
                "webhook_signing_key": "w" * 40,
            }
        )
    )
    # Use the production pepper in the old development row so refusal proves the environment guard.
    with clean_db.transaction("pytest", "hai_admin") as conn:
        seed_demo_api_key(conn, production.model_copy(update={"env": "test"}))
    app = create_app(settings=production, manifest=manifest, state=AppState.build(production, manifest))
    with TestClient(app) as client:
        for credential in (DEMO_API_KEY, "hai_demo.demo"):
            response = client.get("/v1/assessments", headers={"X-API-Key": credential})
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "unauthorized"
