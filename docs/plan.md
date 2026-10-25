# HAI Platform Build Plan

Written 2026-10-24 from `docs/spec/HAI-Platform-Claude-Code-Prompt.md` (the
prompt), `docs/spec/HAI_Ontology_v1_Specification.docx` (the spec) and a full
read of the Phase 6 code on `main`. Where the prompt and the spec disagree the
spec wins; section 3 lists every difference found.

## 1. Where Things Stand

### 1.1 Branch

Work happens on `feature/hai-platform`, created on 2026-10-24 from the
current `origin/main` (`2efc730`). `main` is never touched. The local branch
that previously carried that name (see 1.3) was renamed to
`feature/hai-platform-prior-attempt` and is left untouched for reference. The
remote has no `feature/hai-platform` yet; the new branch is pushed there at
the end.

### 1.2 Legacy Code

`main` holds the Phase 6 Express service: `server.js`, five routes and twelve
services (6,322 lines of services). All of it has been read. The porting
analysis is complete and written to `docs/porting-from-phase6.md` with file
and line references for every carried, corrected and dropped item: 8 groups of
carried constants and behaviours, 12 named corrections plus 15 further
corrections found during the read, and 16 items deliberately dropped.

The physical move to `legacy/express-api/` (prompt section 0, rule 2) is done
with `git mv` in the first Phase 0 commit.

### 1.3 A Prior Attempt Exists And Passes Its Checks

A local branch, now named `feature/hai-platform-prior-attempt`, holds one commit (`6ccfb62`, dated
2026-10-22) on top of the current `main`: 299 files, about 49,000 lines, laid
out exactly as the prompt's section 4 asks. It is not on the remote. I checked
it out into a scratch worktree and ran its checks here:

| Check | Result |
|---|---|
| `hai-ontology validate` | 30 entities, 35 vocabularies, 20 criteria, 16 rules, 0 errors, 0 warnings |
| `hai-ontology codegen --check` | 12 generated files up to date |
| `pytest` unit | 130 passed |
| `pytest -m integration` against a throwaway Postgres 16, roles off | 12 passed |
| same with `HAI_ENFORCE_DB_ROLES=true` | 12 passed |
| `ruff check` | clean |
| `mypy --strict` | clean, 99 files |
| frontend typecheck, lint | clean |
| frontend `vitest` | 67 passed |
| legacy move | done with renames; `git log --follow` reaches the Phase 6 history |

What it has: the manifest with IC-01 to IC-18 and acceptance tests, all five
generators, the versioning CLI, three migrations, hai-core (settings, db,
store, audit chain, queue, blob store), nine connectors, SimHash clustering,
admissibility, incidents, snapshot freeze, four LLM providers (OpenAI,
Anthropic, Ollama, heuristic), the validator, the 16-rule ruleset, scoring,
decide/finalize/replay, the API (assessments including create, reassess,
cancel, certification request, result, report, decisions, findings, trace,
connector runs; reviews; certification sign and public verify; organizations,
evidence ledger, uploads, monitoring, benchmarks; ontology; auth token;
webhooks; audit), the worker with the eight-job chain, a React console with
twelve pages, Docker, compose, Makefile, CI, release workflow, pre-commit,
five ADRs, architecture and ontology guides, glossary and JSON-LD.

Gaps against the prompt that I confirmed:

1. Its `docs/porting-from-phase6.md` has no file or line references
   (prompt section 2 requires them). Mine, written today, replaces it.
2. No `docs/plan.md`, no `CLAUDE.md`.
3. All 20 criterion files are `content_status: draft` (correct, since the
   legacy code has no level descriptors), but there are zero `TODO(humaital)`
   markers, and the draft list is not in a summary.
4. Several regression tests named in my porting notes do not exist yet
   (section 5.2 lists them).
5. Five ADRs; the prompt's section 14 asks for one per major design choice,
   including the beyond-v1 extension points. No crosswalk mapping file.
