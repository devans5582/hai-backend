# Claude Code Prompt: Build The HAI Platform Monorepo

Copy everything below the line into Claude Code, run from a clone of
`https://github.com/devans5582/hai-backend`. Before you start, put the
specification file in the repo at `docs/spec/HAI_Ontology_v1_Specification.docx`
(and the deck export at `docs/spec/HAI_Ontology_and_Development_Plan.pdf` if
you have it), so Claude Code can read them.

---

You are building the Humaital HAI Score platform (Human Alignment Index) as a
production-quality monorepo. I am Charles Adetiloye, the developer on this
project. Work carefully, autonomously and in phases. Read this whole prompt
before doing anything.

## 0. Ground Rules

1. **Never touch `main`.** Run `git fetch origin`, then create and work on a new
   branch from the latest `origin/main`: `git switch -c feature/hai-platform origin/main`.
   If that branch already exists locally or on the remote, inspect it first and
   continue on it rather than recreating it. Never force-push, never rebase or
   rewrite `main`, never commit to `main`.
2. **Keep the existing code.** `main` holds the Phase 6 Node/Express service.
   Move it with `git mv` into `legacy/express-api/` so history is preserved, and
   treat it as read-only reference. Do not delete it.
3. **Plan first, then build.** Start by producing a written plan (section 12)
   and a task list. Then build phase by phase. After each phase: run the
   phase's checks, fix failures, and make one focused commit with a clear
   message. Do not move on with a failing phase.
4. **Do not invent methodology content.** The 20 criteria, their level
   descriptors and Humaital's weights are Humaital's intellectual property. Where
   the spec or the legacy code gives the content, import it exactly. Where it
   does not, write clearly marked drafts (`content_status: draft`) with
   `TODO(humaital)` notes, and list every draft in the final summary. Never
   invent statistics, thresholds or quotes presented as real.
5. **Verify, do not assume.** Run every command you claim works. If something
   cannot be run in this environment (for example no Docker daemon), say so
   explicitly in the final summary instead of implying it was tested.
6. **Writing style for docs.** Plain ASCII prose. No em dashes, no curly quotes,
   no other non-ASCII typographic characters. Title Case headings. Write like an
   engineer explaining to another engineer, not like marketing copy.
7. **Push at the end** with `git push -u origin feature/hai-platform`. If the push
   is refused, create `git bundle create hai-platform.bundle origin/main..feature/hai-platform`
   and tell me where it is.

## 1. What The System Does

Turn public and submitted evidence about an organization into an HAI Score that
anyone can trace, reproduce and defend. Five steps:

1. **Find sources.** Connectors fetch filings, registries, company disclosures,
   news and research.
2. **Extract evidence.** Quote the exact passage that matters, pinned by
   character offsets in a frozen, hashed copy of the document.
3. **Judge each criterion.** An LLM proposes a level per criterion with
   citations. A deterministic rules engine decides.
4. **Compute the score.** 20 criteria roll up into six pillars and the HAI Score,
   with separate confidence and effectiveness outputs.
5. **Certify.** Only a named human reviewer can sign a certification.

Core principle: **LLM proposes, rules decide, a reviewer signs.**

## 2. Learn From The Existing Implementation First

Before writing new code, read every file on `main` (after the move, under
`legacy/express-api/`): `server.js`, `src/routes/*` (evaluate, benchmark,
health, log-patch, send-report) and `src/services/*` (scraper, entity-resolver,
evidence-weighting, negative-signal-overrides, time-decay, proof-of-execution,
supplementary-evidence, report-generator, openai, mailer, db, analysis-logger).

Write `docs/porting-from-phase6.md` with three sections, backed by file and line
references:

