"""Link proposals driven by retrieval hints and lexicons.

For every span and criterion the heuristic proposer decides whether to propose
a link and with which polarity. An optional model-backed proposer may add
proposals, but only for span ids it was shown (checked here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from hai_ontology.meta import CriterionDef, Methodology
from hai_pipeline.signals import LanguageSignals, NegativeMatch, SignalMatcher


@dataclass(frozen=True)
class LinkProposal:
    span_index: int
    criterion_code: str
    polarity: str  # supports | contradicts | neutral
    relevance: float
    matched_hints: tuple[str, ...]
    negative: NegativeMatch | None
    proposer: str
    signals: LanguageSignals


class LinkProposer(Protocol):
    """A proposer sees spans (index, quote) and may only reference indices it was shown."""

    name: str

    async def propose(
        self, spans: list[tuple[int, str]], criteria: list[CriterionDef]
    ) -> list[tuple[int, str, str, float]]: ...


FOUNDATIONAL_TERMS = ["principles", "framework", "methodology", "charter", "code of conduct", "manifesto"]


def heuristic_proposals(
    spans: list[str],
    criteria: list[CriterionDef],
    methodology: Methodology,
    *,
    publisher_type: str,
    source_tier: str,
    proposer_name: str = "heuristic",
) -> list[LinkProposal]:
    matcher = SignalMatcher(methodology)
    out: list[LinkProposal] = []
    for idx, text in enumerate(spans):
        signals = matcher.language(text, criteria)
        negative = matcher.negative(text, publisher_type, source_tier)
        for c in criteria:
            hints = signals.hints.get(c.code, ())
            is_negative_target = negative is not None and c.pillar in negative.affected_pillars
            if not hints and not is_negative_target:
                continue
            if is_negative_target:
                polarity = "contradicts"
                relevance = min(1.0, 0.7 + 0.1 * len(hints))
            elif (
                signals.has_commitment
                or signals.has_specified_control
                or signals.has_documented_execution
                or signals.has_verification
            ):
                polarity = "supports"
                relevance = min(1.0, 0.4 + 0.2 * len(hints))
            else:
                polarity = "neutral"
                relevance = min(1.0, 0.2 + 0.1 * len(hints))
            out.append(
                LinkProposal(
                    span_index=idx,
                    criterion_code=c.code,
                    polarity=polarity,
                    relevance=round(relevance, 2),
                    matched_hints=tuple(hints),
                    negative=negative if is_negative_target else None,
                    proposer=proposer_name,
                    signals=signals,
                )
            )
    return out


def merge_model_proposals(
    base: list[LinkProposal],
    model: list[tuple[int, str, str, float]],
    *,
    shown: set[int],
    spans: list[str],
    criteria: list[CriterionDef],
    methodology: Methodology,
    proposer_name: str,
) -> list[LinkProposal]:
    """Add model proposals that reference shown spans and known criteria; never override polarity."""
    matcher = SignalMatcher(methodology)
    known = {c.code: c for c in criteria}
    existing = {(p.span_index, p.criterion_code) for p in base}
    out = list(base)
    for idx, code, polarity, relevance in model:
        if (
            idx not in shown
            or code not in known
            or (idx, code) in existing
            or polarity not in ("supports", "contradicts", "neutral")
        ):
            continue
        signals = matcher.language(spans[idx], [known[code]])
        out.append(
            LinkProposal(
                span_index=idx,
                criterion_code=code,
                polarity=polarity,
                relevance=max(0.0, min(1.0, float(relevance))),
                matched_hints=tuple(signals.hints.get(code, ())),
                negative=None,
                proposer=proposer_name,
                signals=signals,
            )
        )
    return out


def evidence_class_for(publisher_type: str, signals: LanguageSignals, text: str) -> str:
    """A heuristic evidence class; the engine's classifier may refine it."""
    if publisher_type in ("regulator_record", "standards_registry", "independent_audit"):
        return "external_validation"
    if signals.has_documented_execution or signals.has_specified_control:
        return "operational_evidence"
    lowered = text.lower()
    if any(t in lowered for t in FOUNDATIONAL_TERMS):
        return "foundational_governance"
    return "core_governance"