6. Frontend contract tests: review actions exist; the connector-list drift
   test needs confirming.
7. The CI grep for hand-typed criterion codes and status strings needs
   confirming.
8. `make check`, `make frontend-check` and the compose smoke test have not
   been run end to end here yet.

## 2. Decision: Rebuild From Scratch

Decided 2026-10-24: rebuild everything (ontology, backend, worker, frontend,
tooling) on `feature/hai-platform` without reusing code from the prior
attempt. The prior attempt stays on `feature/hai-platform-prior-attempt` as a
record only; it is not merged, cherry-picked or copied from. Its verified
check results in 1.3 are kept here as evidence that the prompt's targets are
reachable in this environment.

There is no WordPress rubric bundle available, so every criterion definition,
level descriptor and indicator label is a clearly marked draft (section 6).

Every "verify" step in the phases below is therefore a "build" step. The
eight phases, their done-when criteria and the regression test list are
unchanged.

## 3. Spec Versus Prompt Differences (Spec Wins)

| Topic | Prompt | Spec | Plan |
|---|---|---|---|
| D2 materiality | both score and confidence by default, switchable | confidence only in v1 so Purpose and Impact are not made secondary (section 13) | Default `confidence_only`; `both` available via `scoring.pillar_aggregation`. The prior attempt defaults to `both` and must be switched. Phase 6 parity is documented in the porting notes. |
| IC-12 enforcement | table grants plus `SET LOCAL ROLE` | row-level security | Grants and `SET LOCAL ROLE` are kept (they are what the tests prove); RLS policies are added on the three result tables so the spec's wording is also true. |
| IC-13 enforcement | "enforced in the database" | DB CHECK | A CHECK cannot look up another table, so a constraint trigger is used; the IC table in `docs/architecture.md` says so. |
| Connector run outcome | blocked, failed, rate limited | invoked, succeeded, blocked, failed, rate_limited (section 4.2) | All five values. |
| Stage and size bands | legacy values as aliases | placeholders early/growth/mature and small/mid/large/enterprise, to be imported from production (D3, section 7.10) | Spec placeholders are the values; legacy `startup`, `growth`, `enterprise`, `1-10`, `11-50`, `51-200`, `200+`, `1000+` are aliases. |
| Evidence snapshot | frozen judgment columns, incident states and version pins | immutable list of span and link IDs plus manifest hash | Superset: IDs, manifest hash, and the frozen columns. |
| Coverage states | as listed | also `not_tested` and `failed` with report wording | All seven states with wording. |
| Lifecycle | as listed | `completed_unverified` may return to `awaiting_review` when certification is requested | That transition is allowed. |
| Bitemporal fields | `valid_from`, `valid_to`, `recorded_at` | also `retrieved_at` on documents | Both kept. |
| Evidence link `reviewer_id` | not mentioned | optional field (section 4.2) | Present. |
| D10 name | "HAI Score" in reports, `hai` in code | "Human Alignment Index" without a hyphen | Both: the long form appears once in report headers, "HAI Score" elsewhere, `hai` in code. The legacy "Human-Alignment Index" hyphen (report-generator.js:18) is not carried. |
| D8 freshness default | methodology default | 24 months | 24 months. |
| D7 codes | `PIL-NN` with legacy aliases | keep production IDs if stable, else `PIL-NN` | `PIL-NN`; the legacy snake_case IDs were never stable across files, so they become aliases. |

## 4. Environment And What Can Be Verified Here

| Tool | Status |
|---|---|
| uv 0.9.30, Python managed by uv (system Python is 3.14; project pins 3.11+) | available |
| Node 24.6, npm | available |
| Docker daemon, Postgres 16 via container | available and used today |
| pandoc (spec docx to text) | available |
| GitHub Actions | cannot run here; workflow syntax is checked with `actionlint` if installable, otherwise by careful review |
| GHCR publish on tag | cannot be verified here |
| Live connectors (Wikidata, EDGAR, GLEIF, Google News, GitHub, Semantic Scholar, Wayback) | tests use the fake internet fixture; one manual smoke against a real site is optional and will be reported as such |
| Real LLM providers | tests use `httpx.MockTransport`; heuristic provider is the default |