* **Carried over:** every constant and behaviour worth keeping. At minimum:
  pillar max points 20/15/15/15/15/20 (TRU, ACC, PUR, SAF, TRN, IMP, as weights
  0.20/0.15/0.15/0.15/0.15/0.20), criterion materiality weights, source tier
  weights, time-decay curves (FIX-10), negative-signal override rules (FIX-9)
  mapped to a four-level incident severity, proof-of-execution patterns
  (FIX-12), the score cap of 85, the low-confidence caps, the certification
  threshold of 70, stage and size input values (keep them as aliases), the
  Phase 6 criterion IDs (keep them as aliases of the new codes), the rubric
  indicators, and the allowed CORS origins.
* **Corrected:** every defect you find. Look specifically for: substring term
  matching (for example "sued" matching "pursued"); proof-of-execution taken as
  a maximum over a whole website instead of per quote; time decay computed but
  never applied; news items all dated "today"; wrong Wikidata property used for
  SEC CIK and first-hit EDGAR matching; GitHub org guessed from a name slug;
  Wayback snapshot existence treated as support for every criterion; text
  truncated to a fixed character count and one slice sent for all criteria;
  crashes on direct URLs; blocked sources scored as missing evidence; scores
  computed in the browser and patched into logs; the model's output setting the
  score directly. Confirm each one in the code before listing it.
* **Not carried over:** anything deliberately dropped (for example a tier-based
  score uplift with no evidentiary basis, mail sending from the API process,
  log patching), with the reason.

Every correction must have a regression test in the new code.

## 3. Target Stack And Conventions

Follow the conventions I use on my other projects:

* **Python 3.11+** for all backend code, managed as a **uv workspace**
  (`pyproject.toml` at the root, one `pyproject.toml` per package, hatchling
  builds, committed `uv.lock`).
* **FastAPI** for the API, **Pydantic v2** models, **SQLAlchemy Core** (2.x) with
  **psycopg 3**, **PostgreSQL 16** as the system of record.
* **React + TypeScript + Vite** for the frontend, React Router, TanStack Query,
  Vitest and Testing Library, ESLint. Exact dependency versions in `package.json`.
* **YAML** for every piece of metadata (ontology, methodology, connectors).
* **SHA-256 checksums** for documents, migrations, the manifest and the audit chain.
* **Auth:** API keys (`X-API-Key`, stored only as an HMAC with a server pepper,
  shown once) for partners and services; HS256 **JWTs** for named reviewers and
  admins; per-route scopes.
* **Docker** and **docker compose** for local and CI, a **Makefile** as the single
  entry point for every task, **GitHub Actions** for CI and releases,
  **pre-commit** hooks.
* **Quality bar:** `ruff` (lint and format), `mypy --strict` on every package,
  `pytest` with unit and Postgres-backed integration tests, structured JSON
  logging, typed settings from environment variables with an `HAI_` prefix.

## 4. Repository Layout

```
ontology/                       the manifest (source of truth, hand-edited)
  ontology.yaml                 header, layers, entities, fields, relations, IC-xx, AT-xx
  vocabularies/*.yaml           one closed vocabulary per file
  methodology/
    methodology.yaml            scoring, confidence, certification, outcome, freshness, review triggers, lexicons
    pillars.yaml
    criteria/<CODE>.yaml        one file per criterion
    rules.yaml                  the ruleset
    decisions.yaml              open decisions D1 to D10 and current behaviour
  examples/                     valid/ and invalid/ sample records, checked in CI
  CHANGELOG.md
packages/
  hai-ontology/                 meta-model, loader, validator, versioning, code generators, CLI
  hai-core/                     settings, db, typed store, audit chain, job queue, blob store, freshness
  hai-pipeline/                 connectors, entity resolution, text and spans, clustering, linking, admissibility, incidents, snapshot
  hai-engine/                   classification, evidence packs, LLM providers, validator, rules, scoring, decisions, certification, reports
services/
  api/                          FastAPI service, script hai-api
  worker/                       background worker, script hai-worker
frontend/                       React console
db/migrations/                  numbered SQL; 0001 generated from the manifest
config/connectors.yaml          evidence sources, limits, rate settings
docker/                         Dockerfiles
docs/                           architecture, ontology guide, porting notes, ADRs, generated glossary and JSON-LD
tests/                          cross-package integration and end-to-end tests, fixtures (a fake internet)
legacy/express-api/             Phase 6 code, reference only
```

