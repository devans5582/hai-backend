"""Semver, diff classification, bump checks and migration plans."""

from __future__ import annotations

from pathlib import Path

import pytest

from hai_ontology.loader import load_manifest
from hai_ontology.meta import Manifest
from hai_ontology.versioning import ChangeLevel, Version, bump, check_bump, diff, migrate_plan, required_bump


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def test_semver_ordering() -> None:
    assert Version.parse("1.2.3") < Version.parse("1.10.0") < Version.parse("2.0.0")
    assert str(Version.parse("1.2.3").bumped(ChangeLevel.MINOR)) == "1.3.0"
    assert bump("1.2.3", "major") == "2.0.0"
    assert bump("1.2.3", "patch") == "1.2.4"
    assert Version.parse("1.3.0").level_from(Version.parse("1.2.9")) is ChangeLevel.MINOR
    with pytest.raises(ValueError):
        Version.parse("1.2")


@pytest.mark.parametrize(
    ("version", "spec", "ok"),
    [
        ("1.4.2", "^1.2.0", True),
        ("2.0.0", "^1.2.0", False),
        ("1.2.9", "~1.2.0", True),
        ("1.3.0", "~1.2.0", False),
        ("1.3.0", ">=1.2.0", True),
        ("1.3.0", "1.3.0", True),
        ("1.3.1", "==1.3.0", False),
    ],
)
def test_ranges(version: str, spec: str, ok: bool) -> None:
    assert Version.parse(version).satisfies(spec) is ok


def test_no_changes_need_no_bump(manifest: Manifest, copy: Path) -> None:
    changes = diff(manifest, load_manifest(copy))
    assert changes == []
    assert all(r.ok and r.required is ChangeLevel.NONE for r in check_bump(manifest, load_manifest(copy)))


def test_first_release_is_accepted(manifest: Manifest) -> None:
    results = check_bump(None, manifest)
    assert all(r.ok for r in results)
    assert diff(None, manifest)[0].level is ChangeLevel.NONE


def test_label_change_is_patch(manifest: Manifest, copy: Path) -> None:
    _edit(copy / "vocabularies" / "polarity.yaml", "label: Supports", "label: Supports the target")
    changes = diff(manifest, load_manifest(copy))
    assert required_bump(changes, "ontology") is ChangeLevel.PATCH
    results = {r.scope: r for r in check_bump(manifest, load_manifest(copy))}
    assert results["ontology"].ok is False  # version did not move
    _edit(copy / "ontology.yaml", "version: 1.0.0", "version: 1.0.1")
    results = {r.scope: r for r in check_bump(manifest, load_manifest(copy))}
    assert results["ontology"].ok is True


def test_adding_an_enum_value_is_minor_and_migrates(manifest: Manifest, copy: Path) -> None:
    _edit(
        copy / "vocabularies" / "polarity.yaml",
        "    - { code: neutral,",
        "    - { code: mixed, label: Mixed, description: Both ways. }\n    - { code: neutral,",
    )
    new = load_manifest(copy)
    changes = diff(manifest, new)
    assert required_bump(changes, "ontology") is ChangeLevel.MINOR
    plan = migrate_plan(manifest, new)
    assert "ALTER TYPE hai.polarity ADD VALUE IF NOT EXISTS 'mixed' AFTER 'contradicts';" in plan


def test_adding_an_optional_field_is_minor(manifest: Manifest, copy: Path) -> None:
    _edit(
        copy / "ontology.yaml",
        '      - { name: domain, type: text, required: true, unique: true, description: "Registrable domain." }',
        '      - { name: domain, type: text, required: true, unique: true, description: "Registrable domain." }\n'
        "      - { name: country, type: text, description: Country of registration. }",
    )
    new = load_manifest(copy)
    assert required_bump(diff(manifest, new), "ontology") is ChangeLevel.MINOR
    plan = migrate_plan(manifest, new)
    assert "ALTER TABLE hai.publishers ADD COLUMN IF NOT EXISTS country text;" in plan