## 5. Phases

Each phase ends with its checks green and one focused commit. A failing phase
is fixed before moving on.

### Phase 0: Skeleton, Legacy Move, Porting Notes, Register, Defaults

Done when: criterion register written; porting doc lists every carried and
corrected item; `TODO(humaital)` on every draft.

1. Fast-forward the branch to `6ccfb62` (or, on rebuild, `git mv` the Phase 6
   files into `legacy/express-api/` and create the workspace skeleton).
2. Replace `docs/porting-from-phase6.md` with today's version (line refs).
3. Add `docs/plan.md` (this file) and `CLAUDE.md`.
4. Criterion register: table of 20 rows (code, pillar, name, legacy id,
   weight, materiality, freshness) in `docs/ontology-guide.md`, generated from
   the criteria files so it cannot drift.
5. Mark every drafted field (`definition`, five descriptors, retrieval hints
   beyond the legacy keyword map) with `TODO(humaital)` and keep a
   `content_status: draft` list that the final summary prints.
6. D3, D7, D10 defaults recorded in `decisions.yaml` with `current` behaviour.
7. Checks: `make ontology-validate`, `make codegen-check`.

### Phase 1: Ontology Manifest, Meta-Model, Validator, Generators, CLI, Baseline

Done when: validation clean; codegen check passes; generated SQL applies to an
empty database.

1. Walk the spec tables one by one against `ontology.yaml`: 30 entities by
   layer (8, 7, 6, 9), every key field, every relation in section 5 with
   cardinality and time-bound flag, every vocabulary value in section 7,
   IC-01 to IC-18 with `enforced_in`, AT-01 to AT-15. Fix drift.
2. Apply the section 3 decisions (D2 default, connector run `invoked`,
   `not_tested` and `failed` wording, lifecycle transition, RLS policies).
3. Confirm the validator's stable error codes cover: unknown reference,
   relation without FK, duplicate code, pillar weights not summing to 1,
   non-monotonic ladder, unresolved `expression_ref`, vocabulary and entity
   name collision, invalid example record, hand-written derived vocabulary.
4. Confirm generators: SQL (enums, tables, FKs, CHECKs, append-only and
   immutable-column and transition triggers, grants, comments), Python
   (StrEnums, frozen Pydantic models with IC-07 validator, SQLAlchemy Core),
   TypeScript types and labels, strict LLM JSON Schema, labels, glossary,
   JSON-LD. Every file has the header and manifest hash; services refuse to
   start on hash mismatch.
5. Add the CI grep that fails on hand-typed criterion codes or status strings
   outside generated files, with an allowlist for the ontology YAML and tests
   that deliberately use literals.
6. `check-bump git:origin/main 1.0.0` must handle the base branch having no
   ontology (first release).
7. Checks: `make ontology-validate codegen-check`, `make db migrate` on a
   fresh container, `pytest packages/hai-ontology`.

### Phase 2: Core Services And Evidence Pipeline

Done when: every source traced to a connector run; spans verify against stored
text.

1. Settings: production refuses development secrets, secrets under 32
   characters and `HAI_AUTH_DISABLED`.
2. Database helper sets `hai.actor` and `SET LOCAL ROLE` under
   `HAI_ENFORCE_DB_ROLES`; integrity errors map to typed API errors.
3. Typed store refuses updates to append-only and immutable fields; audited
   writes for decision-bearing entities.
4. Audit chain verify; queue claim with `FOR UPDATE SKIP LOCKED`, leases,
   priorities, dedupe keys, backoff, dead state.
