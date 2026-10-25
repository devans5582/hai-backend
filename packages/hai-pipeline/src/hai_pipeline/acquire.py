"""Acquisition orchestrator: connectors, documents, spans, clusters, proposals, links, incidents.

Every connector run is recorded with its outcome even when empty (IC-16). Documents
are content-addressed in the blob store. Spans keep exact offsets (IC-03). Links
are the only bridge to a score; each carries its six judgments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Connection, text

from hai_core.blobstore import BlobStore
from hai_core.db.store import Store
from hai_core.generated.enums import (
    Admissibility,
    ClaimScopeType,
    ClusterMethod,
    ConnectorRunOutcome,
    EvidenceClass,
    ExecutionLevel,
    IncidentSeverity,
    IncidentStatus,
    MaturityRung,
    Polarity,
    PublisherType,
    TargetType,
)
from hai_core.generated.models import (
    Claim,
    ConnectorRun,
    EvidenceLink,
    EvidenceSpan,
    Incident,
    Organization,
    Publisher,
    SourceCluster,
    SourceDocument,
)
from hai_core.generated.models import (
    Connector as ConnectorRow,
)
from hai_core.settings import Settings
from hai_core.signals import SignalMatcher
from hai_ontology.meta import Manifest
from hai_pipeline.admissibility import assess_admissibility
from hai_pipeline.clustering import Clusterer
from hai_pipeline.config import ConnectorsFile
from hai_pipeline.connectors import build_connector
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.entity_resolution import EntityProfile, EntityResolver
from hai_pipeline.extraction import ExtractedDocument, extract
from hai_pipeline.http import Budget, Fetcher
from hai_pipeline.incidents import build_incident
from hai_pipeline.proposals import LinkProposal, evidence_class_for, heuristic_proposals
from hai_pipeline.publishers import classify_publisher, independence_for, source_tier_for
from hai_pipeline.spans import split_spans
from hai_pipeline.urls import canonical_url, registrable_domain

log = logging.getLogger(__name__)


@dataclass
class StagedDocument:
    run_id: UUID
    connector_code: str
    fetched: FetchedDocument
    extracted: ExtractedDocument
    raw_uri: str
    raw_sha: str
    text_uri: str
    text_sha: str
    publisher_type: PublisherType
    publisher_name: str
    publisher_domain: str
    is_org: bool
    cluster_key: str | None = None
    cluster_method: str = "exact_hash"
    simhash: int = 0


@dataclass
class AcquisitionReport:
    assessment_id: UUID
    runs: dict[str, str] = field(default_factory=dict)
    documents: int = 0
    spans: int = 0
    links: int = 0
    incidents: int = 0
    clusters: int = 0
    entity: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class AcquisitionService:
    def __init__(
        self,
        *,
        settings: Settings,
        manifest: Manifest,
        connectors: ConnectorsFile,
        blobs: BlobStore,
        transport: httpx.AsyncBaseTransport | None = None,
        now: datetime | None = None,
    ) -> None:
        self.settings = settings
        self.manifest = manifest
        self.connectors = connectors
        self.blobs = blobs
        self.transport = transport
        self.now = now
        self.matcher = SignalMatcher(manifest.methodology)

    def _fetcher(self) -> Fetcher:
        d = self.connectors.defaults
        website = self.connectors.get("WEBSITE") if "WEBSITE" in self.connectors.codes else None
        markers = tuple(str(m) for m in (website.opt("block_markers", []) if website else []))
        codes = frozenset(
            int(c) for c in (website.opt("block_status_codes", [403, 406, 451]) if website else [403, 406, 451])
        )
        return Fetcher(
            user_agent=self.settings.http_user_agent,
            timeout_seconds=d.timeout_seconds,
            min_interval_seconds=0.0 if self.transport is not None else d.min_interval_seconds,
            max_retries=d.max_retries,
            respect_robots=d.respect_robots,
            max_bytes=d.max_document_bytes,
            transport=self.transport,
            block_markers=markers,
            block_status_codes=codes,
            retry_backoff_seconds=0.0 if self.transport is not None else 2.0,
        )

    # ------------------------------------------------------------------- entry
    async def acquire(self, conn: Connection, store: Store, assessment_id: UUID) -> AcquisitionReport:
        from hai_core.generated.models import Assessment

        assessment = store.require(Assessment, assessment_id)
        org = store.require(Organization, assessment.org_id)
        report = AcquisitionReport(assessment_id=assessment_id)
        as_of = self.now or datetime.now(UTC)
        async with self._fetcher() as fetcher:
            profile = await self._resolve_entity(fetcher, store, org)
            org = store.require(Organization, org.id)
            report.entity = {
                "resolved_name": profile.resolved_name,
                "domain_verified": profile.domain_verified,
                "confidence": profile.confidence,
                "warnings": profile.warnings,
            }
            ctx = ConnectorContext(
                organization_name=org.display_name or org.legal_name,
                organization_domain=org.primary_domain,
                website_url=f"https://{assessment.submitted_domain}",
                direct_urls=list(assessment.direct_urls or []),
                org_id=str(org.id),
                assessment_id=str(assessment.id),
                github_handle=org.github_handle,
                cik=org.cik,
                lei=org.lei,
                aliases=list(org.aliases or []),
                pending_uploads=self._pending_uploads(conn, org.id),
                api_tokens=self._tokens(),
            )
            staged: list[StagedDocument] = []
            connector_rows = {c.code: c for c in store.find(ConnectorRow)}
            for cfg in self.connectors.enabled:
                row = connector_rows.get(cfg.code)
                if row is None:
                    report.notes.append(f"connector {cfg.code} is not seeded; skipped")
                    continue
                run = store.insert(
                    ConnectorRun(
                        assessment_id=assessment.id,
                        connector_id=row.id,
                        outcome=ConnectorRunOutcome.INVOKED,
                        started_at=as_of,
                    )
                )
                budget = Budget(time_seconds=cfg.limits.time_seconds, pages=cfg.limits.pages)
                try:
                    result = await build_connector(cfg.code).run(ctx, fetcher, cfg, budget)
                except Exception as exc:
                    log.exception("connector %s crashed", cfg.code)
                    result = ConnectorResult(outcome="failed", error_code=type(exc).__name__, notes=[str(exc)[:300]])
                for doc in result.documents:
                    sd = self._stage(run.id, cfg.code, doc, org, PublisherType(cfg.publisher_type))
                    if sd is not None:
                        staged.append(sd)
                store.update(
                    ConnectorRun,
                    run.id,
                    {
                        "outcome": ConnectorRunOutcome(result.outcome),
                        "error_code": result.error_code,
                        "items_returned": len([s for s in staged if s.run_id == run.id]),
                        "finished_at": self.now or datetime.now(UTC),
                        "notes": "; ".join(result.notes)[:2000] or None,
                    },
                )
                report.runs[cfg.code] = result.outcome
        report.clusters = self._cluster(staged)
        succeeded_runs = {s.run_id for s in staged}
        criteria = list(self.manifest.criteria)
        for sd in staged:
            publisher = self._publisher(store, sd, org)
            document = store.insert(
                SourceDocument(
                    canonical_url=canonical_url(sd.fetched.url)
                    if not sd.fetched.url.startswith("upload://")
                    else sd.fetched.url,
                    publisher_id=publisher.id,
                    connector_run_id=sd.run_id,
                    cluster_id=self._cluster_row(store, sd).id if sd.cluster_key else None,
                    title=(sd.fetched.title or sd.extracted.title or None),
                    content_type=sd.fetched.content_type.split(";")[0].strip() or None,
                    language=sd.extracted.language,
                    published_at=sd.fetched.published_at or sd.extracted.published_at,
                    retrieved_at=as_of,
                    sha256=sd.raw_sha,
                    text_sha256=sd.text_sha,
                    snapshot_uri=sd.raw_uri,
                    text_uri=sd.text_uri,
                    extraction_version=sd.extracted.extractor_version,
                    rights=sd.fetched.rights,
                    valid_to=sd.fetched.certificate_valid_until,
                )
            )
            report.documents += 1
            if sd.fetched.claim_text is not None:
                store.insert(
                    Claim(
                        claimant_org_id=org.id,
                        assertion_text=sd.fetched.claim_text or (sd.fetched.title or "uploaded document"),
                        scope_type=ClaimScopeType.ORGANIZATION,
                        scope_id=org.id,
                        source_document_id=document.id,
                    )
                )
                if sd.fetched.upload_id:
                    conn.execute(
                        text("UPDATE hai_ops.uploads SET status = 'ingested', source_document_id = :d WHERE id = :id"),
                        {"d": document.id, "id": sd.fetched.upload_id},
                    )
            candidates = split_spans(sd.extracted)
            spans = [
                store.insert(
                    EvidenceSpan(
                        source_document_id=document.id,
                        char_start=c.char_start,
                        char_end=c.char_end,
                        quote=c.quote,
                        asserted_dates=list(c.asserted_dates),
                        section_heading=c.section_heading,
                    )
                )
                for c in candidates
            ]
            report.spans += len(spans)
            tier = source_tier_for(sd.publisher_type)
            independence = independence_for(
                sd.publisher_type,
                publisher_is_org=sd.is_org,
                archived_publisher_is_org=(
                    registrable_domain(sd.fetched.archived_original_url) == registrable_domain(org.primary_domain)
                    if sd.fetched.archived_original_url
                    else None
                ),
            )
            proposals = heuristic_proposals(
                [c.quote for c in candidates],
                criteria,
                self.manifest.methodology,
                publisher_type=sd.publisher_type.value,
                source_tier=tier.value,
            )
            published = sd.fetched.published_at or sd.extracted.published_at
            for p in proposals:
                c = candidates[p.span_index]
                criterion = self.manifest.criterion(p.criterion_code)
                decision = assess_admissibility(
                    stored_text=sd.extracted.text,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    quote=c.quote,
                    criterion=criterion,
                    matched_hints=bool(p.matched_hints),
                    negative_match=p.negative is not None,
                    published_at=published,
                    as_of=as_of,
                    run_succeeded=sd.run_id in succeeded_runs,
                    methodology=self.manifest.methodology,
                    matcher=self.matcher,
                )
                store.insert(
                    EvidenceLink(
                        span_id=spans[p.span_index].id,
                        target_type=TargetType.ORGANIZATION,
                        target_id=org.id,
                        criterion_code=p.criterion_code,
                        polarity=Polarity(p.polarity),
                        admissibility=Admissibility(decision.admissibility),
                        admissibility_reason=decision.reason,
                        maturity_rung=MaturityRung.NONE,
                        execution_level=ExecutionLevel.NONE,
                        evidence_class=EvidenceClass(evidence_class_for(sd.publisher_type.value, p.signals, c.quote)),
                        independence=independence,
                        source_tier=tier,
                        proposer=p.proposer,
                        relevance=p.relevance,
                        valid_from=published,
                    )
                )
                report.links += 1
            report.incidents += self._incidents(store, org, sd, candidates, proposals, published)
        return report

    # ---------------------------------------------------------------- helpers
    async def _resolve_entity(self, fetcher: Fetcher, store: Store, org: Organization) -> EntityProfile:
        resolver = EntityResolver(fetcher)
        try:
            profile = await resolver.resolve(org.display_name or org.legal_name, org.primary_domain)
        except Exception as exc:
            log.warning("entity resolution failed: %s", exc)
            return EntityProfile(
                input_name=org.legal_name,
                input_domain=org.primary_domain,
                resolved_name=org.legal_name,
                warnings=[str(exc)],
            )
        changes: dict[str, Any] = {
            "entity_confidence": profile.confidence,
            "resolved_at": self.now or datetime.now(UTC),
        }
        if profile.domain_verified:
            changes.update(profile.verified_identifiers)
            changes["identifiers_verified"] = True
            if profile.name_match >= 0.6 and profile.resolved_name != org.legal_name:
                changes["aliases"] = sorted(
                    {*(org.aliases or []), profile.resolved_name} - {org.legal_name, org.display_name}
                )
        store.update(Organization, org.id, changes, reason="entity resolution")
        return profile

    def _tokens(self) -> dict[str, str]:
        import os

        out: dict[str, str] = {}
        for key, env in (("GITHUB", "HAI_GITHUB_TOKEN"), ("SEMANTIC_SCHOLAR", "HAI_SEMANTIC_SCHOLAR_API_KEY")):
            value = os.environ.get(env)
            if value:
                out[key] = value
        return out

    def _pending_uploads(self, conn: Connection, org_id: UUID) -> list[dict[str, object]]:
        rows = (
            conn.execute(
                text(
                    "SELECT id, filename, content_type, blob_uri, assertion_text FROM hai_ops.uploads "
                    "WHERE org_id = :o AND status = 'pending' ORDER BY created_at"
                ),
                {"o": org_id},
            )
            .mappings()
            .all()
        )
        out: list[dict[str, object]] = []
        for r in rows:
            try:
                content = self.blobs.get(str(r["blob_uri"]))
            except Exception as exc:
                log.warning("upload %s blob missing: %s", r["id"], exc)
                continue
            out.append(
                {
                    "id": str(r["id"]),
                    "filename": r["filename"],
                    "content_type": r["content_type"],
                    "assertion_text": r["assertion_text"],
                    "content": content,
                }
            )
        return out

    def _stage(
        self, run_id: UUID, code: str, doc: FetchedDocument, org: Organization, default_type: PublisherType
    ) -> StagedDocument | None:
        try:
            extracted = extract(doc.content, doc.content_type, base_url=doc.url)
        except Exception as exc:
            log.warning("extraction failed for %s: %s", doc.url, exc)
            return None
        if not extracted.text.strip():
            return None
        if doc.title and not extracted.title:
            extracted.title = doc.title
        if doc.published_at and not extracted.published_at:
            extracted.published_at = doc.published_at
        raw = self.blobs.put(doc.content)
        txt = self.blobs.put_text(extracted.text)
        if doc.url.startswith("upload://"):
            info_type, name, domain, is_org = PublisherType.ORG_DISCLOSURE, org.display_name, org.primary_domain, True
        else:
            info = classify_publisher(
                doc.archived_original_url or doc.url,
                org_domain=org.primary_domain,
                default=PublisherType(doc.publisher_type_hint or default_type.value),
                name_hint=doc.publisher_hint,
            )
            info_type, name, domain, is_org = info.publisher_type, info.name, info.domain, info.is_organization
            if doc.archived_original_url:
                info_type = PublisherType.ARCHIVE
                name, domain = "Internet Archive", "archive.org"
        return StagedDocument(
            run_id=run_id,
            connector_code=code,
            fetched=doc,
            extracted=extracted,
            raw_uri=raw.uri,
            raw_sha=raw.sha256,
            text_uri=txt.uri,
            text_sha=txt.sha256,
            publisher_type=info_type,
            publisher_name=name,
            publisher_domain=domain,
            is_org=is_org,
        )

    def _cluster(self, staged: list[StagedDocument]) -> int:
        clusterer = Clusterer()
        for i, sd in enumerate(staged):
            c = clusterer.assign(str(i), sd.extracted.text)
            sd.cluster_key, sd.cluster_method, sd.simhash = c.key, c.method, c.simhash
        multi = [c for c in clusterer.clusters if len(c.members) > 1]
        # Only clusters with more than one member are worth a row; singletons stay unclustered.
        keys = {c.key for c in multi}
        for sd in staged:
            if sd.cluster_key not in keys:
                sd.cluster_key = None
        return len(multi)

    def _cluster_row(self, store: Store, sd: StagedDocument) -> SourceCluster:
        assert sd.cluster_key is not None
        existing = store.first(SourceCluster, where={"cluster_key": sd.cluster_key})
        if existing:
            return existing
        return store.insert(
            SourceCluster(
                cluster_key=sd.cluster_key,
                method=ClusterMethod(
                    sd.cluster_method if sd.cluster_method in ("exact_hash", "simhash") else "simhash"
                ),
                simhash=f"{sd.simhash:016x}",
            )
        )

    def _publisher(self, store: Store, sd: StagedDocument, org: Organization) -> Publisher:
        existing = store.first(Publisher, where={"domain": sd.publisher_domain})
        if existing:
            return existing
        return store.insert(
            Publisher(
                name=sd.publisher_name,
                domain=sd.publisher_domain,
                publisher_type=sd.publisher_type,
                org_id=org.id if sd.is_org else None,
            )
        )

    def _incidents(
        self,
        store: Store,
        org: Organization,
        sd: StagedDocument,
        candidates: list[Any],
        proposals: list[LinkProposal],
        published: Any,
    ) -> int:
        seen: set[str] = set()
        created = 0
        for p in proposals:
            if p.negative is None or p.negative.rule_code in seen:
                continue
            seen.add(p.negative.rule_code)
            cand = build_incident(
                str(org.id), p.negative, published, list(self.manifest.criteria), candidates[p.span_index].quote
            )
            if store.first(Incident, where={"canonical_event_key": cand.canonical_event_key}):
                continue
            store.insert(
                Incident(
                    canonical_event_key=cand.canonical_event_key,
                    org_id=org.id,
                    title=cand.title,
                    summary=cand.summary,
                    occurred_at=cand.occurred_at,
                    severity=IncidentSeverity(cand.severity),
                    status=IncidentStatus(cand.status),
                    most_material_criterion=cand.most_material_criterion,
                ),
                reason=f"negative signal {cand.rule_code} from {sd.publisher_domain}",
            )
            created += 1
        return created
