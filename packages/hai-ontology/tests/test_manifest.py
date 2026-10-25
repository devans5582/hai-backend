"""The shipped manifest: valid, the right shape, hashed, with every label and alias."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hai_ontology.codegen import check, render_all
from hai_ontology.codegen.jsonschema_gen import finding_schema, proposal_schema
from hai_ontology.loader import ManifestLoadError, compute_hash, load_manifest
from hai_ontology.meta import Layer, Manifest, Mutability
from hai_ontology.validator import validate


def test_manifest_is_valid(manifest: Manifest) -> None:
    report = validate(manifest)
    assert report.errors == []
    assert report.warnings == []


def test_shape_matches_spec(manifest: Manifest) -> None:
    assert len(manifest.entities) == 30
    by_layer = {layer: [e for e in manifest.entities if e.layer == layer] for layer in Layer}
    assert len(by_layer[Layer.SUBJECT]) == 8
    assert len(by_layer[Layer.EVIDENCE]) == 7
    assert len(by_layer[Layer.METHODOLOGY]) == 6
    assert len(by_layer[Layer.ASSESSMENT]) == 9
    assert len(manifest.pillars) == 6
    assert len(manifest.criteria) == 20
    ics = [ic.id for ic in manifest.ontology.integrity_constraints]
    assert ics == [f"IC-{i:02d}" for i in range(1, 19)]
    ats = [at.id for at in manifest.ontology.acceptance_tests]
    assert ats == [f"AT-{i:02d}" for i in range(1, 16)]
    assert {c.pillar for c in manifest.criteria} == {p.code for p in manifest.pillars}
    assert [len(manifest.criteria_for_pillar(p.code)) for p in manifest.pillars] == [4, 3, 3, 3, 3, 4]


def test_pillar_weights_carry_phase6_pillar_max(manifest: Manifest) -> None:
    weights = {p.code: p.weight for p in manifest.pillars}
    assert weights == {"TRU": 0.20, "ACC": 0.15, "PUR": 0.15, "SAF": 0.15, "TRN": 0.15, "IMP": 0.20}
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_materiality_weights_match_phase6(manifest: Manifest) -> None:
    expected = {
        "trust_user_confidence": 1.2,
        "trust_consistency_of_behavior": 1.0,
        "trust_ethical_intent": 1.1,
        "trust_absence_of_manipulation": 1.1,
        "accountability_ownership_of_outcomes": 1.4,
        "accountability_corrective_action": 1.1,
        "accountability_governance_and_oversight": 1.3,
        "purpose_mission_clarity": 0.9,
        "purpose_human_centered_intent": 1.1,
        "purpose_alignment_words_actions": 1.1,
        "safety_risk_mitigation": 1.4,
        "safety_user_protection_mechanisms": 1.3,
        "safety_long_term_societal_safety": 1.3,
        "transparency_explainability": 1.2,
        "transparency_data_disclosure": 1.2,
        "transparency_communication_honesty": 1.1,
        "impact_positive_human_outcomes": 1.3,
        "impact_shared_human_benefit": 1.0,
        "impact_measurability_of_impact": 1.2,
        "impact_durability_of_impact": 0.8,
    }
    assert {c.legacy_id: c.materiality_weight for c in manifest.criteria} == expected


def test_derived_vocabularies(manifest: Manifest) -> None:
    crit = manifest.vocabularies["criterion_code"]
    assert crit.derived and crit.codes == [c.code for c in manifest.criteria]
    assert crit.resolve_alias("safety_risk_mitigation") == "SAF-01"
    pil = manifest.vocabularies["pillar_code"]
    assert pil.derived and pil.codes == ["TRU", "ACC", "PUR", "SAF", "TRN", "IMP"]
    assert pil.resolve_alias("trust") == "TRU"


def test_hand_written_derived_vocabulary_is_refused(copy: Path) -> None:
    (copy / "vocabularies" / "criterion_code.yaml").write_text(
        "vocabulary:\n  code: criterion_code\n  title: x\n  description: x\n  values:\n    - {code: a, label: A}\n"
    )
    with pytest.raises(ManifestLoadError, match="derived"):
        load_manifest(copy)


def test_unknown_yaml_keys_fail_loudly(copy: Path) -> None:
    path = copy / "vocabularies" / "polarity.yaml"
    path.write_text(path.read_text() + "  colour: red\n")
    with pytest.raises(ManifestLoadError, match="colour"):
        load_manifest(copy)


def test_hash_is_stable_and_sensitive(manifest: Manifest, copy: Path) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", manifest.hash)
    assert compute_hash(manifest) == manifest.hash
    again = load_manifest(copy)
    assert again.hash == manifest.hash
    path = copy / "vocabularies" / "polarity.yaml"
    path.write_text(path.read_text().replace("label: Supports", "label: Supports it"))
    assert load_manifest(copy).hash != manifest.hash


def test_aliases_map_phase6_inputs(manifest: Manifest) -> None:
    assert manifest.vocabularies["stage_band"].resolve_alias("startup") == "early"
    assert manifest.vocabularies["stage_band"].resolve_alias("enterprise") == "mature"
    assert manifest.vocabularies["size_band"].resolve_alias("1-10") == "small"
    assert manifest.vocabularies["size_band"].resolve_alias("1000+") == "enterprise"
    assert manifest.vocabularies["size_band"].resolve_alias("51-200") == "mid"


def test_every_code_has_a_label_and_no_orphans(manifest: Manifest) -> None:
    for voc in manifest.vocabularies.values():
        for v in voc.values:
            assert v.label.strip(), f"{voc.code}.{v.code}"
    labels = json.loads(render_all(manifest, Path("/x"))[9].content)
    for voc in manifest.vocabularies.values():
        assert set(labels["vocabularies"][voc.code]) == set(voc.codes)
    assert set(labels["criteria"]) == {c.code for c in manifest.criteria}


def test_llm_schema_has_every_criterion_and_enum(manifest: Manifest) -> None:
    fs = finding_schema(manifest)
    assert fs["additionalProperties"] is False
    assert set(fs["required"]) == set(fs["properties"])
    assert fs["properties"]["criterion_code"]["enum"] == [c.code for c in manifest.criteria]
    ps = proposal_schema(manifest)
    item = ps["properties"]["proposals"]["items"]
    assert item["additionalProperties"] is False
    assert item["properties"]["polarity"]["enum"] == manifest.vocabularies["polarity"].codes
    assert item["properties"]["criterion_code"]["enum"] == [c.code for c in manifest.criteria]


def test_generated_files_are_up_to_date(manifest: Manifest, repo_root: Path) -> None:
    stale = check(manifest, repo_root)
    assert stale == [], f"run hai-ontology codegen; stale: {[str(p.relative_to(repo_root)) for p in stale]}"


def test_generated_files_carry_header_and_hash(manifest: Manifest, repo_root: Path) -> None:
    for gf in render_all(manifest, repo_root):
        text = gf.path.read_text(encoding="utf-8")
        assert manifest.hash in text, gf.path
        assert "generated by hai-ontology" in text or '"x-generated"' in text or "hai:manifestHash" in text, gf.path


def test_every_criterion_has_a_monotonic_ladder(manifest: Manifest) -> None:
    ranks = manifest.rung_ranks()
    for c in manifest.criteria:
        rungs = [ranks[lv.required_maturity_rung] for lv in sorted(c.levels, key=lambda x: x.level)]
        assert rungs == sorted(rungs), c.code
        assert [lv.level for lv in sorted(c.levels, key=lambda x: x.level)] == [1, 2, 3, 4, 5]


def test_every_ic_names_an_enforcement_point_and_test(manifest: Manifest) -> None:
    ats = {at.id: at for at in manifest.ontology.acceptance_tests}
    for ic in manifest.ontology.integrity_constraints:
        assert ic.implementation.strip()
        assert ic.acceptance_test in ats
    for at in ats.values():
        assert at.tests, at.id


def test_append_only_entities_match_ic02(manifest: Manifest) -> None:
    insert_only = {e.table for e in manifest.entities if e.mutability is not Mutability.MUTABLE}
    assert {"source_documents", "evidence_spans", "criterion_decisions", "audit_events"} <= insert_only


def test_drafts_are_marked(manifest: Manifest) -> None:
    for c in manifest.criteria:
        if c.content_status == "draft":
            assert "TODO(humaital)" in c.definition or "DRAFT" in c.definition, c.code