5. Migration runner refuses edited migrations (checksum ledger). `hai-db`
   has wait, migrate, status, seed, create-api-key, revoke-api-key,
   verify-audit.
6. Entity resolution with the correct Wikidata properties (P856, P5531,
   P1278, P452, P749), GLEIF, SEC tickers; identifiers verified only on a
   registrable-domain match.
7. Connectors from `config/connectors.yaml`: WEBSITE, DIRECT_URL, EDGAR, NEWS
   (real dates and publishers), GITHUB (verified handle only), ACADEMIC,
   WAYBACK (fetches the archived page), UPLOAD, ISO_42001. robots.txt,
   per-host pacing, budgets, retries. Every run recorded even when empty.
8. Content-addressed blob store (`file://`, fsspec), versioned HTML and PDF
   extraction, spans with exact offsets, SimHash clustering calibrated on
   article-length fixtures, link proposals from retrieval hints and lexicons,
   admissibility in fixed order, independence from relations, incidents with
   canonical keys and conservative status, snapshot freeze.
9. Regression tests from the porting notes (section 5.2 below).
10. Checks: `make test-unit`, `make test-integration`.

### Phase 3: LLM Evaluation

Done when: findings pass all validators; heuristic provider works offline.

1. Per-span classification from quote and publisher only: maturity rung,
   execution level, evidence class.
2. Evidence packs per criterion with ranking, size limit and omission count.
3. Providers on httpx: OpenAI-compatible strict schema, Anthropic forced
   tool call, Ollama, heuristic. `provider:model` pinned on assessment and
   finding. Optional second opinion lowers confidence or triggers review.
4. Prompts versioned; evidence as JSON in the user message (IC-17).
5. Validator: IC-05, IC-04, IC-03, IC-06; retry once, fall back to heuristic,
   record in trace; rejected findings stored and never used.
6. Checks: `pytest packages/hai-engine` provider and validator suites with
   `httpx.MockTransport`.

### Phase 4: Rules And Scoring

Done when: the same snapshot and versions give the same result (replay test).

1. Ruleset 1.0.0 as data with registered pure functions; startup fails on an
   unresolved or mismatched `expression_ref`; every decision records each
   rule with before and after state and a note (IC-14).
2. Criterion scope: GATE-APPLICABILITY, GATE-COVERAGE, ADJ-START-FROM-FINDING,
   CAP-NO-ADMISSIBLE-SUPPORT, CAP-MATURITY, CAP-FAILED-EXECUTION,
   GATE-UNVERIFIED-INCIDENTS, ADJ-INCIDENTS, CONF-EVIDENCE (with freshness
   decay applied and clusters counted once), CONF-CONTRADICTION,
   CONF-INCIDENT-CEILING. Assessment scope: CAP-SCORE-CEILING,
   CAP-SCORE-LOW-CONFIDENCE, GATE-REVIEW-TRIGGERS, GATE-CERTIFICATION,
   GATE-OUTCOME-STATUS.
3. Applicability expression language on `ast` allowing only comparisons,
   boolean operators, names and literals.
4. Scoring with D2 default `confidence_only`; excluded states do not count;
   all level 5 is 100; unavailable excluded not zeroed.
5. `decide`, `finalize`, read-only `replay` equal to the stored result.
6. Certification: reviewer JWT only (IC-13), HMAC signature, public verify,
   expiry, revocation supersedes.
7. Checks: every rule has a unit test; replay test; `pytest packages/hai-engine`.

### Phase 5: API, Worker, Review, Certification, Reporting, Webhooks

Done when: only a reviewer can certify; end-to-end test passes.

1. Confirm every route in prompt section 8 exists with consistent shapes,
   the error envelope, request IDs, CORS that denies unknown origins,
   `Idempotency-Key` on create with 202, pagination with totals.
2. Reviews always carry a reason; escalation keeps the task open for a
   different reviewer; four-eyes rule.
