"""Link classification from the quote and the publisher only.

Sets the maturity rung, the per-span execution level and the evidence class.
A title, label or date alone never lifts maturity above none (IC-06); the
independently verified rung needs an independent or regulator publisher
(IC-07); source tier never enters the decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from hai_core.generated.enums import (
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
from hai_ontology.terms import compile_term

MIN_WORDS_FOR_EVIDENCE = 6
EXTERNAL_PUBLISHERS = frozenset(
    {PublisherType.REGULATOR_RECORD, PublisherType.STANDARDS_REGISTRY, PublisherType.INDEPENDENT_AUDIT}
)
FOUNDATIONAL_TERMS = ("principles", "framework", "methodology", "charter", "code of conduct", "manifesto")


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
        if (
            criterion is not None
            and criterion.pillar == PillarCode.SAF.value
            and rung in (MaturityRung.DOCUMENTED_EXECUTION, MaturityRung.INDEPENDENTLY_VERIFIED)
            and self.matcher.lex.ai_context.terms
            and not self.matcher.ai_context(" ".join(part for part in (quote, section_heading, document_title) if part))
        ):
            rung = (
                MaturityRung.SPECIFIED_CONTROL
                if signals.has_specified_control
                else (MaturityRung.STATED_COMMITMENT if signals.has_commitment else MaturityRung.NONE)
            )
            reasons.append("general operational or financial evidence does not establish AI safety execution")
        evidence_class = self._evidence_class(ptype, indep, signals, quote, rung)
        return Classification(rung, ExecutionLevel(execution.level), evidence_class, tuple(reasons))

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
