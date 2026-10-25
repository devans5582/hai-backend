"""End to end through the API and the worker against the fake internet.

Idempotent start, the full job chain, every span matching stored text, every
connector run recorded, injection never admissible, one incident from two
articles, review tasks, replay equals stored result, escalation and four eyes,
API keys refused for signing, reviewer signs, finalize, webhooks delivered with
valid signatures, audit verifies; and a blocked-website run reporting
unavailable rather than missing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hai_api.deps import AppState
from hai_api.main import create_app
from hai_core.auth import Scope, create_api_key, mint_jwt
from hai_core.blobstore import BlobStore
from hai_core.db.engine import Database
from hai_core.db.store import Store
from hai_core.settings import Settings
from hai_core.webhooks import SIGNATURE_HEADER, verify_signature
from hai_engine.llm.heuristic import HeuristicProvider
from hai_ontology.meta import Manifest
from hai_worker.main import Worker
from tests.fixtures.fake_internet import ORG_DOMAIN, FakeInternet

pytestmark = [pytest.mark.integration, pytest.mark.e2e]
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
BODY: dict[str, Any] = {
    "organization_name": "Acme Corp",
    "website": ORG_DOMAIN,
    "stage": "growth",
    "size": "51-200",
    "industry": "Software",
}


class HookSink:
    def __init__(self) -> None:
        self.received: list[tuple[dict[str, str], bytes]] = []

    @property
    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.received.append((dict(request.headers), request.content))
            return httpx.Response(200, json={"ok": True})

        return httpx.MockTransport(handler)


@pytest.fixture
def client(clean_db: Database, settings: Settings, manifest: Manifest) -> Iterator[TestClient]:
    app = create_app(settings=settings, manifest=manifest, state=AppState.build(settings, manifest))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def partner(clean_db: Database, settings: Settings) -> dict[str, str]:
    with clean_db.transaction("pytest", "hai_admin") as conn:
        plaintext, _ = create_api_key(
            conn,
            settings.api_key_pepper.get_secret_value(),
            name="partner",
            scopes=Scope.PARTNER_DEFAULT,
            created_by="pytest",
        )
    return {"X-API-Key": plaintext}


def reviewer(settings: Settings, subject: str) -> dict[str, str]:
    token = mint_jwt(
        settings.jwt_secret.get_secret_value(),
        subject=subject,
        name=subject,
        role="reviewer",
        scopes=Scope.REVIEWER_DEFAULT,
        issuer=settings.jwt_issuer,
    )
    return {"Authorization": f"Bearer {token}"}


def worker_for(settings: Settings, manifest: Manifest, net: FakeInternet, sink: HookSink) -> Worker:
    return Worker(
        settings,
        manifest,
        transport=net.transport,
        webhook_transport=sink.transport,
        provider=HeuristicProvider(),
        now=NOW,
    )


async def test_full_flow(
    client: TestClient, partner: dict[str, str], settings: Settings, manifest: Manifest, clean_db: Database
) -> None:
    sink = HookSink()
    secret = "whsec_" + "x" * 20
    assert (
        client.post(
            "/v1/webhooks",
            json={
                "url": "https://hooks.example/hai",
                "events": ["assessment.completed", "review.required", "score.changed", "certification.signed"],
                "secret": secret,
            },
            headers=partner,
        ).status_code
        == 201
    )

    # idempotent start
    headers = {**partner, "Idempotency-Key": "e2e-1"}
    first = client.post("/v1/assessments", json=BODY, headers=headers)
    second = client.post("/v1/assessments", json=BODY, headers=headers)
    assert first.status_code == 202 and second.json()["id"] == first.json()["id"]
    aid = first.json()["id"]

    # the full job chain
    worker = worker_for(settings, manifest, FakeInternet(inject=True), sink)
    ran = await worker.drain()
    assert ran >= 6
    a = client.get(f"/v1/assessments/{aid}", headers=partner).json()
    assert a["lifecycle_state"] == "awaiting_review", a
    runs = client.get(f"/v1/assessments/{aid}/connector-runs", headers=partner).json()
    assert runs["total"] == 9 and all(r["outcome"] == "succeeded" for r in runs["items"])
    result = client.get(f"/v1/assessments/{aid}/result", headers=partner).json()
    assert result["hai_score"] is not None and 0 < result["hai_score"] <= 85
    assert result["outcome_status"] in ("certification_not_yet_achieved", "confidence_too_low")
    assert any(t.startswith("incident:") for t in result["review_triggers"])

    # every span matches the stored text; injection never admissible; one incident from two articles
    blobs = BlobStore(settings.blob_store_url)
    with clean_db.connect() as conn:
        spans = conn.execute(
            text(
                "SELECT s.char_start, s.char_end, s.quote, d.text_uri FROM hai.evidence_spans s JOIN hai.source_documents d ON d.id = s.source_document_id JOIN hai.connector_runs r ON r.id = d.connector_run_id WHERE r.assessment_id = :a"  # noqa: E501
            ),
            {"a": aid},
        ).all()
        texts: dict[str, str] = {}
        for start, end, quote, uri in spans:
            assert texts.setdefault(uri, blobs.get_text(uri))[start:end] == quote
        assert len(spans) > 10
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM hai.evidence_links l JOIN hai.evidence_spans s ON s.id = l.span_id WHERE s.quote ILIKE '%ignore previous%' AND l.admissibility = 'admissible'"  # noqa: E501
                )
            ).scalar_one()
            == 0
        )
        incidents = conn.execute(text("SELECT status::text FROM hai.incidents")).all()
        assert len(incidents) == 1 and incidents[0][0] == "alleged"

    # the report renders stored values and lists only collected sources
    report = client.get(f"/v1/assessments/{aid}/report", headers=partner).json()
    assert (
        report["result"]["hai_score"] == result["hai_score"]
        and report["result"]["outcome_status"] == result["outcome_status"]
    )
    assert report["coverage_summary"]["observed"] >= 3 and all(
        s["run_outcome"] == "succeeded" for s in report["sources"]
    )
    trace = client.get(f"/v1/assessments/{aid}/trace/SAF-01", headers=partner).json()
    assert trace["criteria"][0]["rules"] and any(e["quote"] for e in trace["criteria"][0]["evidence"])
    assert (
        client.get(f"/v1/assessments/{aid}/trace/safety_risk_mitigation", headers=partner).json()["criteria"][0][
            "criterion_code"
        ]
        == "SAF-01"
    )
    decisions = client.get(f"/v1/assessments/{aid}/decisions", headers=partner).json()
    assert decisions["total"] == 20 and all(d["applied_rule_codes"] for d in decisions["items"])
    findings = client.get(f"/v1/assessments/{aid}/findings", headers=partner).json()
    assert findings["total"] == 20 and all(f["validation_status"] == "accepted" for f in findings["items"])

    # replay equals the stored result
    with clean_db.connect() as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        ok, _, _ = worker.ctx.decisions.replay(conn, store, UUID(aid))
    assert ok

    # review tasks: escalation keeps the task open for a different reviewer; four eyes
    tasks = client.get("/v1/reviews/tasks", headers=reviewer(settings, "rev-1")).json()
    incident_task = next(t for t in tasks["items"] if t["subject_type"] == "incident")
    assert "substantiate" in incident_task["allowed_actions"]
    bad_action = client.post(
        "/v1/reviews",
        json={"task_id": incident_task["id"], "action": "sign", "reason": "wrong action"},
        headers=reviewer(settings, "rev-1"),
    )
    assert bad_action.status_code == 422
    esc = client.post(
        "/v1/reviews",
        json={"task_id": incident_task["id"], "action": "escalate", "reason": "needs a second pair of eyes"},
        headers=reviewer(settings, "rev-1"),
    )
    assert esc.status_code == 201 and esc.json()["task"]["status"] == "escalated"
    again = client.post(
        "/v1/reviews",
        json={"task_id": incident_task["id"], "action": "dismiss", "reason": "changed my mind"},
        headers=reviewer(settings, "rev-1"),
    )
    assert again.status_code == 403
    done = client.post(
        "/v1/reviews",
        json={"task_id": incident_task["id"], "action": "dismiss", "reason": "not this organization"},
        headers=reviewer(settings, "rev-2"),
    )
    assert done.status_code == 201 and done.json()["task"]["status"] == "closed"
    # close any other open tasks so finalize can run
    for t in client.get("/v1/reviews/tasks", headers=reviewer(settings, "rev-2")).json()["items"]:
        action = "approve" if "approve" in t["allowed_actions"] else t["allowed_actions"][0]
        assert (
            client.post(
                "/v1/reviews",
                json={"task_id": t["id"], "action": action, "reason": "reviewed in e2e"},
                headers=reviewer(settings, "rev-2"),
            ).status_code
            == 201
        )
    await worker.drain()
    a = client.get(f"/v1/assessments/{aid}", headers=partner).json()
    assert a["lifecycle_state"] == "completed_unverified"
    result2 = client.get(f"/v1/assessments/{aid}/result", headers=partner).json()
    assert not any(t.startswith("incident:") for t in result2["review_triggers"])

    # API keys are refused for signing; a reviewer signs; finalize; audit verifies
    assert (
        client.post(
            f"/v1/assessments/{aid}/certification", json={"decision": "not_certified", "reason": "x"}, headers=partner
        ).status_code
        == 403
    )
    req = client.post(f"/v1/assessments/{aid}/certification-request", headers=partner)
    assert req.status_code == 200 and req.json()["lifecycle_state"] == "awaiting_review"
    signed = client.post(
        f"/v1/assessments/{aid}/certification",
        json={"decision": "not_certified", "reason": "score below the threshold"},
        headers=reviewer(settings, "rev-3"),
    )
    assert signed.status_code == 201 and signed.json()["decision"] == "not_certified"
    certified = client.post(
        f"/v1/assessments/{aid}/certification",
        json={"decision": "certified", "reason": "please"},
        headers=reviewer(settings, "rev-3"),
    )
    assert certified.status_code == 422  # gates failed
    await worker.drain()
    a = client.get(f"/v1/assessments/{aid}", headers=partner).json()
    assert a["lifecycle_state"] == "completed_unverified"
    audit = client.get("/v1/audit/verify", headers=reviewer(settings, "rev-1")).json()
    assert audit["ok"] and audit["events"] > 50

    # webhooks were delivered with valid signatures for every event kind that fired
    events: dict[str, int] = {}
    for headers_seen, body in sink.received:
        assert verify_signature(secret, body, headers_seen[SIGNATURE_HEADER.lower()])
        events.setdefault(headers_seen["x-hai-event"], 0)
        events[headers_seen["x-hai-event"]] += 1
    assert events.get("review.required") and events.get("assessment.completed") and events.get("certification.signed")
    payload = json.loads(sink.received[0][1])
    assert payload["event"] in events and "data" in payload

    # the organization's evidence ledger is paginated with totals
    org_id = a["org_id"]
    ledger = client.get(f"/v1/organizations/{org_id}/evidence?limit=5", headers=partner).json()
    assert ledger["total"] > 5 and len(ledger["items"]) == 5 and ledger["items"][0]["quote"]
    assert (
        client.get(
            f"/v1/organizations/{org_id}/evidence?criterion=SAF-01&admissibility=admissible", headers=partner
        ).json()["total"]
        >= 1
    )


async def test_blocked_website_reports_unavailable_not_missing(
    client: TestClient, partner: dict[str, str], settings: Settings, manifest: Manifest, clean_db: Database
) -> None:
    created = client.post("/v1/assessments", json={**BODY, "website": ORG_DOMAIN}, headers=partner)
    aid = created.json()["id"]
    worker = worker_for(settings, manifest, FakeInternet(block_website=True, news_available=False), HookSink())
    await worker.drain()
    a = client.get(f"/v1/assessments/{aid}", headers=partner).json()
    assert a["lifecycle_state"] in ("completed_unverified", "awaiting_review"), a
    runs = {
        r["code"]: r["outcome"]
        for r in client.get(f"/v1/assessments/{aid}/connector-runs", headers=partner).json()["items"]
    }
    assert runs["WEBSITE"] == "blocked" and runs["NEWS"] == "failed"
    decisions = client.get(f"/v1/assessments/{aid}/decisions", headers=partner).json()["items"]
    states = {d["criterion_code"]: d["coverage_state"] for d in decisions}
    assert "unavailable" in states.values() and "missing" not in states.values()
    unavailable = [d for d in decisions if d["coverage_state"] == "unavailable"]
    assert all(d["level"] is None for d in unavailable) and "access limitation" in unavailable[0]["coverage_wording"]
    result = client.get(f"/v1/assessments/{aid}/result", headers=partner).json()
    assert result["outcome_status"] in ("access_limited", "insufficient_evidence")
    report = client.get(f"/v1/assessments/{aid}/report", headers=partner).json()
    assert report["coverage_summary"]["unavailable"] >= 10
