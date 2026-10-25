"""Deterministic heuristic provider: follows the ladder, needs no model, no network.

Default for development and CI, and the fallback when a model's finding is
rejected twice.
"""

from __future__ import annotations

from hai_core.generated.enums import RANKS
from hai_engine.llm.base import ProviderResponse
from hai_engine.llm.prompts import PromptBundle
from hai_engine.packs import EvidencePack, PackItem


class HeuristicProvider:
    name = "heuristic"

    def __init__(self, model: str = "ladder-1") -> None:
        self.model = model

    @property
    def model_id(self) -> str:
        return f"{self.name}:{self.model}"

    async def propose(
        self, pack: EvidencePack, prompt: PromptBundle, *, previous_errors: list[str] | None = None
    ) -> ProviderResponse:
        del prompt, previous_errors  # the heuristic never reads instructions; it only follows the ladder
        return ProviderResponse(raw=propose_from_ladder(pack), raw_text="", provider=self.name, model=self.model)


def propose_from_ladder(pack: EvidencePack) -> dict[str, object]:
    ranks = RANKS["maturity_rung"]
    criterion = pack.criterion
    if not pack.supporting:
        return {
            "criterion_code": criterion.code,
            "proposed_level": 1,
            "evidence_link_ids": [],
            "contradicting_link_ids": [i.link_id for i in pack.contradicting[:3]],
            "uncertainty": _uncertainty(pack, cited=0),
            "reasoning_summary": "No admissible supporting evidence was found for this criterion."
            + (" Contradicting evidence is cited." if pack.contradicting else ""),
        }
    best_rank = max(ranks[i.maturity_rung] for i in pack.supporting)
    level = criterion.level_for_rung(best_rank, ranks)
    cited: list[PackItem] = [i for i in pack.supporting if ranks[i.maturity_rung] == best_rank][:3]
    if len(cited) < 3:
        cited += [i for i in pack.supporting if i not in cited][: 3 - len(cited)]
    rung_label = cited[0].maturity_rung.replace("_", " ")
    publishers = sorted({i.publisher_name or i.publisher_type for i in cited})
    summary = (
        f"The best cited quote reaches the {rung_label} rung, which supports level {level} for {criterion.name}. "
        f"Cited from {', '.join(publishers[:3])}."
    )
    if pack.contradicting:
        summary += " Contradicting evidence is also cited."
    return {
        "criterion_code": criterion.code,
        "proposed_level": level,
        "evidence_link_ids": [i.link_id for i in cited],
        "contradicting_link_ids": [i.link_id for i in pack.contradicting[:3]],
        "uncertainty": _uncertainty(pack, cited=len(cited)),
        "reasoning_summary": summary[:600],
    }


def _uncertainty(pack: EvidencePack, *, cited: int) -> float:
    value = 0.6 if cited == 0 else 0.3
    value -= 0.05 * max(0, cited - 1)
    value += 0.03 * pack.omitted
    value += 0.1 if pack.contradicting else 0.0
    if pack.supporting and all(i.independence == "self" for i in pack.supporting):
        value += 0.1
    return round(min(0.95, max(0.05, value)), 2)