Dependencies point one way: `hai-ontology` depends on nothing internal;
`hai-core` on it; `hai-pipeline` and `hai-engine` on both; the services on
everything below them.

## 5. The Ontology (Read The Spec Docx First)

Read `docs/spec/HAI_Ontology_v1_Specification.docx` in full and model it
exactly. Where this prompt and the spec disagree, the spec wins; note the
difference in the plan.

### 5.1 Eight Principles The Schema Enforces

1. One meaning per field: support, usability, maturity, independence and source
   authority are separate columns.
2. Facts are append-only: corrections add a row (`supersedes_id`); nothing is
   overwritten.
3. Scope is explicit: evidence names one target and one criterion.
4. Absence is a state: missing never quietly becomes a zero.
5. Time has two clocks: when it was true (`valid_from`/`valid_to`) and when
   Humaital learned it (`recorded_at`).
6. Proposals are not decisions.
7. Everything is versioned: each assessment pins five versions (ontology,
   methodology, ruleset, prompt, model), none blank.
8. Define once, use everywhere: one manifest feeds the code, the LLM and reports.

Each principle must be enforced by a database constraint, trigger or
validator, not only by convention.

### 5.2 Four Layers, 30 Entities

* **Subject (8):** Organization, OrganizationRelation, AISystem (optional in v1),
  Claim, Control, TestOutcome, Incident, Remediation. Canonical chain:
  Organization operates AISystem, protected by Control, evaluated by
  TestOutcome. Organizations assert Claims (a claim is never proof of itself).
  Incidents affect AI systems and controls; remediations fix incidents. One
  incident row per real event regardless of article count. External IDs are
  stored only when verified.
* **Evidence (7):** Publisher, Connector, ConnectorRun, SourceDocument,
  SourceCluster, EvidenceSpan, EvidenceLink. Connector run proves a fetch
  happened, and whether it was blocked, failed or rate limited. Source documents
  are frozen copies with hash, dates and rights; a re-fetch with a different
  hash is a new row. Spans hold the exact quote with character offsets. Clusters
  make syndicated copies count once.
* **Methodology (6):** MethodologyVersion, Pillar, Criterion, LevelDescriptor,
  CriterionApplicability, Rule.
* **Assessment (9):** Assessment, EvidenceSnapshot, CriterionFinding,
  CriterionDecision, PillarScore, AssessmentResult, CertificationDecision,
  Review, AuditEvent.

**The evidence link is the only bridge.** Nothing reaches a score except
through a link naming one span, one target and one criterion. Each link carries
six separate judgments, each written by exactly one step:

| Dimension | Question | Set by | Can change |
|---|---|---|---|
| Polarity | Support, contradict or neutral? | LLM or heuristic proposer, then validator | Never (trigger) |
| Admissibility | Usable in scoring at all? | Admissibility check | Only via review |
| Maturity rung | How far up the ladder does it prove? | Rules engine | Only with a new ruleset |
| Independence | Who stands behind it? | Publisher and org relations | Recomputed |
| Source tier | How authoritative could it be? | Publisher type lookup | Per version |
| Target and criterion | Exactly what, which criterion? | Ontology resolver | Never |

Maturity ladder (default; per-criterion override is decision D1): none,
stated_commitment, specified_control (named owner plus measurable threshold),
documented_execution (dated results), independently_verified (independent party
or regulator only, IC-07). Source tier never sets maturity, and a title, label
or date alone never lifts maturity above none.

Coverage states, each with its own report wording: observed, missing (searched,
nothing found), unavailable (source blocked or down; only allowed when a
connector run actually failed, IC-15), not_applicable (explicit rule),
not_tested (control exists, no execution evidence), failed, contradictory
(always routed to review). Unavailable and not-applicable criteria are excluded
from the score, not zeroed.

