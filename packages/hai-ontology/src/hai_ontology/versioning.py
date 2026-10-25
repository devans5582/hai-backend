"""Semver, manifest diff, bump classification and migration plans.

The ontology and the methodology are versioned separately. ``diff`` compares
two loaded manifests and classifies every change as patch, minor or major:

* patch: labels, descriptions, wording, decisions text
* minor: new vocabulary value, new optional field, new entity, new criterion,
  new rule, new relation, lexicon changes, parameter changes
* major: removal, rename, type change, new required field, weight or ladder
  change, threshold change, mutability change

``migrate_plan`` turns additive ontology changes into SQL and refuses breaking
changes unless ``allow_breaking`` is set, in which case it writes a skeleton.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from hai_ontology.meta import Manifest

__all__ = [
    "Change",
    "ChangeLevel",
    "Version",
    "bump",
    "check_bump",
    "diff",
    "migrate_plan",
    "required_bump",
]


class ChangeLevel(IntEnum):
    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> Version:
        m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text.strip())
        if not m:
            raise ValueError(f"not a semver version: {text!r}")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def bumped(self, level: ChangeLevel) -> Version:
        if level is ChangeLevel.MAJOR:
            return Version(self.major + 1, 0, 0)
        if level is ChangeLevel.MINOR:
            return Version(self.major, self.minor + 1, 0)
        if level is ChangeLevel.PATCH:
            return Version(self.major, self.minor, self.patch + 1)
        return self

    def level_from(self, old: Version) -> ChangeLevel:
        """How far this version moved from ``old``."""
        if self.major != old.major:
            return ChangeLevel.MAJOR
        if self.minor != old.minor:
            return ChangeLevel.MINOR
        if self.patch != old.patch:
            return ChangeLevel.PATCH
        return ChangeLevel.NONE

    def satisfies(self, spec: str) -> bool:
        """Simple range check: ``^1.2.0`` (same major, at least), ``~1.2.0`` (same minor),
        ``>=1.2.0``, ``==1.2.0`` or an exact version."""
        spec = spec.strip()
        if spec.startswith("^"):
            base = Version.parse(spec[1:])
            return self.major == base.major and self >= base
        if spec.startswith("~"):
            base = Version.parse(spec[1:])
            return (self.major, self.minor) == (base.major, base.minor) and self >= base
        if spec.startswith(">="):
            return self >= Version.parse(spec[2:])
        if spec.startswith("=="):
            return self == Version.parse(spec[2:])
        return self == Version.parse(spec)


def bump(version: str, level: ChangeLevel | str) -> str:
    lvl = level if isinstance(level, ChangeLevel) else ChangeLevel[level.upper()]
    return str(Version.parse(version).bumped(lvl))


@dataclass(frozen=True)
class Change:
    level: ChangeLevel
    scope: str  # ontology | methodology
    path: str
    description: str
    migration: str | None = None  # SQL for additive ontology changes
    breaking_note: str | None = None


# --------------------------------------------------------------------------- diff


def diff(old: Manifest | None, new: Manifest) -> list[Change]:
    """Classify every change from ``old`` to ``new``. ``old`` may be ``None`` (first release)."""
    if old is None:
        return [Change(ChangeLevel.NONE, "ontology", "", "first release: no previous manifest")]
    changes: list[Change] = []
    changes.extend(_diff_entities(old, new))
    changes.extend(_diff_vocabularies(old, new))
    changes.extend(_diff_relations(old, new))
    changes.extend(_diff_ics(old, new))
    changes.extend(_diff_methodology(old, new))
    return changes


def _keyed(items: Iterable[Any], key: str) -> dict[str, Any]:
    return {str(getattr(i, key)): i for i in items}


def _diff_entities(old: Manifest, new: Manifest) -> list[Change]:
    from hai_ontology.codegen import sql as sqlgen

    out: list[Change] = []
    o, n = _keyed(old.entities, "name"), _keyed(new.entities, "name")
    for name in sorted(set(o) - set(n)):
        out.append(
            Change(
                ChangeLevel.MAJOR,
                "ontology",
                f"entities.{name}",
                "entity removed",
                breaking_note=f"DROP TABLE {o[name].table}",
            )
        )
    for name in sorted(set(n) - set(o)):
        out.append(
            Change(
                ChangeLevel.MINOR,
                "ontology",
                f"entities.{name}",
                "entity added",
                migration=sqlgen.table_block(new, n[name]),
            )
        )
    for name in sorted(set(o) & set(n)):
        oe, ne = o[name], n[name]
        p = f"entities.{name}"
        if oe.table != ne.table:
            out.append(Change(ChangeLevel.MAJOR, "ontology", f"{p}.table", f"table renamed {oe.table} -> {ne.table}"))
        if oe.mutability != ne.mutability:
            out.append(
                Change(
                    ChangeLevel.MAJOR,
                    "ontology",
                    f"{p}.mutability",
                    f"mutability {oe.mutability} -> {ne.mutability}",
                )
            )
        if oe.layer != ne.layer:
            out.append(Change(ChangeLevel.MAJOR, "ontology", f"{p}.layer", "layer changed"))
        if oe.description != ne.description:
            out.append(
                Change(
                    ChangeLevel.PATCH,
                    "ontology",
                    f"{p}.description",
                    "description changed",
                    migration=sqlgen.comment_block(new, ne),
                )
            )
        if set(oe.writers) != set(ne.writers):
            out.append(
                Change(
                    ChangeLevel.MINOR,
                    "ontology",
                    f"{p}.writers",
                    "writer roles changed",
                    migration=sqlgen.grant_block(new, ne),
                )
            )
        if oe.transitions != ne.transitions:
            out.append(
                Change(
                    ChangeLevel.MINOR,
                    "ontology",
                    f"{p}.transitions",
                    "transition field changed",
                    migration=sqlgen.trigger_block(new, ne),
                )
            )
        of, nf = {f.name: f for f in oe.all_fields}, {f.name: f for f in ne.all_fields}
        for fname in sorted(set(of) - set(nf)):
            out.append(
                Change(
                    ChangeLevel.MAJOR,
                    "ontology",
                    f"{p}.{fname}",
                    "field removed",
                    breaking_note=f"ALTER TABLE {ne.table} DROP COLUMN {fname}",
                )
            )
        for fname in sorted(set(nf) - set(of)):
            fd = nf[fname]
            if fd.required and fd.default is None:
                out.append(
                    Change(
                        ChangeLevel.MAJOR,
                        "ontology",
                        f"{p}.{fname}",
                        "required field added without default",
                        breaking_note=f"ALTER TABLE {ne.table} ADD COLUMN {fname} ... NOT NULL -- needs a backfill",
                    )
                )
            else:
                out.append(
                    Change(
                        ChangeLevel.MINOR,
                        "ontology",
                        f"{p}.{fname}",
                        "optional field added",
                        migration=sqlgen.add_column(new, ne, fd),
                    )
                )
        for fname in sorted(set(of) & set(nf)):
            a, b = of[fname], nf[fname]
            fp = f"{p}.{fname}"
            if (a.type, a.items, a.vocabulary, a.ref) != (b.type, b.items, b.vocabulary, b.ref):
                out.append(Change(ChangeLevel.MAJOR, "ontology", fp, "field type changed"))
            if not a.required and b.required:
                out.append(Change(ChangeLevel.MAJOR, "ontology", fp, "field became required"))
            elif a.required and not b.required:
                out.append(
                    Change(
                        ChangeLevel.MINOR,
                        "ontology",
                        fp,
                        "field became optional",
                        migration=f"ALTER TABLE {new.schema_name}.{ne.table} ALTER COLUMN {fname} DROP NOT NULL;",
                    )
                )
            if a.immutable != b.immutable:
                out.append(
                    Change(
                        ChangeLevel.MINOR,
                        "ontology",
                        fp,
                        "immutability changed",
                        migration=sqlgen.trigger_block(new, ne),
                    )
                )
            if a.unique != b.unique:
                out.append(
                    Change(
                        ChangeLevel.MAJOR if b.unique else ChangeLevel.MINOR,
                        "ontology",
                        fp,
                        "uniqueness changed",
                    )
                )
            if (a.min, a.max) != (b.min, b.max):
                out.append(Change(ChangeLevel.MAJOR, "ontology", fp, "range changed"))
            if a.default != b.default:
                out.append(
                    Change(
                        ChangeLevel.MINOR,
                        "ontology",
                        fp,
                        "default changed",
                        migration=sqlgen.alter_default(new, ne, b),
                    )
                )
            if a.description != b.description:
                out.append(
                    Change(
                        ChangeLevel.PATCH,
                        "ontology",
                        fp,
                        "description changed",
                        migration=sqlgen.comment_block(new, ne),
                    )
                )
        oc, nc = {c.id: c for c in oe.checks}, {c.id: c for c in ne.checks}
        for cid in sorted(set(oc) - set(nc)):
            out.append(Change(ChangeLevel.MAJOR, "ontology", f"{p}.checks.{cid}", "check removed"))
        for cid in sorted(set(nc) - set(oc)):
            out.append(
                Change(
                    ChangeLevel.MINOR,
                    "ontology",
                    f"{p}.checks.{cid}",
                    "check added",
                    migration=sqlgen.add_check(new, ne, nc[cid]),
                )
            )
        for cid in sorted(set(oc) & set(nc)):
            if oc[cid].sql != nc[cid].sql or oc[cid].py != nc[cid].py:
                out.append(Change(ChangeLevel.MAJOR, "ontology", f"{p}.checks.{cid}", "check predicate changed"))
        if oe.unique != ne.unique:
            out.append(Change(ChangeLevel.MAJOR, "ontology", f"{p}.unique", "unique groups changed"))
    return out


def _diff_vocabularies(old: Manifest, new: Manifest) -> list[Change]:
    from hai_ontology.codegen import sql as sqlgen

    out: list[Change] = []
    o, n = old.vocabularies, new.vocabularies
    for code in sorted(set(o) - set(n)):
        out.append(
            Change(
                ChangeLevel.MAJOR,
                "ontology",
                f"vocabularies.{code}",
                "vocabulary removed",
                breaking_note=f"DROP TYPE {code}",
            )
        )
    for code in sorted(set(n) - set(o)):
        out.append(
            Change(
                ChangeLevel.MINOR,
                "ontology",
                f"vocabularies.{code}",
                "vocabulary added",
                migration=sqlgen.enum_ddl(new, n[code]),
            )
        )
    for code in sorted(set(o) & set(n)):
        ov, nv = o[code], n[code]
        p = f"vocabularies.{code}"
        scope = "methodology" if nv.derived else "ontology"
        ocodes, ncodes = ov.codes, nv.codes
        for value in [c for c in ocodes if c not in ncodes]:
            out.append(
                Change(
                    ChangeLevel.MAJOR,
                    scope,
                    f"{p}.{value}",
                    "value removed",
                    breaking_note=f"-- enum values cannot be dropped in place: recreate type {code}",
                )
            )
        prev: str | None = None
        for value in ncodes:
            if value not in ocodes:
                sql = f"ALTER TYPE {new.schema_name}.{code} ADD VALUE IF NOT EXISTS '{value}'" + (
                    f" AFTER '{prev}';" if prev else ";"
                )
                out.append(Change(ChangeLevel.MINOR, scope, f"{p}.{value}", "value added", migration=sql))
            prev = value
        shared = [c for c in ncodes if c in ocodes]
        if [c for c in ocodes if c in ncodes] != shared:
            out.append(
                Change(
                    ChangeLevel.MINOR,
                    scope,
                    p,
                    "value order changed",
                    migration="-- enum order changed; ranks live in the manifest, no SQL needed",
                )
            )
        if ov.transitions != nv.transitions:
            out.append(
                Change(
                    ChangeLevel.MINOR,
                    scope,
                    f"{p}.transitions",
                    "transitions changed",
                    migration=sqlgen.transition_blocks_for_vocabulary(new, code),
                )
            )
        for value in shared:
            a, b = ov.value(value), nv.value(value)
            if a.label != b.label or a.description != b.description:
                out.append(Change(ChangeLevel.PATCH, scope, f"{p}.{value}", "label or description changed"))
            if a.aliases != b.aliases:
                out.append(Change(ChangeLevel.MINOR, scope, f"{p}.{value}.aliases", "aliases changed"))
            if a.attributes != b.attributes:
                level = ChangeLevel.MAJOR if _is_weight_attr(a.attributes, b.attributes) else ChangeLevel.PATCH
                out.append(Change(level, scope, f"{p}.{value}.attributes", "attributes changed"))
            if a.rank != b.rank:
                out.append(Change(ChangeLevel.MINOR, scope, f"{p}.{value}.rank", "rank changed"))
        if ov.title != nv.title or ov.description != nv.description:
            out.append(Change(ChangeLevel.PATCH, scope, p, "title or description changed"))
    return out


_WEIGHT_ATTRS = {
    "weight",
    "credit",
    "multiplier",
    "bonus",
    "confidence_ceiling",
    "level_effect",
    "materiality_weight",
}


def _is_weight_attr(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return any(a.get(k) != b.get(k) for k in _WEIGHT_ATTRS)


def _diff_relations(old: Manifest, new: Manifest) -> list[Change]:
    from hai_ontology.codegen import sql as sqlgen

    out: list[Change] = []
    o, n = _keyed(old.ontology.relations, "name"), _keyed(new.ontology.relations, "name")
    for name in sorted(set(o) - set(n)):
        out.append(Change(ChangeLevel.MAJOR, "ontology", f"relations.{name}", "relation removed"))
    for name in sorted(set(n) - set(o)):
        out.append(
            Change(
                ChangeLevel.MINOR,
                "ontology",
                f"relations.{name}",
                "relation added",
                migration=sqlgen.fk_block_for_relation(new, n[name]),
            )
        )
    for name in sorted(set(o) & set(n)):
        if o[name].fks != n[name].fks or o[name].to != n[name].to:
            out.append(Change(ChangeLevel.MAJOR, "ontology", f"relations.{name}", "relation shape changed"))
        elif o[name].description != n[name].description:
            out.append(Change(ChangeLevel.PATCH, "ontology", f"relations.{name}", "description changed"))
    return out


def _diff_ics(old: Manifest, new: Manifest) -> list[Change]:
    out: list[Change] = []
    o, n = _keyed(old.ontology.integrity_constraints, "id"), _keyed(new.ontology.integrity_constraints, "id")
    for cid in sorted(set(o) - set(n)):
        out.append(Change(ChangeLevel.MAJOR, "ontology", f"ic.{cid}", "integrity constraint removed"))
    for cid in sorted(set(n) - set(o)):
        out.append(Change(ChangeLevel.MINOR, "ontology", f"ic.{cid}", "integrity constraint added"))
    for cid in sorted(set(o) & set(n)):
        if o[cid] != n[cid]:
            out.append(Change(ChangeLevel.PATCH, "ontology", f"ic.{cid}", "wording changed"))
    oa, na = _keyed(old.ontology.acceptance_tests, "id"), _keyed(new.ontology.acceptance_tests, "id")
    for aid in sorted(set(oa) ^ set(na)):
        out.append(Change(ChangeLevel.MINOR, "ontology", f"at.{aid}", "acceptance test added or removed"))
    for aid in sorted(set(oa) & set(na)):
        if oa[aid] != na[aid]:
            out.append(Change(ChangeLevel.PATCH, "ontology", f"at.{aid}", "acceptance test changed"))
    return out


def _diff_methodology(old: Manifest, new: Manifest) -> list[Change]:
    out: list[Change] = []
    op, np_ = _keyed(old.pillars, "code"), _keyed(new.pillars, "code")
    for code in sorted(set(op) ^ set(np_)):
        out.append(Change(ChangeLevel.MAJOR, "methodology", f"pillars.{code}", "pillar added or removed"))
    for code in sorted(set(op) & set(np_)):
        if op[code].weight != np_[code].weight:
            out.append(
                Change(
                    ChangeLevel.MAJOR,
                    "methodology",
                    f"pillars.{code}.weight",
                    f"weight {op[code].weight} -> {np_[code].weight}",
                )
            )
        if (op[code].name, op[code].description) != (np_[code].name, np_[code].description):
            out.append(Change(ChangeLevel.PATCH, "methodology", f"pillars.{code}", "wording changed"))
        if op[code].display_order != np_[code].display_order:
            out.append(Change(ChangeLevel.MINOR, "methodology", f"pillars.{code}.display_order", "order changed"))
    oc, nc = _keyed(old.criteria, "code"), _keyed(new.criteria, "code")
    for code in sorted(set(oc) - set(nc)):
        out.append(
            Change(
                ChangeLevel.MAJOR,
                "methodology",
                f"criteria.{code}",
                "criterion removed (codes are permanent; retire instead)",
            )
        )
    for code in sorted(set(nc) - set(oc)):
        out.append(Change(ChangeLevel.MINOR, "methodology", f"criteria.{code}", "criterion added"))
    for code in sorted(set(oc) & set(nc)):
        a, b = oc[code], nc[code]
        p = f"criteria.{code}"
        if a.pillar != b.pillar:
            out.append(Change(ChangeLevel.MAJOR, "methodology", f"{p}.pillar", "pillar changed"))
        if (a.weight, a.materiality_weight, a.materiality) != (b.weight, b.materiality_weight, b.materiality):
            out.append(Change(ChangeLevel.MAJOR, "methodology", f"{p}.weight", "weight or materiality changed"))
        if [(lv.level, lv.required_maturity_rung) for lv in a.levels] != [
            (lv.level, lv.required_maturity_rung) for lv in b.levels
        ]:
            out.append(Change(ChangeLevel.MAJOR, "methodology", f"{p}.levels", "ladder changed"))
        elif [lv.descriptor for lv in a.levels] != [lv.descriptor for lv in b.levels]:
            out.append(Change(ChangeLevel.PATCH, "methodology", f"{p}.levels", "descriptor wording changed"))
        if (a.name, a.definition, a.content_status) != (b.name, b.definition, b.content_status):
            out.append(Change(ChangeLevel.PATCH, "methodology", f"{p}.text", "name, definition or status changed"))
        if a.freshness_window_months != b.freshness_window_months:
            out.append(
                Change(
                    ChangeLevel.MINOR,
                    "methodology",
                    f"{p}.freshness_window_months",
                    "freshness window changed",
                )
            )
        if a.retrieval_hints != b.retrieval_hints or a.indicators != b.indicators:
            out.append(Change(ChangeLevel.PATCH, "methodology", f"{p}.hints", "retrieval hints or indicators changed"))
        if a.target_types != b.target_types or a.applicability != b.applicability:
            out.append(
                Change(
                    ChangeLevel.MINOR,
                    "methodology",
                    f"{p}.applicability",
                    "target types or applicability changed",
                )
            )
        if a.legacy_id != b.legacy_id:
            out.append(Change(ChangeLevel.MAJOR, "methodology", f"{p}.legacy_id", "alias changed"))
    orr, nrr = _keyed(old.ruleset.rules, "code"), _keyed(new.ruleset.rules, "code")
    for code in sorted(set(orr) - set(nrr)):
        out.append(Change(ChangeLevel.MAJOR, "methodology", f"rules.{code}", "rule removed"))
    for code in sorted(set(nrr) - set(orr)):
        out.append(Change(ChangeLevel.MINOR, "methodology", f"rules.{code}", "rule added"))
    for code in sorted(set(orr) & set(nrr)):
        a, b = orr[code], nrr[code]
        if (a.kind, a.scope, a.expression_ref) != (b.kind, b.scope, b.expression_ref):
            out.append(
                Change(
                    ChangeLevel.MAJOR,
                    "methodology",
                    f"rules.{code}",
                    "rule kind, scope or implementation changed",
                )
            )
        if a.parameters != b.parameters or a.run_order != b.run_order:
            out.append(Change(ChangeLevel.MINOR, "methodology", f"rules.{code}", "parameters or order changed"))
        if a.description != b.description:
            out.append(Change(ChangeLevel.PATCH, "methodology", f"rules.{code}.description", "wording changed"))
    om, nm = old.methodology, new.methodology
    for section, level in (
        ("scoring", ChangeLevel.MAJOR),
        ("confidence", ChangeLevel.MAJOR),
        ("certification", ChangeLevel.MAJOR),
        ("outcome", ChangeLevel.MAJOR),
        ("freshness", ChangeLevel.MAJOR),
        ("review_triggers", ChangeLevel.MINOR),
        ("lexicons", ChangeLevel.MINOR),
        ("product", ChangeLevel.PATCH),
    ):
        if getattr(om, section) != getattr(nm, section):
            out.append(Change(level, "methodology", f"methodology.{section}", f"{section} changed"))
    od, nd = _keyed(old.decisions, "id"), _keyed(new.decisions, "id")
    if od != nd:
        out.append(Change(ChangeLevel.PATCH, "methodology", "decisions", "decision text changed"))
    return out


# --------------------------------------------------------------------------- bump


def required_bump(changes: Iterable[Change], scope: str) -> ChangeLevel:
    level = ChangeLevel.NONE
    for c in changes:
        if c.scope == scope and c.level > level:
            level = c.level
    return level


@dataclass
class BumpCheck:
    scope: str
    old_version: str
    new_version: str
    required: ChangeLevel
    actual: ChangeLevel
    ok: bool
    notes: list[str] = field(default_factory=list)


def check_bump(old: Manifest | None, new: Manifest) -> list[BumpCheck]:
    """Check that the ontology and methodology versions moved at least as far as required."""
    changes = diff(old, new)
    results: list[BumpCheck] = []
    for scope, old_v, new_v in (
        ("ontology", old.ontology_version if old else None, new.ontology_version),
        ("methodology", old.methodology_version if old else None, new.methodology_version),
    ):
        required = required_bump(changes, scope)
        if old_v is None:
            results.append(BumpCheck(scope, "none", new_v, ChangeLevel.NONE, ChangeLevel.NONE, True, ["first release"]))
            continue
        actual = Version.parse(new_v).level_from(Version.parse(old_v))
        ok = actual >= required
        if Version.parse(new_v) < Version.parse(old_v):
            ok = False
        notes = [f"{c.level.label}: {c.path}: {c.description}" for c in changes if c.scope == scope]
        results.append(BumpCheck(scope, old_v, new_v, required, actual, ok, notes))
    return results


# ------------------------------------------------------------------- migrate plan


def migrate_plan(old: Manifest | None, new: Manifest, allow_breaking: bool = False) -> str:
    """SQL for the schema changes between two manifests.

    Additive changes emit statements; breaking changes raise ``ValueError`` unless
    ``allow_breaking``, which emits a skeleton with TODO markers.
    """
    changes = [c for c in diff(old, new) if c.scope == "ontology"]
    breaking = [c for c in changes if c.level is ChangeLevel.MAJOR]
    if breaking and not allow_breaking:
        lines = "\n".join(f"  - {c.path}: {c.description}" for c in breaking)
        raise ValueError(f"breaking changes need --allow-breaking:\n{lines}")
    out: list[str] = [
        f"-- migration plan: ontology {old.ontology_version if old else 'none'} -> {new.ontology_version}",
        f"-- generated by hai-ontology from manifest {new.hash}",
        "BEGIN;",
    ]
    if old is None:
        out.append("-- first release: apply the baseline migration instead")
    for c in changes:
        if c.level is ChangeLevel.MAJOR:
            out.append(f"-- TODO breaking: {c.path}: {c.description}")
            if c.breaking_note:
                out.append(f"-- {c.breaking_note}")
        elif c.migration:
            out.append(f"-- {c.level.label}: {c.path}: {c.description}")
            out.append(c.migration.rstrip())
    out.append(
        f"UPDATE {new.schema_name}.schema_versions SET ontology_version = '{new.ontology_version}', "
        f"manifest_hash = '{new.hash}', applied_at = now() WHERE singleton;"
    )
    out.append("COMMIT;")
    return "\n".join(out) + "\n"
