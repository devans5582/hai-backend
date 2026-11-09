"""Scoring: criterion ratio, pillar aggregation, the HAI Score, confidence, effectiveness and pillar status.

Pure functions over criterion states. Excluded states (unavailable, not
applicable) do not count; a pillar with no counted criteria is left out and the
remaining pillar weights are renormalised. Pillar weights come from pillars.yaml
or, when ``scoring.pillar_weight_profiles.mode`` is ``stage_profile``, from the
profile of the organization's stage band (decision D11). A pillar's maturity
status is the rung reached by at least half of its counted criteria.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from hai_core.generated.enums import ATTRIBUTES, RANKS
from hai_engine.rules.context import CriterionState
from hai_ontology.meta import CriterionDef, Methodology, PillarDef


@dataclass(frozen=True)
class PillarResult:
    code: str
    score: float
    confidence: float
    counted: int
    excluded: int
    status: str | None = None
    weight: float = 0.0


@dataclass
class ScoreResult:
    hai_score: float | None
    confidence_pct: float | None
    effectiveness: float | None
    pillars: list[PillarResult] = field(default_factory=list)
    counted: int = 0
    excluded: int = 0
    note: str = ""


def criterion_ratio(level: int, methodology: Methodology) -> float:
    lo, hi = methodology.scoring.level_min, methodology.scoring.level_max
    return (max(lo, min(hi, level)) - lo) / (hi - lo)


def maturity_status_for(ranks: list[int]) -> str | None:
    """The status earned by the rung that at least half of the counted criteria reach."""
    if not ranks:
        return None
    ordered = sorted(ranks, reverse=True)
    reached = ordered[math.ceil(len(ordered) / 2) - 1]
    rung_ranks = RANKS["maturity_rung"]
    best: str | None = None
    best_rank = -1
    for code, attrs in ATTRIBUTES["maturity_status"].items():
        needed = rung_ranks.get(str(attrs["min_maturity_rung"]), 0)
        if needed <= reached and needed > best_rank:
            best, best_rank = code, needed
    return best


def pillar_weights(methodology: Methodology, pillars: list[PillarDef], stage_band: str | None) -> dict[str, float]:
    default = {p.code: p.weight for p in pillars}
    return methodology.scoring.pillar_weight_profiles.weights_for(stage_band or "", default)


def aggregate(
    methodology: Methodology,
    pillars: list[PillarDef],
    criteria: list[tuple[CriterionDef, CriterionState]],
    *,
    effectiveness_ranks: list[int] | None = None,
    stage_band: str | None = None,
) -> ScoreResult:
    scale = methodology.scoring.score_scale
    weighted = methodology.scoring.pillar_aggregation == "materiality_weighted"
    weights = pillar_weights(methodology, pillars, stage_band)
    results: list[PillarResult] = []
    counted_total = 0
    excluded_total = 0
    conf_num = 0.0
    conf_den = 0.0
    effective = 0
    min_rank = RANKS["maturity_rung"][methodology.scoring.effectiveness_min_rung]
    ranks = effectiveness_ranks or [0] * len(criteria)
    for pillar in pillars:
        ratio_sum = 0.0
        weight_sum = 0.0
        conf_sum = 0.0
        conf_w = 0.0
        counted = 0
        excluded = 0
        pillar_ranks: list[int] = []
        for (crit, state), rank in zip(criteria, ranks, strict=True):
            if crit.pillar != pillar.code:
                continue
            if not state.counts_in_score or state.level is None:
                excluded += 1
                continue
            w = crit.weight * (crit.materiality_weight if weighted else 1.0)
            ratio_sum += criterion_ratio(state.level, methodology) * w
            weight_sum += w
            conf_sum += state.confidence * crit.materiality_weight
            conf_w += crit.materiality_weight
            counted += 1
            pillar_ranks.append(rank)
            if rank >= min_rank:
                effective += 1
        counted_total += counted
        excluded_total += excluded
        if counted:
            score = round(ratio_sum / weight_sum * scale, 1)
            confidence = round(conf_sum / conf_w, 1)
            conf_num += conf_sum
            conf_den += conf_w
        else:
            score, confidence = 0.0, 0.0
        results.append(
            PillarResult(
                pillar.code,
                score,
                confidence,
                counted,
                excluded,
                maturity_status_for(pillar_ranks),
                weights.get(pillar.code, pillar.weight),
            )
        )
    live = [r for r in results if r.counted]
    if not live:
        return ScoreResult(None, None, None, results, counted_total, excluded_total, "no criterion counted; no score")
    total_weight = sum(r.weight for r in live)
    hai = round(sum(r.weight / total_weight * r.score for r in live), 1)
    confidence_pct = round(conf_num / conf_den, 1) if conf_den else 0.0
    effectiveness = round(effective / counted_total * 100, 1) if counted_total else 0.0
    profile = methodology.scoring.pillar_weight_profiles
    profiled = profile.mode == "stage_profile" and (stage_band or "") in profile.profiles
    note = (
        f"{counted_total} criteria counted, {excluded_total} excluded; "
        f"{'materiality-weighted' if weighted else 'equal'} pillar means; "
        f"{'stage profile ' + str(stage_band) if profiled else 'fixed'} pillar weights; "
        f"{len(live)}/{len(pillars)} pillars live (weights renormalised)"
    )
    return ScoreResult(hai, confidence_pct, effectiveness, results, counted_total, excluded_total, note)