Assessment lifecycle (database-enforced transitions): queued, acquiring,
evaluating, awaiting_review, completed_unverified, completed, failed, cancelled.
Outcome status is a separate field set only by the rules engine, first match
wins: access_limited, insufficient_evidence, governance_baseline,
confidence_too_low, certification_not_yet_achieved, hai_certified. HAI
certified requires a signed certification decision, enforced in the database.

Implement every integrity constraint IC-01 to IC-18 and map every acceptance
test AT-01 to AT-15 to at least one automated test. Keep a table in
`docs/architecture.md` saying where each IC is enforced (DDL check, trigger,
Pydantic validator, rules engine, API) and which test proves it.

### 5.3 Manifest Mechanics

* A strict Pydantic meta-model (`extra="forbid"`) describes the manifest itself:
  entities, fields (types, enums, refs, arrays, defaults, immutability),
  mutability (mutable, append_only, immutable), writer roles, relations
  catalogue, vocabularies (values, labels, descriptions, aliases, ordered
  ranks, typed attributes, allowed transitions), ICs and ATs, and the full
  methodology.
* Derived vocabularies (`criterion_code`, `pillar_code`) are generated from the
  methodology files and must not be hand-written.
* The loader computes a SHA-256 over the canonical manifest content.
* A validator with stable error codes checks references, relations for every
  FK, duplicate codes, pillar weights summing to 1, monotonic level ladders,
  that every rule's `expression_ref` resolves to a registered implementation,
  name collisions between vocabularies and entities, and example records.
* Criterion codes like `SAF-02` are permanent; retired codes are never reused.

### 5.4 Code Generation (One Change, Many Outputs, Checked By CI)

A Python generator in `hai-ontology` writes, deterministically:

1. SQL baseline: schema, one Postgres enum per vocabulary, tables, FKs from the
   relations catalogue, CHECK constraints for declarative ICs, triggers for
   append-only tables, immutable columns and legal state transitions, writer
   role grants, table and column comments.
2. Python: StrEnums, Pydantic entity models (frozen where the entity is
   immutable, with IC validators such as IC-07), SQLAlchemy Core tables.
3. TypeScript types and label maps for the frontend.
4. JSON Schemas for LLM outputs (strict-mode compatible: all properties
   required, `additionalProperties: false`, enums from vocabularies).
5. A label dictionary, a Markdown glossary and a JSON-LD (RDFS plus SKOS) export.

Every generated file carries a "generated, do not edit" header and the manifest
hash. Services refuse to start if their generated code does not match the
manifest they ship with. `hai-ontology codegen --check` fails CI on drift.
Add a check that no criterion code or status string is hand-typed outside
generated files.

### 5.5 Versioning And Growth

* Ontology and methodology each have a semver version. A diff tool classifies
  every change: patch (labels, wording), minor (new value, optional field,
  entity, criterion), major (removal, rename, type change, new required field,
  weight or ladder change).
* `check-bump OLD NEW` fails when the version did not move far enough;
  OLD can be `git:<ref>` so CI compares against the base branch. Handle a ref
  that has no ontology yet (first release) gracefully.
* `migrate-plan OLD NEW` emits SQL for additive changes (for example
  `ALTER TYPE ... ADD VALUE ... AFTER ...`, `ADD COLUMN`) and refuses breaking
  changes unless `--allow-breaking`, which emits a skeleton with TODOs.
* Change process: written change record, valid and invalid examples,
  regenerate, Humaital sign-off, release. Rescoring under a new methodology
  creates a new assessment; history is never edited.
* CLI `hai-ontology`: validate, codegen [--check], diff, check-bump,
  migrate-plan, baseline, show, export, bump.

## 6. Evidence Pipeline (`hai-pipeline`)

* **Entity resolution** before collection: Wikidata (website P856, SEC CIK
  P5531, LEI P1278, industry P452, parent P749), GLEIF, SEC company tickers.
  Mark identifiers verified only when the official website matches the
  submitted domain.
