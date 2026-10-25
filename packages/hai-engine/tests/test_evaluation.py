"""Classification, packs, validator, heuristic provider, prompts and the evaluation loop."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hai_core.generated.enums import EvidenceClass, ExecutionLevel, MaturityRung
from hai_engine.classification import LinkClassifier
from hai_engine.evaluation import Evaluator
from hai_engine.llm.base import ProviderError, ProviderResponse
from hai_engine.llm.heuristic import HeuristicProvider, propose_from_ladder
from hai_engine.llm.prompts import PromptBundle, build_messages
from hai_engine.packs import EvidencePack, build_all_packs, build_pack
from hai_engine.validation import FindingValidator
from hai_ontology.meta import CriterionDef, Manifest


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
