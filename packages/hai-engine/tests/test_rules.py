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


def test_link_counts_only_for_its_criterion(manifest: Manifest) -> None:
    """IC-08: links reach only the criterion they name; a strong SAF-01 link never lifts SAF-02 (AT-02)."""
    from datetime import datetime as _dt
    from uuid import uuid4 as _uuid

    from hai_core.generated.enums import SizeBand, StageBand
    from hai_core.generated.models import Assessment, EvidenceSnapshot
    from hai_engine.decision import ReviewOverlay, build_contexts

    strong = link("SAF-01", "independently_verified", independence="independent", publisher_type="independent_audit")
    weak = link("SAF-02", "stated_commitment")
    states = {
        lk.link_id: {
            "criterion_code": lk.criterion_code,
            "polarity": lk.polarity,
            "admissibility": lk.admissibility,
            "maturity_rung": lk.maturity_rung,
            "execution_level": lk.execution_level,
            "evidence_class": lk.evidence_class,
            "independence": lk.independence,
            "source_tier": lk.source_tier,
            "publisher_type": lk.publisher_type,
            "publisher_domain": lk.publisher_domain,
            "cluster_id": lk.cluster_id,
            "document_id": lk.document_id,
            "span_id": lk.span_id,
            "published_at": lk.published_at.isoformat() if lk.published_at else None,
            "certificate_valid_until": None,
            "quote": lk.quote,
            "canonical_url": None,
            "document_title": None,
        }
        for lk in (strong, weak)
    }
    org = _uuid()
    assessment = Assessment(
        id=_uuid(),
        org_id=org,
        requested_by="pytest",
        submitted_domain="acme.example",
        stage_band=StageBand.GROWTH,
        size_band=SizeBand.MID,
        methodology_version="1.0.0",
        ruleset_version="1.0.0",
        prompt_version="1.0.0",
        model_id="heuristic:ladder-1",
    )
    snapshot = EvidenceSnapshot(
        id=_uuid(),
        assessment_id=assessment.id,
        frozen_at=_dt(2026, 10, 24, tzinfo=UTC),
        manifest_hash="x" * 64,
        span_ids=[],
        link_ids=[],
        link_states=states,
        incident_states={},
        connector_runs={"WEBSITE": {"succeeded": True, "failed_or_blocked": False, "items_returned": 2}},
        version_pins={},
        snapshot_sha256="y" * 64,
    )
    contexts = {c.criterion.code: c for c in build_contexts(manifest, assessment, snapshot, {}, ReviewOverlay())}
    assert [lk.link_id for lk in contexts["SAF-01"].links] == [strong.link_id]
    assert [lk.link_id for lk in contexts["SAF-02"].links] == [weak.link_id]
    assert all(not c.links for code, c in contexts.items() if code not in ("SAF-01", "SAF-02"))
    engine = RuleEngine(manifest)
    saf1 = engine.run_criterion(contexts["SAF-01"]).state
    saf2 = engine.run_criterion(contexts["SAF-02"]).state
    saf3 = engine.run_criterion(contexts["SAF-03"]).state
    assert saf1.level == 5 and saf2.level == 2 and saf3.level == 1 and saf3.coverage_state == "missing"


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


def legacy_confidence(manifest: Manifest) -> Manifest:
    """The manifest with the Phase 6 multiplicative confidence model switched on."""
    md = manifest.methodology
    legacy = md.model_copy(update={"confidence": md.confidence.model_copy(update={"model": "legacy_contribution"})})
    return manifest.model_copy(update={"methodology": legacy})