* **Connectors** configured in `config/connectors.yaml` (a new source is a data
  row, not an ontology change): WEBSITE, DIRECT_URL, EDGAR, NEWS (Google News
  RSS, real dates and publishers), GITHUB, ACADEMIC (Semantic Scholar), WAYBACK
  (fetch the archived page itself), UPLOAD (evidence portal; uploads enter as
  claims), ISO_42001 certificate registry. Async httpx, robots.txt, per-host
  pacing, a time and page budget, retries with backoff. Every run is recorded
  with its outcome, even when empty (IC-16).
* **Documents** are content-addressed: raw bytes and extracted text stored in a
  blob store under their SHA-256 (`file://` locally, fsspec for S3 or GCS). Keep
  the store cloud agnostic.
* **Text extraction** from HTML (drop chrome, keep paragraph structure,
  canonical URL, published date, headings) and PDF, with a versioned extractor.
* **Spans** with exact offsets so `stored_text[start:end] == quote` always holds
  (IC-03), asserted dates, section headings.
* **Clustering** of near-duplicates with 64-bit SimHash so ten copies of one
  story count once (IC-09). Calibrate the threshold with tests on realistic
  article lengths.
* **Link proposals** driven by the methodology's retrieval hints and lexicons
  (tuning relevance is a methodology change, not a code change); an optional
  LLM proposer may only reference spans it was shown.
* **Admissibility**, fixed order, first failure wins: untrusted (prompt
  injection text), unverifiable (quote mismatch or no successful connector run),
  irrelevant, stale (outside the criterion's freshness window; undated evidence
  is never called stale, it is decayed instead).
* **Independence** from publisher and organization relations (self, affiliate,
  commissioned, independent, regulator), never from tier.
* **Incidents:** canonical event keys, conservative initial status (only an
  authoritative source can substantiate automatically), statuses alleged,
  under_investigation, substantiated, remediating, closed_verified, dismissed.
* **Snapshot freeze:** before evaluation, copy every link's judgment columns,
  every targeted incident's status and severity, and the version pins into an
  EvidenceSnapshot. The rules engine reads only the snapshot (AT-07).

## 7. Evaluation And Decisions (`hai-engine`)

* **Link classification** from the quote and publisher only: maturity rung,
  execution level (per-span proof of execution), evidence class (foundational,
  core governance, operational, external validation).
* **Evidence packs** per criterion, built only from that criterion's links,
  ranked, size-limited, with omissions counted and fed into uncertainty (AT-09).
* **LLM providers** behind one protocol, implemented directly on httpx (no
  vendor SDKs): OpenAI-compatible with strict JSON Schema output (works with
  vLLM, Azure OpenAI, LM Studio via base URL), Anthropic with a forced tool call,
  Ollama for local small models, and a deterministic **heuristic** provider that
  needs no model (default for dev and CI, and the fallback). Pin
  `provider:model` on every assessment and finding. Optional second-opinion
  provider: large disagreement lowers confidence or triggers review.
* **Prompts:** static system instruction; evidence passed as JSON data in the
  user message, never concatenated into the system prompt (IC-17). Prompts are
  versioned files.
* **Validator** between model and storage: schema check (IC-05), citations in
  the snapshot and in this criterion's pack with the right polarity and
  admissibility (IC-04), quote matches stored text at offsets (IC-03), no
  credit above stated commitment without real quoted text (IC-06). Retry once,
  then fall back to the heuristic provider and record that in the trace. A
  rejected finding is stored for audit and never used.
* **Rules engine:** rules are data in `rules.yaml` (code, kind cap / gate /
  confidence / adjustment, scope criterion or assessment, order, parameters,
  `expression_ref`). Implementations are pure Python functions registered with
  decorators like `@criterion_rule("CAP-MATURITY")`; no database, no LLM, no
  clock. Startup fails if a reference does not resolve to a function registered
  under the same code. Every decision records each rule that ran with state
  before and after and a one-line note (IC-14).
