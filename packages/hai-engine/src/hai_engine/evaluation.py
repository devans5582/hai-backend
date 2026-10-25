"""Evaluate criteria: provider proposes, validator checks, retry once, fall back to the heuristic.

Every attempt is kept as a finding (accepted or rejected) so the trace is
complete. A rejected finding is never used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hai_engine.llm.base import FindingProposal, Provider, ProviderError
from hai_engine.llm.heuristic import HeuristicProvider
from hai_engine.llm.prompts import PromptBundle
from hai_engine.packs import EvidencePack
from hai_engine.validation import FindingValidator, TextLoader


@dataclass
class Attempt:
    provider: str
    model: str
    role: str  # primary | second_opinion
    attempt: int
    raw: dict[str, Any] | None
    raw_text: str
    accepted: bool
    errors: list[str]
    finding: FindingProposal | None

    @property
    def model_id(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass
class CriterionEvaluation:
    criterion_code: str
    attempts: list[Attempt] = field(default_factory=list)
    accepted: Attempt | None = None
    second_opinion: Attempt | None = None
    trace: list[str] = field(default_factory=list)
    fell_back: bool = False

    @property
    def disagreement_levels(self) -> int | None:
        if (
            self.accepted is None
            or self.second_opinion is None
            or self.accepted.finding is None
            or self.second_opinion.finding is None
        ):
            return None
        return abs(self.accepted.finding.proposed_level - self.second_opinion.finding.proposed_level)


class Evaluator:
    def __init__(
        self,
        *,
        provider: Provider,
        prompt: PromptBundle,
        validator: FindingValidator,
        fallback: Provider | None = None,
        second_opinion: Provider | None = None,
        text_loader: TextLoader | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.provider = provider
        self.prompt = prompt
        self.validator = validator
        self.fallback = fallback or HeuristicProvider()
        self.second_opinion = second_opinion
        self.text_loader = text_loader
        self.max_attempts = max_attempts

    async def evaluate(self, pack: EvidencePack, snapshot_link_ids: set[str]) -> CriterionEvaluation:
        ev = CriterionEvaluation(criterion_code=pack.criterion.code)
        previous: list[str] | None = None
        for n in range(1, self.max_attempts + 1):
            attempt = await self._attempt(
                self.provider, pack, snapshot_link_ids, role="primary", n=n, previous=previous
            )
            ev.attempts.append(attempt)
            if attempt.accepted:
                ev.accepted = attempt
                ev.trace.append(f"{attempt.model_id} accepted on attempt {n}")
                break
            previous = attempt.errors
            ev.trace.append(f"{attempt.model_id} rejected on attempt {n}: {'; '.join(attempt.errors)[:300]}")
        if ev.accepted is None and self.fallback.model_id != self.provider.model_id:
            fb = await self._attempt(
                self.fallback, pack, snapshot_link_ids, role="primary", n=len(ev.attempts) + 1, previous=None
            )
            ev.attempts.append(fb)
            ev.fell_back = True
            if fb.accepted:
                ev.accepted = fb
                ev.trace.append(f"fell back to {fb.model_id}")
            else:
                ev.trace.append(f"fallback {fb.model_id} rejected: {'; '.join(fb.errors)[:300]}")
        if self.second_opinion is not None and ev.accepted is not None:
            so = await self._attempt(
                self.second_opinion, pack, snapshot_link_ids, role="second_opinion", n=1, previous=None
            )
            ev.attempts.append(so)
            if so.accepted:
                ev.second_opinion = so
                ev.trace.append(
                    f"second opinion {so.model_id} proposed level {so.finding.proposed_level if so.finding else '?'}"
                )
            else:
                ev.trace.append(f"second opinion {so.model_id} rejected: {'; '.join(so.errors)[:200]}")
        return ev

    async def _attempt(
        self,
        provider: Provider,
        pack: EvidencePack,
        snapshot_link_ids: set[str],
        *,
        role: str,
        n: int,
        previous: list[str] | None,
    ) -> Attempt:
        try:
            response = await provider.propose(pack, self.prompt, previous_errors=previous)
        except ProviderError as exc:
            return Attempt(provider.name, provider.model, role, n, None, "", False, [f"provider error: {exc}"], None)
        result = self.validator.validate(response.raw, pack, snapshot_link_ids, text_loader=self.text_loader)
        return Attempt(
            provider.name,
            provider.model,
            role,
            n,
            response.raw,
            response.raw_text,
            result.ok,
            result.messages(),
            result.finding,
        )
