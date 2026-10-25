# ADR 0009: Extension Point: Framework Crosswalks

Status: accepted (2026-10-24)

## Context

Customers map AI governance work to the EU AI Act, NIST AI RMF and ISO/IEC
42001.

## Decision

`ontology/methodology/crosswalks.yaml` maps each criterion to clauses with a
direction (covers, supports, informs). The file is a draft marked
`content_status: draft` with `TODO(humaital)`; a test checks that every mapping
names a real criterion and framework. Crosswalks are not inputs to scoring. The
report generator may render them as a "related frameworks" section once the
file is approved.

## Consequences

Humaital can edit the mapping without a code change. Making the mapping part of
the manifest hash is a later decision once the content is approved.