* Suggested ruleset 1.0.0 (adjust to the spec): GATE-APPLICABILITY,
  GATE-COVERAGE, ADJ-START-FROM-FINDING, CAP-NO-ADMISSIBLE-SUPPORT, CAP-MATURITY,
  CAP-FAILED-EXECUTION, GATE-UNVERIFIED-INCIDENTS (alleged incidents go to
  review with no automatic effect, IC-11), ADJ-INCIDENTS (one adjustment per
  incident per assessment on its most material criterion, IC-10),
  CONF-EVIDENCE (tier x class x rung credit x materiality x freshness decay,
  clusters counted once, corroboration bonus, execution bonus),
  CONF-CONTRADICTION, CONF-INCIDENT-CEILING, then assessment scope
  CAP-SCORE-CEILING, CAP-SCORE-LOW-CONFIDENCE, GATE-REVIEW-TRIGGERS,
  GATE-CERTIFICATION, GATE-OUTCOME-STATUS.
* **Applicability** conditions are a tiny safe expression language parsed with
  `ast` that allows only comparisons, boolean operators, names and literals.
* **Scoring:** criterion ratio `(level - 1) / 4`, materiality-weighted pillar
  means, weighted HAI Score across pillars, separate confidence and
  effectiveness. Excluded states do not count.
* **Decision service** with `decide`, `finalize` (after reviews), and a
  read-only `replay` that recomputes from the frozen snapshot and must match
  the stored result.
* **Certification:** only a named reviewer (JWT, never an API key, IC-13); HMAC
  signature over assessment, result and reviewer; public verification; expiry;
  revocation supersedes.
* **Reports:** a full report resource with criteria, evidence, sources, coverage
  wording and execution notes. The browser never computes a score or status.

## 8. Platform Services (`hai-core`, services)

* Settings with `HAI_` prefix; production refuses development secrets or secrets
  shorter than 32 characters, and refuses `HAI_AUTH_DISABLED`.
* Database helper: transactions set the acting principal (`hai.actor`) and,
  when `HAI_ENFORCE_DB_ROLES=true`, `SET LOCAL ROLE` to the component's role so
  table grants enforce writer separation (IC-12). Integrity errors map to typed
  API errors.
* Typed store over the generated models: get, find, insert (audited for
  decision-bearing entities), update (audited; refuses append-only and
  immutable fields), upsert.
* Hash-chained, append-only audit log with a verify routine (AT-15).
* Postgres job queue: `FOR UPDATE SKIP LOCKED`, leases, priorities, dedupe keys,
  exponential backoff, dead state. Worker job chain: acquire_evidence,
  classify_links, freeze_snapshot, evaluate_criteria, decide, finalize, plus
  deliver_webhook and monitoring_tick. A dead pipeline job fails the
  assessment with a reason.
* Migration runner with a checksum ledger that refuses edited migrations. CLI
  `hai-db`: wait, migrate, status, seed (methodology and connector rows from
  YAML), create-api-key, revoke-api-key, verify-audit.
* **API** (FastAPI, OpenAPI generated from the same models, error envelope
  `{"error": {code, message, details}}`, request IDs, CORS):
  * `POST /v1/assessments` (202, `Idempotency-Key`), `GET /v1/assessments`,
    `GET /v1/assessments/{id}`, `/result`, `/report`, `/decisions`,
    `/findings`, `/trace`, `/trace/{criterion}`, `/connector-runs`, `/cancel`,
    `/certification-request`, `/reassess`
  * `GET /v1/reviews/tasks`, `POST /v1/reviews` (always with a reason;
    escalation keeps the task open for a different reviewer)
  * `POST /v1/assessments/{id}/certification`, public
    `GET /v1/certifications/{number}/verify`
  * `GET /v1/organizations`, `/{id}`, `/{id}/assessments`, `/{id}/evidence`
    (paginated with totals), `POST /v1/organizations/{id}/monitoring`,
    `POST /v1/evidence/uploads`
  * `GET /v1/ontology`, `/v1/ontology/{version}`, entities, vocabularies,
    JSON-LD export, labels, methodology criteria, pillars, rules, decisions
  * `GET /v1/benchmarks/industries` (peers by sector, stage and size band)
  * `/health`, `/ready` (database migrated to this ontology version),
    `POST /v1/auth/token` (admin mints reviewer JWTs), webhooks
    (assessment.completed, review.required, score.changed, certification.signed,
    HMAC-signed deliveries), `GET /v1/audit/verify`, `GET /v1/audit/events`
  * Keep response shapes consistent across endpoints.

