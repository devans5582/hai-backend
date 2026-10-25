"""Broken copies of the manifest produce the expected stable error codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from hai_ontology.loader import ManifestLoadError, load_manifest
from hai_ontology.validator import validate


def _codes(path: Path, implementations: dict[str, str] | None = None) -> set[str]:
    return {i.code for i in validate(load_manifest(path), implementations).errors}


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new, 1))


def test_unknown_vocabulary_is_an_error(copy: Path) -> None:
    _edit(
        copy / "ontology.yaml",
        "vocabulary: polarity, required: true",
        "vocabulary: polarityx, required: true",
    )
    assert "E_REF_UNKNOWN_VOCAB" in _codes(copy)


def test_unknown_ref_entity_is_an_error(copy: Path) -> None:
    _edit(copy / "ontology.yaml", "ref: Publisher, required: true", "ref: Publisherz, required: true")
    assert "E_REF_UNKNOWN_ENTITY" in _codes(copy)


def test_fk_missing_from_relationship_catalogue_is_an_error(copy: Path) -> None:
    _edit(copy / "ontology.yaml", "  - { name: published_by,", "  - { name: published_by_x,")
    # the relation still exists under another name, so instead drop its fk
    _edit(
        copy / "ontology.yaml",
        "fks: [{ entity: SourceDocument, field: publisher_id, to: Publisher }]",
        "fks: [], polymorphic: { entity: SourceDocument, type_field: title, id_field: publisher_id }",
    )
    assert "E_FK_NOT_IN_CATALOGUE" in _codes(copy)


def test_relation_without_fk_is_an_error(copy: Path) -> None:
    _edit(
        copy / "ontology.yaml",
        'fks: [{ entity: AISystem, field: owner_org_id, to: Organization }], description: "System ownership can transfer."',  # noqa: E501
        'fks: [], description: "System ownership can transfer."',
    )
    codes = _codes(copy)
    assert "E_RELATION_NO_FK" in codes


def test_duplicate_codes_are_errors(copy: Path) -> None:
    _edit(copy / "vocabularies" / "polarity.yaml", "code: neutral", "code: supports")
    with pytest.raises(ManifestLoadError, match="duplicate"):
        load_manifest(copy)
    _edit(
        copy / "vocabularies" / "polarity.yaml",
        "code: supports, label: Neutral",
        "code: neutral, label: Neutral",
    )
    _edit(copy / "methodology" / "criteria" / "SAF-02.yaml", "code: SAF-02", "code: SAF-01")
    with pytest.raises(ManifestLoadError, match="duplicate"):
        load_manifest(copy)
    _edit(copy / "methodology" / "criteria" / "SAF-02.yaml", "code: SAF-01", "code: SAF-02")
    _edit(copy / "methodology" / "rules.yaml", "code: CAP-FAILED-EXECUTION", "code: CAP-MATURITY")
    assert "E_DUPLICATE_CODE" in _codes(copy)


def test_pillar_weights_must_sum_to_one(copy: Path) -> None:
    _edit(
        copy / "methodology" / "pillars.yaml",
        "weight: 0.20\n    description: Users",
        "weight: 0.25\n    description: Users",
    )
    assert "E_PILLAR_WEIGHTS" in _codes(copy)


def test_decreasing_ladder_is_an_error(copy: Path) -> None:
    path = copy / "methodology" / "criteria" / "TRU-01.yaml"
    _edit(
        path,
        "level: 4\n      required_maturity_rung: documented_execution",
        "level: 4\n      required_maturity_rung: stated_commitment",
    )
    assert "E_LADDER_NOT_MONOTONIC" in _codes(copy)


def test_levels_must_be_one_to_five(copy: Path) -> None:
    path = copy / "methodology" / "criteria" / "TRU-01.yaml"
    _edit(path, "- level: 5", "- level: 6")
    assert "E_LEVELS_COUNT" in _codes(copy)


def test_rule_implementation_must_be_registered(copy: Path) -> None:
    impl = {"GATE-APPLICABILITY": "hai_engine.rules.builtin:gate_applicability"}
    codes = _codes(copy, impl)
    assert "E_RULE_IMPL_UNRESOLVED" in codes
    full = {r.code: r.expression_ref for r in load_manifest(copy).ruleset.rules}
    assert "E_RULE_IMPL_UNRESOLVED" not in _codes(copy, full)
    full["CAP-MATURITY"] = "hai_engine.rules.builtin:somewhere_else"
    assert "E_RULE_IMPL_MISMATCH" in _codes(copy, full)


def test_rule_expression_ref_format(copy: Path) -> None:
    _edit(
        copy / "methodology" / "rules.yaml",
        "expression_ref: hai_engine.rules.builtin:cap_maturity",
        "expression_ref: not a ref",
    )
    assert "E_RULE_IMPL_FORMAT" in _codes(copy)


def test_name_collision_between_vocabulary_and_entity(copy: Path) -> None:
    (copy / "vocabularies" / "reviews.yaml").write_text(
        "vocabulary:\n  code: reviews\n  title: Reviews\n  description: collides with a table\n  values:\n    - {code: a, label: A, description: a}\n"  # noqa: E501
    )
    assert "E_NAME_COLLISION" in _codes(copy)


def test_invalid_example_is_an_error(copy: Path) -> None:
    (copy / "examples" / "valid" / "bad.json").write_text(
        '{"entity": "Publisher", "description": "missing domain", "record": {"name": "x", "publisher_type": "press"}}'
    )
    assert "E_EXAMPLE_INVALID" in _codes(copy)


def test_invalid_example_must_name_its_error(copy: Path) -> None:
    (copy / "examples" / "invalid" / "wrong.json").write_text(
        '{"entity": "Publisher", "description": "says the wrong error", "expect_error": "E_RANGE", '
        '"record": {"name": "x", "publisher_type": "press"}}'
    )
    assert "E_EXAMPLE_INVALID" in _codes(copy)


def test_unsafe_check_expression_is_an_error(copy: Path) -> None:
    _edit(copy / "ontology.yaml", 'py: "char_end > char_start"', "py: \"__import__('os').system('x')\"")
    assert "E_CHECK_UNSAFE" in _codes(copy)


def test_transition_vocabulary_must_define_transitions(copy: Path) -> None:
    _edit(
        copy / "ontology.yaml",
        "transitions: { field: status, vocabulary: incident_status }",
        "transitions: { field: severity, vocabulary: incident_severity }",
    )
    assert "E_TRANSITIONS_UNDEFINED" in _codes(copy)


def test_default_must_be_a_vocabulary_value(copy: Path) -> None:
    _edit(copy / "ontology.yaml", "required: true, default: alleged", "required: true, default: rumoured")
    assert "E_DEFAULT_NOT_IN_VOCAB" in _codes(copy)


def test_unknown_methodology_references(copy: Path) -> None:
    _edit(
        copy / "methodology" / "methodology.yaml",
        "excluded_coverage_states: [unavailable, not_applicable]",
        "excluded_coverage_states: [unavailable, gone]",
    )
    assert "E_ENUM_VALUE" in _codes(copy)


def test_bad_lexicon_regex(copy: Path) -> None:
    _edit(
        copy / "methodology" / "methodology.yaml",
        '"ignore (all )?(previous|prior|above) instructions"',
        '"ignore (all"',
    )
    assert "E_LEXICON_REGEX" in _codes(copy)


def test_criterion_code_format(copy: Path) -> None:
    path = copy / "methodology" / "criteria" / "IMP-04.yaml"
    _edit(path, "code: IMP-04", "code: IMP-4")
    assert "E_CRITERION_CODE_FORMAT" in _codes(copy)
