"""Link proposals driven by retrieval hints and lexicons.

For every span and criterion the heuristic proposer decides whether to propose
a link and with which polarity. An optional model-backed proposer may add
proposals, but only for span ids it was shown (checked here).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from hai_core.signals import LanguageSignals, NegativeMatch, SignalMatcher, with_named_owner
from hai_ontology.meta import CriterionDef, Methodology
from hai_ontology.terms import find_terms
from hai_pipeline.incidents import most_material_criterion


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
    # The span is about AI being governed, built or used; such passages are kept first when a
    # long document is bounded, because the methodology credits them above general governance.
    ai_specific: bool = False


class LinkProposer(Protocol):
    """A proposer sees spans (index, quote) and may only reference indices it was shown."""

    name: str

    async def propose(
        self, spans: list[tuple[int, str]], criteria: list[CriterionDef]
    ) -> list[tuple[int, str, str, float]]: ...


FOUNDATIONAL_TERMS = ["principles", "framework", "methodology", "charter", "code of conduct", "manifesto"]


def assessment_negative(
    matcher: SignalMatcher, text: str, publisher_type: str, source_tier: str, *, section_heading: str | None = None
) -> NegativeMatch | None:
    """Require AI relevance and an asserted event before creating an assessment risk signal."""
    if matcher.lex.ai_context.terms and not matcher.ai_context(f"{section_heading or ''}\n{text}"):
        return None
    if find_terms(text, matcher.lex.negative_signals.hypothetical_terms):
        return None
    return matcher.negative(text, publisher_type, source_tier)


def heuristic_proposals(
    spans: list[str],
    criteria: list[CriterionDef],
    methodology: Methodology,
    *,
    publisher_type: str,
    source_tier: str,
    proposer_name: str = "heuristic",
    section_headings: list[str | None] | None = None,
    require_ai_context: bool = False,
    organization_names: tuple[str, ...] = (),
) -> list[LinkProposal]:
    if section_headings is not None and len(section_headings) != len(spans):
        raise ValueError("section headings must align with the supplied spans")
    matcher = SignalMatcher(methodology)
    out: list[LinkProposal] = []
    for idx, text in enumerate(spans):
        heading = section_headings[idx] if section_headings is not None else None
        context = f"{heading or ''}\n{text}"
        if require_ai_context and matcher.lex.ai_context.terms and not matcher.ai_context(context):
            continue
        signals = with_named_owner(matcher.language(text, criteria), text, organization_names)
        if heading:
            # A local section heading supplies relevance, while evidence of a
            # control or its operation must still be present in the quoted span.
            signals = replace(signals, hints=matcher.hints(context, criteria))
        # A risk factor says what could go wrong. It is recorded, never counted as support.
        cautionary = bool(matcher.caution(text))
        ai_specific = bool(matcher.ai_practice(text))
        negative = assessment_negative(matcher, text, publisher_type, source_tier, section_heading=heading)
        negative_targets: set[str] = set()
        if negative is not None:
            negative_targets = {
                c.code for c in criteria if c.pillar in negative.affected_pillars and signals.hints.get(c.code)
            }
            if not negative_targets:
                # Preserve a real AI event for review without presenting one
                # unscoped keyword hit as a failure of every criterion in a pillar.
                negative_targets.add(most_material_criterion(negative.affected_pillars, criteria))
        for c in criteria:
            hints = signals.hints.get(c.code, ())
            is_negative_target = c.code in negative_targets
            if not hints and not is_negative_target:
                continue
            if is_negative_target:
                polarity = "contradicts"
                relevance = min(1.0, 0.7 + 0.1 * len(hints))
            elif not cautionary and (
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
                    ai_specific=ai_specific,
                )
            )
    return out


def bounded_proposals(proposals: list[LinkProposal], *, max_supporting: int, max_neutral: int) -> list[LinkProposal]:
    """Keep the strongest proposals of one document for each criterion.

    A long report matches a criterion hundreds of times, and every link stored is audited,
    classified and frozen. Supporting proposals are kept by the strength of their language
    (a record, then a control, then a commitment) in equal shares, so a run of look-alike
    passages cannot crowd out the rest. Within a share, passages about AI come first, then the
    most relevant; neutral mentions are kept by relevance; contradicting proposals are always kept.
    Zero means no bound. The original order is preserved.
    """
    if max_supporting <= 0 and max_neutral <= 0:
        return proposals
    keep: set[int] = set()
    by_criterion: dict[str, list[tuple[int, LinkProposal]]] = {}
    for position, proposal in enumerate(proposals):
        by_criterion.setdefault(proposal.criterion_code, []).append((position, proposal))
    for items in by_criterion.values():
        supporting: dict[int, list[tuple[int, LinkProposal]]] = {3: [], 2: [], 1: []}
        neutral: list[tuple[int, LinkProposal]] = []
        for position, proposal in items:
            if proposal.polarity == "supports":
                signals = proposal.signals
                strength = 3 if signals.has_documented_execution else 2 if signals.has_specified_control else 1
                supporting[strength].append((position, proposal))
            elif proposal.polarity == "neutral":
                neutral.append((position, proposal))
            else:
                keep.add(position)
        if max_supporting > 0:
            share = max(1, max_supporting // 3)
            spare = max_supporting
            leftovers: list[tuple[int, LinkProposal]] = []
            for strength in (3, 2, 1):
                ranked = sorted(
                    supporting[strength],
                    key=lambda item: (not item[1].ai_specific, -item[1].relevance, item[0]),
                )
                keep.update(position for position, _ in ranked[:share])
                spare -= min(share, len(ranked))
                leftovers.extend(ranked[share:])
            keep.update(position for position, _ in leftovers[: max(0, spare)])
        else:
            keep.update(position for group in supporting.values() for position, _ in group)
        if max_neutral > 0:
            ranked = sorted(neutral, key=lambda item: (-item[1].relevance, item[0]))
            keep.update(position for position, _ in ranked[:max_neutral])
        else:
            keep.update(position for position, _ in neutral)
    return [proposal for position, proposal in enumerate(proposals) if position in keep]


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
        if polarity == "contradicts":
            # Model suggestions obey the same scope gate as heuristic events.
            if matcher.lex.ai_context.terms and not matcher.ai_context(spans[idx]):
                continue
            if find_terms(spans[idx], matcher.lex.negative_signals.hypothetical_terms):
                continue
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
