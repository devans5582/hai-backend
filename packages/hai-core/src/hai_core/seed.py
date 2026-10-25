"""Seed methodology rows and connector rows from YAML. Idempotent."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, text

from hai_core.db.store import Store
from hai_core.generated.enums import (
    ConnectorStatus,
    ContentStatus,
    Materiality,
    MaturityRung,
    MethodologyStatus,
    RuleKind,
    RuleScope,
)
from hai_core.generated.models import (
    Connector,
    Criterion,
    CriterionApplicability,
    LevelDescriptor,
    MethodologyVersion,
    Pillar,
    Rule,
)
from hai_ontology.meta import Manifest


def seed_methodology(conn: Connection, manifest: Manifest, *, actor: str = "hai-db") -> dict[str, int]:
    store = Store(conn, actor=actor, manifest=manifest, audit=False)
    md = manifest.methodology
    mv = store.upsert(
        MethodologyVersion(
            semver=md.version,
            effective_from=md.effective_from,
            approved_by=md.approved_by,
            change_record_uri=md.change_record_uri,
            status=MethodologyStatus(md.status),
            manifest_hash=manifest.hash,
        ),
        conflict_fields=["semver"],
    )
    counts = {"pillars": 0, "criteria": 0, "level_descriptors": 0, "applicability": 0, "rules": 0}
    pillar_ids: dict[str, Any] = {}
    for p in manifest.pillars:
        row = store.upsert(
            Pillar(
                methodology_version_id=mv.id, code=p.code, name=p.name, display_order=p.display_order, weight=p.weight
            ),
            conflict_fields=["methodology_version_id", "code"],
        )
        pillar_ids[p.code] = row.id
        counts["pillars"] += 1
    for c in manifest.criteria:
        crit = store.upsert(
            Criterion(
                methodology_version_id=mv.id,
                pillar_id=pillar_ids[c.pillar],
                code=c.code,
                pillar_code=c.pillar,
                name=c.name,
                definition=c.definition,
                legacy_id=c.legacy_id,
                content_status=ContentStatus(c.content_status),
                materiality=Materiality(c.materiality),
                materiality_weight=c.materiality_weight,
                weight=c.weight,
                freshness_window_months=c.freshness_window_months,
            ),
            conflict_fields=["methodology_version_id", "code"],
        )
        counts["criteria"] += 1
        for lv in c.levels:
            store.upsert(
                LevelDescriptor(
                    criterion_id=crit.id,
                    level=lv.level,
                    descriptor=lv.descriptor,
                    required_maturity_rung=MaturityRung(lv.required_maturity_rung),
                ),
                conflict_fields=["criterion_id", "level"],
            )
            counts["level_descriptors"] += 1
        conn.execute(text("DELETE FROM hai.criterion_applicability WHERE criterion_id = :cid"), {"cid": crit.id})
        for a in c.applicability:
            store.insert(CriterionApplicability(criterion_id=crit.id, condition=a.condition, effect=a.effect))
            counts["applicability"] += 1
    for r in manifest.ruleset.rules:
        store.upsert(
            Rule(
                ruleset_version=manifest.ruleset.version,
                code=r.code,
                kind=RuleKind(r.kind),
                scope=RuleScope(r.scope),
                run_order=r.run_order,
                expression_ref=r.expression_ref,
                parameters=r.parameters,
                description=r.description,
            ),
            conflict_fields=["ruleset_version", "code"],
        )
        counts["rules"] += 1
    return counts


def load_connector_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "connectors" not in data:
        raise ValueError(f"{path} must contain a connectors list")
    return data


def seed_connectors(conn: Connection, manifest: Manifest, config: dict[str, Any], *, actor: str = "hai-db") -> int:
    store = Store(conn, actor=actor, manifest=manifest, audit=False)
    n = 0
    for c in config["connectors"]:
        status = ConnectorStatus.ACTIVE if c.get("enabled", True) else ConnectorStatus.CONFIGURED
        store.upsert(
            Connector(
                code=str(c["code"]),
                name=str(c.get("name", c["code"])),
                access_terms=c.get("access_terms"),
                status=status,
            ),
            conflict_fields=["code"],
        )
        n += 1
    return n


def seed_all(conn: Connection, manifest: Manifest, connectors_config: Path, *, actor: str = "hai-db") -> dict[str, int]:
    counts = seed_methodology(conn, manifest, actor=actor)
    counts["connectors"] = seed_connectors(conn, manifest, load_connector_config(connectors_config), actor=actor)
    counts["seeded_at"] = int(datetime.now(UTC).timestamp())
    return counts
