# CLAUDE.md

Guidance for future sessions working on the Humaital HAI Score platform.

## What This Is

A monorepo that turns public and submitted evidence about an organization
into an HAI Score that can be traced, reproduced and defended. Core principle:
the LLM proposes, the rules decide, a named reviewer signs.

Read `docs/architecture.md`, `docs/ontology-guide.md` and
`docs/porting-from-phase6.md` before changing anything. The build plan is in
`docs/plan.md`.

## Rules

1. Never commit to `main`. Work on `feature/hai-platform` or a branch from it.
   Never force-push, rebase or rewrite `main`.
2. `legacy/express-api/` is the Phase 6 Node service. It is read-only
   reference. Do not edit or delete it.
3. The manifest under `ontology/` is the source of truth. Generated files
   carry a "generated, do not edit" header and the manifest hash. Edit the
   YAML, then run `make codegen`. CI fails on drift.
4. Do not hand-type criterion codes (`SAF-01`) or status strings outside the
   ontology YAML, generated files and tests. Import the generated enums.
5. Do not invent methodology content. Humaital owns the 20 criteria, their
   level descriptors and weights. Drafts are marked `content_status: draft`
   with `TODO(humaital)`.
6. Nothing reaches a score except through an evidence link naming one span,
   one target and one criterion. The rules engine reads only the frozen
   snapshot. Only the engine writes decisions and results. Only a reviewer
   JWT can sign a certification.
7. Plain ASCII in docs: no em dashes, no curly quotes. Title Case headings.
8. Run every command you claim works. Say explicitly what could not be run.

## Commands

All tasks go through the Makefile. `make help` lists them.

```
make install            uv sync for all packages
make install-frontend   npm ci in frontend/
make ontology-validate  validate the manifest (with rule implementations)
make codegen            regenerate SQL, Python, TypeScript, JSON Schema, docs
make codegen-check      fail if generated files are stale
make check-bump BASE=git:origin/main
make db                 start a throwaway Postgres 16 in Docker
make migrate            run migrations against HAI_DATABASE_URL
make seed               seed methodology and connector rows from YAML
make test-unit          fast tests, no database
make test-integration   Postgres-backed tests (HAI_TEST_DATABASE_URL)
make test               both
make check              fmt check, lint, typecheck, ontology gate, tests
make frontend-check     typecheck, lint, test, build
make dev                api, worker and frontend with hot reload
make up / down          docker compose
```

## Layout

```
ontology/            manifest: ontology.yaml, vocabularies/, methodology/, examples/
packages/hai-ontology  meta-model, loader, validator, versioning, codegen, CLI
packages/hai-core      settings, db, typed store, audit chain, job queue, blob store, auth
packages/hai-pipeline  connectors, entity resolution, text, spans, clustering, admissibility, incidents, snapshot
packages/hai-engine    classification, packs, LLM providers, validator, rules, scoring, decisions, certification, reports
services/api           FastAPI (hai-api)
services/worker        background worker (hai-worker)
frontend/              React console
db/migrations/         0001 generated baseline, later hand-written numbered SQL
config/connectors.yaml evidence sources and limits
tests/                 cross-package integration and end-to-end tests, fake internet fixture
docs/                  architecture, ontology guide, porting notes, ADRs, generated glossary and JSON-LD
```

Dependencies point one way: hai-ontology, then hai-core, then hai-pipeline
and hai-engine, then the services.

## Conventions

* Python 3.11+, uv workspace, hatchling, `uv.lock` committed.
* FastAPI, Pydantic v2, SQLAlchemy Core 2.x, psycopg 3, PostgreSQL 16.
* `ruff` and `mypy --strict` are clean on every package. Tests use `pytest`;
  Postgres tests are marked `integration` and skip without
  `HAI_TEST_DATABASE_URL`.
* Settings come from environment variables with the `HAI_` prefix. Production
  refuses development secrets, secrets under 32 characters and
  `HAI_AUTH_DISABLED`.
* Errors from the API use `{"error": {"code", "message", "details"}}`.
* Rules are pure functions registered with `@criterion_rule("CODE")` or
  `@assessment_rule("CODE")`; no database, no LLM, no clock.
* Commit per phase with a focused message. Do not move on with a failing
  phase.

## Changing The Ontology

1. Edit the YAML. Add valid and invalid examples if a shape changed.
2. `make ontology-validate && make codegen`.
3. `make check-bump BASE=git:origin/main` tells you whether the semver moved
   far enough; `make migrate-plan` writes the additive SQL.
4. Record the change in `ontology/CHANGELOG.md`. Methodology content changes
   need Humaital sign-off before the version is marked approved.
