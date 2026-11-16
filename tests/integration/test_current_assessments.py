"""Finished reruns replace current results without destroying audit history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import text

from hai_api.deps import AppState
from hai_api.main import create_app
from hai_core.assessments import current_assessment_id
from hai_core.db.engine import Database
from hai_core.db.store import Store
from hai_core.generated.enums import LifecycleState, OutcomeStatus, SizeBand, StageBand
from hai_core.generated.models import Assessment, AssessmentResult, Organization
from hai_core.settings import Settings
from hai_engine.reporting import industry_benchmarks
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def _assessment(
    store: Store,
    manifest: Manifest,
    org: Organization,
    index: int,
    state: LifecycleState,
    *,
    methodology_version: str | None = None,
) -> Assessment:
    return store.insert(
        Assessment(
            org_id=org.id,
            requested_by="pytest",
            submitted_domain=org.primary_domain,
            stage_band=StageBand.GROWTH,
            size_band=SizeBand.MID,
            ontology_version=manifest.ontology_version,
            methodology_version=methodology_version or manifest.methodology_version,
            ruleset_version=manifest.ruleset.version,
            prompt_version="1.0.0",
            model_id="heuristic:ladder-1",
            lifecycle_state=state,
            created_at=NOW + timedelta(seconds=index),
        )
    )


def _result(
    store: Store,
    assessment: Assessment,
    score: float | None,
    index: int,
    *,
    supersedes_id: UUID | None = None,
) -> AssessmentResult:
    return store.insert(
        AssessmentResult(
            assessment_id=assessment.id,
            hai_score=score,
            confidence_pct=50,
            outcome_status=OutcomeStatus.CONFIDENCE_TOO_LOW,
            ruleset_version=assessment.ruleset_version,
            result_sha256=uuid4().hex * 2,
            created_at=NOW + timedelta(seconds=index),
            supersedes_id=supersedes_id,
        )
    )


def _client(settings: Settings, manifest: Manifest) -> TestClient:
    enabled = settings.model_copy(update={"auth_disabled": True})
    return TestClient(
        create_app(settings=enabled, manifest=manifest, state=AppState.build(enabled, manifest)),
        raise_server_exceptions=False,
    )


def _pdf_report_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def selected_report(_state: AppState, report: dict[str, Any]) -> Response:
        return Response(report["assessment"]["id"], media_type="application/pdf")

    monkeypatch.setattr("hai_api.routers.organizations.report_pdf_response", selected_report)


@pytest.mark.parametrize(
    "state", [LifecycleState.QUEUED, LifecycleState.EVALUATING, LifecycleState.FAILED, LifecycleState.CANCELLED]
)
def test_unfinished_or_failed_rerun_keeps_current_result_and_download(
    clean_db: Database, settings: Settings, manifest: Manifest, monkeypatch: pytest.MonkeyPatch, state: LifecycleState
) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = store.insert(Organization(legal_name="Current", display_name="Current", primary_domain="current.example"))
        first = _assessment(store, manifest, org, 0, LifecycleState.COMPLETED_UNVERIFIED)
        newer = _assessment(store, manifest, org, 1, state)
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        _result(store, first, 30, 2)
        # Even a result written before a later pipeline failure is not current.
        _result(store, newer, 90, 3)
        assert current_assessment_id(conn, org.id) == first.id
    _pdf_report_id(monkeypatch)
    with _client(settings, manifest) as client:
        row = client.get("/v1/organizations/overview").json()["items"][0]
        assert row["latest"]["id"] == str(newer.id) and row["latest"]["lifecycle_state"] == state.value
        assert row["current"]["id"] == str(first.id) and row["current"]["version"] == 1
        assert row["result"]["hai_score"] == 30 and row["score_delta"] is None
        history = client.get(f"/v1/organizations/{org.id}/history").json()
        assert history["latest_id"] == str(newer.id) and history["current_id"] == str(first.id)
        assert [item["is_current"] for item in history["items"]] == [False, True]
        pdf = client.get(f"/v1/organizations/{org.id}/report.pdf")
        assert pdf.status_code == 200 and pdf.text == str(first.id)


@pytest.mark.parametrize("state", [LifecycleState.AWAITING_REVIEW, LifecycleState.COMPLETED_UNVERIFIED])
@pytest.mark.parametrize("score", [60.0, None])
def test_new_scored_run_replaces_current_including_na_without_overwriting_history(
    clean_db: Database,
    settings: Settings,
    manifest: Manifest,
    monkeypatch: pytest.MonkeyPatch,
    state: LifecycleState,
    score: float | None,
) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = store.insert(Organization(legal_name="Current", display_name="Current", primary_domain="current.example"))
        first = _assessment(store, manifest, org, 0, LifecycleState.COMPLETED_UNVERIFIED)
        newer = _assessment(store, manifest, org, 1, state)
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        original = _result(store, first, 30, 2)
        _result(store, newer, score, 3)
        assert current_assessment_id(conn, org.id) == newer.id
        assert store.require(AssessmentResult, original.id).hai_score == 30
    _pdf_report_id(monkeypatch)
    with _client(settings, manifest) as client:
        row = client.get("/v1/organizations/overview").json()["items"][0]
        assert row["current"]["id"] == row["latest"]["id"] == str(newer.id)
        assert row["current"]["lifecycle_state"] == state.value
        assert row["result"]["hai_score"] == score
        assert row["previous"]["id"] == str(first.id)
        assert row["score_delta"] == (None if score is None else 30)
        history = client.get(f"/v1/organizations/{org.id}/history").json()
        assert history["current_id"] == str(newer.id)
        assert [item["is_current"] for item in history["items"]] == [True, False]
        assert history["items"][1]["result"]["hai_score"] == 30
        assert client.get(f"/v1/organizations/{org.id}/report.pdf").text == str(newer.id)
        historical = client.get(f"/v1/assessments/{first.id}/report").json()
        assert historical["assessment"]["id"] == str(first.id) and historical["result"]["hai_score"] == 30


def test_late_old_finalization_cannot_replace_newer_assessment_or_mix_benchmark_versions(
    clean_db: Database, settings: Settings, manifest: Manifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = store.insert(
            Organization(
                legal_name="Current",
                display_name="Current",
                primary_domain="current.example",
                industry_code="technology",
            )
        )
        first = _assessment(store, manifest, org, 0, LifecycleState.COMPLETED_UNVERIFIED)
        newer = _assessment(store, manifest, org, 1, LifecycleState.COMPLETED_UNVERIFIED)
        peer = store.insert(
            Organization(
                legal_name="Old Peer",
                display_name="Old Peer",
                primary_domain="peer.example",
                industry_code="technology",
            )
        )
        old_peer = _assessment(
            store, manifest, peer, 0, LifecycleState.COMPLETED_UNVERIFIED, methodology_version="0.0.1"
        )
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        new_initial = _result(store, newer, 60, 2)
        _result(store, newer, 70, 3, supersedes_id=new_initial.id)
        old_initial = _result(store, first, 30, 4)
        _result(store, first, 99, 5, supersedes_id=old_initial.id)
        _result(store, old_peer, 10, 6)
        assert current_assessment_id(conn, org.id) == newer.id
        latest = (
            conn.execute(text("SELECT * FROM hai_ops.v_latest_results WHERE org_id = :org"), {"org": org.id})
            .mappings()
            .one()
        )
        assert latest["assessment_id"] == newer.id and float(latest["hai_score"]) == 70
        cohorts = (
            conn.execute(text("SELECT * FROM hai_ops.v_industry_benchmarks ORDER BY methodology_version"))
            .mappings()
            .all()
        )
        assert len(cohorts) == 2 and all(row["organizations"] == 1 for row in cohorts)
        assert {float(row["average_score"]) for row in cohorts} == {10, 70}
        benchmark = industry_benchmarks(
            conn,
            ontology_version=manifest.ontology_version,
            methodology_version=manifest.methodology_version,
            ruleset_version=manifest.ruleset.version,
        )
        assert len(benchmark) == 1 and benchmark[0]["organizations"] == 1
        assert float(benchmark[0]["average_score"]) == 70
    _pdf_report_id(monkeypatch)
    with _client(settings, manifest) as client:
        rows = client.get("/v1/organizations/overview").json()["items"]
        row = next(item for item in rows if item["organization"]["id"] == str(org.id))
        assert row["current"]["id"] == str(newer.id) and row["result"]["hai_score"] == 70
        assert client.get(f"/v1/organizations/{org.id}/report.pdf").text == str(newer.id)
