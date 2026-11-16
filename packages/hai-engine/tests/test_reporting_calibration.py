"""Calibration disclosures describe the stored result, including legacy and unavailable results."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from hai_core.generated.enums import OutcomeStatus
from hai_core.generated.models import AssessmentResult
from hai_engine.reporting import score_calibration, score_calibration_from_trace


@pytest.mark.parametrize("baseline, displayed", [(12.5, 56.3), (7.7, 34.7), (30.0, 100.0), (0.0, 0.0), (None, None)])
def test_calibration_is_a_projection_of_stored_values(baseline: float | None, displayed: float | None) -> None:
    recorded = {
        "baseline_score": baseline,
        "multiplier": 4.5,
        "calibrated_score": displayed,
        "cap": 100,
        "certification_basis": "baseline",
        "pillar_basis": "baseline",
        "threshold": 65,
    }
    result = AssessmentResult(
        assessment_id=uuid4(),
        outcome_status=OutcomeStatus.CERTIFICATION_NOT_YET_ACHIEVED,
        hai_score=displayed,
        ruleset_version="3.0.0",
        result_sha256="a" * 64,
        trace={"calibration": {**recorded, "internal_detail": "not part of the disclosure"}},
    )
    assert score_calibration(result) == recorded
    assert score_calibration_from_trace(result.trace) == recorded
    assert isinstance(result.trace, dict)
    assert "internal_detail" in result.trace["calibration"]


@pytest.mark.parametrize(
    "trace", [None, {}, {"rules": []}, {"calibration": None}, {"calibration": {"multiplier": 4.5}}]
)
def test_no_calibration_is_inferred_for_legacy_or_incomplete_traces(trace: Any) -> None:
    assert score_calibration_from_trace(trace) is None
    assert score_calibration(None) is None
