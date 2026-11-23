"""Classification, packs, validator, heuristic provider, prompts and the evaluation loop."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hai_core.generated.enums import EvidenceClass, ExecutionLevel, MaturityRung
from hai_engine.classification import Classification, LinkClassifier
from hai_engine.evaluation import Evaluator
from hai_engine.llm.base import ProviderError, ProviderResponse
from hai_engine.llm.heuristic import HeuristicProvider, propose_from_ladder
from hai_engine.llm.prompts import PromptBundle, build_messages
from hai_engine.packs import EvidencePack, build_all_packs, build_pack
from hai_engine.validation import FindingValidator
from hai_ontology.meta import CriterionDef, Manifest
from hai_pipeline.proposals import heuristic_proposals


# --------------------------------------------------------------- classification
def test_metadata_is_not_evidence(manifest: Manifest) -> None:
    c = LinkClassifier(manifest.methodology)
    for quote in ("Responsible AI Policy", "AI Governance Report 2025", "2025-06-30", "SOC 2 Type II"):
        result = c.classify(quote, polarity="supports", publisher_type="org_disclosure", independence="self")
        assert result.maturity_rung is MaturityRung.NONE, quote


def test_commitment_language_is_a_stated_commitment(manifest: Manifest) -> None:
    c = LinkClassifier(manifest.methodology)
    r = c.classify(
        "We are committed to developing AI that is safe, fair and accountable for every user.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
    )
    assert r.maturity_rung is MaturityRung.STATED_COMMITMENT and r.execution_level is ExecutionLevel.NONE


def test_owner_and_threshold_is_a_specified_control(manifest: Manifest) -> None:
    c = LinkClassifier(manifest.methodology)
    r = c.classify(
        "Our Chief AI Officer owns AI risk management; every release is reviewed against a 2% disparate impact threshold.",  # noqa: E501
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
    )
    assert r.maturity_rung is MaturityRung.SPECIFIED_CONTROL and r.evidence_class is EvidenceClass.OPERATIONAL_EVIDENCE
    owner_only = c.classify(
        "Our Chief AI Officer is responsible for AI risk across the company and its products.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
    )
    assert owner_only.maturity_rung is not MaturityRung.SPECIFIED_CONTROL


def test_dated_results_are_documented_execution(manifest: Manifest) -> None:
    c = LinkClassifier(manifest.methodology)
    r = c.classify(
        "In Q2 2025 the AI Governance Committee completed 14 model reviews and resolved 3 incidents reported.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
    )
    assert r.maturity_rung is MaturityRung.DOCUMENTED_EXECUTION and r.execution_level in (
        ExecutionLevel.PARTIAL,
        ExecutionLevel.VERIFIED,
    )


def test_documented_procedure_and_owner_do_not_need_a_numeric_threshold(manifest: Manifest) -> None:
    methodology = manifest.methodology.model_copy(deep=True)
    methodology.lexicons.control.procedure_terms[:] = ["requires human approval"]
    c = LinkClassifier(methodology)
    result = c.classify(
        "Our accountable executive requires human approval before high-risk AI deployments proceed.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
    )
    assert result.maturity_rung is MaturityRung.SPECIFIED_CONTROL
    assert result.evidence_class is EvidenceClass.OPERATIONAL_EVIDENCE
    assert result.execution_level is not ExecutionLevel.VERIFIED
    # A procedure without an assigned owner does not establish accountability.
    unowned = c.classify(
        "The deployment process requires human approval before high-risk AI systems go live.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
    )
    assert unowned.maturity_rung is not MaturityRung.SPECIFIED_CONTROL
    # Older manifests without procedure terms retain their numeric-threshold requirement.
    methodology.lexicons.control.procedure_terms.clear()
    legacy = LinkClassifier(methodology).classify(
        "Our accountable executive requires human approval before high-risk AI deployments proceed.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
    )
    assert legacy.maturity_rung is not MaturityRung.SPECIFIED_CONTROL


@pytest.mark.parametrize(
    "quote",
    [
        "Our mission is to provide an independent, evidence-based standard for evaluating whether organizations "
        "develop, deploy, and govern AI responsibly and in alignment with human values.",
        "Transparency Notes are created to help customers understand our AI systems and make informed choices.",
        "Identified weaknesses, assessment errors, and material governance concerns are addressed through "
        "documented review and appropriate corrective action.",
        "Material findings, assessment errors, methodology changes, and corrective actions are subject to "
        "documented oversight.",
    ],
)
def test_factual_mission_and_governance_statements_receive_baseline_credit(manifest: Manifest, quote: str) -> None:
    result = LinkClassifier(manifest.methodology).classify(
        quote, polarity="supports", publisher_type="org_disclosure", independence="self"
    )
    assert result.maturity_rung is MaturityRung.STATED_COMMITMENT
    assert result.evidence_class in (EvidenceClass.CORE_GOVERNANCE, EvidenceClass.FOUNDATIONAL_GOVERNANCE)


def test_designated_human_oversight_and_defined_review_are_a_documented_control(manifest: Manifest) -> None:
    result = LinkClassifier(manifest.methodology).classify(
        "Designated human oversight is responsible for reviewing material findings, identifying potential conflicts, "
        "and ensuring that certification decisions follow approved standards.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
    )
    assert result.maturity_rung is MaturityRung.SPECIFIED_CONTROL


def test_generic_assessment_business_description_is_not_operational_proof(manifest: Manifest) -> None:
    quote = (
        "While many organizations have published AI principles and governance policies, few have a consistent, "
        "evidence-based method for measuring whether those commitments are reflected in practice. Humaital was "
        "created to address that gap by providing an independent assessment of publicly available evidence across "
        "six foundational human pillars: Trust, Purpose, Safety, Transparency, Accountability, and Impact."
    )
    result = LinkClassifier(manifest.methodology).classify(
        quote, polarity="supports", publisher_type="org_disclosure", independence="self"
    )
    assert result.maturity_rung is MaturityRung.STATED_COMMITMENT


def test_financial_operations_do_not_establish_ai_safety_execution(manifest: Manifest) -> None:
    result = LinkClassifier(manifest.methodology).classify(
        "Financial risk management within the Group is governed by policies reviewed by the Board of Directors. "
        "Policy implementation and day-to-day risk management are carried out by the treasury functions and "
        "regular reporting on these risks is performed by the relevant accounting and controlling functions.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
        criterion=manifest.criterion("SAF-01"),
        section_heading="Financial risk management",
        document_title="Risk management",
    )
    # Decision D14: general governance can document a control. It never proves AI execution.
    assert result.maturity_rung in (MaturityRung.STATED_COMMITMENT, MaturityRung.SPECIFIED_CONTROL)
    assert "general operational or financial evidence does not establish AI execution" in result.reasons


def test_operational_metrics_under_ai_heading_keep_their_context(manifest: Manifest) -> None:
    result = LinkClassifier(manifest.methodology).classify(
        "In Q2 2025 the committee completed 14 risk reviews and resolved 3 incidents reported.",
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
        criterion=manifest.criterion("SAF-01"),
        section_heading="Responsible AI risk management",
    )
    assert result.maturity_rung is MaturityRung.DOCUMENTED_EXECUTION


def test_independent_verification_needs_an_independent_source(manifest: Manifest) -> None:
    c = LinkClassifier(manifest.methodology)
    quote = "An independent audit in March 2026 confirmed that the model risk controls operate as designed."
    self_published = c.classify(quote, polarity="supports", publisher_type="org_disclosure", independence="self")
    assert self_published.maturity_rung is not MaturityRung.INDEPENDENTLY_VERIFIED
    regulator = c.classify(quote, polarity="supports", publisher_type="regulator_record", independence="regulator")
    assert (
        regulator.maturity_rung is MaturityRung.INDEPENDENTLY_VERIFIED
        and regulator.evidence_class is EvidenceClass.EXTERNAL_VALIDATION
    )
    # tier alone changes nothing: a T1 publisher that is the organization itself stays self
    own_t1 = c.classify(quote, polarity="supports", publisher_type="regulator_record", independence="self")
    assert own_t1.maturity_rung is not MaturityRung.INDEPENDENTLY_VERIFIED


def test_contradicting_links_earn_no_rung(manifest: Manifest) -> None:
    c = LinkClassifier(manifest.methodology)
    r = c.classify(
        "In Q2 2025 the committee completed 14 model reviews and resolved 3 incidents reported.",
        polarity="contradicts",
        publisher_type="press",
        independence="independent",
    )
    assert r.maturity_rung is MaturityRung.NONE


def test_execution_is_per_span(manifest: Manifest) -> None:
    c = LinkClassifier(manifest.methodology)
    audited = c.classify(
        "ISO 42001 certified after an independent audit completed in 2025 by an accredited body.",
        polarity="supports",
        publisher_type="standards_registry",
        independence="independent",
    )
    plain = c.classify(
        "We believe AI should serve people and we are committed to that mission every day.",
        polarity="supports",
        publisher_type="standards_registry",
        independence="independent",
    )
    assert audited.execution_level is ExecutionLevel.VERIFIED and plain.execution_level is ExecutionLevel.NONE


# ------------------------------------------------------------------------ packs
def test_evidence_pack_is_per_criterion_and_counts_omissions(
    saf01: CriterionDef, sample_states: dict[str, dict[str, Any]], manifest: Manifest
) -> None:
    pack = build_pack(saf01, sample_states)
    assert pack.total_links == 5 and pack.inadmissible == 1
    assert len(pack.supporting) == 3 and len(pack.contradicting) == 1
    assert all(st["criterion_code"] == "SAF-01" for lid, st in sample_states.items() if lid in pack.shown_ids)
    assert "Ignore previous" not in json.dumps(pack.for_model())
    assert pack.supporting[0].maturity_rung == "documented_execution"  # ranked best first
    small = build_pack(saf01, sample_states, max_items=1)
    assert len(small.supporting) == 1 and small.omitted == 2
    packs = build_all_packs(list(manifest.criteria), sample_states)
    assert len(packs) == 20 and packs["TRU-03"].total_links == 1 and packs["IMP-01"].is_empty


def test_a_source_cluster_counts_once_in_packs(saf01: CriterionDef, make_link_state: Any) -> None:
    link_state = make_link_state
    a_id, a = link_state(
        "SAF-01",
        "Acme completed 14 model reviews in Q2 2025 and resolved 3 incidents reported.",
        maturity_rung="documented_execution",
        cluster_id="c1",
    )
    b_id, b = link_state(
        "SAF-01",
        "Acme completed fourteen model reviews in Q2 2025 and resolved three incidents.",
        maturity_rung="documented_execution",
        cluster_id="c1",
    )
    c_id, c = link_state("SAF-01", "We are committed to responsible AI.", maturity_rung="stated_commitment")
    pack = build_pack(saf01, {a_id: a, b_id: b, c_id: c})
    assert len(pack.supporting) == 2 and pack.omitted == 1


# -------------------------------------------------------------------- validator
def _good(pack: EvidencePack) -> dict[str, Any]:
    return propose_from_ladder(pack)


def test_a_good_finding_passes(pack: EvidencePack, validator: FindingValidator) -> None:
    result = validator.validate(_good(pack), pack, set(pack.shown_ids))
    assert result.ok and result.finding is not None and result.finding.proposed_level == 4


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d, p: d.update(proposed_level=9), "IC-05"),
        (lambda d, p: d.pop("uncertainty"), "IC-05"),
        (lambda d, p: d.update(criterion_code="TRU-03"), "IC-05"),
        (lambda d, p: d.update(evidence_link_ids=[], proposed_level=3), "IC-05"),
        (lambda d, p: d.update(evidence_link_ids=["11111111-1111-4111-8111-111111111111"]), "IC-04"),
        (lambda d, p: d.update(evidence_link_ids=list(p.contradicting_ids)), "IC-04"),
        (lambda d, p: d.update(contradicting_link_ids=list(p.supporting_ids)[:1]), "IC-04"),
        (
            lambda d, p: d.update(
                evidence_link_ids=[i.link_id for i in p.supporting if i.maturity_rung == "stated_commitment"],
                proposed_level=4,
            ),
            "IC-06",
        ),
        (lambda d, p: d.update(extra="field"), "IC-05"),
    ],
)
def test_bad_findings_are_rejected(pack: EvidencePack, validator: FindingValidator, mutate: Any, code: str) -> None:
    data = _good(pack)
    mutate(data, pack)
    result = validator.validate(data, pack, set(pack.shown_ids))
    assert not result.ok and code in result.codes, result.messages()


def test_citation_outside_the_snapshot(pack: EvidencePack, validator: FindingValidator) -> None:
    data = _good(pack)
    snapshot_ids = set(pack.shown_ids) - set(data["evidence_link_ids"][:1])
    result = validator.validate(data, pack, snapshot_ids)
    assert "IC-04" in result.codes and any("not in the evidence snapshot" in m for m in result.messages())


def test_quote_offsets_and_quotes(pack: EvidencePack, validator: FindingValidator) -> None:
    data = _good(pack)
    texts = {i.document_id: "x" * i.char_start + i.quote + " tail" for i in (*pack.supporting, *pack.contradicting)}
    assert validator.validate(data, pack, set(pack.shown_ids), text_loader=lambda d: texts.get(d)).ok
    broken = {k: v.replace("committed", "comitted").replace("Chief", "Chef") for k, v in texts.items()}
    result = validator.validate(data, pack, set(pack.shown_ids), text_loader=lambda d: broken.get(d))
    assert "IC-03" in result.codes


def test_non_json_output_is_rejected(pack: EvidencePack, validator: FindingValidator) -> None:
    assert validator.validate(None, pack, set(pack.shown_ids)).codes == {"IC-05"}


# -------------------------------------------------------------------- heuristic
def test_heuristic_provider_follows_the_ladder(
    manifest: Manifest, saf01: CriterionDef, validator: FindingValidator, make_link_state: Any
) -> None:
    link_state = make_link_state
    ranks = manifest.rung_ranks()
    for rung in ("none", "stated_commitment", "specified_control", "documented_execution", "independently_verified"):
        lid, st = link_state(
            "SAF-01",
            "Some supporting quote long enough to count as evidence here.",
            maturity_rung=rung,
            independence="regulator" if rung == "independently_verified" else "self",
        )
        pack = build_pack(saf01, {lid: st})
        proposal = propose_from_ladder(pack)
        assert proposal["proposed_level"] == saf01.level_for_rung(ranks[rung], ranks)
        assert validator.validate(proposal, pack, {lid}).ok
    empty = build_pack(saf01, {})
    assert propose_from_ladder(empty)["proposed_level"] == 1 and propose_from_ladder(empty)["evidence_link_ids"] == []


# ---------------------------------------------------------------------- prompts
def test_injection_never_reaches_the_model(
    pack: EvidencePack, prompt: PromptBundle, sample_states: dict[str, dict[str, Any]]
) -> None:
    messages = build_messages(prompt, pack)
    assert messages[0]["role"] == "system" and messages[1]["role"] == "user"
    system, user = messages[0]["content"], messages[1]["content"]
    # IC-17: no evidence text in the system instruction; evidence travels as JSON data
    for st in sample_states.values():
        assert st["quote"] not in system
    payload = json.loads(user)
    assert payload["task"] == "propose_criterion_finding" and "data" in payload
    assert "Ignore previous instructions" not in user  # inadmissible_untrusted links are never shown
    assert any("Chief AI Officer" in item["quote"] for item in payload["data"]["supporting_evidence"])


# --------------------------------------------------------------------- evaluator
class _ScriptedProvider:
    name = "scripted"
    model = "v1"

    def __init__(self, outputs: list[dict[str, Any] | Exception]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[str] | None] = []

    @property
    def model_id(self) -> str:
        return "scripted:v1"

    async def propose(
        self, pack: EvidencePack, prompt: PromptBundle, *, previous_errors: list[str] | None = None
    ) -> ProviderResponse:
        self.calls.append(previous_errors)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return ProviderResponse(raw=out, raw_text=json.dumps(out), provider=self.name, model=self.model)


async def test_retry_once_then_fall_back(pack: EvidencePack, prompt: PromptBundle, validator: FindingValidator) -> None:
    bad = {**_good(pack), "proposed_level": 5}  # IC-06: no cited quote reaches independently_verified
    scripted = _ScriptedProvider([bad, bad])
    ev = await Evaluator(provider=scripted, prompt=prompt, validator=validator, fallback=HeuristicProvider()).evaluate(
        pack, set(pack.shown_ids)
    )
    assert [a.accepted for a in ev.attempts] == [False, False, True]
    assert scripted.calls[1] and any("IC-06" in e for e in scripted.calls[1])  # the retry saw the errors
    assert ev.fell_back and ev.accepted is not None and ev.accepted.provider == "heuristic"
    assert any("fell back" in t for t in ev.trace)
    rejected = [a for a in ev.attempts if not a.accepted]
    assert all(a.raw is not None and a.errors for a in rejected)  # kept for audit, never used


async def test_provider_errors_are_recorded_and_second_opinion_disagreement(
    pack: EvidencePack, prompt: PromptBundle, validator: FindingValidator
) -> None:
    good = _good(pack)
    primary = _ScriptedProvider([ProviderError("boom"), good])
    second = _ScriptedProvider([{**good, "proposed_level": 2, "evidence_link_ids": good["evidence_link_ids"][:1]}])
    ev = await Evaluator(provider=primary, prompt=prompt, validator=validator, second_opinion=second).evaluate(
        pack, set(pack.shown_ids)
    )
    assert ev.accepted is not None and ev.accepted.attempt == 2 and not ev.fell_back
    assert ev.attempts[0].errors == ["provider error: boom"]
    assert ev.disagreement_levels == 2


# ------------------------------------------------------------- evidence guards (methodology 6.0.0, ADR 0021)


def _classify(manifest: Manifest, quote: str, code: str | None = None, **kw: object) -> Classification:
    return LinkClassifier(manifest.methodology).classify(
        quote,
        polarity="supports",
        publisher_type="org_disclosure",
        independence="self",
        criterion=manifest.criterion(code) if code else None,
        **kw,  # type: ignore[arg-type]
    )


def test_general_governance_documents_a_control_on_any_pillar_but_never_ai_execution(manifest: Manifest) -> None:
    quote = (
        "In 2025 the Audit Committee reviewed 14 ethics investigations and reported the results of each "
        "to the Board of Directors."
    )
    general = _classify(manifest, quote, "ACC-02", document_title="Proxy statement")
    assert general.maturity_rung is MaturityRung.SPECIFIED_CONTROL
    about_ai = _classify(manifest, quote, "ACC-02", section_heading="Responsible AI governance")
    assert about_ai.maturity_rung is MaturityRung.DOCUMENTED_EXECUTION


@pytest.mark.parametrize(
    "quote",
    [
        # a passing mention of AI is not the organization's AI practice
        "Ms. Mayer holds a degree in artificial intelligence and in 2025 completed 12 board assignments "
        "reviewed by the committee.",
        # a product name
        "In 2025 the committee reviewed and completed the sale of 40 Dazzle AI glasses to investors.",
    ],
)
def test_a_passing_mention_of_ai_does_not_open_the_execution_rung(manifest: Manifest, quote: str) -> None:
    assert _classify(manifest, quote).maturity_rung is not MaturityRung.DOCUMENTED_EXECUTION


def test_risk_factor_language_is_not_evidence(manifest: Manifest) -> None:
    quote = (
        "Our use of AI systems could adversely affect our business, and the Board reviews these risks; "
        "we may not be able to comply with new laws."
    )
    result = _classify(manifest, quote, "SAF-01")
    assert result.maturity_rung is MaturityRung.NONE
    proposals = heuristic_proposals(
        [quote], [manifest.criterion("SAF-01")], manifest.methodology, publisher_type="org_disclosure", source_tier="T3"
    )
    assert [p.polarity for p in proposals] == ["neutral"]


@pytest.mark.parametrize(
    "quote",
    [
        "KATHY N. WALLER  Executive Director of the Atlanta Committee for Progress; former CFO  67  2015  2  "
        "Audit Risk",
        "Security Ownership Of Certain Beneficial Owners And Management Risk Committee Review 54",
    ],
)
def test_table_rows_and_contents_lines_are_not_controls(manifest: Manifest, quote: str) -> None:
    assert _classify(manifest, quote, "SAF-01").maturity_rung is not MaturityRung.SPECIFIED_CONTROL


def test_owner_and_procedure_must_be_one_statement(manifest: Manifest) -> None:
    together = "The Risk Committee reviews enterprise risk assessments each quarter and reports to the full Board."
    assert _classify(manifest, together, "SAF-01").maturity_rung is MaturityRung.SPECIFIED_CONTROL
    apart = (
        "The Risk Committee met four times this year in person and by video conference, and its members "
        "are listed in the table that follows this paragraph together with their other board memberships; "
        "separately, suppliers are expected to manage risk and may be subject to audits."
    )
    assert _classify(manifest, apart, "SAF-01").maturity_rung is not MaturityRung.SPECIFIED_CONTROL


def test_the_organization_speaking_for_itself_can_document_a_control(manifest: Manifest) -> None:
    quote = "We review every supplier risk assessment before a contract is signed and escalate open findings."
    assert _classify(manifest, quote, "SAF-01").maturity_rung is MaturityRung.SPECIFIED_CONTROL


def test_a_control_must_speak_to_the_criterion_in_the_quote_itself(manifest: Manifest) -> None:
    quote = "The Compensation Committee reviews and approves the annual bonus plan for executive officers."
    under_heading = _classify(manifest, quote, "SAF-01", section_heading="Risk management")
    assert under_heading.maturity_rung is MaturityRung.STATED_COMMITMENT
    assert "does not speak to the criterion" in under_heading.reasons[-1]


def test_execution_needs_the_organizations_voice_and_no_reported_speech(manifest: Manifest) -> None:
    heading = {"section_heading": "Responsible AI"}
    own = "We completed 14 AI model reviews in 2026 and published the results for every AI system."
    assert _classify(manifest, own, **heading).maturity_rung is MaturityRung.DOCUMENTED_EXECUTION
    by_name = "In 2026 Acme completed 14 AI model reviews and published the results for every AI system."
    named = _classify(manifest, by_name, organization_names=("Acme",), **heading)
    assert named.maturity_rung is MaturityRung.DOCUMENTED_EXECUTION
    customer = (
        "Apollo Hospitals tracked 40 patient safety metrics after the AI system was deployed in 2026 "
        "and reported gains."
    )
    assert _classify(manifest, customer, **heading).maturity_rung is not MaturityRung.DOCUMENTED_EXECUTION
    quoted = "We completed 14 AI model reviews in 2026, said the chief executive of a partner company."
    assert _classify(manifest, quoted, **heading).maturity_rung is not MaturityRung.DOCUMENTED_EXECUTION


def test_a_counted_result_is_a_record_and_a_threshold_is_not(manifest: Manifest) -> None:
    counted = "We red team our AI models before release and completed 120 red team exercises across our AI systems."
    assert _classify(manifest, counted).maturity_rung is MaturityRung.DOCUMENTED_EXECUTION
    threshold = (
        "Our Chief AI Officer owns AI risk management; every release is reviewed against a 2% disparate "
        "impact threshold."
    )
    assert _classify(manifest, threshold).maturity_rung is MaturityRung.SPECIFIED_CONTROL
