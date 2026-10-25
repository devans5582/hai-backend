"""Versioned prompts.

The system instruction is a static file. Evidence is passed as JSON data in the
user message and never concatenated into the system prompt (IC-17).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hai_engine.packs import EvidencePack

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
DEFAULT_PROMPT_VERSION = "1.0.0"


@dataclass(frozen=True)
class PromptBundle:
    version: str
    system: str
    schema: dict[str, Any]

    def user_payload(self, pack: EvidencePack, previous_errors: list[str] | None = None) -> dict[str, Any]:
        payload = {
            "task": "propose_criterion_finding",
            "prompt_version": self.version,
            "data": pack.for_model(),
        }
        if previous_errors:
            payload["previous_attempt_was_rejected"] = {"errors": list(previous_errors)}
        return payload

    def user_message(self, pack: EvidencePack, previous_errors: list[str] | None = None) -> str:
        return json.dumps(self.user_payload(pack, previous_errors), ensure_ascii=True, default=str)


def available_versions() -> list[str]:
    return sorted(p.name for p in PROMPTS_DIR.iterdir() if p.is_dir() and (p / "system.md").exists())


def load_prompt(version: str, schema: dict[str, Any]) -> PromptBundle:
    path = PROMPTS_DIR / version / "system.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt version {version} not found under {PROMPTS_DIR}")
    return PromptBundle(version=version, system=path.read_text(encoding="utf-8").strip(), schema=schema)


def build_messages(
    prompt: PromptBundle, pack: EvidencePack, previous_errors: list[str] | None = None
) -> list[dict[str, str]]:
    """Chat messages: static system instruction, evidence as JSON data in the user turn (IC-17)."""
    return [
        {"role": "system", "content": prompt.system},
        {"role": "user", "content": prompt.user_message(pack, previous_errors)},
    ]
