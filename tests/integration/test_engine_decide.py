"""Acquire, classify, freeze, evaluate, decide, replay, review, finalize, certify: against Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text

from hai_core.auth import Principal, Scope
from hai_core.blobstore import BlobStore
from hai_core.db.engine import Database
from hai_core.db.store import Store
from hai_core.errors import ForbiddenError
from hai_core.generated.enums import IncidentStatus, LifecycleState, SizeBand, StageBand
from hai_core.generated.models import Assessment, CriterionFinding, Incident, Organization
from hai_core.settings import Settings
from hai_engine.certification import CertificationService
from hai_engine.decision import DecisionService
from hai_engine.llm.heuristic import HeuristicProvider
from hai_engine.reporting import build_report
from hai_engine.services import classify_links, evaluate_assessment
from hai_ontology.meta import Manifest
from hai_pipeline.acquire import AcquisitionService
from hai_pipeline.config import load_connectors
from hai_pipeline.snapshot import build_snapshot
from tests.fixtures.fake_internet import ORG_DOMAIN, ORG_NAME, FakeInternet

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


async def _pipeline(db: Database, manifest: Manifest, settings: Settings, net: FakeInternet) -> tuple[UUID, UUID]:
    with db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = store.insert(Organization(legal_name=ORG_NAME, display_name=ORG_NAME, primary_domain=ORG_DOMAIN))
        a = store.insert(
            Assessment(
                org_id=org.id,
                requested_by="pytest",
                submitted_domain=ORG_DOMAIN,
                stage_band=StageBand.GROWTH,
                size_band=SizeBand.MID,
                methodology_version="1.0.0",
                ruleset_version="1.0.0",
                prompt_version="1.0.0",
                model_id="heuristic:ladder-1",
                lifecycle_state=LifecycleState.ACQUIRING,
            )
        )
    service = AcquisitionService(
        settings=settings,
        manifest=manifest,
        connectors=load_connectors(settings.connectors_config),
        blobs=BlobStore(settings.blob_store_url),
        transport=net.transport,
        now=NOW,
    )
    with db.transaction("pytest", "hai_pipeline") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        await service.acquire(conn, store, a.id)
    with db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        assert classify_links(conn, store, manifest, a.id) > 10
    with db.transaction("pytest", "hai_pipeline") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        store.update(Assessment, a.id, {"lifecycle_state": LifecycleState.EVALUATING})
        build_snapshot(conn, store, store.require(Assessment, a.id), manifest, frozen_at=NOW)
    with db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        summary = await evaluate_assessment(
            store,
            manifest,
            a.id,
            provider=HeuristicProvider(),
            prompt_version="1.0.0",
            blobs=BlobStore(settings.blob_store_url),
        )
        assert summary.criteria == 20 and summary.accepted == 20 and summary.rejected == 0
    return org.id, a.id


async def test_decide_replay_and_report(clean_db: Database, manifest: Manifest, settings: Settings) -> None:
    _org_id, assessment_id = await _pipeline(clean_db, manifest, settings, FakeInternet(inject=True))
    svc = DecisionService(manifest)
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        decision = svc.decide(conn, store, assessment_id)
    r = decision.result
    assert r.hai_score is not None and 0 < float(r.hai_score) <= 85
    assert len(decision.decisions) == 20 and len(decision.pillar_scores) == 6
    by_code = {str(d.criterion_code.value): d for d in decision.decisions}
    assert (
        by_code["SAF-01"].level is not None and by_code["SAF-01"].level >= 3
    )  # specified control plus dated results on the site
    assert all(d.applied_rule_codes for d in decision.decisions)
    # the alleged lawsuit incident routed its criterion to review with no automatic effect (IC-11)
    assert any(t.startswith("incident:") for t in r.review_triggers)
    assert by_code["ACC-01"].review_required
    # replay from the frozen snapshot matches the stored result (AT-07)
    with clean_db.connect() as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        ok, recomputed, stored = svc.replay(conn, store, assessment_id)
    assert ok and recomputed == stored
    # the report lists only sources collected through a succeeded run (IC-16) and renders stored values
    with clean_db.connect() as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        report = build_report(conn, store, manifest, assessment_id)
    assert (
        report["result"]["hai_score"] == float(r.hai_score)
        and report["result"]["outcome_status"] == r.outcome_status.value
    )
    assert len(report["criteria"]) == 20 and all(c["coverage_wording"] for c in report["criteria"])
    assert all(s["run_outcome"] == "succeeded" for s in report["sources"]) and len(report["connector_runs"]) == 9
    assert any(c["evidence"] for c in report["criteria"])
    assert not any(
        "Ignore previous" in e["quote"] and e["admissibility"] == "admissible"
        for c in report["criteria"]
        for e in c["evidence"]
    )
    # findings were stored for every criterion, accepted
    with clean_db.connect() as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        assert store.count(CriterionFinding, where={"assessment_id": assessment_id}) == 20


async def test_review_finalize_and_certification(clean_db: Database, manifest: Manifest, settings: Settings) -> None:
    org_id, assessment_id = await _pipeline(clean_db, manifest, settings, FakeInternet())
    svc = DecisionService(manifest)
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        first = svc.decide(conn, store, assessment_id)
    # a reviewer dismisses the alleged incident; finalize applies the overlay and supersedes rows
    with clean_db.transaction("reviewer:rev-1", "hai_reviewer") as conn:
        store = Store(conn, actor="reviewer:rev-1", manifest=manifest)
        inc = store.find(Incident, where={"org_id": org_id})[0]
        store.update(Incident, inc.id, {"status": IncidentStatus.DISMISSED}, reason="not this organization")
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        final = svc.finalize(conn, store, assessment_id)
    assert final.result.supersedes_id == first.result.id
    assert not any(t.startswith("incident:") for t in final.result.review_triggers)
    with clean_db.connect() as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        ok, _, _ = svc.replay(conn, store, assessment_id)
        live = svc.latest_decisions(store, assessment_id)
    assert ok and len(live) == 20 and all(d.supersedes_id for d in live)
    # certification: an API key cannot sign; a reviewer can; the signature verifies; revocation supersedes
    certs = CertificationService(manifest.methodology, "k" * 40)
    api_key = Principal("api_key", "partner", "Partner", Scope.PARTNER_DEFAULT)
    reviewer = Principal("reviewer", "rev-1", "Reviewer One", Scope.REVIEWER_DEFAULT)
    with clean_db.transaction("pytest", "hai_reviewer") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        assessment = store.require(Assessment, assessment_id)
        result = svc.latest_result(store, assessment_id)
        assert result is not None
        with pytest.raises(ForbiddenError):
            certs.sign(
                store, assessment=assessment, result=result, principal=api_key, decision="not_certified", reason="x"
            )
        signed = certs.sign(
            store,
            assessment=assessment,
            result=result,
            principal=reviewer,
            decision="not_certified",
            reason="score below threshold",
            now=NOW,
        )
    assert signed.certificate_number is None and signed.reviewer_id == "rev-1"
    # force a certified decision by clearing gate reasons on a copy, then verify and revoke
    with clean_db.transaction("pytest", "hai_reviewer") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        assessment = store.require(Assessment, assessment_id)
        result = svc.latest_result(store, assessment_id)
        assert result is not None
        eligible = result.model_copy(update={"gate_reasons": []})
        cert = certs.sign(
            store,
            assessment=assessment,
            result=eligible,
            principal=reviewer,
            decision="certified",
            reason="pilot",
            now=NOW,
        )
        assert cert.certificate_number and cert.expires_at is not None
        verified = certs.verify(store, cert.certificate_number, now=NOW)
        assert verified.valid and verified.status == "valid" and verified.organization == ORG_NAME
        assert certs.verify(store, cert.certificate_number, now=datetime(2028, 1, 1, tzinfo=UTC)).status == "expired"
        assert certs.verify(store, "HAI-0000-NOPE").status == "not_found"
        revoked = certs.revoke(store, current=cert, principal=reviewer, reason="appeal upheld", now=NOW)
        assert revoked.supersedes_id == cert.id
        assert certs.verify(store, cert.certificate_number, now=NOW).status == "revoked"
    with clean_db.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM hai.certification_decisions WHERE assessment_id = :a"), {"a": assessment_id}
        ).scalar_one()
    assert n == 3