def test_confidence_formula(manifest: Manifest) -> None:
    from hai_core.freshness import decay_multiplier

    manifest = legacy_confidence(manifest)
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
    manifest = legacy_confidence(manifest)
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
    # 2.0.0 weights by materiality (the published report does); equal_mean is the spec's alternative
    assert manifest.methodology.scoring.pillar_aggregation == "materiality_weighted"
    weighted = manifest.methodology
    manifest = manifest.model_copy(
        update={
            "methodology": manifest.methodology.model_copy(
                update={"scoring": manifest.methodology.scoring.model_copy(update={"pillar_aggregation": "equal_mean"})}
            )
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


# ------------------------------------------------------------ AT-16: verification over assertion
from hai_engine.rules.context import FrozenControl, FrozenTestOutcome, TargetStates  # noqa: E402


def _control(control_id: str, *capabilities: str, monitoring: str | None = None) -> FrozenControl:
    return FrozenControl(
        control_id=control_id,
        name="Model kill switch",
        capabilities=tuple(capabilities),
        monitoring_mode=monitoring,
        operational_status="implemented",
        can_pause_or_rollback=None,
        ai_system_id=None,
    )


def _test(
    control_id: str, *capabilities: str, result: str = "pass", method: str | None = "live_drill"
) -> FrozenTestOutcome:
    return FrozenTestOutcome(
        test_id=str(uuid4()),
        control_id=control_id,
        result=result,
        method=method,
        capabilities_exercised=tuple(capabilities),
        threats_exercised=(),
        performed_at=date(2026, 6, 1),
        verifier_org_id=None,
    )


def _control_ctx(manifest: Manifest, targets: TargetStates, control_id: str) -> CriterionContext:
    base = ctx(manifest, links=[link("SAF-01", "documented_execution", execution="partial")])
    supporting = FrozenLink(**{**base.links[0].__dict__, "target_type": "control", "target_id": control_id})
    return CriterionContext(**{**base.__dict__, "links": (supporting,), "targets": targets})


def test_claimed_capability_without_exercise_is_capped(manifest: Manifest) -> None:
    """A control that says it can pause or roll back the system is documented, not verified, until a passing
    test exercised that capability (IC-19). Document review does not count as exercising."""
    control_id = str(uuid4())
    params = {"cap_level": 3, "capabilities": ["pause", "shutdown", "rollback", "isolate"]}
    claimed_only = TargetStates(controls={control_id: _control(control_id, "pause", "rollback")})
    c = _control_ctx(manifest, claimed_only, control_id)
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    assert state.level == 4  # the ladder alone allows documented execution
    note = rules.cap_unexercised_capability(c, state, params)
    assert state.level == 3 and "CAP-UNEXERCISED-CAPABILITY" in state.caps_applied and "capped" in note
    assert any(f.startswith("unexercised_capability:") for f in state.review_flags)
    # a document review is not an exercise; a failed drill is not either
    reviewed = TargetStates(
        controls={control_id: _control(control_id, "pause")},
        tests=(_test(control_id, "pause", method="document_review"), _test(control_id, "pause", result="fail")),
    )
    state = CriterionState()
    c = _control_ctx(manifest, reviewed, control_id)
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    rules.cap_unexercised_capability(c, state, params)
    assert state.level == 3
    # a passing live drill of the claimed capability lifts the cap
    exercised = TargetStates(controls={control_id: _control(control_id, "pause")}, tests=(_test(control_id, "pause"),))
    state = CriterionState()
    c = _control_ctx(manifest, exercised, control_id)
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    note = rules.cap_unexercised_capability(c, state, params)
    assert state.level == 4 and not state.caps_applied and "no control claims" in note
    # a control without a stopping capability is not affected
    other = TargetStates(controls={control_id: _control(control_id, "rate_limit")})
    state = CriterionState()
    c = _control_ctx(manifest, other, control_id)
    rules.gate_coverage(c, state, {})
    rules.adj_start_from_finding(c, state, {})
    rules.cap_unexercised_capability(c, state, params)
    assert state.level == 4
    # the review trigger carries the criterion
    engine = RuleEngine(manifest)
    outcome = engine.run_criterion(_control_ctx(manifest, claimed_only, control_id))
    assert "CAP-UNEXERCISED-CAPABILITY" in outcome.applied_rule_codes and outcome.state.level == 3
    result = engine.run_assessment(
        [outcome],
        stage_band="growth",
        size_band="mid",
        certification_requested=False,
        signed_certification=False,
        connector_runs=runs(WEBSITE="succeeded"),
        incidents=(),
        as_of=AS_OF,
    )
    assert "verification:SAF-01" in result.state.review_triggers


def test_confidence_components_follow_the_published_weights(manifest: Manifest) -> None:
    """Confidence is the published decomposition: credibility 40, evidence type 30, cross-source 20, recency 10."""
    from hai_core.freshness import decay_multiplier

    md = manifest.methodology
    comps = md.confidence.components
    assert md.confidence.model == "components"
    assert comps.weights == {
        "source_credibility": 0.40,
        "evidence_type": 0.30,
        "cross_source_validation": 0.20,
        "recency": 0.10,
    }
    # one policy quote from the organization's own website, undated: the profile of the published report
    c = ctx(manifest, links=[link("SAF-01", "stated_commitment", published=None)])
    state = CriterionState()
    rules.gate_coverage(c, state, {})
    rules.conf_evidence(c, state, {})
    decay = decay_multiplier(md, "org_disclosure", None, AS_OF)
    expected = 0.4 * 60 + 0.3 * comps.evidence_type_credit["stated_commitment"] * 100 + 0.2 * 0 + 0.1 * decay * 100
    assert state.confidence == pytest.approx(expected, abs=0.1)
    assert 35 <= state.confidence <= 45  # the published website-only profile lands near 41
    assert state.confidence_components["cross_source_validation"] == 0
    # stated commitment, documented control, test result and independent verification earn strictly more
    ladder = ["stated_commitment", "specified_control", "documented_execution", "independently_verified"]
    confs = []
    for rung in ladder:
        kwargs: dict[str, Any] = {}
        if rung == "independently_verified":
            kwargs = {
                "publisher_type": "regulator_record",
                "independence": "regulator",
                "tier": "T1",
                "publisher": "sec.gov",
            }
        c = ctx(manifest, links=[link("SAF-01", rung, published=date(2026, 10, 1), **kwargs)])
        s_ = CriterionState()
        rules.gate_coverage(c, s_, {})
        rules.conf_evidence(c, s_, {})
        confs.append(s_.confidence)
    assert confs == sorted(confs) and len(set(confs)) == len(confs)
    # three distinct sources earn the full cross-source component; ten syndicated copies count once (IC-09)
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
                publisher="research.example",
                publisher_type="academic_research",
                independence="independent",
                tier="T2",
            ),
        ],
    )
    s3 = CriterionState()
    rules.gate_coverage(three, s3, {})
    rules.conf_evidence(three, s3, {})
    assert s3.confidence_components["cross_source_validation"] == 100
    copies = ctx(
        manifest,
        links=[link("SAF-01", "documented_execution", publisher=f"copy{i}.example", cluster="c1") for i in range(10)],
    )
    sc = CriterionState()
    rules.gate_coverage(copies, sc, {})
    rules.conf_evidence(copies, sc, {})
    assert sc.confidence_components["cross_source_validation"] == 0
    # no admissible support: zero, with every component recorded
    empty = CriterionState()
    rules.gate_coverage(ctx(manifest), empty, {})
    rules.conf_evidence(ctx(manifest), empty, {})
    assert empty.confidence == 0 and set(comps.weights) <= set(empty.confidence_components)


