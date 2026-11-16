"""Exports use the stage threshold without relabeling a historical score."""

from __future__ import annotations

import pytest

from hai_core.db.engine import Database
from hai_core.db.store import Store
from hai_core.generated.enums import LifecycleState, OutcomeStatus, SizeBand, StageBand
from hai_core.generated.models import Assessment, AssessmentResult, Organization
from hai_engine.reporting import build_report
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("historical", [False, True])
def test_report_preserves_score_and_uses_only_compatible_thresholds(
    clean_db: Database, manifest: Manifest, historical: bool
) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = store.insert(Organization(legal_name="Example", display_name="Example", primary_domain="example.test"))
        assessment = store.insert(
            Assessment(
                org_id=org.id,
                requested_by="pytest",
                submitted_domain=org.primary_domain,
                stage_band=StageBand.EARLY,
                size_band=SizeBand.SMALL,
                ontology_version="1.2.0" if historical else manifest.ontology_version,
                methodology_version="2.0.0" if historical else manifest.methodology_version,
                ruleset_version="1.1.0" if historical else manifest.ruleset.version,
                prompt_version="1.0.0",
                model_id="heuristic:ladder-1",
                lifecycle_state=LifecycleState.COMPLETED_UNVERIFIED,
            )
        )
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        result = store.insert(
            AssessmentResult(
                assessment_id=assessment.id,
                hai_score=42.5,
                confidence_pct=61.2,
                outcome_status=OutcomeStatus.CONFIDENCE_TOO_LOW,
                ruleset_version=assessment.ruleset_version,
                result_sha256="a" * 64,
            )
        )
    with clean_db.connect() as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        report = build_report(conn, store, manifest, assessment.id)
        assert report["result"]["hai_score"] == 42.5
        assert report["assessment"]["versions"]["methodology"] == assessment.methodology_version
        assert report["scale"]["certification_threshold"] == (None if historical else 65)
        assert bool(report["methodology_notice"]) is historical
        if historical:
            assert "methodology 2.0.0" in report["methodology_notice"]
        assert store.require(AssessmentResult, result.id).result_sha256 == "a" * 64