## 9. Frontend (`frontend/`)

A React console using the generated TypeScript types:

* Dashboard, new assessment form (with server validation errors mapped to
  fields), assessment detail (overview with score dial, pillar bars, coverage
  strip and outcome status exactly as stored; criteria; sources and connector
  runs; reviews), a trace drawer from any score down to the exact quote and
  source, the review queue (actions allowed per subject type, mandatory reason,
  escalation), certificate signing for reviewers, a public certificate verify
  page, an ontology browser (entities, vocabularies, criteria, ICs), organizations
  and peer benchmarks, and settings for API key or reviewer token.
* Humaital look (red accent `#D41920`, grays), light and dark mode, works at
  phone width, accessible.
* Contract tests that fail if the allowed review actions or the connector list
  drift from the backend files.
* Dockerfile building with Node and serving with unprivileged nginx on 8080,
  proxying the API from `API_UPSTREAM`.

## 10. Tooling, Docker And CI

* `docker/python.Dockerfile`, multi-stage with uv, non-root user, targets
  `api`, `worker`, `tools`; the ontology, config and migrations are copied into
  the image so an image pins one ontology version.
* `docker-compose.yml`: postgres, migrate (wait, migrate, seed, validate), api,
  worker, frontend, and an optional `ollama` profile. `.env.example` documents
  every setting.
* `Makefile` with `help` plus: install, install-frontend, hooks,
  ontology-validate, codegen, codegen-check, check-bump, ontology-diff,
  migrate-plan, baseline, db (throwaway test Postgres), migrate, seed,
  api-key, verify-audit, run-api, run-worker, run-frontend, dev, fmt, lint,
  typecheck, test-unit, test-integration, test, coverage, frontend-check,
  check, build, up, down, logs, reset, bundle, clean.
* `.github/workflows/ci.yml`: lint and mypy; an ontology gate (validate with
  implementations, codegen check, diff and check-bump against the base branch,
  migration plan uploaded as an artifact); tests against a Postgres service,
  run twice (database roles off and enforced), with coverage and JUnit;
  frontend typecheck, lint, test and build; Docker image builds; a compose
  smoke test hitting `/health`, `/ready` and `/v1/ontology`.
* `.github/workflows/release.yml`: on `v*` tags publish images to GHCR with the
  ontology and methodology versions as labels.
* `.pre-commit-config.yaml` with ruff, basic hygiene hooks, and local hooks for
  ontology validation and codegen check.

## 11. Tests

* **Ontology:** the shipped manifest loads and validates with zero errors and
  zero warnings; shape matches the spec (30 entities, layer counts, 20 criteria,
  6 pillars, IC-01..IC-18); broken copies of the manifest produce the expected
  error codes; semver ordering and ranges; diff and bump classification;
  migration plans; generated files are up to date; every code has a label; the
  LLM schema lists every enum value.
* **Pipeline and engine:** HTML extraction, canonical URLs, whole-word term
  matching, span offsets, negative-signal severity, injection detection,
  SimHash on realistic articles, admissibility order, independence, incident
  status, freshness decay and certificate expiry, classification rungs, the
  condition language refusing code, scoring (all level 5 is 100, unavailable is
  excluded not zeroed), every rule in the ruleset, the validator rejecting each
  bad finding with the right IC code, providers against mocked HTTP
  (`httpx.MockTransport`), the heuristic provider following the ladder.
* **Integration (Postgres):** create a throwaway database per test session from
  `HAI_TEST_DATABASE_URL`, migrate, seed, truncate between tests; migrations
  recorded with checksums; audit chain verifies and detects tampering;
  append-only and transition triggers; enum constraints; queue claim, dedupe and
  backoff.
