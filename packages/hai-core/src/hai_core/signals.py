"""Lexicon matching over methodology terms.

Everything here is driven by ``methodology.yaml``: commitment, control, execution
dates, independent verification, execution categories (Phase 6 FIX-12), negative
signals (Phase 6 FIX-9) and prompt injection. Tuning relevance is a methodology
change, not a code change. Terms match whole words only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from hai_ontology.meta import CriterionDef, Methodology, NegativeRule
from hai_ontology.terms import compile_term, find_terms

_CACHE_SIZE = 20_000


@dataclass(frozen=True)
class ExecutionSignal:
    level: str  # none | asserted | partial | verified
    categories: tuple[str, ...]
    total_weight: float
    matched: tuple[str, ...]


@dataclass(frozen=True)
class NegativeMatch:
    rule_code: str
    severity: str
    initial_status: str
    affected_pillars: tuple[str, ...]
    description: str
    matched_terms: tuple[str, ...]
    publisher_type: str
    via_default: bool = False


@dataclass(frozen=True)
class LanguageSignals:
    commitment: tuple[str, ...] = ()
    owner: tuple[str, ...] = ()
    threshold: tuple[str, ...] = ()
    procedure: tuple[str, ...] = ()
    execution_dates: tuple[str, ...] = ()
    execution_results: tuple[str, ...] = ()
    execution_quantities: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    injection: tuple[str, ...] = ()
    hints: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def has_commitment(self) -> bool:
        return bool(self.commitment)

    @property
    def has_specified_control(self) -> bool:
        return bool(self.owner) and bool(self.threshold or self.procedure)

    @property
    def has_documented_execution(self) -> bool:
        return bool(self.execution_dates or self.execution_quantities) and bool(self.execution_results)

    @property
    def has_verification(self) -> bool:
        return bool(self.verification)


class SignalMatcher:
    def __init__(self, methodology: Methodology) -> None:
        self.md = methodology
        self.lex = methodology.lexicons
        # A span is classified once per criterion it is linked to; its language does not change.
        self._language: dict[str, LanguageSignals] = {}
        self._execution: dict[str, ExecutionSignal] = {}

    # ----------------------------------------------------------- basic terms
    def language(self, text: str, criteria: list[CriterionDef] | None = None) -> LanguageSignals:
        cached = self._language.get(text)
        if cached is None:
            cached = LanguageSignals(
                commitment=tuple(find_terms(text, self.lex.commitment.terms)),
                owner=tuple(find_terms(text, self.lex.control.owner_terms)),
                threshold=tuple(find_terms(text, self.lex.control.threshold_terms)),
                procedure=tuple(find_terms(text, self.lex.control.procedure_terms)),
                execution_dates=tuple(find_terms(text, self.lex.execution_dates.terms)),
                execution_results=tuple(find_terms(text, self.lex.execution_dates.result_terms)),
                execution_quantities=tuple(find_terms(text, self.lex.execution_dates.quantity_terms)),
                verification=tuple(find_terms(text, self.lex.independent_verification.terms)),
                injection=tuple(find_terms(text, self.lex.injection.terms)),
            )
            if len(self._language) >= _CACHE_SIZE:
                self._language.clear()
            self._language[text] = cached
        if not criteria:
            return cached
        return replace(cached, hints=self.hints(text, criteria))

    def hints(self, text: str, criteria: list[CriterionDef]) -> dict[str, tuple[str, ...]]:
        """The retrieval hints each criterion matches in ``text``; criteria without a match are absent."""
        out: dict[str, tuple[str, ...]] = {}
        for c in criteria:
            found = tuple(find_terms(text, c.retrieval_hints))
            if found:
                out[c.code] = found
        return out

    def injection_terms(self, text: str) -> list[str]:
        return find_terms(text, self.lex.injection.terms)

    def ai_context(self, text: str) -> tuple[str, ...]:
        """Configured AI terminology, for checking the scope of adverse evidence."""
        return tuple(find_terms(text, self.lex.ai_context.terms))

    def ai_practice(self, text: str) -> tuple[str, ...]:
        """Phrases showing the passage is about AI being governed, built or used by someone."""
        terms = self.lex.ai_context.practice_terms or self.lex.ai_context.terms
        return tuple(find_terms(text, terms))

    def control_gap(self, text: str, signals: LanguageSignals) -> int | None:
        """Characters between an accountable owner and the nearest procedure or threshold; None when
        the passage does not hold both as separate phrases."""
        return _gap(text, signals.owner, (*signals.procedure, *signals.threshold))

    def execution_gap(self, text: str, signals: LanguageSignals) -> int | None:
        """Characters between an execution date or quantity and the nearest result term."""
        return _gap(text, (*signals.execution_dates, *signals.execution_quantities), signals.execution_results)

    def caution(self, text: str) -> tuple[str, ...]:
        """Risk-factor language: what could go wrong, not what the organization does."""
        return tuple(find_terms(text, self.lex.evidence_quality.caution_terms))

    # ------------------------------------------------------------ focus areas
    def focus_areas(self, text: str) -> tuple[str, ...]:
        """Every focus area whose lexicon matches the text, in manifest order."""
        return tuple(area for area, terms in self.lex.focus_areas.items() if find_terms(text, terms.terms))

    def focus_area_for(self, text: str, criterion: CriterionDef) -> str | None:
        """The first matching focus area the criterion lists, or None. Reporting only."""
        if not criterion.focus_areas:
            return None
        for area in self.focus_areas(text):
            if area in criterion.focus_areas:
                return area
        return None

    def hint_matches(self, text: str, criterion: CriterionDef) -> list[str]:
        return find_terms(text, criterion.retrieval_hints)

    # -------------------------------------------------------------- execution
    def execution(self, text: str) -> ExecutionSignal:
        """Per-span proof of execution (Phase 6 FIX-12 thresholds, legacy proof-of-execution.js:132-149)."""
        cached = self._execution.get(text)
        if cached is not None:
            return cached
        categories: list[str] = []
        matched: list[str] = []
        total = 0.0
        for name, cat in self.lex.execution.categories.items():
            hits = [p for p in cat.patterns if compile_term(p).search(text)]
            if hits:
                categories.append(name)
                matched.extend(hits)
                total += cat.weight
        cats = set(categories)
        if total == 0:
            level = "none"
        elif "audit" in cats or ("metrics" in cats and total >= 1.8):
            level = "verified"
        elif "metrics" in cats or ("process" in cats and "control" in cats):
            level = "partial"
        else:
            level = "asserted"
        signal = ExecutionSignal(level, tuple(categories), round(total, 2), tuple(matched))
        if len(self._execution) >= _CACHE_SIZE:
            self._execution.clear()
        self._execution[text] = signal
        return signal

    # --------------------------------------------------------------- negative
    def negative(self, text: str, publisher_type: str, source_tier: str) -> NegativeMatch | None:
        """First matching negative-signal rule for this publisher type; a rule whose terms match
        but whose publisher types do not include this one falls back to the default severity."""
        fallback: NegativeRule | None = None
        fallback_terms: list[str] = []
        for rule in self.lex.negative_signals.rules:
            terms = find_terms(text, rule.terms)
            if not terms:
                continue
            if publisher_type in rule.publisher_types:
                return NegativeMatch(
                    rule_code=rule.code,
                    severity=rule.severity,
                    initial_status=rule.initial_status,
                    affected_pillars=tuple(rule.affected_pillars),
                    description=rule.description,
                    matched_terms=tuple(terms),
                    publisher_type=publisher_type,
                )
            if fallback is None:
                fallback, fallback_terms = rule, terms
        if fallback is None:
            return None
        default = self.lex.negative_signals.default
        return NegativeMatch(
            rule_code=f"{fallback.code}:default",
            severity=default.severity_by_tier.get(source_tier, "low"),
            initial_status=default.initial_status,
            affected_pillars=tuple(fallback.affected_pillars or default.affected_pillars),
            description=default.description,
            matched_terms=tuple(fallback_terms),
            publisher_type=publisher_type,
            via_default=True,
        )


def _gap(text: str, first: tuple[str, ...], second: tuple[str, ...]) -> int | None:
    """The smallest distance between a match of ``first`` and a non-overlapping match of ``second``."""
    a = [m.span() for term in first for m in compile_term(term).finditer(text)]
    b = [m.span() for term in second for m in compile_term(term).finditer(text)]
    best: int | None = None
    for a_start, a_end in a:
        for b_start, b_end in b:
            if a_start < b_end and b_start < a_end:
                continue  # one phrase ("internal audit") cannot be both the owner and the procedure
            gap = b_start - a_end if b_start >= a_end else a_start - b_end
            if best is None or gap < best:
                best = gap
    return best
