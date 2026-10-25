# Humaital HAI Score Platform

The HAI Score (Human Alignment Index) rates how well an organization governs
its use of AI, from public evidence and submitted documents. This repository is
the platform that produces the score: an ontology-driven evidence pipeline,
model-assisted evaluation, a rules engine that makes every decision, a review
and certification workflow, an API, a worker and a web console.

Core principle: the model proposes, the rules decide, a named reviewer signs.
Nothing reaches a score except through an evidence link that names one quoted
span, one target and one criterion. Every result can be replayed from its
frozen snapshot and reproduces the stored hash.

## Layout

```
ontology/                manifest: ontology.yaml, vocabularies/, methodology/, examples/, CHANGELOG.md
packages/hai-ontology    meta-model, loader, validator, versioning, code generators, CLI (hai-ontology)
packages/hai-core        settings, db, typed store, audit chain, job queue, blob store, auth, reviews, webhooks (hai-db)
packages/hai-pipeline    connectors, entity resolution, extraction, spans, clustering, admissibility, incidents, snapshot
packages/hai-engine      classification, evidence packs, LLM providers, validator, rules, scoring, decisions, certification, reports
services/api             FastAPI service (hai-api)
services/worker          background worker (hai-worker)
frontend/                React console (Vite), served by nginx in Docker
db/migrations/           0001 generated from the manifest, 0002 operations schema
config/connectors.yaml   evidence sources, limits and rate settings
docker/                  python.Dockerfile (targets api, worker, tools)
docs/                    architecture, ontology guide, porting notes, plan, ADRs, generated glossary and JSON-LD
tests/                   integration and end-to-end tests, the fake internet fixture
legacy/express-api/      the Phase 6 Node service, reference only
```

## Quick Start With Docker

Requirements: Docker with Compose v2.

```
cp .env.example .env
make up            # postgres, migrate (wait, migrate, seed, validate), api, worker, console
make smoke         # /health, /ready and /v1/ontology through the console proxy
```

Console: http://localhost:8080. API docs: http://localhost:8000/docs.

Create an API key inside the stack and start an assessment:

```
docker compose run --rm migrate hai-db create-api-key --name partner
# ...prints "api key (shown once): hai_xxxx.yyyy"

curl -s -X POST http://localhost:8000/v1/assessments \
  -H "X-API-Key: $HAI_API_KEY" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"organization_name": "Acme Corp", "website": "https://www.acme.example",
       "stage": "growth", "size": "mid", "industry": "Software",
       "direct_urls": ["https://www.acme.example/responsible-ai"]}'
```

The response carries the assessment id and links. Poll
`GET /v1/assessments/{id}`; when the lifecycle state is `completed_unverified`
or `awaiting_review`, read `/result`, `/report`, `/decisions`, `/trace` and
`/connector-runs`.

Reviewer and admin tokens are minted by an admin:

```
docker compose run --rm migrate hai-db create-api-key --name admin --scopes admin
curl -s -X POST http://localhost:8000/v1/auth/token -H "X-API-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"subject": "rev-1", "name": "Reviewer One", "role": "reviewer"}'
```

Paste the API key or the token into the console's Settings page.

## Quick Start Without Docker

Requirements: Python 3.12 via uv, Node 20, Docker for the throwaway Postgres.

```
make install install-frontend
make db                                   # Postgres 16 on localhost:55432
export HAI_DATABASE_URL=postgresql://hai:hai@localhost:55432/hai
make migrate seed
make api-key NAME=partner
make dev                                  # api :8000, worker, console :5173
```

## How An Assessment Runs

1. The API records the assessment with five version pins and enqueues work.
2. The worker runs every connector (website, supplied URLs, EDGAR, news,
   GitHub, research, web archive, uploads, ISO 42001 registry) and records a
   run for each, blocked or not. Text is stored, cut into spans with offsets,
   linked to criteria, judged for admissibility, and negative signals become
   incidents (one per event, alleged until substantiated).
3. The judgments are frozen into a snapshot. The model proposes a level per
   criterion citing only snapshot spans; invalid findings are rejected.
4. The rules engine decides each criterion from the snapshot alone, aggregates
   pillars, applies caps and gates, and stores the result with a hash and a
   rule-by-rule trace. Anything uncertain opens a review task.
5. A reviewer acts with a reason; finalize reruns the engine with the review
   overlay. A reviewer signs the certification; the public verify endpoint
   confirms it.

`docs/architecture.md` has the full flow and the integrity constraint table.

## LLM Providers

Set `HAI_LLM_PROVIDER` to one of:

* `heuristic` (default): offline, deterministic, follows the evidence ladder.
  Used by the test suite and fine for local runs.
* `openai`: OpenAI-compatible chat completions with strict JSON Schema output;
  `HAI_LLM_BASE_URL` points at OpenAI, Azure OpenAI, vLLM or LM Studio.
* `anthropic`: Messages API with a forced tool call whose schema is the finding
  schema.
* `ollama`: local models; `docker compose --profile ollama up` starts a server.

Whatever the provider, the output is validated against the generated schema
and the snapshot before the rules see it. The model never sets a score.

## Working On The Ontology

The YAML under `ontology/` is the source of truth. After an edit:

```
make ontology-validate        # meta-model, references, rule implementations
make codegen                  # SQL, Python, TypeScript, JSON Schema, glossary, JSON-LD
make check-bump               # did the semver move far enough against origin/main?
make migrate-plan             # additive SQL for the change
```

Generated files carry the manifest hash; services refuse to start on drift and
CI fails on stale output. Record the change in `ontology/CHANGELOG.md`.
Methodology content (criterion definitions, level descriptors, weights,
crosswalks) belongs to Humaital; drafts are marked `content_status: draft`
with `TODO(humaital)`.

## Tests

```
make test-unit          # no database
make db                 # throwaway Postgres for the next two
make test-integration   # Postgres-backed, roles not enforced
make test-enforced      # Postgres-backed, SET LOCAL ROLE enforced
make frontend-check     # typecheck, lint, vitest, build
make check              # the full gate CI runs
```

The end-to-end test drives the API and worker against a fake internet (a
company site with governance pages, two syndicated copies of one lawsuit
story, a prompt injection page, empty source APIs, a blocked-website option)
and checks the acceptance tests AT-01 to AT-15 listed in the manifest.

## Documentation

* `docs/architecture.md`: components, flow, IC enforcement table, AT mapping.
* `docs/ontology-guide.md`: files, criterion register, ladder, coverage states.
* `docs/porting-from-phase6.md`: what was carried, corrected and dropped.
* `docs/plan.md`: the build plan, drafts that need Humaital, decisions.
* `docs/adr/`: architecture decision records.
* `CLAUDE.md`: commands and rules for future sessions.

License: proprietary. The methodology is Humaital intellectual property.