3. Worker chain and dead-job handling; webhooks HMAC-signed for the four
   events; monitoring tick.
4. Report resource with coverage wording per state and execution notes;
   IC-16 collected-sources rule.
5. End-to-end test on the fake internet: idempotent start, full chain, spans
   match, every run recorded, injection never admissible, one incident from
   two articles, review tasks, replay equals stored, escalation, API key
   refused for signing, reviewer signs, finalize, audit verifies; blocked
   website run reports unavailable.
6. Checks: `make test`, both role modes.

### Phase 6: Frontend

Done when: typecheck, lint, tests and build pass.

1. Confirm pages: dashboard, new assessment with server errors mapped to
   fields, assessment detail (score dial, pillar bars, coverage strip, outcome
   exactly as stored, criteria, sources and runs, reviews), trace drawer to
   the quote, review queue with per-subject actions and mandatory reason,
   certificate signing, public verify, ontology browser, organizations and
   benchmarks, settings.
2. Humaital look (`#D41920`), light and dark, phone width, accessibility pass
   with axe in tests.
3. Contract tests for review actions and connector list drift.
4. Dockerfile: Node build, unprivileged nginx on 8080, `API_UPSTREAM`.
5. Checks: `make frontend-check`, `docker build frontend`.

### Phase 7: Docker, Makefile, CI, Docs

Done when: `make check` and `make frontend-check` pass; AT-01 to AT-15 each
mapped to a passing test.

1. Multi-stage `docker/python.Dockerfile` with uv, non-root, targets api,
   worker, tools; ontology, config and migrations copied in.
2. Compose: postgres, migrate (wait, migrate, seed, validate), api, worker,
   frontend, optional ollama profile; `.env.example` documents every setting.
3. Makefile: every target in prompt section 10 present and working.
4. CI: lint and mypy; ontology gate with migration plan artifact; tests twice
   (roles off and enforced) with coverage and JUnit; frontend; Docker builds;
   compose smoke on `/health`, `/ready`, `/v1/ontology`. Release workflow
   labels images with ontology and methodology versions.
5. Pre-commit with ruff, hygiene hooks, local ontology hooks.
6. Docs: README, architecture with the IC enforcement table (where enforced,
   which test), ontology guide with the register, porting notes, CHANGELOG,
   CLAUDE.md, ADRs for each section 14 extension point, crosswalk mapping
   file (EU AI Act, NIST AI RMF, ISO 42001) as a draft with `TODO(humaital)`.
7. Final: regenerate, rebuild a fresh database, run the whole suite, run the
   compose smoke test locally, fetch `origin/main`, confirm the base, push
   `new-hai-platform-10242026` (bundle fallback).

### 5.2 Regression Tests To Add Or Confirm

From `docs/porting-from-phase6.md`. Tests already present in the prior
attempt are marked present; the rest are new.

