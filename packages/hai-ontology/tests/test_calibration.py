"""Score calibration is explicit, bounded in the engine, and safe for legacy manifests."""

import pytest
from pydantic import ValidationError

from hai_ontology.meta import Manifest, Scoring, ScoringCalibration


def test_legacy_scoring_defaults_to_no_calibration(manifest: Manifest) -> None:
    old_scoring = manifest.methodology.scoring.model_dump(exclude={"calibration"})
    assert Scoring.model_validate(old_scoring).calibration == ScoringCalibration(multiplier=1.0)


def test_explicit_calibration_retains_baseline_certification() -> None:
    assert ScoringCalibration.model_validate({"multiplier": 4.5, "certification_basis": "baseline"}).multiplier == 4.5


@pytest.mark.parametrize("multiplier", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_invalid_calibration_multiplier_is_rejected(multiplier: float) -> None:
    with pytest.raises(ValidationError):
        ScoringCalibration.model_validate({"multiplier": multiplier})


def test_calibration_cannot_change_certification_basis() -> None:
    with pytest.raises(ValidationError):
        ScoringCalibration.model_validate({"multiplier": 4.5, "certification_basis": "calibrated"})
