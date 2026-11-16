import type { ScoreCalibration } from "../lib/api";
import { fmtNum } from "../lib/format";

export function ScoreCalibrationLabel({ calibration }: { calibration: ScoreCalibration | null | undefined }) {
  if (!calibration) return null;
  return <small className="muted" title="Overall score calibration; pillar scores and certification use the baseline scale.">{fmtNum(calibration.multiplier)}x; baseline {fmtNum(calibration.baseline_score)}</small>;
}

export function ScoreCalibrationNote({ calibration }: { calibration: ScoreCalibration | null | undefined }) {
  if (!calibration) return null;
  return (
    <div className="small muted" aria-label="Score calibration">
      <p>Calibration: {fmtNum(calibration.multiplier)}x; baseline {fmtNum(calibration.baseline_score)}/100; displayed {fmtNum(calibration.calibrated_score)}/100. Score ceiling: {fmtNum(calibration.cap)}/100.</p>
      <p>Certification uses the baseline score{calibration.threshold !== null ? ` (minimum ${fmtNum(calibration.threshold)}/100)` : ""}, evidence confidence, evidence in every pillar and a named reviewer's signature.</p>
    </div>
  );
}
