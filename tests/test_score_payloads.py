"""Webhook recipients can identify the scoring basis without recomputing it."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hai_core.generated.enums import OutcomeStatus, SizeBand, StageBand
from hai_core.generated.models import Assessment, AssessmentResult
from hai_worker.jobs import _result_payload


@pytest.mark.parametrize("calibrated", [False, True])
def test_webhook_score_payload_preserves_recorded_calibration_and_version_basis(calibrated: bool) -> None:
    assessment = Assessment(
        org_id=uuid4(),
        requested_by="pytest",
        submitted_domain="example.test",
        stage_band=StageBand.MATURE,
        size_band=SizeBand.ENTERPRISE,
        ontology_version="1.3.0",
        methodology_version="4.0.0" if calibrated else "2.0.0",
        ruleset_version="3.0.0" if calibrated else "1.1.0",
        prompt_version="1.0.0",
        model_id="heuristic:ladder-1",
    )
    calibration = {
        "baseline_score": 12.5,
        "multiplier": 4.5,
        "calibrated_score": 56.3,
        "cap": 100,
        "certification_basis": "baseline",
        "pillar_basis": "baseline",
        "threshold": 70,
    }
    result = AssessmentResult(
        assessment_id=assessment.id,
        outcome_status=OutcomeStatus.CONFIDENCE_TOO_LOW,
        hai_score=56.3 if calibrated else 12.5,
        confidence_pct=50,
        result_sha256="a" * 64,
        ruleset_version=assessment.ruleset_version,
        trace={"calibration": calibration, "overlay": {"private": True}} if calibrated else None,
    )
    payload = _result_payload(assessment, result, "completed_unverified")
    assert payload["assessment_id"] == str(assessment.id)
    score = payload["result"]
    assert score["hai_score"] == result.hai_score and score["confidence_pct"] == 50
    assert score["calibration"] == (calibration if calibrated else None)
    assert score["version_basis"] == {
        "ontology_version": assessment.ontology_version,
        "methodology_version": assessment.methodology_version,
        "ruleset_version": assessment.ruleset_version,
    }
    assert "overlay" not in score