def test_adding_an_entity_is_minor_and_creates_the_table(manifest: Manifest, copy: Path) -> None:
    _edit(
        copy / "ontology.yaml",
        "# Relationship catalogue",
        "  - name: Note\n    table: notes\n    layer: assessment\n    mutability: append_only\n"
        "    writers: [hai_api]\n    description: A note.\n    fields:\n"
        "      - { name: body, type: text, required: true, description: Text. }\n\n# Relationship catalogue",
    )
    new = load_manifest(copy)
    assert required_bump(diff(manifest, new), "ontology") is ChangeLevel.MINOR
    plan = migrate_plan(manifest, new)
    assert "CREATE TABLE hai.notes" in plan and "trg_notes_append_only" in plan


def test_removing_a_field_is_breaking(manifest: Manifest, copy: Path) -> None:
    _edit(
        copy / "ontology.yaml",
        '      - { name: rights, type: text, description: "Usage rights or licence noted at fetch time." }\n',
        "",
    )
    new = load_manifest(copy)
    assert required_bump(diff(manifest, new), "ontology") is ChangeLevel.MAJOR
    with pytest.raises(ValueError, match="breaking"):
        migrate_plan(manifest, new)
    skeleton = migrate_plan(manifest, new, allow_breaking=True)
    assert "TODO breaking" in skeleton and "DROP COLUMN rights" in skeleton


def test_new_required_field_is_breaking(manifest: Manifest, copy: Path) -> None:
    _edit(
        copy / "ontology.yaml",
        '      - { name: domain, type: text, required: true, unique: true, description: "Registrable domain." }',
        '      - { name: domain, type: text, required: true, unique: true, description: "Registrable domain." }\n'
        "      - { name: country, type: text, required: true, description: Country. }",
    )
    assert required_bump(diff(manifest, load_manifest(copy)), "ontology") is ChangeLevel.MAJOR


def test_methodology_weight_change_needs_methodology_major(manifest: Manifest, copy: Path) -> None:
    _edit(
        copy / "methodology" / "criteria" / "SAF-01.yaml",
        "materiality_weight: 1.4",
        "materiality_weight: 1.5",
    )
    changes = diff(manifest, load_manifest(copy))
    assert required_bump(changes, "methodology") is ChangeLevel.MAJOR
    assert required_bump(changes, "ontology") is ChangeLevel.NONE


def test_ladder_change_is_major_and_descriptor_wording_is_patch(manifest: Manifest, copy: Path) -> None:
    path = copy / "methodology" / "criteria" / "SAF-01.yaml"
    _edit(path, "DRAFT: No public evidence of risk mitigation.", "DRAFT: Nothing found on risk mitigation.")
    assert required_bump(diff(manifest, load_manifest(copy)), "methodology") is ChangeLevel.PATCH
    _edit(
        path,
        "level: 3\n      required_maturity_rung: specified_control",
        "level: 3\n      required_maturity_rung: stated_commitment",
    )
    assert required_bump(diff(manifest, load_manifest(copy)), "methodology") is ChangeLevel.MAJOR


def test_new_criterion_is_minor(manifest: Manifest, copy: Path) -> None:
    src = (copy / "methodology" / "criteria" / "IMP-04.yaml").read_text()
    (copy / "methodology" / "criteria" / "IMP-05.yaml").write_text(
        src.replace("code: IMP-04", "code: IMP-05")
        .replace("legacy_id: impact_durability_of_impact", "legacy_id: impact_new")
        .replace("I4_", "I5_")
    )
    assert required_bump(diff(manifest, load_manifest(copy)), "methodology") is ChangeLevel.MINOR


def test_version_going_backwards_fails(manifest: Manifest, copy: Path) -> None:
    _edit(copy / "ontology.yaml", "version: 1.0.0", "version: 0.9.0")
    results = {r.scope: r for r in check_bump(manifest, load_manifest(copy))}
    assert results["ontology"].ok is False
