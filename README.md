<p align="center">
  <a href="https://humaital.com/">
    <img src="docs/assets/humaital-logo.png" alt="Humaital" width="360">
  </a>
</p>

<h1 align="center">HAI Score Platform</h1>

<p align="center">
  The platform behind the <strong>HAI Score</strong> (Human Alignment Index):
  an ontology-driven evidence pipeline, model-assisted evaluation, a rules
  engine that makes every decision, a reviewer workflow, an API, a worker and
  a web console.
</p>

<p align="center">
  <em>The model proposes. The rules decide. A named reviewer signs.</em>
</p>

---

## Contents

1. [What It Does](#what-it-does)
2. [Principles](#principles)
3. [Architecture Overview](#architecture-overview)
4. [Repository Layout](#repository-layout)
5. [Quick Start With Docker](#quick-start-with-docker)
6. [Quick Start Without Docker](#quick-start-without-docker)
7. [Your First Assessment](#your-first-assessment)
8. [How An Assessment Runs](#how-an-assessment-runs)
9. [The Console](#the-console)
10. [LLM Providers](#llm-providers)
11. [Working On The Ontology](#working-on-the-ontology)
12. [Tests And Quality Gates](#tests-and-quality-gates)
13. [Configuration](#configuration)
14. [Documentation](#documentation)
15. [Status And Ownership](#status-and-ownership)

---

## What It Does

The HAI Score rates how well an organization governs its use of AI. The
platform collects public evidence (the organization's website, regulatory
filings, news, code repositories, research, web archives, certificate
registries) and submitted documents, turns that evidence into quoted,
traceable spans, evaluates twenty criteria across six pillars, and produces
a score, a confidence figure, an outcome status and a certificate that anyone
can verify.

| Pillar | Code | Criteria |
|---|---|---|
| Trust | `TRU` | 4 |
| Accountability | `ACC` | 3 |
| Purpose | `PUR` | 3 |
| Safety | `SAF` | 3 |
| Transparency | `TRN` | 3 |
| Impact | `IMP` | 4 |

Every number in a report can be followed back to a quote, its character
offsets in a stored document, the connector run that fetched it, and the rules
that turned it into a level.

## Principles

| Principle | What it means in the code |
|---|---|
| One manifest everywhere | The YAML under `ontology/` is the only hand-edited definition. SQL, Python, TypeScript, JSON Schemas and docs are generated from it and carry its hash. Services refuse to start on drift. |
| Evidence links are the only bridge | Nothing reaches a score except an `evidence_link` naming one span, one target and one criterion. Polarity is immutable. A link counts only for the criterion it names. |
| The rules engine reads the snapshot | Judgments are frozen into an `evidence_snapshot`; the engine is a set of pure rules over it. Replaying a snapshot reproduces the stored result hash. |
| One authority per write | Database roles and grants make the engine the only writer of decisions and results, and a reviewer JWT the only signer of certifications. The console never computes. |
| Unavailable is not missing | A blocked source excludes a criterion; a searched source with nothing found counts against the score. Reports list only sources that were actually collected. |
| Everything is audited | Every write goes through a hash-chained audit log that `hai-db verify-audit` can check. |

## Architecture Overview

```mermaid
flowchart LR
    classDef red fill:#D41920,stroke:#A8141A,color:#ffffff
    classDef grey fill:#f3f3f5,stroke:#9a9aa4,color:#1a1a1f
    classDef store fill:#ffffff,stroke:#D41920,color:#1a1a1f,stroke-dasharray: 4 3

    subgraph Clients
        console["Console<br/>React, nginx"]
        partner["Partner systems<br/>API key, webhooks"]
        public["Anyone<br/>public verify"]
    end

    subgraph Platform
        api["hai-api<br/>FastAPI"]
        worker["hai-worker<br/>job chain"]
        engine["hai-engine<br/>rules decide"]
        pipeline["hai-pipeline<br/>connectors, spans, links"]
    end

    subgraph Storage
        pg[("PostgreSQL 16<br/>hai + hai_ops schemas<br/>roles, RLS, triggers, audit chain, job queue")]
        blobs[("Blob store<br/>document text")]
    end

    subgraph Outside
        sources["Evidence sources<br/>website, EDGAR, news, GitHub,<br/>research, archive, uploads, ISO 42001"]
        llm["LLM provider<br/>heuristic, OpenAI, Anthropic, Ollama"]
    end

    manifest["Ontology manifest<br/>ontology/*.yaml"]
    gen["Generated code<br/>SQL, Python, TypeScript, JSON Schema"]

    console --> api
    partner --> api
    public --> api
    api --> pg
    api -- enqueue --> pg
    pg -- claim job --> worker
    worker --> pipeline
    worker --> engine
    pipeline --> sources
    pipeline --> blobs
    pipeline --> pg
    engine -- proposals only --> llm
    engine -- decisions, results --> pg
    api -- webhooks --> partner
    manifest -- hai-ontology codegen --> gen
    gen -.-> api
    gen -.-> worker
    gen -.-> pg
    gen -.-> console

    class api,worker,engine,pipeline red
    class console,partner,public,sources,llm grey
    class manifest,gen store
```

Red boxes are the platform's own services and libraries. The manifest on the
left of the dashed arrows is generated into every layer, so one ontology
version is pinned from the database to the browser. The detailed component,
lifecycle, authority and sequence diagrams are in `docs/architecture.md`.

## Repository Layout

```
ontology/                manifest: ontology.yaml, vocabularies/, methodology/, examples/, CHANGELOG.md
packages/
  hai-ontology/          meta-model, loader, validator, versioning, code generators, CLI (hai-ontology)
  hai-core/              settings, db roles, typed store, audit chain, job queue, blob store, auth, reviews, webhooks (hai-db)
  hai-pipeline/          connectors, entity resolution, extraction, spans, clustering, admissibility, incidents, snapshot
  hai-engine/            classification, evidence packs, LLM providers, validator, rules, scoring, decisions, certification, reports
services/
  api/                   FastAPI service (hai-api)
  worker/                background worker (hai-worker)
frontend/                React console (Vite), served by unprivileged nginx in Docker
db/migrations/           0001 generated from the manifest, 0002 operations schema
config/connectors.yaml   evidence sources, limits and rate settings
docker/                  python.Dockerfile with targets api, worker, tools
docs/                    architecture, ontology guide, porting notes, plan, ADRs, generated glossary and JSON-LD
tests/                   integration and end-to-end tests, the fake internet fixture
legacy/express-api/      the Phase 6 Node service, read-only reference
```

Dependencies point one way: `hai-ontology`, then `hai-core`, then
`hai-pipeline` and `hai-engine`, then the services. The console talks only to
the API.

## Quick Start With Docker

Requirements: Docker with Compose v2.

```bash
cp .env.example .env
make up          # postgres, migrate (wait, migrate, seed, validate), api, worker, console
make smoke       # /health, /ready and /v1/ontology through the console proxy
```

| Service | URL |
|---|---|
| Console | http://localhost:8080 |
| API docs | http://localhost:8000/docs |
| Health and readiness | http://localhost:8000/health and http://localhost:8000/ready |

If ports 8000 or 8080 are taken, set `API_PORT` and `FRONTEND_PORT` in `.env`.
`make down` stops the stack; `make reset` also deletes its volumes.

## Quick Start Without Docker

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 20, and
Docker for the throwaway Postgres.

```bash
make install install-frontend
make db                                              # Postgres 16 on localhost:55432
export HAI_DATABASE_URL=postgresql://hai:hai@localhost:55432/hai
make migrate seed
make dev                                             # api :8000, worker, console :5173
```

## Your First Assessment

Create an API key. It is printed once.

```bash
# in the Docker stack
docker compose run --rm migrate hai-db create-api-key --name partner
# without Docker
make api-key NAME=partner
```

Start an assessment. The `Idempotency-Key` makes a retried request return the
same assessment instead of starting a second one.

```bash
curl -s -X POST http://localhost:8000/v1/assessments \
  -H "X-API-Key: $HAI_API_KEY" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
        "organization_name": "Acme Corp",
        "website": "https://www.acme.example",
        "stage": "growth",
        "size": "mid",
        "industry": "Software",
        "direct_urls": ["https://www.acme.example/responsible-ai"]
      }'
```

Follow it through the API:

| Endpoint | Returns |
|---|---|
| `GET /v1/assessments/{id}` | lifecycle state, version pins, links |
| `GET /v1/assessments/{id}/result` | score, confidence, outcome status, pillar scores |
| `GET /v1/assessments/{id}/report` | the full report with criteria, evidence, sources and connector runs |
| `GET /v1/assessments/{id}/trace/{criterion}` | rule-by-rule trace down to the quoted evidence |
| `GET /v1/assessments/{id}/connector-runs` | one row per connector, including blocked and failed runs |

Reviewer and admin tokens are minted by an admin key:

```bash
docker compose run --rm migrate hai-db create-api-key --name admin --scopes admin
curl -s -X POST http://localhost:8000/v1/auth/token \
  -H "X-API-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
  -d '{"subject": "rev-1", "name": "Reviewer One", "role": "reviewer"}'
```

Paste the API key or the token into the console's Settings page.

## How An Assessment Runs

```mermaid
flowchart TD
    classDef red fill:#D41920,stroke:#A8141A,color:#ffffff
    classDef grey fill:#f3f3f5,stroke:#9a9aa4,color:#1a1a1f
    classDef human fill:#fbe9ea,stroke:#D41920,color:#1a1a1f

    start(["POST /v1/assessments<br/>Idempotency-Key, five version pins"])
    acquire["acquire_evidence<br/>every connector runs and is recorded<br/>text stored, spans verified, links proposed<br/>admissibility judged, incidents created"]
    classify["classify_links<br/>maturity rung, execution, class, independence per span"]
    freeze["freeze_snapshot<br/>judgments, incidents, run outcomes, pins, SHA-256"]
    evaluate["evaluate_criteria<br/>per-criterion packs to the model<br/>findings validated against the snapshot"]
    decide["decide<br/>rules in methodology order<br/>decisions, pillar scores, result hash, trace"]
    review{"review<br/>triggers?"}
    tasks["awaiting_review<br/>reviewer acts with a reason<br/>escalation, four eyes"]
    finalize["finalize<br/>rerun with the review overlay<br/>supersede earlier rows"]
    unverified(["completed_unverified"])
    sign["reviewer signs certification<br/>API keys refused"]
    done(["completed<br/>public verify, webhooks"])

    start --> acquire --> classify --> freeze --> evaluate --> decide --> review
    review -- yes --> tasks --> finalize --> unverified
    review -- no --> unverified
    unverified --> sign --> done

    class acquire,classify,freeze,evaluate,decide,finalize red
    class tasks,sign human
    class start,unverified,done,review grey
```

1. **Record.** The API resolves or creates the organization, pins five
   versions (ontology, methodology, ruleset, prompt, model) and enqueues work.
2. **Acquire.** Every connector in `config/connectors.yaml` runs and records
   an outcome, blocked or not. Text goes to the blob store; spans are cut with
   offsets that are checked against the stored text.
3. **Judge.** Links are classified from descriptors, never from the source
   tier. Negative signals become incidents in `alleged` status unless a
   regulator published them.
4. **Freeze.** The snapshot is the only thing the engine reads from here on.
5. **Propose.** The provider sees per-criterion packs built from full
   documents, with crawled text as data and never as instructions. Invalid
   findings are rejected and kept for audit.
6. **Decide.** The rules engine writes decisions with applied rule codes,
   aggregates pillars, applies caps and gates, and stores the result hash.
7. **Review and sign.** Reviewers act with a reason; escalation hands a task
   to a different reviewer; the requester of a certification cannot sign it.
   Verification is public and reflects expiry and revocation.

`docs/architecture.md` has the full flow and the integrity constraint table.

## The Console

| Page | Purpose |
|---|---|
| Dashboard | recent assessments, open review tasks, API status |
| New assessment | the request form; server validation errors land on the right field |
| Assessment | score dial, pillar bars, coverage strip, outcome exactly as stored; criteria, sources and connector runs, reviews |
| Trace drawer | the rules in order and every quote, offset and source behind a criterion |
| Reviews | the queue with only the actions allowed for each subject type; a reason is mandatory |
| Verify | public certificate check |
| Ontology | entities, vocabularies, criteria, rules and integrity constraints from the generated module |
| Organizations | evidence ledger per organization and peer benchmarks |
| Settings | API key or reviewer token, kept in the browser only |

The console uses `frontend/src/generated/ontology.ts` for every code and
label, and contract tests check its connector list and review actions against
the backend files. It is shipped as an unprivileged nginx image that proxies
`/v1` to `API_UPSTREAM`.

## LLM Providers

Set `HAI_LLM_PROVIDER` to one of the following. Whatever the provider, the
output is validated against the generated JSON Schema and the snapshot before
the rules see it. The model never sets a score.

| Provider | Notes |
|---|---|
| `heuristic` (default) | offline and deterministic; follows the evidence ladder; used by the test suite |
| `openai` | OpenAI-compatible chat completions with strict JSON Schema output; `HAI_LLM_BASE_URL` can point at OpenAI, Azure OpenAI, vLLM or LM Studio |
| `anthropic` | Messages API with a forced tool call whose input schema is the finding schema |
| `ollama` | local models; `docker compose --profile ollama up` starts a server |

## Working On The Ontology

The YAML under `ontology/` is the source of truth. After an edit:

```bash
make ontology-validate     # meta-model, references, rule implementations
make codegen               # SQL, Python, TypeScript, JSON Schema, glossary, JSON-LD
make check-bump            # did the semver move far enough against origin/main?
make migrate-plan          # additive SQL for the change
```

Generated files carry the manifest hash; services refuse to start on drift and
CI fails on stale output. Record every change in `ontology/CHANGELOG.md`.

Methodology content (criterion definitions, level descriptors, weights,
crosswalks) belongs to Humaital. Placeholders are marked
`content_status: draft` with `TODO(humaital)` and are listed in
`docs/plan.md`, section 6.

## Tests And Quality Gates

```bash
make test-unit           # no database
make db                  # throwaway Postgres for the next two
make test-integration    # Postgres-backed, roles not enforced
make test-enforced       # Postgres-backed, SET LOCAL ROLE enforced
make frontend-check      # typecheck, lint, vitest, build
make check               # the full gate CI runs
```

| Gate | What it covers |
|---|---|
| `ruff`, `mypy --strict` | every package, service and test tree |
| Ontology gate | validation with rule implementations, generated files current, semver bump and migration plan against the base branch |
| Unit tests | ontology tooling, pipeline, engine rules, providers against mocked HTTP, guard tests for hand-typed codes and the AT mapping |
| Postgres tests, twice | migrations, audit chain, triggers, grants, queue, acquisition, decide and replay, API contracts, end-to-end against a fake internet; with roles off and enforced |
| Frontend | typecheck, lint, component and contract tests, production build |
| Docker | image builds and a compose smoke test on `/health`, `/ready` and `/v1/ontology` |

Acceptance tests AT-01 to AT-15 are listed in the manifest with the test
functions that prove them; a guard test fails when a listed function does not
exist. `docs/architecture.md` renders the mapping.

## Configuration

Every setting is an environment variable with the `HAI_` prefix;
`.env.example` documents all of them. The ones you are most likely to change:

| Variable | Purpose |
|---|---|
| `HAI_DATABASE_URL` | Postgres connection string |
| `HAI_ENFORCE_DB_ROLES` | `SET LOCAL ROLE` per component in every transaction |
| `HAI_API_KEY_PEPPER`, `HAI_JWT_SECRET`, `HAI_CERT_SIGNING_KEY`, `HAI_WEBHOOK_SIGNING_KEY` | signing secrets; production refuses `dev-` values and anything under 32 characters |
| `HAI_BLOB_STORE_URL` | fsspec URL for stored document text (`file://`, `s3://`, `gs://`, `az://`) |
| `HAI_LLM_PROVIDER`, `HAI_LLM_MODEL`, `HAI_LLM_BASE_URL`, `HAI_LLM_API_KEY` | evaluation provider |
| `HAI_CORS_ORIGINS`, `HAI_CORS_ORIGIN_SUFFIXES` | browser origins allowed to call the API |

## Documentation

| Document | Contents |
|---|---|
| `ontology/README.md` | the manifest explained: layers, entity relationship diagram, the evidence link, methodology, ladder, lifecycle, every entity, relation, vocabulary, rule and constraint |
| `docs/architecture.md` | components, flow, IC enforcement table, AT mapping, authority model, operations |
| `docs/ontology-guide.md` | manifest files, criterion register, maturity ladder, coverage states, how to change it |
| `docs/porting-from-phase6.md` | what was carried, corrected and dropped from the Node service, with file and line references |
| `docs/plan.md` | the build plan, drafts that need Humaital, decisions taken |
| `docs/adr/` | architecture decision records, including the extension points |
| `docs/generated/` | glossary, labels and JSON-LD generated from the manifest |
| `CLAUDE.md` | commands and rules for future coding sessions |

## Status And Ownership

The platform is feature complete for v1 and green on every gate. The
methodology version is `1.0.0` with status `draft`: criterion definitions,
level descriptors, some weights and the framework crosswalk are placeholders
until Humaital approves them. Nothing is presented as approved content.

Copyright Humaital. Proprietary. The HAI methodology, its criteria, level
descriptors and weights are Humaital intellectual property.
