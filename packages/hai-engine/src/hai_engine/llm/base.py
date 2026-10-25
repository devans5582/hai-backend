"""Provider protocol and shared types."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from hai_engine.llm.prompts import PromptBundle
from hai_engine.packs import EvidencePack


class ProviderError(Exception):
    """The provider could not produce a response (transport, HTTP or empty output)."""


@dataclass(frozen=True)
class FindingProposal:
    criterion_code: str
    proposed_level: int
    evidence_link_ids: list[str]
    contradicting_link_ids: list[str]
    uncertainty: float
    reasoning_summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "criterion_code": self.criterion_code,
            "proposed_level": self.proposed_level,
            "evidence_link_ids": list(self.evidence_link_ids),
            "contradicting_link_ids": list(self.contradicting_link_ids),
            "uncertainty": self.uncertainty,
            "reasoning_summary": self.reasoning_summary,
        }


@dataclass
class ProviderResponse:
    raw: dict[str, Any] | None
    raw_text: str
    usage: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    error: str | None = None


class Provider(Protocol):
    name: str
    model: str

    @property
    def model_id(self) -> str: ...

    async def propose(
        self, pack: EvidencePack, prompt: PromptBundle, *, previous_errors: list[str] | None = None
    ) -> ProviderResponse: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from model output, tolerating code fences and surrounding prose."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None
