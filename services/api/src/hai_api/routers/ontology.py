"""The running ontology and methodology, served from the manifest in memory. Public."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from hai_api.deps import State
from hai_core.errors import NotFoundError
from hai_engine.rules import RULE_IMPLEMENTATIONS
from hai_ontology.codegen import docs_gen

router = APIRouter(prefix="/v1", tags=["ontology"])


@router.get("/ontology", summary="Versions, hash and a summary of the running manifest")
def ontology_summary(st: State) -> dict[str, Any]:
    m = st.manifest
    return {
        "ontology_version": m.ontology_version,
        "methodology_version": m.methodology_version,
        "methodology_status": m.methodology.status,
        "ruleset_version": m.ruleset.version,
        "manifest_hash": m.hash,
        "title": m.ontology.ontology.title,
        "layers": [layer.model_dump() for layer in m.ontology.layers],
        "entities": [
            {
                "name": e.name,
                "table": e.table,
                "layer": e.layer,
                "mutability": e.mutability,
                "fields": len(e.all_fields),
            }
            for e in m.entities
        ],
        "vocabularies": sorted(m.vocabularies),
        "criteria": [c.code for c in m.criteria],
        "pillars": [p.code for p in m.pillars],
        "integrity_constraints": [ic.id for ic in m.ontology.integrity_constraints],
        "acceptance_tests": [at.id for at in m.ontology.acceptance_tests],
        "links": {
            "entities": "/v1/ontology/entities/{name}",
            "vocabularies": "/v1/ontology/vocabularies/{code}",
            "jsonld": "/v1/ontology/export/jsonld",
            "labels": "/v1/ontology/labels",
        },
    }


@router.get("/ontology/labels", summary="Report label dictionary")
def labels(st: State) -> dict[str, Any]:
    return docs_gen.labels(st.manifest)


@router.get("/ontology/export/jsonld", summary="JSON-LD (RDFS plus SKOS) export")
def jsonld(st: State) -> dict[str, Any]:
    return docs_gen.jsonld(st.manifest)


@router.get("/ontology/entities/{name}", summary="One entity with its fields, checks and relations")
def entity(name: str, st: State) -> dict[str, Any]:
    try:
        e = st.manifest.entity(name)
    except KeyError as exc:
        raise NotFoundError(f"no entity named {name}") from exc
    relations = [
        r.model_dump(by_alias=True)
        for r in st.manifest.ontology.relations
        if r.from_entity == name or name in r.to or any(fk.entity == name for fk in r.fks)
    ]
    return {**e.model_dump(), "fields": [f.model_dump() for f in e.all_fields], "relations": relations}


@router.get("/ontology/vocabularies/{code}", summary="One vocabulary with values, labels, attributes and transitions")
def vocabulary(code: str, st: State) -> dict[str, Any]:
    voc = st.manifest.vocabularies.get(code)
    if voc is None:
        raise NotFoundError(f"no vocabulary named {code}")
    return voc.model_dump()


@router.get("/ontology/integrity-constraints", summary="IC-01 to IC-18 and where each is enforced")
def integrity_constraints(st: State) -> dict[str, Any]:
    items = [ic.model_dump() for ic in st.manifest.ontology.integrity_constraints]
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.get("/ontology/{version}", summary="The manifest for a version (only the running version is served)")
def ontology_version(version: str, st: State) -> dict[str, Any]:
    m = st.manifest
    if version not in (m.ontology_version, "current"):
        raise NotFoundError(f"ontology {version} is not the running version {m.ontology_version}")
    return m.model_dump(mode="json", exclude={"source_dir", "examples_valid", "examples_invalid"})


@router.get("/methodology/criteria", summary="The criterion register")
def criteria(st: State) -> dict[str, Any]:
    items = [c.model_dump() for c in st.manifest.criteria]
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.get("/methodology/criteria/{code}", summary="One criterion (code or Phase 6 alias)")
def criterion(code: str, st: State) -> dict[str, Any]:
    resolved = st.manifest.vocabularies["criterion_code"].resolve_alias(code)
    if resolved is None:
        raise NotFoundError(f"no criterion {code}")
    return st.manifest.criterion(resolved).model_dump()


@router.get("/methodology/pillars", summary="The six pillars and weights")
def pillars(st: State) -> dict[str, Any]:
    items = [p.model_dump() for p in st.manifest.pillars]
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.get("/methodology/rules", summary="The ruleset and the registered implementations")
def rules(st: State) -> dict[str, Any]:
    items = [{**r.model_dump(), "implementation": RULE_IMPLEMENTATIONS.get(r.code)} for r in st.manifest.ruleset.rules]
    return {
        "ruleset_version": st.manifest.ruleset.version,
        "items": items,
        "total": len(items),
        "limit": len(items),
        "offset": 0,
    }


@router.get("/methodology/decisions", summary="Open decisions D1 to D10 and the current behaviour")
def decisions(st: State) -> dict[str, Any]:
    items = [d.model_dump() for d in st.manifest.decisions]
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.get("/methodology/scoring", summary="Scoring, confidence, certification, outcome and freshness parameters")
def scoring(st: State) -> dict[str, Any]:
    md = st.manifest.methodology
    return {
        "version": md.version,
        "status": md.status,
        "product": md.product.model_dump(),
        "scoring": md.scoring.model_dump(),
        "confidence": md.confidence.model_dump(),
        "certification": md.certification.model_dump(),
        "outcome": md.outcome.model_dump(),
        "freshness": md.freshness.model_dump(),
        "review_triggers": md.review_triggers.model_dump(),
    }
