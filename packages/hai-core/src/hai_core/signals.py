"""Lexicon matching over methodology terms.

Everything here is driven by ``methodology.yaml``: commitment, control, execution
dates, independent verification, execution categories (Phase 6 FIX-12), negative
signals (Phase 6 FIX-9) and prompt injection. Tuning relevance is a methodology
change, not a code change. Terms match whole words only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hai_ontology.meta import CriterionDef, Methodology, NegativeRule
from hai_ontology.terms import compile_term, find_terms


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
    execution_dates: tuple[str, ...] = ()
    execution_results: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    injection: tuple[str, ...] = ()
    hints: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def has_commitment(self) -> bool:
        return bool(self.commitment)

    @property
    def has_specified_control(self) -> bool:
        return bool(self.owner) and bool(self.threshold)

    @property
    def has_documented_execution(self) -> bool:
        return bool(self.execution_dates) and bool(self.execution_results)

    @property
    def has_verification(self) -> bool:
        return bool(self.verification)


class SignalMatcher:
    def __init__(self, methodology: Methodology) -> None:
        self.md = methodology
        self.lex = methodology.lexicons

    # ----------------------------------------------------------- basic terms
    def language(self, text: str, criteria: list[CriterionDef] | None = None) -> LanguageSignals:
        hints: dict[str, tuple[str, ...]] = {}
        for c in criteria or []:
            found = tuple(find_terms(text, c.retrieval_hints))
            if found:
                hints[c.code] = found
        return LanguageSignals(
            commitment=tuple(find_terms(text, self.lex.commitment.terms)),
            owner=tuple(find_terms(text, self.lex.control.owner_terms)),
            threshold=tuple(find_terms(text, self.lex.control.threshold_terms)),
            execution_dates=tuple(find_terms(text, self.lex.execution_dates.terms)),
            execution_results=tuple(find_terms(text, self.lex.execution_dates.result_terms)),
            verification=tuple(find_terms(text, self.lex.independent_verification.terms)),
            injection=tuple(find_terms(text, self.lex.injection.terms)),
            hints=hints,
        )

    def injection_terms(self, text: str) -> list[str]:
        return find_terms(text, self.lex.injection.terms)

    def hint_matches(self, text: str, criterion: CriterionDef) -> list[str]:
        return find_terms(text, criterion.retrieval_hints)

    # -------------------------------------------------------------- execution
    def execution(self, text: str) -> ExecutionSignal:
        """Per-span proof of execution (Phase 6 FIX-12 thresholds, legacy proof-of-execution.js:132-149)."""
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
        return ExecutionSignal(level, tuple(categories), round(total, 2), tuple(matched))

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
