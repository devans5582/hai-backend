"""Every rule in the ruleset, scoring, the engine trace and replay determinism."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest

from hai_engine.rules import RULE_IMPLEMENTATIONS, RuleEngine, RuleRegistryError
from hai_engine.rules import builtin as rules
from hai_engine.rules.context import (
    ConnectorSummary,
    CriterionContext,
    CriterionState,
    FrozenFinding,
    FrozenIncident,
    FrozenLink,
)
from hai_engine.rules.registry import criterion_rule, resolve
from hai_engine.scoring import aggregate, criterion_ratio
from hai_ontology.meta import CriterionDef, Manifest
from hai_ontology.validator import validate

AS_OF = datetime(2026, 10, 24, tzinfo=UTC)


def link(
    code: str,
    rung: str,
    *,
    polarity: str = "supports",
    admissibility: str = "admissible",
    execution: str = "none",
    publisher: str = "acme.example",
    publisher_type: str = "org_disclosure",
    independence: str = "self",
    tier: str = "T3",
    cluster: str | None = None,
    published: date | None = date(2026, 3, 1),
    evidence_class: str = "core_governance",
) -> FrozenLink:
    return FrozenLink(
        link_id=str(uuid4()),
        span_id=str(uuid4()),
        criterion_code=code,
        polarity=polarity,
        admissibility=admissibility,
        maturity_rung=rung,
        execution_level=execution,
        evidence_class=evidence_class,
        independence=independence,
        source_tier=tier,
        publisher_type=publisher_type,
        publisher_domain=publisher,
        cluster_id=cluster,
        document_id=str(uuid4()),
        published_at=published,
        certificate_valid_until=None,
        quote="A long enough quote describing the evidence for this criterion.",
        canonical_url=None,
        document_title=None,
    )


def incident(code: str, status: str, severity: str) -> FrozenIncident:
    return FrozenIncident(
        incident_id=str(uuid4()),
        status=status,
        severity=severity,
        most_material_criterion=code,
        occurred_at=date(2026, 4, 2),
        title="x",
    )


def runs(**outcomes: str) -> tuple[ConnectorSummary, ...]:
    return tuple(
        ConnectorSummary(
            code, out == "succeeded", out in ("failed", "blocked", "rate_limited"), 1 if out == "succeeded" else 0
        )
        for code, out in outcomes.items()
    )


def ctx(
    manifest: Manifest,
    code: str = "SAF-01",
    *,
    links: list[FrozenLink] | None = None,
    incidents: list[FrozenIncident] | None = None,
    finding: FrozenFinding | None = None,
    connector_runs: tuple[ConnectorSummary, ...] | None = None,
    omitted: int = 0,
    inputs: dict[str, Any] | None = None,
    criterion: CriterionDef | None = None,
) -> CriterionContext:
    return CriterionContext(
        criterion=criterion or manifest.criterion(code),
        methodology=manifest.methodology,
        links=tuple(links or []),
        incidents=tuple(incidents or []),
        connector_runs=connector_runs if connector_runs is not None else runs(WEBSITE="succeeded", NEWS="succeeded"),
        finding=finding,
        as_of=AS_OF,
        inputs=inputs or {"stage_band": "growth", "size_band": "mid", "direct_urls": 0},
        omitted_evidence=omitted,
    )


@pytest.fixture
def engine(manifest: Manifest) -> RuleEngine:
    return RuleEngine(manifest)


# --------------------------------------------------------------------- registry
def test_rules_resolve_and_match_the_manifest(manifest: Manifest, engine: RuleEngine) -> None:
    assert set(RULE_IMPLEMENTATIONS) == {r.code for r in manifest.ruleset.rules}
    assert engine.criterion_rule_codes == [
        r.code for r in sorted(manifest.ruleset.rules, key=lambda r: r.run_order) if r.scope == "criterion"
    ]
    report = validate(manifest, RULE_IMPLEMENTATIONS)
    assert report.errors == [] and report.warnings == []


def test_an_unregistered_expression_ref_refuses_to_start(manifest: Manifest) -> None:
    broken = manifest.model_copy(deep=True)
    broken.ruleset.rules[0].__dict__["expression_ref"] = "hai_engine.rules.builtin:not_there"
    with pytest.raises(RuleRegistryError, match="not resolve"):
        resolve(broken)


def test_rule_codes_cannot_be_registered_twice() -> None:
    def other(ctx: Any, state: Any, params: Any) -> str:
        return ""

    with pytest.raises(RuleRegistryError, match="already registered"):
        criterion_rule("CAP-MATURITY")(other)


# ---------------------------------------------------------------- criterion rules
def test_applicability_condition(manifest: Manifest) -> None:
    crit = manifest.criterion("IMP-04").model_copy(
        update={"applicability": [manifest.criterion("IMP-04").applicability.__class__()]}
    )
    from hai_ontology.meta import ApplicabilityDef

    na = manifest.criterion("IMP-04").model_copy(
        update={
            "applicability": [
                ApplicabilityDef(condition="stage_band == 'early' and size_band == 'small'", effect="not_applicable")
            ]
        }
    )
    state = CriterionState()
    note = rules.gate_applicability(
        ctx(manifest, criterion=na, inputs={"stage_band": "early", "size_band": "small"}), state, {}
    )
    assert state.excluded and state.coverage_state == "not_applicable" and "excluded" in note
    state = CriterionState()
    rules.gate_applicability(
        ctx(manifest, criterion=na, inputs={"stage_band": "growth", "size_band": "small"}), state, {}
    )
    assert not state.excluded
    rev = manifest.criterion("IMP-04").model_copy(
        update={"applicability": [ApplicabilityDef(condition="direct_urls == 0", effect="review")]}
    )
    state = CriterionState()
    rules.gate_applicability(ctx(manifest, criterion=rev), state, {})
    assert state.review_flags and state.review_flags[0].startswith("applicability:")
    unsafe = manifest.criterion("IMP-04").model_copy(
        update={"applicability": [ApplicabilityDef(condition="__import__('os')", effect="not_applicable")]}
    )
    state = CriterionState()
    assert "refused" in rules.gate_applicability(ctx(manifest, criterion=unsafe), state, {}) and not state.excluded
    assert crit is not None


def test_coverage_states(manifest: Manifest) -> None:
    primary = {"primary_connectors": ["WEBSITE", "DIRECT_URL"]}

    def coverage(**kw: Any) -> CriterionState:
        state = CriterionState()
        rules.gate_coverage(ctx(manifest, **kw), state, primary)
        return state

    assert coverage(links=[link("SAF-01", "stated_commitment")]).coverage_state == "observed"
    assert coverage(links=[link("SAF-01", "specified_control")]).coverage_state == "not_tested"
    both = coverage(links=[link("SAF-01", "stated_commitment"), link("SAF-01", "none", polarity="contradicts")])
    assert both.coverage_state == "contradictory" and "contradictory" in both.review_flags
    failed = coverage(
        links=[
            link("SAF-01", "specified_control"),
            link("SAF-01", "none", polarity="contradicts", execution="verified"),
        ]
    )
    assert failed.coverage_state == "failed"
    assert coverage(links=[link("SAF-01", "none", polarity="contradicts")]).coverage_state == "observed"
    assert (
        coverage(links=[link("SAF-01", "stated_commitment", admissibility="inadmissible_stale")]).coverage_state
        == "missing"
    )


def test_missing_when_sources_were_searched(manifest: Manifest) -> None:
    state = CriterionState()
    note = rules.gate_coverage(
        ctx(manifest, connector_runs=runs(WEBSITE="succeeded", NEWS="failed")),
        state,
        {"primary_connectors": ["WEBSITE"]},
    )
    assert state.coverage_state == "missing" and not state.excluded and "searched" in note


def test_unavailable_only_when_a_connector_failed(manifest: Manifest) -> None:
    params = {"primary_connectors": ["WEBSITE", "DIRECT_URL"]}
    blocked = CriterionState()
    rules.gate_coverage(ctx(manifest, connector_runs=runs(WEBSITE="blocked", NEWS="succeeded")), blocked, params)
    assert blocked.coverage_state == "unavailable" and blocked.excluded and blocked.level is None
    all_ok = CriterionState()
    rules.gate_coverage(ctx(manifest, connector_runs=runs(WEBSITE="succeeded", NEWS="succeeded")), all_ok, params)
    assert all_ok.coverage_state == "missing"
    # evidence found elsewhere keeps the criterion observed even if the website was blocked (IC-15 is about absence)
    found = CriterionState()
    rules.gate_coverage(
        ctx(manifest, links=[link("SAF-01", "stated_commitment")], connector_runs=runs(WEBSITE="blocked")),
        found,
        params,
    )
    assert found.coverage_state == "observed"
    no_runs = CriterionState()
    rules.gate_coverage(ctx(manifest, connector_runs=()), no_runs, params)
    assert no_runs.coverage_state == "missing"


def test_start_from_finding_and_caps(manifest: Manifest) -> None:
    links = [link("SAF-01", "specified_control")]
    finding = FrozenFinding(
        proposed_level=5,
        evidence_link_ids=(links[0].link_id,),
        contradicting_link_ids=(),
        uncertainty=0.2,
        model_id="openai:test",
    )
    c = ctx(manifest, links=links, finding=finding)
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    assert state.level == 5
    rules.cap_no_admissible_support(c, state, {})
    assert state.level == 5
    note = rules.cap_maturity(c, state, {})
    assert state.level == 3 and "CAP-MATURITY" in state.caps_applied and "capped from 5" in note
    # without a finding the ladder level is the start
    s2 = CriterionState()
    c2 = ctx(manifest, links=links)
    rules.gate_coverage(c2, s2, {})
    rules.adj_start_from_finding(c2, s2, {})
    assert s2.level == 3 and "no_accepted_finding" in s2.review_flags


def test_level_is_capped_by_the_evidence_ladder(manifest: Manifest) -> None:
    for rung, expected in (
        ("none", 1),
        ("stated_commitment", 2),
        ("specified_control", 3),
        ("documented_execution", 4),
        ("independently_verified", 5),
    ):
        c = ctx(
            manifest,
            links=[link("SAF-01", rung, independence="regulator" if rung == "independently_verified" else "self")],
            finding=FrozenFinding(5, (), (), 0.1, "m"),
        )
        state = CriterionState()
        rules.gate_coverage(c, state, {})
        rules.adj_start_from_finding(c, state, {})
        rules.cap_maturity(c, state, {})
        assert state.level == expected, rung


def test_no_admissible_support_caps_to_the_floor(manifest: Manifest) -> None:
    c = ctx(
        manifest,
        links=[link("SAF-01", "documented_execution", admissibility="inadmissible_untrusted")],
        finding=FrozenFinding(4, (), (), 0.1, "m"),
    )
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    rules.cap_no_admissible_support(c, state, {})
    assert state.level == 1 and "CAP-NO-ADMISSIBLE-SUPPORT" in state.caps_applied


def test_failed_execution_caps(manifest: Manifest) -> None:
    c = ctx(
        manifest,
        links=[
            link("SAF-01", "documented_execution"),
            link("SAF-01", "none", polarity="contradicts", execution="verified"),
        ],
    )
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    assert state.level == 4
    rules.cap_failed_execution(c, state, {"cap_level": 3})
    assert state.level == 3 and "CAP-FAILED-EXECUTION" in state.caps_applied


def test_alleged_incident_has_no_automatic_effect(manifest: Manifest) -> None:
    inc = incident("SAF-01", "alleged", "critical")
    c = ctx(manifest, links=[link("SAF-01", "documented_execution")], incidents=[inc])
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    rules.gate_unverified_incidents(c, state, {})
    rules.adj_incidents(c, state, {})
    assert state.level == 4 and f"unverified_incident:{inc.incident_id}" in state.review_flags and not state.adjustments
    rules.conf_evidence(c, state, {})
    before = state.confidence
    rules.conf_incident_ceiling(c, state, {})
    assert state.confidence == before


def test_substantiated_incident_adjustment(manifest: Manifest) -> None:
    for severity, expected in (("low", 4), ("moderate", 3), ("high", 2), ("critical", 1)):
        c = ctx(
            manifest,
            links=[link("SAF-01", "documented_execution")],
            incidents=[incident("SAF-01", "substantiated", severity)],
        )
        state = CriterionState()
        rules.gate_coverage(c, state, {})
        rules.adj_start_from_finding(c, state, {})
        rules.adj_incidents(c, state, {})
        assert state.level == expected, severity


def test_incident_adjusts_only_its_target_criterion(manifest: Manifest) -> None:
    inc = incident("ACC-01", "substantiated", "critical")
    # the engine only hands a criterion the incidents whose most material criterion it is; a stray one changes nothing
    c = ctx(manifest, "SAF-01", links=[link("SAF-01", "documented_execution")], incidents=[inc])
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    rules.adj_incidents(c, state, {})
    assert state.level == 4
    rules.conf_evidence(c, state, {})
    before = state.confidence
    rules.conf_incident_ceiling(c, state, {})
    assert state.confidence == before


def test_low_severity_incident_caps_confidence(manifest: Manifest) -> None:
    c = ctx(
        manifest,
        links=[
            link("SAF-01", "documented_execution"),
            link("SAF-01", "documented_execution", publisher="other.example"),
        ],
        incidents=[incident("SAF-01", "substantiated", "low")],
    )
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    rules.adj_incidents(c, state, {})
    assert state.level == 4
    rules.conf_evidence(c, state, {})
    assert state.confidence > 20
    rules.conf_incident_ceiling(c, state, {})
    assert state.confidence == 20


def test_confidence_formula(manifest: Manifest) -> None:
    from hai_core.freshness import decay_multiplier

    md = manifest.methodology
    published = date(2026, 10, 1)
    c = ctx(manifest, links=[link("SAF-01", "documented_execution", published=published)])
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.conf_evidence(c, state, {})
    # tier T3 0.6 x rung credit 1.0 x class 0.7 x materiality 1.4 x freshness decay x 30, plus the execution bonus (none: -5)  # noqa: E501
    decay = decay_multiplier(md, "org_disclosure", published, AS_OF)
    expected = 0.6 * 1.0 * 0.7 * 1.4 * decay * md.confidence.base_contribution - 5
    assert state.confidence == pytest.approx(expected, abs=0.1)
    assert 0.9 < decay < 1.0  # three weeks old: decayed, not current


def test_a_source_cluster_counts_once(manifest: Manifest) -> None:
    one = ctx(manifest, links=[link("SAF-01", "documented_execution", publisher="a.example", cluster="c1")])
    s1 = CriterionState()
    rules.gate_coverage(one, s1, {})
    rules.conf_evidence(one, s1, {})
    ten = ctx(
        manifest,
        links=[link("SAF-01", "documented_execution", publisher=f"copy{i}.example", cluster="c1") for i in range(10)],
    )
    s10 = CriterionState()
    rules.gate_coverage(ten, s10, {})
    rules.conf_evidence(ten, s10, {})
    # ten syndicated copies contribute once; only the corroboration bonus (distinct publishers) differs
    assert (
        s10.confidence - s1.confidence <= manifest.methodology.confidence.corroboration_bonus.three_or_more * 1.4 + 0.01
    )


def test_independent_corroboration_raises_confidence(manifest: Manifest) -> None:
    single = ctx(manifest, links=[link("SAF-01", "documented_execution")])
    s1 = CriterionState()
    rules.gate_coverage(single, s1, {})
    rules.conf_evidence(single, s1, {})
    three = ctx(
        manifest,
        links=[
            link("SAF-01", "documented_execution"),
            link(
                "SAF-01",
                "documented_execution",
                publisher="press.example",
                publisher_type="press",
                independence="independent",
            ),
            link(
                "SAF-01",
                "documented_execution",
                publisher="sec.gov",
                publisher_type="regulator_record",
                independence="regulator",
                tier="T1",
            ),
        ],
    )
    s3 = CriterionState()
    rules.gate_coverage(three, s3, {})
    rules.conf_evidence(three, s3, {})
    assert s3.confidence > s1.confidence + 15


def test_decay_is_applied_in_confidence(manifest: Manifest) -> None:
    fresh = ctx(manifest, links=[link("SAF-01", "documented_execution", published=date(2026, 10, 1))])
    old = ctx(manifest, links=[link("SAF-01", "documented_execution", published=date(2025, 1, 1))])
    undated = ctx(manifest, links=[link("SAF-01", "documented_execution", published=None)])
    confs = []
    for c in (fresh, old, undated):
        s = CriterionState()
        rules.gate_coverage(c, s, {})
        rules.conf_evidence(c, s, {})
        confs.append(s.confidence)
    assert confs[0] > confs[1] and confs[0] > confs[2]


def test_omissions_and_second_opinion_lower_confidence(manifest: Manifest) -> None:
    strong = [
        link(
            "SAF-01",
            "documented_execution",
            publisher=f"{i}.example",
            execution="verified",
            published=date(2026, 10, 1),
        )
        for i in range(3)
    ]
    base = ctx(manifest, links=strong)
    s0 = CriterionState()
    rules.gate_coverage(base, s0, {})
    rules.conf_evidence(base, s0, {})
    omitted = ctx(manifest, links=strong, omitted=5)
    s1 = CriterionState()
    rules.gate_coverage(omitted, s1, {})
    rules.conf_evidence(omitted, s1, {})
    assert s1.confidence == pytest.approx(s0.confidence - 5)
    disagree = ctx(manifest, links=strong, finding=FrozenFinding(4, (), (), 0.1, "m", second_opinion_level=1))
    s2 = CriterionState()
    rules.gate_coverage(disagree, s2, {})
    rules.conf_evidence(disagree, s2, {})
    assert s2.confidence == pytest.approx(max(0.0, s0.confidence - 15)) and any(
        f.startswith("second_opinion_disagreement") for f in s2.review_flags
    )


def test_contradiction_lowers_confidence(manifest: Manifest) -> None:
    c = ctx(
        manifest,
        links=[
            link("SAF-01", "documented_execution"),
            link("SAF-01", "none", polarity="contradicts", publisher_type="press"),
        ],
    )
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.conf_evidence(c, state, {})
    before = state.confidence
    rules.conf_contradiction(c, state, {})
    assert state.confidence == max(0.0, before - 10)


# ------------------------------------------------------------------------ scoring
def _states(
    manifest: Manifest, level: int, coverage: str = "observed", confidence: float = 80.0
) -> list[tuple[CriterionDef, CriterionState]]:
    return [(c, CriterionState(level=level, coverage_state=coverage, confidence=confidence)) for c in manifest.criteria]


def test_all_level_five_scores_one_hundred(manifest: Manifest) -> None:
    result = aggregate(manifest.methodology, manifest.pillars, _states(manifest, 5))
    assert result.hai_score == 100.0 and result.confidence_pct == 80.0 and result.counted == 20
    assert all(p.score == 100.0 for p in result.pillars)
    assert criterion_ratio(1, manifest.methodology) == 0.0 and criterion_ratio(3, manifest.methodology) == 0.5


def test_all_level_one_scores_zero(manifest: Manifest) -> None:
    assert aggregate(manifest.methodology, manifest.pillars, _states(manifest, 1)).hai_score == 0.0


def test_unavailable_criteria_are_excluded_not_zeroed(manifest: Manifest) -> None:
    states = _states(manifest, 5)
    for i, (crit, _st) in enumerate(states):
        if crit.pillar == "IMP":
            states[i] = (crit, CriterionState(level=None, coverage_state="unavailable", confidence=0.0))
    result = aggregate(manifest.methodology, manifest.pillars, states)
    assert result.hai_score == 100.0 and result.excluded == 4 and result.counted == 16
    imp = next(p for p in result.pillars if p.code == "IMP")
    assert imp.counted == 0 and imp.excluded == 4
    # zeroing them instead would have cost the whole Impact weight
    zeroed = _states(manifest, 5)
    for i, (crit, _st) in enumerate(zeroed):
        if crit.pillar == "IMP":
            zeroed[i] = (crit, CriterionState(level=1, coverage_state="missing", confidence=0.0))
    assert aggregate(manifest.methodology, manifest.pillars, zeroed).hai_score == 80.0


def test_missing_criteria_count_against_the_score(manifest: Manifest) -> None:
    states = _states(manifest, 3)
    states[0] = (states[0][0], CriterionState(level=1, coverage_state="missing", confidence=0.0))
    result = aggregate(manifest.methodology, manifest.pillars, states)
    assert result.hai_score is not None and result.hai_score < 50.0 and result.counted == 20


def test_pillar_weights_carry_phase6_pillar_max_in_scoring(manifest: Manifest) -> None:
    states = _states(manifest, 1)
    states = [
        (c, CriterionState(level=5, coverage_state="observed", confidence=80) if c.pillar == "TRU" else st)
        for c, st in states
    ]
    result = aggregate(manifest.methodology, manifest.pillars, states)
    assert result.hai_score == 20.0  # Trust is worth 20 of 100 points


def test_materiality_weighting_is_switchable(manifest: Manifest) -> None:
    weighted = manifest.methodology.model_copy(
        update={
            "scoring": manifest.methodology.scoring.model_copy(update={"pillar_aggregation": "materiality_weighted"})
        }
    )
    states = _states(manifest, 1)
    saf = [c for c in manifest.criteria if c.pillar == "SAF"]
    states = [
        (c, CriterionState(level=5, coverage_state="observed", confidence=80) if c.code == saf[0].code else st)
        for c, st in states
    ]
    equal = aggregate(manifest.methodology, manifest.pillars, states).hai_score
    mat = aggregate(weighted, manifest.pillars, states).hai_score
    assert equal is not None and mat is not None and mat != equal  # SAF-01 weighs 1.4 of 4.0 instead of 1 of 3


def test_effectiveness_is_the_share_proven_in_practice(manifest: Manifest) -> None:
    states = _states(manifest, 4)
    ranks = [3 if i < 5 else 1 for i in range(20)]
    result = aggregate(manifest.methodology, manifest.pillars, states, effectiveness_ranks=ranks)
    assert result.effectiveness == 25.0


# --------------------------------------------------------------------- the engine
def _full_outcomes(manifest: Manifest, engine: RuleEngine, *, blocked: bool = False) -> list[Any]:
    outcomes = []
    cr = runs(WEBSITE="blocked" if blocked else "succeeded", NEWS="succeeded", EDGAR="succeeded")
    for crit in manifest.criteria:
        links = (
            []
            if blocked
            else [link(crit.code, "documented_execution" if crit.pillar in ("SAF", "ACC") else "stated_commitment")]
        )
        outcomes.append(engine.run_criterion(ctx(manifest, crit.code, links=links, connector_runs=cr)))
    return outcomes


def test_rules_run_in_methodology_order_and_trace_everything(manifest: Manifest, engine: RuleEngine) -> None:
    outcome = engine.run_criterion(ctx(manifest, links=[link("SAF-01", "documented_execution")]))
    assert outcome.applied_rule_codes == engine.criterion_rule_codes
    assert [t.rule_code for t in outcome.trace] == outcome.applied_rule_codes
    assert all(t.note for t in outcome.trace) and all("level" in t.before and "level" in t.after for t in outcome.trace)
    assert outcome.state.level == 4 and outcome.state.coverage_state == "observed"


def test_assessment_rules_and_outcome_status(manifest: Manifest, engine: RuleEngine) -> None:
    outcomes = _full_outcomes(manifest, engine)
    result = engine.run_assessment(
        outcomes,
        stage_band="growth",
        size_band="mid",
        certification_requested=False,
        signed_certification=False,
        connector_runs=runs(WEBSITE="succeeded"),
        incidents=(),
        as_of=AS_OF,
    )
    st = result.state
    assert st.hai_score is not None and 0 < st.hai_score <= 85
    assert (
        next(t.rule_code for t in result.trace) == "SCORING" and result.applied_rule_codes[-1] == "GATE-OUTCOME-STATUS"
    )
    assert st.outcome_status in ("confidence_too_low", "certification_not_yet_achieved")
    assert st.threshold_applied == 70


def test_score_ceiling_and_low_confidence_cap(manifest: Manifest, engine: RuleEngine) -> None:
    outcomes = []
    for crit in manifest.criteria:
        outcomes.append(
            engine.run_criterion(
                ctx(
                    manifest,
                    crit.code,
                    links=[
                        link(
                            crit.code,
                            "independently_verified",
                            independence="regulator",
                            publisher_type="regulator_record",
                            tier="T1",
                            publisher=f"{i}.gov",
                            evidence_class="external_validation",
                            execution="verified",
                            published=date(2026, 10, 1),
                        )
                        for i in range(3)
                    ],
                    finding=FrozenFinding(5, (), (), 0.1, "m"),
                )
            )
        )
    result = engine.run_assessment(
        outcomes,
        stage_band="growth",
        size_band="mid",
        certification_requested=True,
        signed_certification=False,
        connector_runs=runs(WEBSITE="succeeded"),
        incidents=(),
        as_of=AS_OF,
    )
    assert (
        result.state.score_before_caps == 100.0
        and result.state.hai_score == 85.0
        and "CAP-SCORE-CEILING" in result.state.caps_applied
    )
    assert result.state.confidence_pct is not None and result.state.confidence_pct >= 70
    assert result.state.certification_eligible is True and "certification:requested" in result.state.review_triggers
    assert result.state.outcome_status == "certification_not_yet_achieved"
    signed = engine.run_assessment(
        outcomes,
        stage_band="growth",
        size_band="mid",
        certification_requested=True,
        signed_certification=True,
        connector_runs=runs(WEBSITE="succeeded"),
        incidents=(),
        as_of=AS_OF,
    )
    assert signed.state.outcome_status == "hai_certified"


def test_blocked_sources_are_unavailable_not_missing_in_the_engine(manifest: Manifest, engine: RuleEngine) -> None:
    outcomes = _full_outcomes(manifest, engine, blocked=True)
    assert all(o.state.coverage_state == "unavailable" and o.state.level is None for o in outcomes)
    result = engine.run_assessment(
        outcomes,
        stage_band="growth",
        size_band="mid",
        certification_requested=False,
        signed_certification=False,
        connector_runs=runs(WEBSITE="blocked"),
        incidents=(),
        as_of=AS_OF,
    )
    assert result.state.outcome_status == "access_limited" and result.state.hai_score is None


def test_governance_baseline_and_insufficient_evidence(manifest: Manifest, engine: RuleEngine) -> None:
    outcomes = [
        engine.run_criterion(
            ctx(manifest, c.code, links=[link(c.code, "none", polarity="contradicts")] if c.code == "SAF-01" else [])
        )
        for c in manifest.criteria
    ]
    result = engine.run_assessment(
        outcomes,
        stage_band="growth",
        size_band="mid",
        certification_requested=False,
        signed_certification=False,
        connector_runs=runs(WEBSITE="succeeded"),
        incidents=(),
        as_of=AS_OF,
    )
    assert result.state.hai_score == 0.0 and result.state.outcome_status == "governance_baseline"
    few = [
        engine.run_criterion(
            ctx(
                manifest,
                c.code,
                links=[link(c.code, "stated_commitment")] if c.code in ("SAF-01", "SAF-02") else [],
                connector_runs=runs(WEBSITE="blocked"),
            )
        )
        for c in manifest.criteria
    ]
    r2 = engine.run_assessment(
        few,
        stage_band="growth",
        size_band="mid",
        certification_requested=False,
        signed_certification=False,
        connector_runs=runs(WEBSITE="blocked"),
        incidents=(),
        as_of=AS_OF,
    )
    assert r2.state.outcome_status in ("access_limited", "insufficient_evidence")


def test_replay_matches_stored_result(manifest: Manifest, engine: RuleEngine) -> None:
    def run() -> str:
        outcomes = _full_outcomes(manifest, engine)
        result = engine.run_assessment(
            outcomes,
            stage_band="growth",
            size_band="mid",
            certification_requested=False,
            signed_certification=False,
            connector_runs=runs(WEBSITE="succeeded"),
            incidents=(),
            as_of=AS_OF,
        )
        return result.result_hash(methodology_version="1.0.0", ruleset_version="1.0.0", snapshot_sha256="snap")

    assert run() == run()
