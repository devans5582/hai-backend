# ADR 0001: Ontology Manifest As The Single Source Of Truth

Status: accepted (2026-10-24)

## Context

The Phase 6 service kept criterion ids, labels, weights and status strings in
at least four places (the Node scoring code, the OpenAI prompt, the report
generator and the WordPress plugin) and they drifted. The spec requires one
manifest everywhere (AT-12).

## Decision

The YAML under `ontology/` is the only hand-edited definition of entities,
fields, relations, vocabularies, pillars, criteria, rules and integrity
constraints. Everything else is generated from it with a header that carries
the manifest SHA-256: the baseline SQL, Python enums and Pydantic models, the
TypeScript module, the JSON Schemas for LLM output, the glossary, the JSON-LD
export. Services refuse to start when the generated code hash does not match
the manifest (`hai_core.manifest.verify_generated_code`). `hai-ontology codegen
--check` fails CI on drift. A guard test (`tests/test_codes_not_hand_typed.py`)
fails when a criterion code or distinctive status string is typed outside the
manifest, generated files and tests.

## Consequences

Changing a vocabulary value is a manifest edit plus `make codegen`; the
compiler and the type checker then find every consumer. Versioning is semver on
the manifest with a diff tool that classifies changes and a check that refuses
a version that moved too little. The cost is a generation step in the workflow
and a strict meta-model that rejects unknown keys.
