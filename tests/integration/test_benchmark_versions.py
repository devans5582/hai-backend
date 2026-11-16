"""Peer cohorts never mix methodology versions or discard finalized results."""

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
from hai_engine.reporting import industry_benchmark
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def _pins(manifest: Manifest) -> dict[str, str]:
    return {
        "ontology_version": manifest.ontology_version,
        "methodology_version": manifest.methodology_version,
        "ruleset_version": manifest.ruleset.version,
    }


def _peer(
    database: Database,
    manifest: Manifest,
    score: float | None,
    *,
    pins: dict[str, str] | None = None,
    organization: Organization | None = None,
    created_at: datetime = NOW,
    stage: StageBand = StageBand.MATURE,
    size: SizeBand = SizeBand.ENTERPRISE,
    outcome: OutcomeStatus = OutcomeStatus.CERTIFICATION_NOT_YET_ACHIEVED,
) -> tuple[Organization, Assessment, AssessmentResult]:
    versions = pins if pins is not None else _pins(manifest)
    with database.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        if organization is None:
            organization = store.insert(
                Organization(
                    legal_name="Peer",
                    display_name="Peer",
                    primary_domain=f"peer-{uuid4().hex}.example",
                    industry_code="technology",
                )
            )
        assessment = store.insert(
            Assessment(
                org_id=organization.id,
                requested_by="pytest",
                submitted_domain=organization.primary_domain,
                stage_band=stage,
                size_band=size,
                prompt_version="1.0.0",
                model_id="heuristic:ladder-1",
                lifecycle_state=LifecycleState.COMPLETED_UNVERIFIED,
                created_at=created_at,
                **versions,
            )
        )
    with database.transaction("pytest", "hai_engine") as conn:
        result = Store(conn, actor="pytest", manifest=manifest).insert(
            AssessmentResult(
                assessment_id=assessment.id,
                outcome_status=outcome,
                hai_score=score,
                confidence_pct=80,
                ruleset_version=versions["ruleset_version"],
                result_sha256=uuid4().hex * 2,
                created_at=created_at,
            )
        )
    return organization, assessment, result


def _cohort(database: Database, pins: dict[str, str]) -> dict[str, object] | None:
    with database.connect() as conn:
        return industry_benchmark(conn, "technology", "mature", "enterprise", 75, **pins)


def test_report_benchmark_matches_all_version_pins_and_includes_finalized_results(
    clean_db: Database, manifest: Manifest
) -> None:
    pins = _pins(manifest)
    _, assessment, original = _peer(clean_db, manifest, 80)
    with clean_db.transaction("pytest", "hai_engine") as conn:
        Store(conn, actor="pytest", manifest=manifest).insert(
            AssessmentResult(
                assessment_id=assessment.id,
                outcome_status=OutcomeStatus.CERTIFICATION_NOT_YET_ACHIEVED,
                hai_score=70,
                confidence_pct=80,
                ruleset_version=assessment.ruleset_version,
                result_sha256=uuid4().hex * 2,
                supersedes_id=original.id,
                created_at=NOW + timedelta(seconds=1),
            )
        )
    _peer(clean_db, manifest, 50)
    for key in pins:
        _peer(clean_db, manifest, 10, pins={**pins, key: "0.0.1"})
    _peer(clean_db, manifest, 100, stage=StageBand.EARLY)
    _peer(clean_db, manifest, 100, size=SizeBand.SMALL)
    _peer(clean_db, manifest, 100, outcome=OutcomeStatus.ACCESS_LIMITED)
    _peer(clean_db, manifest, None)
    benchmark = _cohort(clean_db, pins)
    assert benchmark is not None
    assert benchmark["organizations"] == 2 and benchmark["average_score"] == 60
    assert benchmark["position"] == "above" and benchmark["average_confidence"] == 80


def test_benchmark_does_not_fall_back_to_an_organizations_older_methodology(
    clean_db: Database, manifest: Manifest
) -> None:
    current = _pins(manifest)
    old = {**current, "methodology_version": "2.0.0"}
    organization, _, _ = _peer(clean_db, manifest, 40, pins=old)
    _peer(clean_db, manifest, 80, organization=organization, created_at=NOW + timedelta(seconds=2))
    _peer(clean_db, manifest, 20, pins=old)
    old_benchmark = _cohort(clean_db, old)
    current_benchmark = _cohort(clean_db, current)
    assert old_benchmark is not None and old_benchmark["organizations"] == 1
    assert old_benchmark["average_score"] == 20
    assert current_benchmark is not None and current_benchmark["organizations"] == 1
    assert current_benchmark["average_score"] == 80


def test_industry_benchmark_endpoint_uses_current_manifest_versions(
    clean_db: Database, settings: Settings, manifest: Manifest
) -> None:
    _peer(clean_db, manifest, 80)
    _peer(clean_db, manifest, 60)
    _peer(clean_db, manifest, 10, pins={**_pins(manifest), "methodology_version": "2.0.0"})
    enabled = settings.model_copy(update={"auth_disabled": True})
    state = AppState.build(enabled, manifest)
    app = create_app(settings=enabled, manifest=manifest, state=state)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/benchmarks/industries?industry=technology")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["organizations"] == 2 and body["items"][0]["average_score"] == 70
        assert client.get("/v1/benchmarks/industries?industry=healthcare").json()["items"] == []
