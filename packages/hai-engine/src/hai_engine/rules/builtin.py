"""Ruleset 1.0.0 implementations. Pure functions: no database, no model, no clock.

Each function mutates the state it is given and returns a one-line note. The
engine records the state before and after every rule (IC-14).
"""

from __future__ import annotations

from typing import Any

from hai_core.freshness import decay_multiplier
from hai_core.generated.enums import RANKS, CoverageState, ExecutionLevel, OutcomeStatus
from hai_engine.rules.context import AssessmentContext, AssessmentState, CriterionContext, CriterionState
from hai_engine.rules.registry import assessment_rule, criterion_rule
from hai_engine.scoring import aggregate
from hai_ontology.conditions import UnsafeExpressionError, evaluate

_RUNGS = RANKS["maturity_rung"]
_EXECUTION_EVIDENCE = (ExecutionLevel.PARTIAL.value, ExecutionLevel.VERIFIED.value)


# ----------------------------------------------------------------------- criterion


@criterion_rule("GATE-APPLICABILITY")
def gate_applicability(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    if not ctx.criterion.applicability:
        return "no applicability conditions; the criterion applies"
    for cond in ctx.criterion.applicability:
        try:
            holds = evaluate(cond.condition, ctx.inputs)
        except UnsafeExpressionError as exc:
            return f"condition refused: {exc}"
        if not holds:
            continue
        if cond.effect == "not_applicable":  # hai-codes: ok - applicability_effect value
            state.excluded = True
            state.level = None
            state.coverage_state = CoverageState.NOT_APPLICABLE.value
            return f"condition '{cond.condition}' holds: not applicable, excluded from the score"
        state.review_flags.append(f"applicability:{cond.condition}")
        return f"condition '{cond.condition}' holds: routed to review"
    return "no applicability condition holds; the criterion applies"


@criterion_rule("GATE-COVERAGE")
def gate_coverage(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    if state.excluded:
        return "excluded earlier; coverage unchanged"
    support, contra = ctx.admissible_support, ctx.admissible_contradicting
    state.best_rung_rank = ctx.best_rung_rank
    if support:
        if any(link.execution_level in _EXECUTION_EVIDENCE for link in contra):
            state.coverage_state = CoverageState.FAILED.value
            return (
                f"{len(support)} supporting and {len(contra)} contradicting links; execution evidence shows a failure"
            )
        if contra:
            state.coverage_state = CoverageState.CONTRADICTORY.value
            state.review_flags.append("contradictory")
            return f"{len(support)} supporting and {len(contra)} contradicting admissible links; routed to review"
        best = _rung_name(state.best_rung_rank)
        if best == "specified_control":  # hai-codes: ok - maturity rung value
            state.coverage_state = CoverageState.NOT_TESTED.value
            return "a control is documented but no execution evidence; not tested"
        state.coverage_state = CoverageState.OBSERVED.value
        return f"{len(support)} admissible supporting links; best rung {best}"
    if contra:
        state.coverage_state = CoverageState.OBSERVED.value
        return f"only contradicting evidence ({len(contra)} links); observed at the floor"
    primary = [str(c) for c in params.get("primary_connectors", [])]
    primary_runs = ctx.runs(primary)
    succeeded_any = any(r.succeeded and r.items_returned > 0 for r in ctx.connector_runs)
    primary_down = bool(primary_runs) and all(r.failed_or_blocked and not r.succeeded for r in primary_runs)
    all_down = bool(ctx.connector_runs) and not any(r.succeeded for r in ctx.connector_runs)
    if (primary_down or all_down) and any(r.failed_or_blocked for r in ctx.connector_runs):
        state.coverage_state = CoverageState.UNAVAILABLE.value
        state.excluded = True
        state.level = None
        down = ", ".join(r.code for r in ctx.connector_runs if r.failed_or_blocked)
        return f"no admissible links and the primary sources could not be reached ({down}); unavailable (IC-15)"
    state.coverage_state = CoverageState.MISSING.value
    return (
        "sources were searched"
        + (" and returned documents" if succeeded_any else "")
        + "; nothing admissible for this criterion"
    )


@criterion_rule("ADJ-START-FROM-FINDING")
def adj_start_from_finding(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    if state.excluded:
        return "excluded; no level"
    if ctx.finding is not None:
        state.level = ctx.finding.proposed_level
        return f"start from the accepted finding ({ctx.finding.model_id}): level {state.level}"
    state.level = ctx.ladder_level
    if ctx.admissible_support:
        state.review_flags.append("no_accepted_finding")
    return f"no accepted finding; start from the evidence ladder: level {state.level}"


@criterion_rule("CAP-NO-ADMISSIBLE-SUPPORT")
def cap_no_admissible_support(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    if state.excluded or state.level is None:
        return "excluded; no cap"
    if ctx.admissible_support:
        return f"{len(ctx.admissible_support)} admissible supporting links; no cap"
    floor = ctx.methodology.scoring.missing_level
    if state.level != floor:
        state.level = floor
        state.caps_applied.append("CAP-NO-ADMISSIBLE-SUPPORT")
        return f"no admissible support; level set to {floor}"
    return f"no admissible support; level already {floor}"


@criterion_rule("CAP-MATURITY")
def cap_maturity(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    if state.excluded or state.level is None:
        return "excluded; no cap"
    cap = ctx.ladder_level
    if state.level > cap:
        before = state.level
        state.level = cap
        state.caps_applied.append("CAP-MATURITY")
        return (
            f"best admissible rung {_rung_name(ctx.best_rung_rank)} supports at most level {cap}; capped from {before}"
        )
    return f"level {state.level} is within the ladder cap {cap}"


@criterion_rule("CAP-FAILED-EXECUTION")
def cap_failed_execution(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del ctx
    if state.excluded or state.level is None or state.coverage_state != CoverageState.FAILED.value:
        return "no failed execution evidence"
    cap = int(params.get("cap_level", 3))
    if state.level > cap:
        state.level = cap
        state.caps_applied.append("CAP-FAILED-EXECUTION")
        return f"failed execution evidence caps the level at {cap}"
    return f"failed execution evidence; level {state.level} already at or below {cap}"


@criterion_rule("GATE-UNVERIFIED-INCIDENTS")
def gate_unverified_incidents(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    unverified = [i for i in ctx.incidents if not i.can_adjust_score and i.status != "dismissed"]  # hai-codes: ok
    if not unverified:
        return "no unverified incidents target this criterion"
    for inc in unverified:
        state.review_flags.append(f"unverified_incident:{inc.incident_id}")
    return f"{len(unverified)} alleged or under-investigation incident(s) routed to review; no automatic effect (IC-11)"


@criterion_rule("ADJ-INCIDENTS")
def adj_incidents(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    if state.excluded or state.level is None:
        return "excluded; no adjustment"
    applied: list[str] = []
    for inc in ctx.incidents:
        if not inc.can_adjust_score or inc.most_material_criterion != ctx.criterion.code:
            continue
        effect = inc.level_effect
        before = state.level
        if effect == "force_level_1":
            state.level = 1
        elif effect == "reduce_2":
            state.level = max(1, state.level - 2)
        elif effect == "reduce_1":
            state.level = max(1, state.level - 1)
        if state.level != before:
            state.adjustments.append(f"ADJ-INCIDENTS:{inc.incident_id}")
        applied.append(f"{inc.incident_id[:8]} ({inc.severity}: {effect}, level {before} -> {state.level})")
    if not applied:
        return "no substantiated incident targets this criterion"
    return "one adjustment per incident (IC-10): " + "; ".join(applied)


@criterion_rule("CONF-EVIDENCE")
def conf_evidence(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    if state.excluded:
        state.confidence = 0.0
        return "excluded; confidence 0"
    md = ctx.methodology
    conf = md.confidence
    materiality = ctx.criterion.materiality_weight
    best_per_source: dict[str, tuple[float, str]] = {}
    for link in ctx.admissible_support:
        decay = decay_multiplier(
            md,
            link.publisher_type,
            link.published_at,
            ctx.as_of,
            certificate_valid_until=link.certificate_valid_until,
        )
        contribution = (
            link.tier_weight * link.rung_credit * link.class_multiplier * materiality * decay * conf.base_contribution
        )
        key = link.source_key
        if key not in best_per_source or contribution > best_per_source[key][0]:
            best_per_source[key] = (contribution, link.link_id)
    total = sum(v[0] for v in best_per_source.values())
    publishers = {link.publisher_domain or link.document_id for link in ctx.admissible_support}
    bonus = 0.0
    if len(publishers) >= 3:
        bonus = conf.corroboration_bonus.three_or_more
    elif len(publishers) == 2:
        bonus = conf.corroboration_bonus.two_sources
    if conf.corroboration_bonus.scaled_by_materiality:
        bonus = round(bonus * materiality)
    execution = (
        max((link.execution_bonus for link in ctx.admissible_support), default=0.0) if ctx.admissible_support else 0.0
    )
    omission = min(conf.omission_penalty.max, conf.omission_penalty.per_omitted_span * ctx.omitted_evidence)
    second = 0.0
    if ctx.finding is not None and ctx.finding.second_opinion_level is not None:
        gap = abs(ctx.finding.proposed_level - ctx.finding.second_opinion_level)
        if gap >= conf.second_opinion.disagreement_levels_for_penalty:
            second = conf.second_opinion.penalty
        if gap >= conf.second_opinion.disagreement_levels_for_review:
            state.review_flags.append(f"second_opinion_disagreement:{gap}")
    value = total + bonus + execution - omission - second
    state.confidence = max(conf.clamp.min, min(conf.clamp.max, round(value, 1)))
    return (
        f"{len(best_per_source)} source(s) counted once: {total:.1f}; corroboration +{bonus:.0f}; "
        f"execution {execution:+.0f}; omissions -{omission:.0f}; second opinion -{second:.0f} -> {state.confidence:.1f}"
    )


@criterion_rule("CONF-CONTRADICTION")
def conf_contradiction(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    if state.excluded:
        return "excluded"
    contra = ctx.admissible_contradicting
    if not contra:
        return "no admissible contradicting links"
    penalty_cfg = ctx.methodology.confidence.contradiction_penalty
    penalty = min(penalty_cfg.max, penalty_cfg.per_admissible_contradicting_link * len(contra))
    before = state.confidence
    state.confidence = max(ctx.methodology.confidence.clamp.min, round(state.confidence - penalty, 1))
    return f"{len(contra)} contradicting link(s): confidence {before:.1f} -> {state.confidence:.1f}"


@criterion_rule("CONF-INCIDENT-CEILING")
def conf_incident_ceiling(ctx: CriterionContext, state: CriterionState, params: dict[str, Any]) -> str:
    del params
    if state.excluded:
        return "excluded"
    ceilings = [
        inc.confidence_ceiling
        for inc in ctx.incidents
        if inc.can_adjust_score and inc.most_material_criterion == ctx.criterion.code
    ]
    if not ceilings:
        return "no incident ceiling"
    ceiling = min(ceilings)
    if state.confidence > ceiling:
        before = state.confidence
        state.confidence = ceiling
        return f"incident ceiling {ceiling:.0f}: confidence {before:.1f} -> {ceiling:.0f}"
    return f"confidence {state.confidence:.1f} already under the incident ceiling {ceiling:.0f}"


# ---------------------------------------------------------------------- assessment


@assessment_rule("CAP-SCORE-CEILING")
def cap_score_ceiling(ctx: AssessmentContext, state: AssessmentState, params: dict[str, Any]) -> str:
    del params
    if state.hai_score is None:
        return "no score to cap"
    cap = ctx.methodology.scoring.score_cap
    if state.hai_score > cap:
        before = state.hai_score
        state.hai_score = cap
        state.caps_applied.append("CAP-SCORE-CEILING")
        return f"score {before:.1f} capped at {cap:.0f}"
    return f"score {state.hai_score:.1f} is under the ceiling {cap:.0f}"


@assessment_rule("CAP-SCORE-LOW-CONFIDENCE")
def cap_score_low_confidence(ctx: AssessmentContext, state: AssessmentState, params: dict[str, Any]) -> str:
    del params
    if state.hai_score is None or state.confidence_pct is None:
        return "no score to cap"
    cfg = ctx.methodology.scoring.low_confidence_cap
    if state.confidence_pct < cfg.confidence_below and state.hai_score > cfg.cap:
        before = state.hai_score
        state.hai_score = cfg.cap
        state.caps_applied.append("CAP-SCORE-LOW-CONFIDENCE")
        return f"confidence {state.confidence_pct:.1f} below {cfg.confidence_below:.0f}: score {before:.1f} capped at {cfg.cap:.0f}"  # noqa: E501
    return f"confidence {state.confidence_pct:.1f}; no low-confidence cap"


@assessment_rule("GATE-REVIEW-TRIGGERS")
def gate_review_triggers(ctx: AssessmentContext, state: AssessmentState, params: dict[str, Any]) -> str:
    del params
    rt = ctx.methodology.review_triggers
    triggers: list[str] = []
    for outcome in ctx.criteria:
        for flag in outcome.state.review_flags:
            if flag == "contradictory" and rt.contradictory_coverage:
                triggers.append(f"contradiction:{outcome.criterion.code}")
            elif flag.startswith("unverified_incident:") and rt.unverified_incidents:
                triggers.append(f"incident:{flag.split(':', 1)[1]}")
            elif (flag == "no_accepted_finding" and rt.no_finding_with_admissible_support) or flag.startswith(
                "second_opinion_disagreement"
            ):
                triggers.append(f"finding:{outcome.criterion.code}")
            elif flag.startswith("applicability:"):
                triggers.append(f"applicability:{outcome.criterion.code}")
    if (
        state.confidence_pct is not None
        and rt.borderline_confidence_band.low <= state.confidence_pct <= rt.borderline_confidence_band.high
    ):
        triggers.append(f"confidence:{state.confidence_pct:.1f}")
    if ctx.certification_requested and rt.certification_request and not ctx.signed_certification:
        triggers.append("certification:requested")
    state.review_triggers = sorted(set(triggers))
    return f"{len(state.review_triggers)} review trigger(s)" + (
        ": " + ", ".join(state.review_triggers) if state.review_triggers else ""
    )


@assessment_rule("GATE-CERTIFICATION")
def gate_certification(ctx: AssessmentContext, state: AssessmentState, params: dict[str, Any]) -> str:
    del params
    cert = ctx.methodology.certification
    threshold = cert.threshold
    if cert.threshold_mode == "stage_size":
        for row in cert.stage_size_table.rows:
            if row.stage_band == ctx.stage_band and row.size_band == ctx.size_band:
                threshold = row.threshold
                break
    state.threshold_applied = threshold
    reasons: list[str] = []
    if state.hai_score is None:
        reasons.append("no score computed")
    elif state.hai_score < threshold:
        reasons.append(f"score {state.hai_score:.1f} below threshold {threshold:.0f}")
    if state.confidence_pct is None or state.confidence_pct < cert.min_confidence:
        reasons.append(f"confidence {state.confidence_pct or 0:.1f} below minimum {cert.min_confidence:.0f}")
    blocking = [t for t in state.review_triggers if not t.startswith("certification:")]
    if blocking:
        reasons.append("open review triggers: " + ", ".join(blocking))
    state.gate_reasons = reasons
    state.certification_eligible = not reasons
    return "eligible for certification" if not reasons else "not eligible: " + "; ".join(reasons)


@assessment_rule("GATE-OUTCOME-STATUS")
def gate_outcome_status(ctx: AssessmentContext, state: AssessmentState, params: dict[str, Any]) -> str:
    del params
    cfg = ctx.methodology.outcome
    total = len(ctx.criteria)
    unavailable_share = state.unavailable_criteria / total if total else 0.0
    if unavailable_share >= cfg.access_limited_unavailable_share:
        state.outcome_status = OutcomeStatus.ACCESS_LIMITED.value
        return f"{state.unavailable_criteria}/{total} criteria unavailable: access limited"
    if state.counted_criteria < cfg.insufficient_min_observed_criteria:
        state.outcome_status = OutcomeStatus.INSUFFICIENT_EVIDENCE.value
        return f"only {state.counted_criteria} criteria counted: insufficient evidence"
    if (state.hai_score or 0) == 0 and state.admissible_links >= cfg.governance_baseline_min_admissible_links:
        state.outcome_status = OutcomeStatus.GOVERNANCE_BASELINE.value
        return f"score 0 with {state.admissible_links} admissible links: governance baseline"
    if state.confidence_pct is None or state.confidence_pct < ctx.methodology.certification.min_confidence:
        state.outcome_status = OutcomeStatus.CONFIDENCE_TOO_LOW.value
        return f"confidence {state.confidence_pct or 0:.1f} below the certification minimum"
    if state.certification_eligible and ctx.signed_certification:
        state.outcome_status = OutcomeStatus.HAI_CERTIFIED.value
        return "gates pass and a signed certification decision exists"
    state.outcome_status = OutcomeStatus.CERTIFICATION_NOT_YET_ACHIEVED.value
    if state.certification_eligible:
        return "gates pass; awaiting a reviewer's signature"
    return "a certification gate failed"


def _rung_name(rank: int) -> str:
    for name, r in _RUNGS.items():
        if r == rank:
            return name
    return "none"


def compute_scores(ctx: AssessmentContext, state: AssessmentState) -> str:
    """Scores before the assessment rules run. Not a rule: pure aggregation (scoring.py)."""
    result = aggregate(
        ctx.methodology,
        list(ctx.pillars),
        [(o.criterion, o.state) for o in ctx.criteria],
        effectiveness_ranks=[o.state.best_rung_rank for o in ctx.criteria],
    )
    state.hai_score = result.hai_score
    state.score_before_caps = result.hai_score
    state.confidence_pct = result.confidence_pct
    state.effectiveness = result.effectiveness
    state.pillar_scores = {p.code: (p.score, p.confidence, p.counted, p.excluded) for p in result.pillars}
    state.counted_criteria = result.counted
    state.excluded_criteria = result.excluded
    state.unavailable_criteria = sum(
        1 for o in ctx.criteria if o.state.coverage_state == CoverageState.UNAVAILABLE.value
    )
    state.admissible_links = sum(
        len(o.context.admissible_support) + len(o.context.admissible_contradicting) for o in ctx.criteria
    )
    return result.note
