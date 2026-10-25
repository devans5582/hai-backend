"""Acquisition against the fake internet: runs recorded, spans verify, injection inadmissible,
one incident from two articles, clusters, blocked website gives a blocked run, snapshot freeze."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text

from hai_core.blobstore import BlobStore
from hai_core.db.engine import Database
from hai_core.db.store import Store
from hai_core.generated.enums import SizeBand, StageBand
from hai_core.generated.models import Assessment, EvidenceSnapshot, Organization
from hai_core.settings import Settings
from hai_ontology.meta import Manifest
from hai_pipeline.acquire import AcquisitionReport, AcquisitionService
from hai_pipeline.config import load_connectors
from hai_pipeline.snapshot import build_snapshot
from tests.fixtures.fake_internet import CIK, ORG_DOMAIN, ORG_NAME, FakeInternet

pytestmark = pytest.mark.integration


def _service(settings: Settings, manifest: Manifest, net: FakeInternet) -> AcquisitionService:
    return AcquisitionService(
        settings=settings,
        manifest=manifest,
        connectors=load_connectors(settings.connectors_config),
        blobs=BlobStore(settings.blob_store_url),
        transport=net.transport,
        now=datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
    )


def _new_assessment(db: Database, manifest: Manifest, *, direct_urls: list[str] | None = None) -> tuple[UUID, UUID]:
    with db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = store.insert(Organization(legal_name=ORG_NAME, display_name=ORG_NAME, primary_domain=ORG_DOMAIN))
        a = store.insert(
            Assessment(
                org_id=org.id,
                requested_by="pytest",
                submitted_domain=ORG_DOMAIN,
                direct_urls=direct_urls or [],
                stage_band=StageBand.GROWTH,
                size_band=SizeBand.MID,
                methodology_version="1.0.0",
                ruleset_version="1.0.0",
                prompt_version="1.0.0",
                model_id="heuristic:ladder-1",
            )
        )
    return org.id, a.id


async def _acquire(
    db: Database, manifest: Manifest, settings: Settings, net: FakeInternet, assessment_id: UUID
) -> AcquisitionReport:
    service = _service(settings, manifest, net)
    with db.transaction("pytest", "hai_pipeline") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        return await service.acquire(conn, store, assessment_id)


async def test_acquisition_end_to_end(clean_db: Database, manifest: Manifest, settings: Settings) -> None:
    org_id, assessment_id = _new_assessment(clean_db, manifest, direct_urls=[f"https://{ORG_DOMAIN}/governance"])
    net = FakeInternet(inject=True)
    report = await _acquire(clean_db, manifest, settings, net, assessment_id)

    # Every connector ran and was recorded (IC-16), even the empty ones
    assert set(report.runs) == {
        "WEBSITE",
        "DIRECT_URL",
        "EDGAR",
        "NEWS",
        "GITHUB",
        "ACADEMIC",
        "WAYBACK",
        "UPLOAD",
        "ISO_42001",
    }
    assert all(v == "succeeded" for v in report.runs.values())
    with clean_db.connect() as conn:
        runs = conn.execute(
            text(
                "SELECT c.code, r.outcome::text, r.items_returned FROM hai.connector_runs r JOIN hai.connectors c ON c.id = r.connector_id WHERE r.assessment_id = :a"  # noqa: E501
            ),
            {"a": assessment_id},
        ).all()
        assert len(runs) == 9 and all(r[1] == "succeeded" for r in runs)
        by_code = {r[0]: r[2] for r in runs}
        assert by_code["ISO_42001"] == 0 and by_code["UPLOAD"] == 0 and by_code["GITHUB"] == 1 and by_code["NEWS"] >= 2

        # Entity resolution stored verified identifiers with the right Wikidata properties
        org = conn.execute(
            text("SELECT cik, lei, github_handle, identifiers_verified FROM hai.organizations WHERE id = :o"),
            {"o": org_id},
        ).one()
        assert org[0] == CIK and org[1] and org[2] == "acme-labs" and org[3] is True

        # Every span matches the stored text at its offsets (IC-03)
        blobs = BlobStore(settings.blob_store_url)
        spans = conn.execute(
            text(
                "SELECT s.char_start, s.char_end, s.quote, d.text_uri FROM hai.evidence_spans s JOIN hai.source_documents d ON d.id = s.source_document_id JOIN hai.connector_runs r ON r.id = d.connector_run_id WHERE r.assessment_id = :a"  # noqa: E501
            ),
            {"a": assessment_id},
        ).all()
        assert len(spans) == report.spans > 10
        texts: dict[str, str] = {}
        for start, end, quote, uri in spans:
            stored = texts.setdefault(uri, blobs.get_text(uri))
            assert stored[start:end] == quote

        # Injection text never becomes admissible; the clean page does
        rows = conn.execute(
            text(
                "SELECT l.admissibility::text, s.quote FROM hai.evidence_links l JOIN hai.evidence_spans s ON s.id = l.span_id JOIN hai.source_documents d ON d.id = s.source_document_id WHERE d.canonical_url LIKE '%blog/approach%'"  # noqa: E501
            ),
        ).all()
        assert rows and all(a == "inadmissible_untrusted" for a, q in rows if "Ignore previous" in q)
        admissible = conn.execute(
            text("SELECT count(*) FROM hai.evidence_links WHERE admissibility = 'admissible'")
        ).scalar_one()
        assert admissible > 5

        # One incident from two syndicated lawsuit articles, status alleged (IC-10, IC-11)
        incidents = conn.execute(
            text(
                "SELECT status::text, severity::text, most_material_criterion::text, title FROM hai.incidents WHERE org_id = :o"  # noqa: E501
            ),
            {"o": org_id},
        ).all()
        assert len(incidents) == 1
        assert incidents[0][0] == "alleged" and incidents[0][1] == "high" and incidents[0][2] == "ACC-01"
        contradicting = conn.execute(
            text(
                "SELECT count(*) FROM hai.evidence_links WHERE polarity = 'contradicts' AND admissibility = 'admissible'"  # noqa: E501
            )
        ).scalar_one()
        assert contradicting >= 2

        # Syndicated copies share a cluster (IC-09)
        clusters = conn.execute(
            text(
                "SELECT cluster_id, count(*) FROM hai.source_documents WHERE cluster_id IS NOT NULL GROUP BY cluster_id"
            )
        ).all()
        assert report.clusters >= 1 and any(c[1] >= 2 for c in clusters)

        # Publishers and tiers: the SEC filing is a regulator record, the archive is independent of the tier
        pubs = conn.execute(text("SELECT domain, publisher_type::text FROM hai.publishers ORDER BY domain")).all()
        types: dict[str, str] = dict(pubs)
        assert types.get("sec.gov") == "regulator_record" and types.get("acme.example") == "org_disclosure"
        assert types.get("dailywire.example") == "press" and types.get("archive.org") == "archive"
        archive_links = conn.execute(
            text(
                "SELECT DISTINCT l.independence::text FROM hai.evidence_links l JOIN hai.evidence_spans s ON s.id = l.span_id JOIN hai.source_documents d ON d.id = s.source_document_id JOIN hai.publishers p ON p.id = d.publisher_id WHERE p.publisher_type = 'archive'"  # noqa: E501
            )
        ).all()
        assert [r[0] for r in archive_links] == ["self"]

        # No metadata-only link gets maturity above none before classification
        assert (
            conn.execute(text("SELECT count(*) FROM hai.evidence_links WHERE maturity_rung <> 'none'")).scalar_one()
            == 0
        )

    # Snapshot freezes link states, incidents, runs and pins; same content hashes the same
    with clean_db.transaction("pytest", "hai_pipeline") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        a = store.require(Assessment, assessment_id)
        snap = build_snapshot(conn, store, a, manifest, frozen_at=datetime(2026, 10, 24, 12, 5, tzinfo=UTC))
    assert len(snap.link_ids) == report.links and len(snap.link_states) == report.links
    assert set(snap.connector_runs) == set(report.runs) and snap.connector_runs["WEBSITE"]["succeeded"]
    assert len(snap.incident_states) == 1 and snap.version_pins["model_id"] == "heuristic:ladder-1"
    with clean_db.transaction("pytest", "hai_pipeline") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        again = EvidenceSnapshot.model_validate(store.require(EvidenceSnapshot, snap.id).model_dump())
    assert again.snapshot_sha256 == snap.snapshot_sha256


async def test_blocked_sources_are_recorded_as_blocked(
    clean_db: Database, manifest: Manifest, settings: Settings
) -> None:
    _, assessment_id = _new_assessment(clean_db, manifest)
    report = await _acquire(
        clean_db, manifest, settings, FakeInternet(block_website=True, news_available=False), assessment_id
    )
    assert report.runs["WEBSITE"] == "blocked"
    assert report.runs["NEWS"] == "failed"
    assert report.runs["EDGAR"] == "succeeded"
    with clean_db.connect() as conn:
        row = conn.execute(
            text(
                "SELECT r.outcome::text, r.error_code, r.items_returned FROM hai.connector_runs r JOIN hai.connectors c ON c.id = r.connector_id WHERE r.assessment_id = :a AND c.code = 'WEBSITE'"  # noqa: E501
            ),
            {"a": assessment_id},
        ).one()
    assert row[0] == "blocked" and row[1] == "http_403" and row[2] == 0
