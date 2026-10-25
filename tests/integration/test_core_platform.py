"""Postgres-backed tests for hai-core: migrations, audit chain, triggers, constraints, queue, store, auth, seed."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from hai_core.audit import append_event, verify_chain
from hai_core.auth import Scope, create_api_key, revoke_api_key, verify_api_key
from hai_core.db.engine import Database
from hai_core.db.migrate import MigrationError, discover, migrate, migration_status
from hai_core.db.store import Store
from hai_core.errors import (
    AppendOnlyError,
    CertificationRequiredError,
    ConflictError,
    ForbiddenError,
    ImmutableFieldError,
    IntegrityViolationError,
    InvalidTransitionError,
    ValidationFailedError,
)
from hai_core.generated.enums import (
    Admissibility,
    CoverageState,
    EvidenceClass,
    ExecutionLevel,
    Independence,
    LifecycleState,
    MaturityRung,
    OutcomeStatus,
    Polarity,
    PublisherType,
    SizeBand,
    SourceTier,
    StageBand,
    TargetType,
)
from hai_core.generated.models import (
    Assessment,
    AssessmentResult,
    CriterionDecision,
    EvidenceLink,
    EvidenceSpan,
    Organization,
    Publisher,
)
from hai_core.queue import JobQueue
from hai_core.seed import seed_methodology
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration

ENFORCED = os.environ.get("HAI_ENFORCE_DB_ROLES", "").lower() in ("1", "true", "yes")


def _org(store: Store) -> Organization:
    return store.insert(
        Organization(legal_name="Acme Corp", display_name="Acme", primary_domain=f"acme-{uuid4().hex[:6]}.example")
    )


def _assessment(store: Store, org: Organization) -> Assessment:
    return store.insert(
        Assessment(
            org_id=org.id,
            requested_by="pytest",
            submitted_domain=org.primary_domain,
            stage_band=StageBand.GROWTH,
            size_band=SizeBand.MID,
            methodology_version="1.0.0",
            ruleset_version="1.0.0",
            prompt_version="1.0.0",
            model_id="heuristic:ladder-1",
        )
    )


def test_migrations_are_recorded_with_checksums(clean_db: Database, repo_root: Path, tmp_path: Path) -> None:
    status = migration_status(clean_db, repo_root / "db" / "migrations")
    assert all(s.applied and s.checksum_ok for s in status)
    assert [s.filename for s in status][:2] == ["0001_ontology_baseline.sql", "0002_operations.sql"]
    # Re-running is a no-op
    assert migrate(clean_db, repo_root / "db" / "migrations") == []
    # An edited migration is refused
    edited = tmp_path / "migrations"
    edited.mkdir()
    for m in discover(repo_root / "db" / "migrations"):
        (edited / m.filename).write_text(m.sql)
    (edited / "0002_operations.sql").write_text("-- edited\n" + (edited / "0002_operations.sql").read_text())
    with pytest.raises(MigrationError, match="never edited"):
        migrate(clean_db, edited)


def test_schema_versions_record_the_manifest(clean_db: Database, manifest: Manifest) -> None:
    with clean_db.connect() as conn:
        row = conn.execute(
            text("SELECT ontology_version, methodology_version, manifest_hash FROM hai.schema_versions")
        ).one()
    assert (row[0], row[1], row[2]) == (manifest.ontology_version, manifest.methodology_version, manifest.hash)


def test_methodology_is_seeded_from_yaml(clean_db: Database, manifest: Manifest) -> None:
    with clean_db.connect() as conn:
        n_crit = conn.execute(text("SELECT count(*) FROM hai.criteria")).scalar_one()
        n_levels = conn.execute(text("SELECT count(*) FROM hai.level_descriptors")).scalar_one()
        n_rules = conn.execute(text("SELECT count(*) FROM hai.rules")).scalar_one()
        n_conn = conn.execute(text("SELECT count(*) FROM hai.connectors WHERE status = 'active'")).scalar_one()
    assert (n_crit, n_levels, n_rules, n_conn) == (20, 100, 16, 9)
    with clean_db.transaction("pytest", "hai_admin") as conn:
        counts = seed_methodology(conn, manifest)  # idempotent
    assert counts["criteria"] == 20
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM hai.criteria")).scalar_one() == 20


def test_every_write_is_audited_and_the_chain_verifies(clean_db: Database, manifest: Manifest) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = _org(store)
        assessment = _assessment(store, org)
        store.update(
            Assessment, assessment.id, {"lifecycle_state": LifecycleState.ACQUIRING}, reason="worker picked it up"
        )
    with clean_db.connect() as conn:
        result = verify_chain(conn)
        events = conn.execute(text("SELECT action, subject_type FROM hai.audit_events ORDER BY seq")).all()
    assert result.ok and result.events == 3
    assert [tuple(e) for e in events] == [
        ("insert", "Organization"),
        ("insert", "Assessment"),
        ("update", "Assessment"),
    ]


def test_audit_tampering_is_detected(clean_db: Database) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        for i in range(3):
            append_event(conn, actor="pytest", action="note", subject_type="Test", subject_id=None, after={"i": i})
    with clean_db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE hai.audit_events DISABLE TRIGGER trg_audit_events_append_only"))
        conn.execute(text("UPDATE hai.audit_events SET after = '{\"i\": 99}'::jsonb WHERE seq = 2"))
        conn.execute(text("ALTER TABLE hai.audit_events ENABLE TRIGGER trg_audit_events_append_only"))
    with clean_db.connect() as conn:
        result = verify_chain(conn)
    assert result.ok is False and result.first_bad_seq == 2
    assert "altered" in result.message


def test_append_only_tables_refuse_updates(clean_db: Database) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        append_event(conn, actor="pytest", action="note", subject_type="Test", subject_id=None)
    # as the table owner (no role switch) the trigger is what refuses the change
    with pytest.raises(AppendOnlyError), clean_db.transaction("pytest") as conn:
        conn.execute(text("UPDATE hai.audit_events SET actor = 'mallory'"))
    with pytest.raises(AppendOnlyError), clean_db.transaction("pytest") as conn:
        conn.execute(text("DELETE FROM hai.audit_events"))
    if ENFORCED:  # under a component role the missing UPDATE grant refuses it even earlier
        with pytest.raises((AppendOnlyError, ForbiddenError)), clean_db.transaction("pytest", "hai_admin") as conn:
            conn.execute(text("UPDATE hai.audit_events SET actor = 'mallory'"))


def test_polarity_is_immutable(clean_db: Database, manifest: Manifest) -> None:
    link = _make_link(clean_db, manifest)
    with pytest.raises(ImmutableFieldError), clean_db.transaction("pytest", "hai_reviewer") as conn:
        conn.execute(text("UPDATE hai.evidence_links SET polarity = 'contradicts' WHERE id = :id"), {"id": link.id})
    # The store refuses before the database does
    with clean_db.transaction("pytest", "hai_reviewer") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        with pytest.raises(ImmutableFieldError):
            store.update(EvidenceLink, link.id, {"polarity": Polarity.CONTRADICTS})
        # admissibility may change via review
        updated = store.update(
            EvidenceLink,
            link.id,
            {"admissibility": Admissibility.PENDING_REVIEW, "reviewer_id": "rev-1"},
            reason="review",
        )
    assert updated.admissibility is Admissibility.PENDING_REVIEW


def _make_link(
    db: Database,
    manifest: Manifest,
    *,
    independence: Independence = Independence.SELF,
    rung: MaturityRung = MaturityRung.NONE,
) -> EvidenceLink:
    with db.transaction("pytest", "hai_pipeline") as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        org = _org(store)
        pub = store.insert(
            Publisher(
                name="Acme", domain=org.primary_domain, publisher_type=PublisherType.ORG_DISCLOSURE, org_id=org.id
            )
        )
        assessment = _assessment(store, org)
        run_id = conn.execute(
            text(
                "INSERT INTO hai.connector_runs (ontology_version, assessment_id, connector_id, outcome, started_at) "
                "VALUES ('1.0.0', :a, (SELECT id FROM hai.connectors WHERE code = 'WEBSITE'), 'succeeded', now()) RETURNING id"  # noqa: E501
            ),
            {"a": assessment.id},
        ).scalar_one()
        doc_id = conn.execute(
            text(
                "INSERT INTO hai.source_documents (ontology_version, canonical_url, publisher_id, connector_run_id, retrieved_at, "  # noqa: E501
                "sha256, text_sha256, snapshot_uri, text_uri, extraction_version) VALUES ('1.0.0', :u, :p, :r, now(), 'a', 'b', 'file:///x', 'file:///y', 'html-1') RETURNING id"  # noqa: E501
            ),
            {"u": f"https://{org.primary_domain}/ethics", "p": pub.id, "r": run_id},
        ).scalar_one()
        span = store.insert(EvidenceSpan(source_document_id=doc_id, char_start=0, char_end=5, quote="hello"))
        return store.insert(
            EvidenceLink(
                span_id=span.id,
                target_type=TargetType.ORGANIZATION,
                target_id=org.id,
                criterion_code=manifest.criteria[0].code,
                polarity=Polarity.SUPPORTS,
                admissibility=Admissibility.ADMISSIBLE,
                maturity_rung=rung,
                execution_level=ExecutionLevel.NONE,
                evidence_class=EvidenceClass.CORE_GOVERNANCE,
                independence=independence,
                source_tier=SourceTier.T3,
                proposer="pytest",
            )
        )


def test_check_constraints_come_from_the_ontology(clean_db: Database, manifest: Manifest) -> None:
    # IC-07 at the database, bypassing the Pydantic validator
    link = _make_link(clean_db, manifest)
    with pytest.raises(IntegrityViolationError) as exc, clean_db.transaction("pytest", "hai_engine") as conn:
        conn.execute(
            text("UPDATE hai.evidence_links SET maturity_rung = 'independently_verified' WHERE id = :id"),
            {"id": link.id},
        )
    assert exc.value.details.get("constraint") == "ck_evidence_links_ic_07"
    # IC-07 at the model
    with pytest.raises(ValueError, match="IC-07"):
        EvidenceLink(
            span_id=uuid4(),
            target_type=TargetType.ORGANIZATION,
            target_id=uuid4(),
            criterion_code=manifest.criteria[0].code,
            polarity=Polarity.SUPPORTS,
            admissibility=Admissibility.ADMISSIBLE,
            maturity_rung=MaturityRung.INDEPENDENTLY_VERIFIED,
            execution_level=ExecutionLevel.NONE,
            evidence_class=EvidenceClass.CORE_GOVERNANCE,
            independence=Independence.SELF,
            source_tier=SourceTier.T3,
            proposer="x",
        )
    # IC-14 at the database
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        a = _assessment(store, _org(store))
    with pytest.raises(IntegrityViolationError) as exc2, clean_db.transaction("pytest", "hai_engine") as conn:
        conn.execute(
            text(
                "INSERT INTO hai.criterion_decisions (ontology_version, assessment_id, criterion_code, level, coverage_state, confidence, applied_rule_codes, trace) "  # noqa: E501
                "VALUES ('1.0.0', :a, :c, 2, 'observed', 10, '{}', '[]')"
            ),
            {"a": a.id, "c": manifest.criteria[0].code},
        )
    assert exc2.value.details.get("constraint") == "ck_criterion_decisions_ic_14"
    # Enum constraint
    with (
        pytest.raises(Exception, match="invalid input value for enum"),
        clean_db.transaction("pytest", "hai_api") as conn,
    ):
        conn.execute(
            text(
                "INSERT INTO hai.publishers (ontology_version, name, domain, publisher_type) VALUES ('1.0.0', 'x', 'x.example', 'blog')"  # noqa: E501
            )
        )


def test_lifecycle_transitions_are_enforced_by_the_database(clean_db: Database, manifest: Manifest) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        a = _assessment(store, _org(store))
    with pytest.raises(InvalidTransitionError), clean_db.transaction("pytest", "hai_engine") as conn:
        Store(conn, actor="pytest", manifest=manifest).update(
            Assessment, a.id, {"lifecycle_state": LifecycleState.COMPLETED}
        )
    with clean_db.transaction("pytest", "hai_pipeline") as conn:
        Store(conn, actor="pytest", manifest=manifest).update(
            Assessment, a.id, {"lifecycle_state": LifecycleState.ACQUIRING}
        )
        Store(conn, actor="pytest", manifest=manifest).update(
            Assessment, a.id, {"lifecycle_state": LifecycleState.EVALUATING}
        )
    with clean_db.connect() as conn:
        state = conn.execute(
            text("SELECT lifecycle_state FROM hai.assessments WHERE id = :id"), {"id": a.id}
        ).scalar_one()
    assert state == "evaluating"


def test_version_pins_are_mandatory(clean_db: Database, manifest: Manifest) -> None:
    with pytest.raises(IntegrityViolationError), clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        org = _org(store)
        conn.execute(
            text(
                "INSERT INTO hai.assessments (ontology_version, org_id, requested_by, submitted_domain, stage_band, size_band, "  # noqa: E501
                "methodology_version, ruleset_version, prompt_version, lifecycle_state) VALUES ('1.0.0', :o, 'x', 'x', 'early', 'small', '1.0.0', '1.0.0', '1.0.0', 'queued')"  # noqa: E501
            ),
            {"o": org.id},
        )


def test_hai_certified_requires_signed_decision(clean_db: Database, manifest: Manifest) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        a = _assessment(
            Store(conn, actor="pytest", manifest=manifest, audit=False),
            _org(Store(conn, actor="pytest", manifest=manifest, audit=False)),
        )
    with pytest.raises(CertificationRequiredError), clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        store.insert(
            AssessmentResult(
                assessment_id=a.id,
                hai_score=80,
                confidence_pct=80,
                effectiveness=50,
                outcome_status=OutcomeStatus.HAI_CERTIFIED,
                ruleset_version="1.0.0",
                result_sha256="x",
            )
        )


def test_escalation_and_four_eyes(clean_db: Database, manifest: Manifest) -> None:
    """AT-14: escalate hands the task to a different reviewer; the escalating reviewer is locked out; the
    reviewer who requested certification cannot sign it; every action needs a reason."""
    from hai_core.auth import Principal, Scope
    from hai_core.generated.enums import IncidentSeverity, IncidentStatus, ReviewSubjectType
    from hai_core.generated.models import Incident
    from hai_core.reviews import act, create_task, get_task

    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        org = _org(store)
        assessment = _assessment(store, org)
    with clean_db.transaction("pytest", "hai_pipeline") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        incident = store.insert(
            Incident(
                canonical_event_key=uuid4().hex,
                org_id=org.id,
                title="Lawsuit reported",
                severity=IncidentSeverity.HIGH,
                most_material_criterion=manifest.criteria[0].code,
            )
        )
    one = Principal("reviewer", "rev-1", "Reviewer One", Scope.REVIEWER_DEFAULT)
    two = Principal("reviewer", "rev-2", "Reviewer Two", Scope.REVIEWER_DEFAULT)
    partner = Principal("api_key", "partner", "Partner", Scope.PARTNER_DEFAULT)
    with clean_db.transaction("pytest", "hai_reviewer") as conn:
        store = Store(conn, actor="pytest", manifest=manifest)
        task = create_task(
            conn,
            assessment_id=assessment.id,
            subject_type=ReviewSubjectType.INCIDENT.value,
            subject_id=incident.id,
            reason="alleged incident",
            opened_by="service:worker",
        )
        # the same open subject is never queued twice
        again = create_task(
            conn,
            assessment_id=assessment.id,
            subject_type=ReviewSubjectType.INCIDENT.value,
            subject_id=incident.id,
            reason="dup",
            opened_by="service:worker",
        )
        assert again.id == task.id
        with pytest.raises(ForbiddenError):
            act(conn, store, task_id=task.id, principal=partner, action="dismiss", reason="not allowed")
        with pytest.raises(ValidationFailedError):
            act(conn, store, task_id=task.id, principal=one, action="dismiss", reason="   ")
        with pytest.raises(ValidationFailedError):
            act(conn, store, task_id=task.id, principal=one, action="sign", reason="wrong action for an incident")
        _, escalated = act(conn, store, task_id=task.id, principal=one, action="escalate", reason="need a second look")
        assert escalated.status == "escalated" and escalated.excluded_reviewers == ["rev-1"]
        with pytest.raises(ForbiddenError):
            act(conn, store, task_id=task.id, principal=one, action="dismiss", reason="changed my mind")
        _, closed = act(conn, store, task_id=task.id, principal=two, action="dismiss", reason="not this organization")
        assert closed.status == "closed" and closed.closed_by == "rev-2"
        assert store.require(Incident, incident.id).status is IncidentStatus.DISMISSED
        with pytest.raises(ConflictError):
            act(conn, store, task_id=task.id, principal=two, action="dismiss", reason="already closed")
        # four eyes: the reviewer who opened a certification task cannot sign it
        cert = create_task(
            conn,
            assessment_id=assessment.id,
            subject_type=ReviewSubjectType.CERTIFICATION.value,
            subject_id=assessment.id,
            reason="certification requested",
            opened_by=one.actor,
        )
        with pytest.raises(ForbiddenError):
            act(conn, store, task_id=cert.id, principal=one, action="sign", reason="signing my own request")
        assert get_task(conn, cert.id).status == "open"


def test_store_refuses_append_only_updates_before_the_database(clean_db: Database, manifest: Manifest) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        api_store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        a = _assessment(api_store, _org(api_store))
    with clean_db.transaction("pytest", "hai_engine") as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        decision = store.insert(
            CriterionDecision(
                assessment_id=a.id,
                criterion_code=manifest.criteria[0].code,
                level=2,
                coverage_state=CoverageState.OBSERVED,
                confidence=40,
                applied_rule_codes=["GATE-COVERAGE"],
                trace=[],
            )
        )
        with pytest.raises(AppendOnlyError):
            store.update(CriterionDecision, decision.id, {"level": 3})
        newer = store.supersede(decision, decision.model_copy(update={"id": uuid4(), "level": 3}), reason="finalize")
    assert newer.supersedes_id == decision.id


def test_queue_claims_each_job_once_with_dedupe_and_backoff(clean_db: Database) -> None:
    q = JobQueue()
    with clean_db.transaction("pytest", "hai_api") as conn:
        first = q.enqueue(conn, "acquire_evidence", {"assessment_id": "a"}, dedupe_key="acquire:a", max_attempts=2)
        dup = q.enqueue(conn, "acquire_evidence", {"assessment_id": "a"}, dedupe_key="acquire:a")
        later = q.enqueue(conn, "monitoring_tick", {}, run_after=datetime.now(UTC) + timedelta(hours=1))
        urgent = q.enqueue(conn, "deliver_webhook", {}, priority=10)
    assert first is not None and dup is None and later is not None and urgent is not None
    with clean_db.transaction("pytest", "hai_engine") as conn:
        j1 = q.claim(conn, "w1")
        j2 = q.claim(conn, "w2")
        j3 = q.claim(conn, "w3")
    assert j1 is not None and j1.id == urgent and j1.attempts == 1
    assert j2 is not None and j2.id == first
    assert j3 is None  # the future job is not due
    with clean_db.transaction("pytest", "hai_engine") as conn:
        assert q.fail(conn, first, "boom") == "queued"
        job = q.get(conn, first)
        assert job is not None and job.run_after > datetime.now(UTC) + timedelta(seconds=3)
        conn.execute(text("UPDATE hai_ops.jobs SET run_after = now() WHERE id = :id"), {"id": first})
        again = q.claim(conn, "w1", kinds=["acquire_evidence"])
        assert again is not None and again.attempts == 2
        assert q.fail(conn, first, "boom again") == "dead"
        q.complete(conn, urgent, {"ok": True})
        counts = q.counts(conn)
    assert counts == {"dead": 1, "done": 1, "queued": 1}
    with clean_db.transaction("pytest", "hai_engine") as conn:
        conn.execute(text("UPDATE hai_ops.jobs SET run_after = now() WHERE id = :id"), {"id": later})
        j = q.claim(conn, "w1")
        assert j is not None
        conn.execute(
            text("UPDATE hai_ops.jobs SET lease_until = now() - interval '1 minute' WHERE id = :id"), {"id": later}
        )
        assert q.reap_expired(conn) == 1
        assert q.get(conn, later).state == "queued"  # type: ignore[union-attr]


def test_api_keys_are_hashed(clean_db: Database, settings: object) -> None:
    pepper = "p" * 40
    with clean_db.transaction("pytest", "hai_admin") as conn:
        plaintext, rec = create_api_key(conn, pepper, name="partner", scopes=Scope.PARTNER_DEFAULT, created_by="pytest")
        stored = conn.execute(
            text("SELECT key_hmac FROM hai_ops.api_keys WHERE key_id = :k"), {"k": rec.key_id}
        ).scalar_one()
    assert plaintext.startswith(f"hai_{rec.key_id}.") and plaintext.split(".", 1)[1] not in stored
    with clean_db.transaction("pytest", "hai_api") as conn:
        principal = verify_api_key(conn, pepper, plaintext)
        assert principal is not None and principal.kind == "api_key" and principal.has(Scope.ASSESSMENTS_WRITE)
        assert verify_api_key(conn, pepper, plaintext + "x") is None
        assert verify_api_key(conn, "other" * 8, plaintext) is None
        assert verify_api_key(conn, pepper, f"hai_{uuid4().hex[:12]}.secret") is None
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert revoke_api_key(conn, rec.key_id) is True
    with clean_db.transaction("pytest", "hai_api") as conn:
        assert verify_api_key(conn, pepper, plaintext) is None


def test_unique_constraints_become_conflicts(clean_db: Database, manifest: Manifest) -> None:
    with pytest.raises(ConflictError), clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        store.insert(Organization(legal_name="A", display_name="A", primary_domain="dupe.example"))
        store.insert(Organization(legal_name="B", display_name="B", primary_domain="dupe.example"))


@pytest.mark.skipif(not ENFORCED, reason="needs HAI_ENFORCE_DB_ROLES=true")
def test_result_tables_are_writable_only_by_engine_role(clean_db: Database, manifest: Manifest) -> None:
    with clean_db.transaction("pytest", "hai_api") as conn:
        store = Store(conn, actor="pytest", manifest=manifest, audit=False)
        a = _assessment(store, _org(store))
    decision = CriterionDecision(
        assessment_id=a.id,
        criterion_code=manifest.criteria[0].code,
        level=2,
        coverage_state=CoverageState.OBSERVED,
        confidence=40,
        applied_rule_codes=["GATE-COVERAGE"],
        trace=[],
    )
    for role in ("hai_api", "hai_pipeline", "hai_reviewer"):
        with pytest.raises(ForbiddenError), clean_db.transaction("pytest", role) as conn:
            Store(conn, actor="pytest", manifest=manifest, audit=False).insert(decision)
    with clean_db.transaction("pytest", "hai_engine") as conn:
        Store(conn, actor="pytest", manifest=manifest, audit=False).insert(decision)
    # Only reviewers write certification decisions; the engine cannot
    with pytest.raises(ForbiddenError), clean_db.transaction("pytest", "hai_engine") as conn:
        conn.execute(
            text(
                "INSERT INTO hai.certification_decisions (ontology_version, assessment_id, result_id, threshold_applied, decision, reviewer_id, signed_at, signature) "  # noqa: E501
                "VALUES ('1.0.0', :a, :a, 70, 'not_certified', 'r', now(), 'sig')"
            ),
            {"a": a.id},
        )
