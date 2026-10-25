"""Admissibility in a fixed order; the first failure wins.

untrusted (prompt injection text), unverifiable (quote mismatch or no successful
connector run), irrelevant (no retrieval hint and no negative signal for the
criterion), stale (dated and outside the criterion's freshness window; undated
evidence is never stale, it is decayed instead).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from hai_core.freshness import is_stale
from hai_core.generated.enums import Admissibility
from hai_core.signals import SignalMatcher
from hai_ontology.meta import CriterionDef, Methodology
from hai_pipeline.spans import verify_span


@dataclass(frozen=True)
class AdmissibilityDecision:
    admissibility: str
    reason: str | None


def assess_admissibility(
    *,
    stored_text: str,
    char_start: int,
    char_end: int,
    quote: str,
    criterion: CriterionDef,
    matched_hints: bool,
    negative_match: bool,
    published_at: date | datetime | None,
    as_of: date | datetime,
    run_succeeded: bool,
    methodology: Methodology,
    matcher: SignalMatcher | None = None,
) -> AdmissibilityDecision:
    m = matcher or SignalMatcher(methodology)
    injected = m.injection_terms(quote)
    if injected:
        return AdmissibilityDecision(
            Admissibility.INADMISSIBLE_UNTRUSTED.value, f"prompt injection terms: {', '.join(injected[:3])}"
        )
    if not run_succeeded:
        return AdmissibilityDecision(
            Admissibility.INADMISSIBLE_UNVERIFIABLE.value, "no successful connector run for the source"
        )
    if not verify_span(stored_text, char_start, char_end, quote):
        return AdmissibilityDecision(
            Admissibility.INADMISSIBLE_UNVERIFIABLE.value, "quote does not match the stored text at its offsets (IC-03)"
        )
    if methodology.lexicons.irrelevance.require_hint_match and not matched_hints and not negative_match:
        return AdmissibilityDecision(
            Admissibility.INADMISSIBLE_IRRELEVANT.value, f"no retrieval hint for {criterion.code} matched"
        )
    window = criterion.freshness_window_months or methodology.freshness.default_window_months
    if is_stale(published_at, as_of, window):
        return AdmissibilityDecision(
            Admissibility.INADMISSIBLE_STALE.value, f"published {published_at} is outside the {window}-month window"
        )
    return AdmissibilityDecision(Admissibility.ADMISSIBLE.value, None)
