"""Link classification from the quote and the publisher only.

Sets the maturity rung, the per-span execution level and the evidence class.
A title, label or date alone never lifts maturity above none (IC-06); the
independently verified rung needs an independent or regulator publisher
(IC-07); source tier never enters the decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from hai_core.generated.enums import (
    RANKS,
    EvidenceClass,
    ExecutionLevel,
    Independence,
    MaturityRung,
    PillarCode,
    Polarity,
    PublisherType,
)
from hai_core.signals import ExecutionSignal, LanguageSignals, SignalMatcher
from hai_ontology.meta import CriterionDef, Methodology
from hai_ontology.terms import compile_term, find_terms

MIN_WORDS_FOR_EVIDENCE = 6
EXTERNAL_PUBLISHERS = frozenset(
    {PublisherType.REGULATOR_RECORD, PublisherType.STANDARDS_REGISTRY, PublisherType.INDEPENDENT_AUDIT}
)
FOUNDATIONAL_TERMS = ("principles", "framework", "methodology", "charter", "code of conduct", "manifesto")


def _prose_share(quote: str) -> float:
    """The share of words that start in lower case. Running prose is mostly lower case; a table row,
    a list of names or a line of headings is not."""
    words = [w for w in quote.split() if w[:1].isalpha()]
    if not words:
        return 0.0
    return sum(1 for w in words if w[:1].islower()) / len(words)


@dataclass(frozen=True)
class Classification:
    maturity_rung: MaturityRung
    execution_level: ExecutionLevel
    evidence_class: EvidenceClass
    reasons: tuple[str, ...]


class LinkClassifier:
    def __init__(self, methodology: Methodology) -> None:
        self.matcher = SignalMatcher(methodology)

    def classify(
        self,
        quote: str,
        *,
        polarity: Polarity | str,
        publisher_type: PublisherType | str,
        independence: Independence | str,
        criterion: CriterionDef | None = None,
        section_heading: str | None = None,
        document_title: str | None = None,
        organization_names: tuple[str, ...] = (),
    ) -> Classification:
        pol = Polarity(polarity)
        ptype = PublisherType(publisher_type)
        indep = Independence(independence)
        signals = self.matcher.language(quote)
        execution = self.matcher.execution(quote)
        reasons: list[str] = []
        if execution.level in (ExecutionLevel.PARTIAL.value, ExecutionLevel.VERIFIED.value):
            without_dates = quote
            for term in signals.execution_dates:
                without_dates = compile_term(term).sub(" ", without_dates)
            if self.matcher.execution(without_dates).total_weight == 0:
                # A date can locate an alleged event, but cannot prove that an
                # operational control was exercised or that a test failed.
                execution = replace(execution, level=ExecutionLevel.ASSERTED.value)
                reasons.append("a calendar reference alone does not demonstrate operational execution")
        rung = self._rung(quote, pol, indep, signals, execution, reasons)
        rung = self._require_substance(rung, signals, criterion, quote, reasons, organization_names)
        rung = self._require_ai_context(rung, signals, criterion, quote, section_heading, document_title, reasons)
        evidence_class = self._evidence_class(ptype, indep, signals, quote, rung)
        return Classification(rung, ExecutionLevel(execution.level), evidence_class, tuple(reasons))

    def _require_substance(
        self,
        rung: MaturityRung,
        signals: LanguageSignals,
        criterion: CriterionDef | None,
        quote: str,
        reasons: list[str],
        organization_names: tuple[str, ...] = (),
    ) -> MaturityRung:
        """Guards on the control and execution rungs: prose, in the organization's own declarative
        voice, that itself speaks to the criterion, with the owner beside the procedure and the date
        beside the result. A passage that fails a guard keeps the credit of the rung below."""
        quality = self.matcher.lex.evidence_quality
        ranks = RANKS["maturity_rung"]
        if ranks[rung.value] < ranks[MaturityRung.STATED_COMMITMENT.value]:
            return rung
        if self.matcher.caution(quote):
            reasons.append("risk-factor language describes exposure, not a commitment or a control")
            return MaturityRung.NONE
        if ranks[rung.value] < ranks[MaturityRung.SPECIFIED_CONTROL.value]:
            return rung
        if rung is MaturityRung.INDEPENDENTLY_VERIFIED:
            return rung
        commitment = MaturityRung.STATED_COMMITMENT
        if len(quote.split()) < quality.min_words_for_control or _prose_share(quote) < quality.min_prose_share:
            reasons.append("a heading, list or table row does not describe a control or its operation")
            return commitment
        gate = quality.hint_in_quote_from_rung
        if (
            gate is not None
            and criterion is not None
            and ranks[rung.value] >= ranks[gate]
            and not self.matcher.hint_matches(quote, criterion)
        ):
            reasons.append("the section is relevant but the quote itself does not speak to the criterion")
            return commitment
        control = self._control_or_commitment(signals, quote, reasons)
        if rung is MaturityRung.SPECIFIED_CONTROL:
            return control
        # documented execution
        # The organization's voice: first person, its own name, or one of its accountable bodies
        # as the actor ("the AI Governance Committee completed 14 reviews").
        voice = [*quality.execution_voice_terms, *(re.escape(n) for n in organization_names if len(n) > 1)]
        if quality.execution_voice_terms and not (find_terms(quote, voice) or signals.owner):
            reasons.append("results are not stated in the organization's own voice")
            return control
        if find_terms(quote, quality.reported_speech_terms):
            reasons.append("a quotation of another party is not the organization's own record")
            return control
        if quality.execution_max_gap_chars is not None and signals.has_documented_execution:
            gap = self.matcher.execution_gap(quote, signals)
            if gap is None or gap > quality.execution_max_gap_chars:
                reasons.append("the date and the result are not part of one statement")
                return control
        return rung

    def _control_or_commitment(self, signals: LanguageSignals, quote: str, reasons: list[str]) -> MaturityRung:
        """A specified control when the owner stands beside the procedure; otherwise a commitment."""
        if not signals.has_specified_control:
            return MaturityRung.STATED_COMMITMENT
        limit = self.matcher.lex.evidence_quality.control_max_gap_chars
        if limit is None:
            return MaturityRung.SPECIFIED_CONTROL
        gap = self.matcher.control_gap(quote, signals)
        if gap is None or gap > limit:
            reasons.append("the accountable owner and the procedure are not part of one statement")
            return MaturityRung.STATED_COMMITMENT
        return MaturityRung.SPECIFIED_CONTROL

    def _require_ai_context(
        self,
        rung: MaturityRung,
        signals: LanguageSignals,
        criterion: CriterionDef | None,
        quote: str,
        section_heading: str | None,
        document_title: str | None,
        reasons: list[str],
    ) -> MaturityRung:
        """Hold a rung back to the level general governance can earn when the evidence is not about AI.

        The methodology names the rung from which AI context is required. Before 6.0.0 it named none
        and the check covered the Safety pillar's execution and verification rungs only.
        """
        lexicon = self.matcher.lex.ai_context
        if not lexicon.terms:
            return rung
        ranks = RANKS["maturity_rung"]
        if lexicon.required_from_rung is None:
            gated = (
                criterion is not None
                and criterion.pillar == PillarCode.SAF.value
                and rung in (MaturityRung.DOCUMENTED_EXECUTION, MaturityRung.INDEPENDENTLY_VERIFIED)
            )
            floor = ranks[MaturityRung.DOCUMENTED_EXECUTION.value]
        else:
            floor = ranks[lexicon.required_from_rung]
            gated = ranks[rung.value] >= floor
        if not gated:
            return rung
        context = " ".join(part for part in (quote, section_heading, document_title) if part)
        about_ai = (
            self.matcher.ai_context(context)
            if lexicon.required_from_rung is None
            else self.matcher.ai_practice(context)
        )
        if about_ai:
            return rung
        reasons.append("general operational or financial evidence does not establish AI execution")
        earned = MaturityRung.NONE
        for candidate, holds in (
            (MaturityRung.STATED_COMMITMENT, signals.has_commitment or signals.has_verification),
            (MaturityRung.SPECIFIED_CONTROL, signals.has_specified_control),
        ):
            if holds and ranks[candidate.value] < floor:
                earned = candidate
        if earned is MaturityRung.NONE and floor > ranks[MaturityRung.STATED_COMMITMENT.value]:
            # Dated results are at least a statement that the organization does this.
            earned = MaturityRung.STATED_COMMITMENT
        return earned

    def _rung(
        self,
        quote: str,
        polarity: Polarity,
        independence: Independence,
        signals: LanguageSignals,
        execution: ExecutionSignal,
        reasons: list[str],
    ) -> MaturityRung:
        if polarity is not Polarity.SUPPORTS:
            reasons.append("only supporting links earn maturity")
            return MaturityRung.NONE
        if len(quote.split()) < MIN_WORDS_FOR_EVIDENCE:
            reasons.append("a title, label or date alone is metadata, not evidence (IC-06)")
            return MaturityRung.NONE
        if signals.has_verification and independence in (Independence.INDEPENDENT, Independence.REGULATOR):
            reasons.append("independent verification language from an independent or regulator publisher (IC-07)")
            return MaturityRung.INDEPENDENTLY_VERIFIED
        operating_process = "process" in execution.categories and "control" in execution.categories
        if signals.has_documented_execution or (
            execution.level in ("partial", "verified") and (signals.execution_results or operating_process)
        ):
            reasons.append("dated results or execution artefacts in the quote")
            return MaturityRung.DOCUMENTED_EXECUTION
        if signals.has_specified_control:
            reasons.append("a named owner and a defined procedure or measurable threshold in the quote")
            return MaturityRung.SPECIFIED_CONTROL
        if signals.has_commitment or signals.has_verification:
            if signals.has_verification:
                reasons.append("verification claimed by a self or commissioned publisher counts as a stated commitment")
            else:
                reasons.append("commitment or policy language in the quote")
            return MaturityRung.STATED_COMMITMENT
        reasons.append("the quote mentions the topic without a commitment, control or result")
        return MaturityRung.NONE

    @staticmethod
    def _evidence_class(
        ptype: PublisherType, independence: Independence, signals: LanguageSignals, quote: str, rung: MaturityRung
    ) -> EvidenceClass:
        if ptype in EXTERNAL_PUBLISHERS or (
            signals.has_verification and independence in (Independence.INDEPENDENT, Independence.REGULATOR)
        ):
            return EvidenceClass.EXTERNAL_VALIDATION
        if rung in (MaturityRung.SPECIFIED_CONTROL, MaturityRung.DOCUMENTED_EXECUTION):
            return EvidenceClass.OPERATIONAL_EVIDENCE
        lowered = quote.lower()
        if any(t in lowered for t in FOUNDATIONAL_TERMS):
            return EvidenceClass.FOUNDATIONAL_GOVERNANCE
        return EvidenceClass.CORE_GOVERNANCE