* **End to end:** a fake internet fixture (company site with governance pages,
  a news feed with two syndicated copies of one lawsuit story, a prompt
  injection page, empty source APIs, an option to block the website). Drive it
  through the API and worker: idempotent start, full job chain, every span
  matches stored text, every connector run recorded, injection never admissible,
  one incident from two articles, review tasks created, replay equals stored
  result, escalation and four-eyes rule, API keys refused for signing, reviewer
  signs, finalize, audit verifies; and a blocked-website run reporting
  unavailable rather than missing.

## 12. Phases And Done-When

Produce `docs/plan.md` first, then follow it:

| Phase | Build | Done when |
|---|---|---|
| 0 | Repo skeleton, legacy move, porting notes, criterion register, D3/D7/D10 defaults | Criterion register written; porting doc lists every carried and corrected item |
| 1 | Ontology manifest, meta-model, validator, generators, versioning CLI, baseline migration | Validation clean; codegen check passes; generated SQL applies to an empty database |
| 2 | Core services and evidence pipeline | Every source traced to a connector run; spans verify against stored text |
| 3 | LLM evaluation | Findings pass all validators; heuristic provider works offline |
| 4 | Rules and scoring | Same snapshot and versions give the same result (replay test) |
| 5 | API, worker, review, certification, reporting, webhooks | Only a reviewer can certify; end-to-end test passes |
| 6 | Frontend | Typecheck, lint, tests and build pass |
| 7 | Docker, Makefile, CI, docs | `make check` and `make frontend-check` pass; AT-01..AT-15 each mapped to a passing test |

## 13. Open Decisions (Implement A Default, Make It Configurable, Document It)

Record each in `ontology/methodology/decisions.yaml` with the current behaviour:

* D1 maturity rungs to levels: default ladder, per-criterion override allowed.
* D2 materiality affects score, confidence or both: both by default, switchable.
* D3 certification threshold: universal 70 by default, stage and size table supported.
* D4 incident severity scale and appeals: low, moderate, high, critical; appeals as a review subject.
* D5 applicability: methodology-defined conditions with not_applicable or review effects.
* D6 AI system as a required level: optional in v1.
* D7 criterion code format: `PIL-NN` (for example `SAF-02`), Phase 6 IDs as aliases.
* D8 freshness window per criterion: per-criterion field with a methodology default.
* D9 source tier table and evidence classes: vocabulary attributes.
* D10 product name form: "HAI Score" in reports, `hai` in code.

## 14. Beyond v1 (Leave Clean Extension Points, Build What Is Cheap)

Design so these are additions, not rewrites: continuous monitoring (monitoring
subscriptions and a scheduler tick), the evidence portal (uploads as claims),
framework crosswalks to the EU AI Act, NIST AI RMF and ISO 42001 (a mapping
file in the methodology), the score explorer (the trace API), peer benchmarks,
the verifiable badge (public verify with expiry), a what-if simulator (replay
under a different methodology without writing), a reviewer copilot, and due
diligence packs. Write an ADR for each major design choice in `docs/adr/`.

## 15. Finish

When everything passes:

1. Regenerate code and the baseline migration, rebuild a fresh database, and run
   the full suite once more.
2. Write `README.md` (what it is, layout, quick start with Docker and without,
   a curl example, how an assessment runs, LLM providers, working on the
   ontology, tests), `docs/architecture.md` (including the IC enforcement
   table), `docs/ontology-guide.md`, `docs/porting-from-phase6.md`,
   `ontology/CHANGELOG.md`, and a `CLAUDE.md` with the commands and rules for
   future sessions.
3. Commit on `feature/hai-platform`, `git fetch origin main`, confirm the branch
   is based on the latest `main`, and push (bundle fallback as in section 0).
4. Give me a short summary: what was built, the test results with counts, what
   could not be verified here, every drafted methodology item that needs
   Humaital's content, and any open issues.