| Test | Status |
|---|---|
| test_term_regex_is_whole_word | present |
| test_execution_patterns | present |
| test_execution_is_per_span | new |
| test_polarity_is_immutable (trigger, IC-01) | new (append-only is covered; polarity update needs its own) |
| test_freshness_decay_and_certificates, test_undated_evidence_is_never_stale | present |
| test_decay_is_applied_in_confidence | new |
| test_news_items_carry_real_dates_and_publishers | new |
| test_simhash_finds_syndicated_copies | present |
| test_registrable_domain | present |
| test_identifiers_verified_only_on_domain_match | new |
| test_wikidata_properties_are_the_right_ones | new |
| test_github_requires_a_verified_handle | new |
| test_metadata_is_not_evidence | present |
| test_wayback_fetches_the_archived_page | new |
| test_spans_have_exact_offsets | present |
| test_evidence_pack_is_per_criterion_and_counts_omissions | new |
| test_direct_urls_are_fetched_and_recorded | new |
| test_unavailable_only_when_a_connector_failed, test_unavailable_criteria_are_excluded_not_zeroed, test_blocked_sources_are_unavailable_not_missing | present |
| test_append_only_tables_refuse_updates, test_public_endpoints_and_auth | present |
| test_result_tables_are_writable_only_by_engine_role | new (roles-enforced mode) |
| test_bad_findings_are_rejected, test_level_is_capped_by_the_evidence_ladder, test_a_good_finding_passes | present |
| test_every_connector_runs_and_is_recorded | new |
| test_incident_adjusts_only_its_target_criterion, test_event_keys_bucket_by_month, test_alleged_incident_has_no_automatic_effect, test_incidents_start_conservative | present |
| test_independence_comes_from_the_publisher_not_the_tier, test_owner_and_threshold_is_a_specified_control | present |
| test_a_source_cluster_counts_once, test_independent_corroboration_raises_confidence | present |
| test_cors_denies_unknown_origins | new |
| test_api_keys_are_hashed | new |
| test_injection_is_detected | present |
| test_injection_never_reaches_the_model | new |
| test_academic_requires_entity_match | new |
| test_replay_matches_stored_result | present as part of the lifecycle test; split out |
| test_no_hand_typed_codes_outside_generated_files | new |

## 6. Drafted Methodology Content (Needs Humaital)

Listed here so the final summary can repeat it. Everything below is marked
`content_status: draft` and `TODO(humaital)` in the manifest.

* All 20 criterion `definition` fields.
* All 100 level descriptors (five per criterion). The legacy code has only
  the five generic level meanings in `openai.js:149-154`.
* Rubric indicator labels for the R, S, G and O items (IDs are known from
  `openai.js:52-134`; labels are in the WordPress bundle, not in this repo).
* Retrieval hints beyond the legacy keyword map
  (`supplementary-evidence.js:111-132`).
* Source tier weights for T2 versus T3 (legacy had one "medium" weight).
* Evidence class definitions (spec 7.8 says "definitions to confirm").
* Freshness window per criterion (default 24 months applied everywhere).
* Partial-evaluation confidence ceiling of 69 (referenced but not defined in
  the legacy backend).
* Certification stage and size table (D3; the universal 70 is the default).
* Crosswalk mappings to EU AI Act, NIST AI RMF, ISO 42001.
* D1 to D10 themselves remain open; the manifest records the current
  behaviour for each.

## 7. Decisions Taken With You

1. Approach: rebuild from scratch (section 2). Decided 2026-10-24.
2. D2 default follows the spec: confidence-only, with `both` switchable.
3. No WordPress bundle exists, so the drafts in section 6 stand until
   Humaital supplies content.
4. The branch is `feature/hai-platform`, pushed to the remote under that
   name at the end; the bundle fallback applies if the push is refused.

## 8. Task List

- [ ] P0 legacy move, skeleton, porting notes, plan, CLAUDE.md, register,
      drafts marked, D3/D7/D10 recorded, commit
- [ ] P1 manifest audit against spec tables, D2 default, RLS, validator
      codes, generators, hand-typed-code grep, check-bump first release,
      fresh DB apply, commit
- [ ] P2 settings, db roles, store, audit, queue, migrations, hai-db,
      entity resolution, connectors, blob store, extraction, spans,
      clustering, proposals, admissibility, independence, incidents,
      snapshot, new regression tests, commit
- [ ] P3 classification, packs, providers, prompts, validator, fallback,
      commit
- [ ] P4 ruleset, expression language, scoring, decide/finalize/replay,
      certification, per-rule tests, commit
- [ ] P5 routes, reviews, worker, webhooks, report, end-to-end, both role
      modes, commit
- [ ] P6 frontend pages, look, a11y, contract tests, Dockerfile, commit
- [ ] P7 Docker, compose, Makefile, CI, release, pre-commit, docs, ADRs,
      crosswalk, final regenerate and full run, push, summary
