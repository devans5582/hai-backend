"""Engine services used by the worker: classify links, evaluate criteria.

``classify_links`` sets maturity rung, execution level and evidence class on
every live link of an assessment from the quote and the publisher.
``evaluate_assessment`` builds a pack per criterion from the frozen snapshot,
runs the evaluator and stores every attempt as a finding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.blobstore import BlobStore
from hai_core.db.store import Store
from hai_core.generated.enums import FindingValidationStatus
from hai_core.generated.models import Assessment, CriterionFinding, EvidenceLink, EvidenceSnapshot
from hai_engine.classification import LinkClassifier
from hai_engine.evaluation import Attempt, Evaluator
from hai_engine.generated import finding_schema
from hai_engine.llm.base import Provider
from hai_engine.llm.heuristic import HeuristicProvider
from hai_engine.llm.prompts import load_prompt
from hai_engine.packs import build_all_packs
from hai_engine.validation import FindingValidator
from hai_ontology.meta import Manifest

log = logging.getLogger(__name__)

LINKS_SQL = """
SELECT l.id, s.quote, l.polarity::text, p.publisher_type::text, l.independence::text
FROM hai.evidence_links l
JOIN hai.evidence_spans s ON s.id = l.span_id
JOIN hai.source_documents d ON d.id = s.source_document_id
JOIN hai.publishers p ON p.id = d.publisher_id
JOIN hai.connector_runs r ON r.id = d.connector_run_id
WHERE r.assessment_id = :a
  AND NOT EXISTS (SELECT 1 FROM hai.evidence_links newer WHERE newer.supersedes_id = l.id)
"""


def classify_links(conn: Connection, store: Store, manifest: Manifest, assessment_id: UUID) -> int:
    classifier = LinkClassifier(manifest.methodology)
    rows = conn.execute(text(LINKS_SQL), {"a": assessment_id}).all()
    n = 0
    for link_id, quote, polarity, publisher_type, independence in rows:
        result = classifier.classify(
            str(quote), polarity=str(polarity), publisher_type=str(publisher_type), independence=str(independence)
        )
        store.update(
            EvidenceLink,
            link_id,
            {
                "maturity_rung": result.maturity_rung,
                "execution_level": result.execution_level,
                "evidence_class": result.evidence_class,
            },
            reason="classification: " + "; ".join(result.reasons),
        )
        n += 1
    return n


@dataclass
class EvaluationSummary:
    criteria: int = 0
    accepted: int = 0
    rejected: int = 0
    fell_back: int = 0
    findings: list[UUID] = field(default_factory=list)
    trace: dict[str, list[str]] = field(default_factory=dict)


def _text_loader(blobs: BlobStore, snapshot: EvidenceSnapshot) -> Any:
    uris: dict[str, str] = {}
    for st in snapshot.link_states.values():
        uris.setdefault(str(st["document_id"]), str(st.get("text_uri") or ""))
    cache: dict[str, str | None] = {}

    def load(document_id: str) -> str | None:
        if document_id in cache:
            return cache[document_id]
        uri = uris.get(document_id)
        text_value: str | None = None
        if uri:
            try:
                text_value = blobs.get_text(uri)
            except Exception as exc:
                log.warning("stored text for %s unavailable: %s", document_id, exc)
        cache[document_id] = text_value
        return text_value

    return load


async def evaluate_assessment(
    store: Store,
    manifest: Manifest,
    assessment_id: UUID,
    *,
    provider: Provider,
    prompt_version: str,
    second_opinion: Provider | None = None,
    blobs: BlobStore | None = None,
) -> EvaluationSummary:
    assessment = store.require(Assessment, assessment_id)
    snapshot = store.first(EvidenceSnapshot, where={"assessment_id": assessment_id})
    if snapshot is None:
        raise ValueError("no evidence snapshot; freeze before evaluating")
    prompt = load_prompt(prompt_version, finding_schema())
    validator = FindingValidator(finding_schema())
    loader = (
        _text_loader(blobs, snapshot)
        if blobs is not None and any("text_uri" in st for st in snapshot.link_states.values())
        else None
    )
    evaluator = Evaluator(
        provider=provider,
        prompt=prompt,
        validator=validator,
        fallback=HeuristicProvider(),
        second_opinion=second_opinion,
        text_loader=loader,
    )
    packs = build_all_packs(list(manifest.criteria), snapshot.link_states, connector_runs=snapshot.connector_runs)
    snapshot_ids = {str(x) for x in snapshot.link_ids}
    summary = EvaluationSummary()
    for code, pack in packs.items():
        ev = await evaluator.evaluate(pack, snapshot_ids)
        summary.criteria += 1
        summary.trace[code] = ev.trace
        if ev.fell_back:
            summary.fell_back += 1
        for attempt in ev.attempts:
            row = _finding_row(
                assessment, code, attempt, prompt_version, fell_back=ev.fell_back and attempt is ev.accepted
            )
            stored = store.insert(row, reason="; ".join(ev.trace)[:500])
            summary.findings.append(stored.id)
            if attempt.accepted:
                summary.accepted += 1
            else:
                summary.rejected += 1
    return summary


def _finding_row(
    assessment: Assessment, code: str, attempt: Attempt, prompt_version: str, *, fell_back: bool
) -> CriterionFinding:
    f = attempt.finding
    raw = attempt.raw or {}
    return CriterionFinding(
        assessment_id=assessment.id,
        criterion_code=code,
        proposed_level=int(
            f.proposed_level
            if f
            else max(1, min(5, int(raw.get("proposed_level", 1)) if isinstance(raw.get("proposed_level"), int) else 1))
        ),
        evidence_link_ids=[UUID(x) for x in (f.evidence_link_ids if f else _uuids(raw.get("evidence_link_ids")))],
        contradicting_link_ids=[
            UUID(x) for x in (f.contradicting_link_ids if f else _uuids(raw.get("contradicting_link_ids")))
        ],
        uncertainty=float(f.uncertainty if f else _num(raw.get("uncertainty"), 1.0)),
        reasoning_summary=str(
            f.reasoning_summary if f else raw.get("reasoning_summary") or "; ".join(attempt.errors)[:600] or "rejected"
        )[:600],
        provider=attempt.provider,
        model_id=attempt.model_id,
        prompt_version=prompt_version,
        attempt=attempt.attempt,
        validation_status=FindingValidationStatus.ACCEPTED if attempt.accepted else FindingValidationStatus.REJECTED,
        validation_errors=[{"message": e} for e in attempt.errors] if attempt.errors else None,
        raw_output={"output": attempt.raw, "text": attempt.raw_text[:4000], "fell_back": fell_back},
        role=attempt.role,
    )


def _uuids(value: Any) -> list[str]:
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        try:
            out.append(str(UUID(str(item))))
        except ValueError:
            continue
    return out


def _num(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default
