"""Score summaries disclose calibration and compare only compatible releases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hai_api.deps import AppState
from hai_api.main import create_app
from hai_core.db.engine import Database
from hai_core.db.store import Store
from hai_core.generated.enums import LifecycleState, OutcomeStatus, SizeBand, StageBand
from hai_core.generated.models import Assessment, AssessmentResult, Organization
from hai_core.settings import Settings
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("changed_pin", [None, "ontology_version", "methodology_version", "ruleset_version"])
def test_organization_scores_keep_their_basis_and_do_not_compare_releases(
    clean_db: Database, settings: Settings, manifest: Manifest, changed_pin: str | None
) -> None:
    pins = {
        "ontology_version": manifest.ontology_version,
        "methodology_version": manifest.methodology_version,
        "ruleset_version": manifest.ruleset.version,
    }
    old_pins = {**pins, changed_pin: "0.0.1"} if changed_pin else pins
    calibration = {
        "baseline_score": 10,
        "multiplier": 4.5,
        "calibrated_score": 45,
        "cap": 100,
        "certification_basis": "baseline",
        "pillar_basis": "baseline",
        "threshold": 70,
    }
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = store.insert(
            Organization(legal_name="Score Example", display_name="Score Example", primary_domain="score.example")
        )
        assessments = [
            store.insert(
                Assessment(
                    org_id=org.id,
                    requested_by="pytest",
                    submitted_domain=org.primary_domain,
                    stage_band=StageBand.MATURE,
                    size_band=SizeBand.ENTERPRISE,
                    prompt_version="1.0.0",
                    model_id="heuristic:ladder-1",
                    lifecycle_state=LifecycleState.COMPLETED_UNVERIFIED,
                    created_at=now + timedelta(seconds=index),
                    **versions,
                )
            )
            for index, versions in enumerate((old_pins, pins))
        ]
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        for index, assessment in enumerate(assessments):
            current = index == 1
            prior_calibration = {**calibration, "baseline_score": 9, "calibrated_score": 40.5}
            recorded = calibration if current else prior_calibration if not changed_pin else None
            store.insert(
                AssessmentResult(
                    assessment_id=assessment.id,
                    hai_score=45 if current else 10 if changed_pin else 40.5,
                    confidence_pct=50,
                    outcome_status=OutcomeStatus.CONFIDENCE_TOO_LOW,
                    ruleset_version=assessment.ruleset_version,
                    result_sha256=uuid4().hex * 2,
                    trace={"calibration": recorded} if recorded else None,
                )
            )
    enabled = settings.model_copy(update={"auth_disabled": True})
    app = create_app(settings=enabled, manifest=manifest, state=AppState.build(enabled, manifest))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/organizations/overview")
        assert response.status_code == 200, response.text
        row = response.json()["items"][0]
        assert row["result"]["hai_score"] == 45
        assert row["result"]["calibration"] == calibration
        assert row["result"]["version_basis"] == row["latest"]["version_basis"] == pins
        assert row["previous"]["version_basis"] == old_pins
        assert row["score_delta"] == (None if changed_pin else 4.5)
        history_response = client.get(f"/v1/organizations/{org.id}/history")
        assert history_response.status_code == 200, history_response.text
        history = history_response.json()["items"]
        assert history[0]["result"]["calibration"] == calibration
        assert history[0]["result"]["version_basis"] == pins
        assert history[1]["result"]["version_basis"] == old_pins
        if changed_pin:
            assert row["previous"]["hai_score"] == history[1]["result"]["hai_score"] == 10
            assert row["previous"]["calibration"] is None and history[1]["result"]["calibration"] is None