def test_pillar_status_follows_the_rung_reached_by_half_the_criteria(manifest: Manifest) -> None:
    from hai_engine.scoring import maturity_status_for

    rank = dict(rules._RUNGS)
    assert maturity_status_for([]) is None
    assert maturity_status_for([rank["none"], rank["none"], rank["none"]]) == "needs_attention"
    # three criteria: policy, policy, control -> at least half reach stated_commitment -> developing
    assert (
        maturity_status_for([rank["stated_commitment"], rank["stated_commitment"], rank["specified_control"]])
        == "developing"
    )
    # one verified criterion does not make a pillar strong
    assert maturity_status_for([rank["independently_verified"], rank["none"], rank["none"]]) == "needs_attention"
    # two of four with execution -> progressing; three of four verified -> strong
    assert (
        maturity_status_for(
            [rank["documented_execution"], rank["documented_execution"], rank["none"], rank["stated_commitment"]]
        )
        == "progressing"
    )
    assert maturity_status_for([rank["independently_verified"]] * 3 + [rank["none"]]) == "strong"
    # through aggregate: statuses ride on the pillar results and the report wording comes from the vocabulary
    states = _states(manifest, 3)
    ranks = [rank["documented_execution"] if c.pillar == "SAF" else rank["stated_commitment"] for c, _ in states]
    result = aggregate(manifest.methodology, manifest.pillars, states, effectiveness_ranks=ranks)
    by_code = {p.code: p.status for p in result.pillars}
    assert by_code["SAF"] == "progressing" and by_code["TRU"] == "developing"


