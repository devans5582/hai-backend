"""TypeScript generator: vocabulary unions, label maps, entity interfaces, methodology constants."""

from __future__ import annotations

import json

from hai_ontology.codegen.common import const_name, header, pascal
from hai_ontology.meta import FieldDef, FieldType, Manifest

TS_TYPES: dict[FieldType, str] = {
    FieldType.UUID: "string",
    FieldType.TEXT: "string",
    FieldType.INT: "number",
    FieldType.BIGINT: "number",
    FieldType.NUMERIC: "number",
    FieldType.BOOL: "boolean",
    FieldType.TIMESTAMP: "string",
    FieldType.DATE: "string",
    FieldType.JSON: "unknown",
    FieldType.REF: "string",
}


def _ts_type(f: FieldDef) -> str:
    if f.type is FieldType.ENUM:
        assert f.vocabulary is not None
        return pascal(f.vocabulary)
    if f.type is FieldType.ARRAY:
        assert f.items is not None
        if f.items is FieldType.ENUM:
            assert f.vocabulary is not None
            return f"{pascal(f.vocabulary)}[]"
        return f"{TS_TYPES[f.items]}[]"
    return TS_TYPES[f.type]


def typescript_module(manifest: Manifest) -> str:
    out = [header(manifest, "//"), "\n"]
    out.append(f'export const ONTOLOGY_VERSION = "{manifest.ontology_version}" as const;\n')
    out.append(f'export const METHODOLOGY_VERSION = "{manifest.methodology_version}" as const;\n')
    out.append(f'export const RULESET_VERSION = "{manifest.ruleset.version}" as const;\n')
    out.append(f'export const MANIFEST_HASH = "{manifest.hash}" as const;\n\n')
    for code in sorted(manifest.vocabularies):
        voc = manifest.vocabularies[code]
        name = pascal(code)
        values = ", ".join(f'"{v.code}"' for v in voc.ordered_values)
        out.append(f"/** {voc.title}: {voc.description} */\n")
        out.append(f"export const {const_name(code)}_VALUES = [{values}] as const;\n")
        out.append(f"export type {name} = (typeof {const_name(code)}_VALUES)[number];\n\n")
    labels = {code: {v.code: v.label for v in voc.values} for code, voc in sorted(manifest.vocabularies.items())}
    out.append(
        f"export const LABELS: Record<string, Record<string, string>> = {json.dumps(labels, indent=2, sort_keys=True)};\n\n"  # noqa: E501
    )
    descriptions = {
        code: {v.code: v.description for v in voc.values} for code, voc in sorted(manifest.vocabularies.items())
    }
    out.append(
        f"export const DESCRIPTIONS: Record<string, Record<string, string>> = {json.dumps(descriptions, indent=2, sort_keys=True)};\n\n"  # noqa: E501
    )
    attrs = {
        code: {v.code: v.attributes for v in voc.values if v.attributes}
        for code, voc in sorted(manifest.vocabularies.items())
        if voc.attributes
    }
    out.append(
        f"export const ATTRIBUTES: Record<string, Record<string, Record<string, unknown>>> = {json.dumps(attrs, indent=2, sort_keys=True)};\n\n"  # noqa: E501
    )
    transitions = {code: voc.transitions for code, voc in sorted(manifest.vocabularies.items()) if voc.transitions}
    out.append(
        f"export const TRANSITIONS: Record<string, Record<string, string[]>> = {json.dumps(transitions, indent=2, sort_keys=True)};\n\n"  # noqa: E501
    )
    review_actions = {
        v.code: v.attributes.get("allowed_actions", []) for v in manifest.vocabularies["review_subject_type"].values
    }
    out.append(
        f"export const REVIEW_ACTIONS_BY_SUBJECT: Record<ReviewSubjectType, ReviewAction[]> = {json.dumps(review_actions, indent=2, sort_keys=True)};\n\n"  # noqa: E501
    )
    coverage = {v.code: v.attributes for v in manifest.vocabularies["coverage_state"].values}
    out.append(
        f"export const COVERAGE_STATE_INFO: Record<CoverageState, {{ counts_in_score: boolean; report_wording: string; routes_to_review: boolean }}> = {json.dumps(coverage, indent=2, sort_keys=True)};\n\n"  # noqa: E501
    )
    pillars = [
        {
            "code": p.code,
            "name": p.name,
            "weight": p.weight,
            "display_order": p.display_order,
            "description": p.description,
        }
        for p in manifest.pillars
    ]
    out.append(
        "export interface PillarInfo { code: PillarCode; name: string; weight: number; display_order: number; description: string }\n"  # noqa: E501
    )
    out.append(f"export const PILLARS: PillarInfo[] = {json.dumps(pillars, indent=2)};\n\n")
    criteria = [
        {
            "code": c.code,
            "pillar": c.pillar,
            "name": c.name,
            "legacy_id": c.legacy_id,
            "materiality": c.materiality,
            "materiality_weight": c.materiality_weight,
            "weight": c.weight,
            "freshness_window_months": c.freshness_window_months,
            "content_status": c.content_status,
            "definition": c.definition,
            "levels": [
                {
                    "level": lv.level,
                    "required_maturity_rung": lv.required_maturity_rung,
                    "descriptor": lv.descriptor,
                }
                for lv in c.levels
            ],
        }
        for c in manifest.criteria
    ]
    out.append(
        "export interface CriterionInfo {\n  code: CriterionCode; pillar: PillarCode; name: string; legacy_id: string;\n"  # noqa: E501
        "  materiality: Materiality; materiality_weight: number; weight: number; freshness_window_months: number;\n"
        "  content_status: ContentStatus; definition: string;\n"
        "  levels: { level: number; required_maturity_rung: MaturityRung; descriptor: string }[];\n}\n"
    )
    out.append(f"export const CRITERIA: CriterionInfo[] = {json.dumps(criteria, indent=2)};\n\n")
    ics = [
        {
            "id": ic.id,
            "rule": ic.rule,
            "enforced_in": ic.enforced_in,
            "implementation": ic.implementation,
            "acceptance_test": ic.acceptance_test,
        }
        for ic in manifest.ontology.integrity_constraints
    ]
    out.append(f"export const INTEGRITY_CONSTRAINTS = {json.dumps(ics, indent=2)} as const;\n\n")
    rules = [
        {
            "code": r.code,
            "kind": r.kind,
            "scope": r.scope,
            "run_order": r.run_order,
            "description": r.description,
        }
        for r in manifest.ruleset.rules
    ]
    out.append(f"export const RULES = {json.dumps(rules, indent=2)} as const;\n\n")
    out.append(
        "export interface EntityBase { id: string; ontology_version: string; created_at: string; created_by: string }\n\n"  # noqa: E501
    )
    for e in manifest.entities:
        out.append(f"/** {e.description} */\n")
        out.append(f"export interface {e.name} extends EntityBase {{\n")
        for f in e.all_fields:
            opt = "" if f.required else "?"
            null = "" if f.required else " | null"
            out.append(f"  {f.name}{opt}: {_ts_type(f)}{null};\n")
        out.append("}\n\n")
    entities = [
        {
            "name": e.name,
            "table": e.table,
            "layer": e.layer,
            "mutability": e.mutability,
            "writers": e.writers,
            "description": e.description,
            "fields": [
                {
                    "name": f.name,
                    "type": f.type,
                    "required": f.required,
                    "immutable": f.immutable,
                    "vocabulary": f.vocabulary,
                    "ref": f.ref,
                    "description": f.description,
                }
                for f in e.all_fields
            ],
        }
        for e in manifest.entities
    ]
    out.append(f"export const ENTITIES = {json.dumps(entities, indent=2)} as const;\n")
    return "".join(out)
