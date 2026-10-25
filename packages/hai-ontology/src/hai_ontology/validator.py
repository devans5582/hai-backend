"""Manifest validator with stable error codes.

Checks references, the relationship catalogue, duplicate codes, pillar weights,
level ladders, rule implementations, name collisions, methodology references,
lexicon regular expressions and the example records.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from hai_ontology.conditions import UnsafeExpressionError, parse
from hai_ontology.meta import COMMON_FIELD_NAMES, EntityDef, FieldType, Manifest, Mutability
from hai_ontology.records import validate_record

__all__ = ["Issue", "ValidationReport", "validate"]

Severity = Literal["error", "warning"]
RULE_REF_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    path: str = ""
    severity: Severity = "error"

    def __str__(self) -> str:
        where = f" [{self.path}]" if self.path else ""
        return f"{self.severity.upper()} {self.code}{where}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}


def validate(manifest: Manifest, implementations: Mapping[str, str] | None = None) -> ValidationReport:
    """Validate ``manifest``. ``implementations`` maps rule code to the registered
    ``module:function`` reference; when given, every rule must resolve to it."""
    v = _Validator(manifest, implementations)
    v.run()
    return ValidationReport(v.issues)


class _Validator:
    def __init__(self, m: Manifest, implementations: Mapping[str, str] | None) -> None:
        self.m = m
        self.impl = implementations
        self.issues: list[Issue] = []

    def err(self, code: str, message: str, path: str = "") -> None:
        self.issues.append(Issue(code, message, path, "error"))

    def warn(self, code: str, message: str, path: str = "") -> None:
        self.issues.append(Issue(code, message, path, "warning"))

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        self.check_layers_and_roles()
        self.check_entities()
        self.check_relations()
        self.check_vocabularies()
        self.check_name_collisions()
        self.check_pillars_and_criteria()
        self.check_rules()
        self.check_ics_and_ats()
        self.check_methodology_refs()
        self.check_lexicons()
        self.check_examples()

    # ------------------------------------------------------------- entities
    def check_layers_and_roles(self) -> None:
        layers = {layer.code for layer in self.m.ontology.layers}
        roles = {r.code for r in self.m.ontology.roles}
        for e in self.m.entities:
            if e.layer not in layers:
                self.err("E_LAYER_UNKNOWN", f"layer {e.layer} is not declared", e.name)
            for w in e.writers:
                if w not in roles:
                    self.err("E_WRITER_UNKNOWN_ROLE", f"writer role {w!r} is not declared", e.name)
            if not e.writers:
                self.err("E_NO_WRITERS", "entity has no writer role", e.name)

    def check_entities(self) -> None:
        names = [e.name for e in self.m.entities]
        tables = [e.table for e in self.m.entities]
        for dupe in sorted({n for n in names if names.count(n) > 1}):
            self.err("E_DUPLICATE_CODE", f"entity {dupe} is declared twice")
        for dupe in sorted({t for t in tables if tables.count(t) > 1}):
            self.err("E_DUPLICATE_CODE", f"table {dupe} is declared twice")
        entity_names = set(names)
        for e in self.m.entities:
            if not e.description.strip():
                self.warn("W_NO_DESCRIPTION", "entity has no description", e.name)
            field_names = {f.name for f in e.all_fields}
            for f in e.all_fields:
                path = f"{e.name}.{f.name}"
                if not f.description.strip():
                    self.warn("W_NO_DESCRIPTION", "field has no description", path)
                if f.ref and f.ref not in entity_names:
                    self.err("E_REF_UNKNOWN_ENTITY", f"ref to unknown entity {f.ref}", path)
                if f.vocabulary and f.vocabulary not in self.m.vocabularies:
                    self.err("E_REF_UNKNOWN_VOCAB", f"unknown vocabulary {f.vocabulary}", path)
                if (
                    f.default is not None
                    and f.vocabulary
                    and f.vocabulary in self.m.vocabularies
                    and str(f.default) not in self.m.vocabularies[f.vocabulary].codes
                ):
                    self.err("E_DEFAULT_NOT_IN_VOCAB", f"default {f.default!r} is not in {f.vocabulary}", path)
                if (f.type is FieldType.REF and not self.m.fks_for(e.name)) or (
                    f.type is FieldType.REF and f.name not in {fk.field for fk in self.m.fks_for(e.name)}
                ):
                    self.err("E_FK_NOT_IN_CATALOGUE", "ref field has no relation in the catalogue", path)
            for group in e.unique:
                for name in group:
                    if name not in field_names:
                        self.err("E_UNIQUE_FIELD_UNKNOWN", f"unique group names unknown field {name}", e.name)
            for check in e.checks:
                self._check_expression(check.py, field_names, f"{e.name}:{check.id}")
            if e.transitions:
                tf = e.field_map.get(e.transitions.field)
                if tf is None:
                    self.err("E_TRANSITION_FIELD_UNKNOWN", f"no field {e.transitions.field}", e.name)
                elif tf.type is not FieldType.ENUM or tf.vocabulary != e.transitions.vocabulary:
                    self.err(
                        "E_TRANSITION_FIELD_MISMATCH",
                        "transition field must be an enum of that vocabulary",
                        e.name,
                    )
                voc = self.m.vocabularies.get(e.transitions.vocabulary)
                if voc is None:
                    self.err("E_REF_UNKNOWN_VOCAB", f"unknown vocabulary {e.transitions.vocabulary}", e.name)
                elif voc.transitions is None:
                    self.err("E_TRANSITIONS_UNDEFINED", f"vocabulary {voc.code} defines no transitions", e.name)
            if e.mutability is Mutability.IMMUTABLE and any(f.immutable for f in e.fields):
                self.warn("W_REDUNDANT_IMMUTABLE", "immutable entity marks fields immutable", e.name)

    def _check_expression(self, expr: str, field_names: set[str], path: str) -> None:
        try:
            tree = parse(expr)
        except UnsafeExpressionError as exc:
            self.err("E_CHECK_UNSAFE", str(exc), path)
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id not in field_names and node.id not in {"len", "nonblank"}:
                if node.id in COMMON_FIELD_NAMES:
                    continue
                self.err("E_CHECK_FIELD_UNKNOWN", f"expression names unknown field {node.id}", path)

    # ------------------------------------------------------------ relations
    def check_relations(self) -> None:
        names = [r.name for r in self.m.ontology.relations]
        for dupe in sorted({n for n in names if names.count(n) > 1}):
            self.err("E_DUPLICATE_CODE", f"relation {dupe} is declared twice")
        entity_names = set(self.m.entity_names)
        for rel in self.m.ontology.relations:
            for name in (rel.from_entity, *rel.to, *([rel.via] if rel.via else [])):
                if name not in entity_names:
                    self.err("E_REF_UNKNOWN_ENTITY", f"relation names unknown entity {name}", rel.name)
            if not rel.fks and not rel.polymorphic and not rel.array_field:
                self.err(
                    "E_RELATION_NO_FK",
                    "relation declares no foreign key, polymorphic or array field",
                    rel.name,
                )
            for fk in rel.fks:
                if fk.entity not in entity_names or fk.to not in entity_names:
                    self.err("E_REF_UNKNOWN_ENTITY", f"fk {fk.entity}.{fk.field} -> {fk.to}", rel.name)
                    continue
                field = self.m.entity(fk.entity).field_map.get(fk.field)
                if field is None:
                    self.err("E_RELATION_FK_UNKNOWN_FIELD", f"{fk.entity} has no field {fk.field}", rel.name)
                elif field.type is not FieldType.REF or field.ref != fk.to:
                    self.err("E_RELATION_FK_MISMATCH", f"{fk.entity}.{fk.field} is not a ref to {fk.to}", rel.name)
            if rel.polymorphic:
                p = rel.polymorphic
                if p.entity not in entity_names:
                    self.err("E_REF_UNKNOWN_ENTITY", f"polymorphic entity {p.entity}", rel.name)
                else:
                    fm = self.m.entity(p.entity).field_map
                    if p.type_field not in fm or p.id_field not in fm:
                        self.err("E_RELATION_FK_UNKNOWN_FIELD", "polymorphic fields missing", rel.name)
            if rel.array_field:
                a = rel.array_field
                if a.entity not in entity_names or a.to not in entity_names:
                    self.err("E_REF_UNKNOWN_ENTITY", f"array field {a.entity}.{a.field}", rel.name)
                else:
                    af = self.m.entity(a.entity).field_map.get(a.field)
                    if af is None or af.type is not FieldType.ARRAY or af.items is not FieldType.UUID:
                        self.err(
                            "E_RELATION_FK_MISMATCH",
                            f"{a.entity}.{a.field} is not an array of uuid",
                            rel.name,
                        )

    # --------------------------------------------------------- vocabularies
    def check_vocabularies(self) -> None:
        for voc in self.m.vocabularies.values():
            if not voc.description.strip():
                self.warn("W_NO_DESCRIPTION", "vocabulary has no description", voc.code)
            for v in voc.values:
                if not v.description.strip():
                    self.warn("W_NO_DESCRIPTION", "value has no description", f"{voc.code}.{v.code}")
                if not v.label.strip():
                    self.err("E_NO_LABEL", "value has no label", f"{voc.code}.{v.code}")
            codes_lower = [c.lower() for c in voc.codes]
            for v in voc.values:
                for alias in v.aliases:
                    if alias.lower() in codes_lower and alias.lower() != v.code.lower():
                        self.err(
                            "E_ALIAS_COLLISION",
                            f"alias {alias!r} is another value's code",
                            f"{voc.code}.{v.code}",
                        )

    def check_name_collisions(self) -> None:
        taken: dict[str, str] = {}
        for e in self.m.entities:
            taken[e.table] = f"table {e.table}"
            taken[_snake(e.name)] = f"entity {e.name}"
        for code in self.m.vocabularies:
            if code in taken:
                self.err("E_NAME_COLLISION", f"vocabulary {code} collides with {taken[code]}", code)

    # ------------------------------------------------------- methodology
    def check_pillars_and_criteria(self) -> None:
        pillars = self.m.pillars
        codes = [p.code for p in pillars]
        for dupe in sorted({c for c in codes if codes.count(c) > 1}):
            self.err("E_DUPLICATE_CODE", f"pillar {dupe} is declared twice")
        total = sum(p.weight for p in pillars)
        if abs(total - 1.0) > 1e-9:
            self.err("E_PILLAR_WEIGHTS", f"pillar weights sum to {total:.6f}, not 1.0")
        rungs = self.m.rung_ranks()
        materiality = self.m.vocabularies["materiality"].codes
        content_status = self.m.vocabularies["content_status"].codes
        target_types = self.m.vocabularies["target_type"].codes
        effects = self.m.vocabularies["applicability_effect"].codes
        ccodes = [c.code for c in self.m.criteria]
        for dupe in sorted({c for c in ccodes if ccodes.count(c) > 1}):
            self.err("E_DUPLICATE_CODE", f"criterion {dupe} is declared twice")
        legacy = [c.legacy_id for c in self.m.criteria]
        for dupe in sorted({c for c in legacy if legacy.count(c) > 1}):
            self.err("E_DUPLICATE_CODE", f"legacy id {dupe} is used twice")
        indicator_codes: list[str] = []
        code_re = re.compile(r"^[A-Z]{3}-\d{2}$")
        for c in self.m.criteria:
            if not code_re.match(c.code):
                self.err("E_CRITERION_CODE_FORMAT", f"{c.code} is not PIL-NN", c.code)
            if c.pillar not in codes:
                self.err("E_CRITERION_PILLAR_UNKNOWN", f"pillar {c.pillar} does not exist", c.code)
            elif not c.code.startswith(c.pillar + "-"):
                self.err("E_CRITERION_CODE_FORMAT", f"{c.code} does not start with its pillar {c.pillar}", c.code)
            if c.materiality not in materiality:
                self.err("E_ENUM_VALUE", f"materiality {c.materiality!r} unknown", c.code)
            if c.content_status not in content_status:
                self.err("E_ENUM_VALUE", f"content_status {c.content_status!r} unknown", c.code)
            for t in c.target_types:
                if t not in target_types:
                    self.err("E_ENUM_VALUE", f"target type {t!r} unknown", c.code)
            levels = sorted(lv.level for lv in c.levels)
            if levels != [1, 2, 3, 4, 5]:
                self.err("E_LEVELS_COUNT", f"levels are {levels}, expected 1 to 5", c.code)
            prev = -1
            for lv in sorted(c.levels, key=lambda x: x.level):
                rank = rungs.get(lv.required_maturity_rung)
                if rank is None:
                    self.err(
                        "E_RUNG_UNKNOWN",
                        f"level {lv.level} names unknown rung {lv.required_maturity_rung}",
                        c.code,
                    )
                    continue
                if rank < prev:
                    self.err(
                        "E_LADDER_NOT_MONOTONIC",
                        f"level {lv.level} requires a lower rung than level {lv.level - 1}",
                        c.code,
                    )
                prev = rank
                if not lv.descriptor.strip():
                    self.err("E_NO_LABEL", f"level {lv.level} has no descriptor", c.code)
            for a in c.applicability:
                if a.effect not in effects:
                    self.err("E_ENUM_VALUE", f"applicability effect {a.effect!r} unknown", c.code)
                try:
                    parse(a.condition)
                except UnsafeExpressionError as exc:
                    self.err("E_CONDITION_UNSAFE", str(exc), c.code)
            if not c.retrieval_hints:
                self.warn("W_NO_RETRIEVAL_HINTS", "criterion has no retrieval hints", c.code)
            indicator_codes.extend(i.code for i in c.indicators)
            if c.freshness_window_months < 1:
                self.err("E_RANGE", "freshness window must be positive", c.code)
        for dupe in sorted({c for c in indicator_codes if indicator_codes.count(c) > 1}):
            self.err("E_DUPLICATE_CODE", f"indicator {dupe} is used twice")

    def check_rules(self) -> None:
        kinds = self.m.vocabularies["rule_kind"].codes
        scopes = self.m.vocabularies["rule_scope"].codes
        codes = [r.code for r in self.m.ruleset.rules]
        for dupe in sorted({c for c in codes if codes.count(c) > 1}):
            self.err("E_DUPLICATE_CODE", f"rule {dupe} is declared twice")
        seen_order: dict[tuple[str, int], str] = {}
        for r in self.m.ruleset.rules:
            if r.kind not in kinds:
                self.err("E_ENUM_VALUE", f"rule kind {r.kind!r} unknown", r.code)
            if r.scope not in scopes:
                self.err("E_ENUM_VALUE", f"rule scope {r.scope!r} unknown", r.code)
            key = (r.scope, r.run_order)
            if key in seen_order:
                self.err("E_RULE_ORDER_DUPLICATE", f"shares run_order {r.run_order} with {seen_order[key]}", r.code)
            seen_order[key] = r.code
            if not RULE_REF_RE.match(r.expression_ref):
                self.err(
                    "E_RULE_IMPL_FORMAT",
                    f"expression_ref {r.expression_ref!r} is not module:function",
                    r.code,
                )
            if self.impl is not None:
                registered = self.impl.get(r.code)
                if registered is None:
                    self.err("E_RULE_IMPL_UNRESOLVED", f"no implementation registered under {r.code}", r.code)
                elif registered != r.expression_ref:
                    self.err(
                        "E_RULE_IMPL_MISMATCH",
                        f"registered {registered} but the ruleset says {r.expression_ref}",
                        r.code,
                    )
        if self.impl is not None:
            for code in sorted(set(self.impl) - set(codes)):
                self.warn("W_RULE_IMPL_UNUSED", f"implementation {code} is not in the ruleset", code)

    def check_ics_and_ats(self) -> None:
        ics = [ic.id for ic in self.m.ontology.integrity_constraints]
        ats = [at.id for at in self.m.ontology.acceptance_tests]
        for dupe in sorted({c for c in ics if ics.count(c) > 1}):
            self.err("E_DUPLICATE_CODE", f"integrity constraint {dupe} is declared twice")
        for dupe in sorted({c for c in ats if ats.count(c) > 1}):
            self.err("E_DUPLICATE_CODE", f"acceptance test {dupe} is declared twice")
        for ic in self.m.ontology.integrity_constraints:
            if ic.acceptance_test not in ats:
                self.err("E_IC_UNKNOWN_AT", f"names unknown acceptance test {ic.acceptance_test}", ic.id)
        for at in self.m.ontology.acceptance_tests:
            if not at.tests:
                self.warn("W_AT_NO_TESTS", "acceptance test lists no automated tests", at.id)

    def check_methodology_refs(self) -> None:
        md = self.m.methodology
        coverage = self.m.vocabularies["coverage_state"].codes
        rungs = self.m.vocabularies["maturity_rung"].codes
        severities = self.m.vocabularies["incident_severity"].codes
        statuses = self.m.vocabularies["incident_status"].codes
        pub_types = self.m.vocabularies["publisher_type"].codes
        tiers = self.m.vocabularies["source_tier"].codes
        pillars = [p.code for p in self.m.pillars]
        stages = self.m.vocabularies["stage_band"].codes
        sizes = self.m.vocabularies["size_band"].codes
        for s in md.scoring.excluded_coverage_states:
            if s not in coverage:
                self.err("E_ENUM_VALUE", f"excluded coverage state {s!r} unknown", "methodology.scoring")
        if md.scoring.effectiveness_min_rung not in rungs:
            self.err("E_ENUM_VALUE", "effectiveness_min_rung unknown", "methodology.scoring")
        if not (md.scoring.level_min == 1 and md.scoring.level_max == 5):
            self.err("E_RANGE", "levels must run 1 to 5", "methodology.scoring")
        voc, _, attr = md.confidence.execution_bonus_from.partition(".")
        if voc not in self.m.vocabularies or attr not in self.m.vocabularies[voc].attributes:
            self.err(
                "E_REF_UNKNOWN_VOCAB",
                f"execution_bonus_from {md.confidence.execution_bonus_from!r}",
                "methodology.confidence",
            )
        for key in md.freshness.decay_curves:
            if key != "default" and key not in pub_types:
                self.err("E_ENUM_VALUE", f"decay curve for unknown publisher type {key}", "methodology.freshness")
        if "default" not in md.freshness.decay_curves:
            self.err("E_REQUIRED", "decay_curves needs a default", "methodology.freshness")
        for row in md.certification.stage_size_table.rows:
            if row.stage_band not in stages or row.size_band not in sizes:
                self.err(
                    "E_ENUM_VALUE",
                    f"stage/size row {row.stage_band}/{row.size_band} unknown",
                    "methodology.certification",
                )
        for rule in md.lexicons.negative_signals.rules:
            if rule.severity not in severities:
                self.err("E_ENUM_VALUE", f"severity {rule.severity!r} unknown", rule.code)
            if rule.initial_status not in statuses:
                self.err("E_ENUM_VALUE", f"initial status {rule.initial_status!r} unknown", rule.code)
            for p in rule.publisher_types:
                if p not in pub_types:
                    self.err("E_ENUM_VALUE", f"publisher type {p!r} unknown", rule.code)
            for p in rule.affected_pillars:
                if p not in pillars:
                    self.err("E_ENUM_VALUE", f"pillar {p!r} unknown", rule.code)
        default = md.lexicons.negative_signals.default
        for tier, sev in default.severity_by_tier.items():
            if tier not in tiers or sev not in severities:
                self.err("E_ENUM_VALUE", f"default severity {tier}:{sev} unknown", "negative_signals.default")
        if default.initial_status not in statuses:
            self.err("E_ENUM_VALUE", "default initial status unknown", "negative_signals.default")

    def check_lexicons(self) -> None:
        lex = self.m.methodology.lexicons
        groups: list[tuple[str, list[str]]] = [
            ("commitment", lex.commitment.terms),
            ("control.owner", lex.control.owner_terms),
            ("control.threshold", lex.control.threshold_terms),
            ("execution_dates", lex.execution_dates.terms),
            ("execution_dates.result", lex.execution_dates.result_terms),
            ("independent_verification", lex.independent_verification.terms),
            ("injection", lex.injection.terms),
        ]
        for name, cat in lex.execution.categories.items():
            groups.append((f"execution.{name}", cat.patterns))
        for rule in lex.negative_signals.rules:
            groups.append((rule.code, rule.terms))
        from hai_ontology.terms import compile_term

        for name, terms in groups:
            for t in terms:
                try:
                    compile_term(t)
                except re.error as exc:
                    self.err("E_LEXICON_REGEX", f"{t!r}: {exc}", name)

    # --------------------------------------------------------------- examples
    def check_examples(self) -> None:
        entity_names = set(self.m.entity_names)
        for ex in self.m.examples_valid:
            if ex.entity not in entity_names:
                self.err("E_REF_UNKNOWN_ENTITY", f"example names unknown entity {ex.entity}", ex.path)
                continue
            errors = validate_record(self.m, self.m.entity(ex.entity), ex.record)
            if errors:
                self.err("E_EXAMPLE_INVALID", "; ".join(str(e) for e in errors), ex.path)
        for ex in self.m.examples_invalid:
            if ex.entity not in entity_names:
                self.err("E_REF_UNKNOWN_ENTITY", f"example names unknown entity {ex.entity}", ex.path)
                continue
            if not ex.expect_error:
                self.err("E_EXAMPLE_INVALID", "invalid example does not say which error it expects", ex.path)
                continue
            errors = validate_record(self.m, self.m.entity(ex.entity), ex.record)
            codes = {e.code for e in errors}
            if ex.expect_error not in codes:
                self.err(
                    "E_EXAMPLE_INVALID",
                    f"expected {ex.expect_error} but got {sorted(codes) or 'no errors'}",
                    ex.path,
                )


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def entity_fk_fields(entity: EntityDef) -> list[str]:
    return [f.name for f in entity.all_fields if f.type is FieldType.REF]