def test_incident_response_without_verified_correction_routes_to_review(manifest: Manifest) -> None:
    substantiated = incident("SAF-01", "substantiated", "high")
    uncorrected = ctx(manifest, incidents=[substantiated])
    state = CriterionState()
    note = rules.gate_incident_response(uncorrected, state, {})
    assert f"uncorrected_incident:{substantiated.incident_id}" in state.review_flags and "not corrected" in note
    corrected = FrozenIncident(**{**substantiated.__dict__, "corrected_at": date(2026, 5, 1)})
    state = CriterionState()
    rules.gate_incident_response(ctx(manifest, incidents=[corrected]), state, {})
    assert f"unverified_correction:{substantiated.incident_id}" in state.review_flags
    verified = FrozenIncident(
        **{**corrected.__dict__, "correction_verified_at": date(2026, 6, 1), "correction_verified_by": str(uuid4())}
    )
    state = CriterionState()
    note = rules.gate_incident_response(ctx(manifest, incidents=[verified]), state, {})
    assert not state.review_flags and "no substantiated incident awaits" in note
    # alleged incidents are IC-11's business, not this gate's
    state = CriterionState()
    rules.gate_incident_response(ctx(manifest, incidents=[incident("SAF-01", "alleged", "high")]), state, {})
    assert not state.review_flags
    # the trigger names the incident
    engine = RuleEngine(manifest)
    outcome = engine.run_criterion(uncorrected)
    result = engine.run_assessment(
        [outcome],
        stage_band="growth",
        size_band="mid",
        certification_requested=False,
        signed_certification=False,
        connector_runs=runs(WEBSITE="succeeded"),
        incidents=(substantiated,),
        as_of=AS_OF,
    )
    assert f"incident_response:{substantiated.incident_id}" in result.state.review_triggers


def test_self_reported_monitoring_routes_to_review(manifest: Manifest) -> None:
    system_id = str(uuid4())
    from hai_engine.rules.context import FrozenSystem

    def system(mode: str | None) -> TargetStates:
        return TargetStates(systems={system_id: FrozenSystem(system_id, "Agent", "bounded_autonomous", mode, None)})

    base = ctx(manifest, "SAF-02", links=[link("SAF-02", "documented_execution")])
    supporting = FrozenLink(**{**base.links[0].__dict__, "target_type": "ai_system", "target_id": system_id})
    for mode, flagged in (
        ("self_explanation", True),
        ("operator_logs", False),
        ("independent_recording", False),
        (None, False),
    ):
        c = CriterionContext(**{**base.__dict__, "links": (supporting,), "targets": system(mode)})
        state = CriterionState()
        rules.gate_coverage(c, state, {})
        rules.gate_self_reported_monitoring(c, state, {})
        assert ("self_reported_monitoring" in state.review_flags) is flagged, mode


def test_certification_needs_evidence_in_every_pillar(manifest: Manifest, engine: RuleEngine) -> None:
    assert manifest.methodology.certification.require_evidence_in_every_pillar
    outcomes = []
    cr = runs(WEBSITE="succeeded", NEWS="succeeded", EDGAR="succeeded")
    for crit in manifest.criteria:
        links = (
            []
            if crit.pillar == "IMP"
            else [
                link(
                    crit.code,
                    "independently_verified",
                    publisher="sec.gov",
                    publisher_type="regulator_record",
                    independence="regulator",
                    tier="T1",
                )
            ]
        )
        outcomes.append(engine.run_criterion(ctx(manifest, crit.code, links=links, connector_runs=cr)))
    result = engine.run_assessment(
        outcomes,
        stage_band="growth",
        size_band="mid",
        certification_requested=False,
        signed_certification=False,
        connector_runs=cr,
        incidents=(),
        as_of=AS_OF,
    )
    assert any(r == "no admissible evidence in pillar IMP" for r in result.state.gate_reasons)
    assert not result.state.certification_eligible


def test_stage_profile_weights_are_switchable(manifest: Manifest) -> None:
    from hai_engine.scoring import pillar_weights

    md = manifest.methodology
    fixed = pillar_weights(md, manifest.pillars, "mature")
    assert fixed == {p.code: p.weight for p in manifest.pillars}  # mode fixed: the profile is recorded, not applied
    profiled = md.model_copy(
        update={
            "scoring": md.scoring.model_copy(
                update={
                    "pillar_weight_profiles": md.scoring.pillar_weight_profiles.model_copy(
                        update={"mode": "stage_profile"}
                    )
                }
            )
        }
    )
    mature = pillar_weights(profiled, manifest.pillars, "mature")
    assert mature == {"TRU": 0.18, "ACC": 0.20, "PUR": 0.12, "SAF": 0.18, "TRN": 0.17, "IMP": 0.15}  # HAI Report
    assert pillar_weights(profiled, manifest.pillars, "early") == fixed  # no profile: pillars.yaml
    states = _states(manifest, 1)
    states = [
        (c, CriterionState(level=5, coverage_state="observed", confidence=80) if c.pillar == "ACC" else st)
        for c, st in states
    ]
    assert aggregate(profiled, manifest.pillars, states, stage_band="mature").hai_score == 20.0
    assert aggregate(md, manifest.pillars, states, stage_band="mature").hai_score == 15.0
