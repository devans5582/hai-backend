"""The validator between the model and storage.

* IC-05: schema (strict JSON Schema), known criterion matching the pack, citations
  for any level above 1.
* IC-04: every cited id is in the snapshot and in this criterion's pack, with the
  right polarity and admissible.
* IC-03: each cited quote still matches the stored text at its offsets.
* IC-06: no credit above stated commitment unless a cited quote reaches the rung the
  level requires; cited quotes carry non-empty text.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from hai_core.generated.enums import RANKS, MaturityRung
from hai_engine.llm.base import FindingProposal
from hai_engine.packs import EvidencePack

TextLoader = Callable[[str], str | None]  # document_id -> stored text


@dataclass(frozen=True)
class ValidationError:
    code: str  # IC-03 | IC-04 | IC-05 | IC-06
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass
class ValidationResult:
    ok: bool
    errors: list[ValidationError] = field(default_factory=list)
    finding: FindingProposal | None = None

    @property
    def codes(self) -> set[str]:
        return {e.code for e in self.errors}

    def messages(self) -> list[str]:
        return [str(e) for e in self.errors]


class FindingValidator:
    def __init__(self, schema: dict[str, Any], rung_ranks: dict[str, int] | None = None) -> None:
        self.schema = schema
        self._validator = jsonschema.Draft202012Validator(schema)
        self.ranks = rung_ranks or RANKS["maturity_rung"]

    def validate(
        self,
        raw: dict[str, Any] | None,
        pack: EvidencePack,
        snapshot_link_ids: set[str],
        *,
        text_loader: TextLoader | None = None,
    ) -> ValidationResult:
        errors: list[ValidationError] = []
        if raw is None:
            return ValidationResult(False, [ValidationError("IC-05", "output is not a JSON object")])
        for err in sorted(self._validator.iter_errors(raw), key=lambda e: list(e.path)):
            where = "/".join(str(p) for p in err.path) or "root"
            errors.append(ValidationError("IC-05", f"schema: {where}: {err.message}"))
        if errors:
            return ValidationResult(False, errors)
        finding = FindingProposal(
            criterion_code=str(raw["criterion_code"]),
            proposed_level=int(raw["proposed_level"]),
            evidence_link_ids=[str(x) for x in raw["evidence_link_ids"]],
            contradicting_link_ids=[str(x) for x in raw["contradicting_link_ids"]],
            uncertainty=float(raw["uncertainty"]),
            reasoning_summary=str(raw["reasoning_summary"]),
        )
        if finding.criterion_code != pack.criterion.code:
            errors.append(
                ValidationError(
                    "IC-05", f"criterion_code {finding.criterion_code} does not match the pack {pack.criterion.code}"
                )
            )
        if finding.proposed_level > 1 and not finding.evidence_link_ids:
            errors.append(ValidationError("IC-05", f"level {finding.proposed_level} proposed without any citation"))
        if len(set(finding.evidence_link_ids)) != len(finding.evidence_link_ids):
            errors.append(ValidationError("IC-05", "duplicate citations"))
        # IC-04: citations must be in the snapshot and in this pack with the right polarity
        for link_id in finding.evidence_link_ids:
            if link_id not in snapshot_link_ids:
                errors.append(ValidationError("IC-04", f"cited link {link_id} is not in the evidence snapshot"))
            elif link_id not in pack.supporting_ids:
                kind = (
                    "contradicting"
                    if link_id in pack.contradicting_ids
                    else "not shown as admissible support for this criterion"
                )
                errors.append(ValidationError("IC-04", f"cited link {link_id} is {kind}"))
        for link_id in finding.contradicting_link_ids:
            if link_id not in snapshot_link_ids:
                errors.append(ValidationError("IC-04", f"contradicting link {link_id} is not in the evidence snapshot"))
            elif link_id not in pack.contradicting_ids:
                errors.append(
                    ValidationError(
                        "IC-04", f"link {link_id} is not an admissible contradicting link for this criterion"
                    )
                )
        if errors:
            return ValidationResult(False, errors, finding)
        # IC-03: cited quotes match the stored text at their offsets
        cited = [pack.item(i) for i in (*finding.evidence_link_ids, *finding.contradicting_link_ids)]
        for item in cited:
            assert item is not None
            if not item.quote.strip():
                errors.append(ValidationError("IC-06", f"link {item.link_id} has no quoted text"))
                continue
            if hashlib.sha256(item.quote.encode("utf-8")).hexdigest() != item.quote_sha256:
                errors.append(ValidationError("IC-03", f"link {item.link_id}: quote hash differs from the snapshot"))
            if text_loader is not None:
                stored = text_loader(item.document_id)
                if stored is None or stored[item.char_start : item.char_end] != item.quote:
                    errors.append(
                        ValidationError(
                            "IC-03", f"link {item.link_id}: quote does not match the stored text at its offsets"
                        )
                    )
        # IC-06: the proposed level needs a cited supporting quote that reaches its required rung
        if finding.proposed_level > 1:
            required = _required_rung(pack, finding.proposed_level)
            cited_items = [item for item in (pack.item(i) for i in finding.evidence_link_ids) if item is not None]
            best = max((self.ranks[item.maturity_rung] for item in cited_items), default=0)
            if best < self.ranks[required]:
                errors.append(
                    ValidationError(
                        "IC-06",
                        f"level {finding.proposed_level} requires the {required} rung but the best cited quote reaches "
                        f"{_rung_name(self.ranks, best)}",
                    )
                )
        return ValidationResult(not errors, errors, finding)


def _required_rung(pack: EvidencePack, level: int) -> str:
    for lv in pack.criterion.levels:
        if lv.level == level:
            return lv.required_maturity_rung
    return MaturityRung.INDEPENDENTLY_VERIFIED.value


def _rung_name(ranks: dict[str, int], rank: int) -> str:
    for name, r in ranks.items():
        if r == rank:
            return name
    return "none"
