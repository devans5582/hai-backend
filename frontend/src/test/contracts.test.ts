// Contract tests: the console's connector list and review actions must match the backend files.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { REVIEW_ACTIONS_BY_SUBJECT, REVIEW_SUBJECT_TYPE_VALUES, CRITERIA, PILLARS, MANIFEST_HASH } from "../generated/ontology";
import { CONNECTOR_CODES } from "../lib/connectors";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

function yamlFile(rel: string): unknown {
  return parse(readFileSync(resolve(ROOT, rel), "utf-8"));
}

describe("backend contracts", () => {
  it("connector list matches config/connectors.yaml", () => {
    const config = yamlFile("config/connectors.yaml") as { connectors: { code: string }[] };
    const backend = config.connectors.map((c) => c.code).sort();
    expect([...CONNECTOR_CODES].sort()).toEqual(backend);
  });

  it("allowed review actions match ontology/vocabularies/review_subject_type.yaml", () => {
    const voc = yamlFile("ontology/vocabularies/review_subject_type.yaml") as { vocabulary: { values: { code: string; attributes: { allowed_actions: string[] } }[] } };
    const backend: Record<string, string[]> = {};
    for (const v of voc.vocabulary.values) backend[v.code] = [...v.attributes.allowed_actions].sort();
    const frontend: Record<string, string[]> = {};
    for (const subject of REVIEW_SUBJECT_TYPE_VALUES) frontend[subject] = [...(REVIEW_ACTIONS_BY_SUBJECT[subject] ?? [])].sort();
    expect(frontend).toEqual(backend);
  });

  it("criteria and pillars match the methodology files", () => {
    const pillars = yamlFile("ontology/methodology/pillars.yaml") as { pillars: { code: string; weight: number }[] };
    expect(PILLARS.map((p) => [p.code, p.weight])).toEqual(pillars.pillars.map((p) => [p.code, p.weight]));
    expect(CRITERIA).toHaveLength(20);
    expect(MANIFEST_HASH).toMatch(/^[0-9a-f]{64}$/);
  });
});
