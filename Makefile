# HAI Score platform. `make help` lists targets. Python goes through uv; the frontend through npm.
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
NPM ?= npm
COMPOSE ?= docker compose
BASE ?= git:origin/main
DB_CONTAINER ?= hai-dev-pg
DB_PORT ?= 55432
HAI_TEST_DATABASE_URL ?= postgresql://hai:hai@localhost:$(DB_PORT)/postgres
export HAI_TEST_DATABASE_URL
PY_SRC := packages/hai-ontology/src packages/hai-core/src packages/hai-pipeline/src packages/hai-engine/src services/api/src services/worker/src
PY_TESTS := packages/hai-ontology/tests packages/hai-core/tests packages/hai-pipeline/tests packages/hai-engine/tests services/api/tests
PG_TESTS := tests/integration tests/e2e services/api/tests

.PHONY: help install install-frontend hooks ontology-validate codegen codegen-check check-bump ontology-diff migrate-plan \
        baseline db db-stop migrate seed api-key verify-audit run-api run-worker run-frontend dev fmt fmt-check lint typecheck \
        test-unit test-integration test-enforced test coverage frontend-check check build up down logs reset smoke bundle clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ------------------------------------------------------------------ setup
install: ## uv sync for every package (dev extras included)
	$(UV) sync --all-packages

install-frontend: ## npm ci in frontend/
	cd frontend && $(NPM) ci --no-audit --no-fund

hooks: ## Install pre-commit hooks
	$(UV) run pre-commit install

# ------------------------------------------------------------------ ontology
ontology-validate: ## Validate the manifest, including rule implementations
	$(UV) run hai-ontology validate --implementations hai_engine.rules

codegen: ## Regenerate SQL, Python, TypeScript, JSON Schema and docs from the manifest
	$(UV) run hai-ontology codegen

codegen-check: ## Fail if any generated file is stale
	$(UV) run hai-ontology codegen --check

check-bump: ## Check the version moved far enough against BASE (default git:origin/main)
	$(UV) run hai-ontology check-bump $(BASE) ontology --verbose

ontology-diff: ## Classify every change against BASE
	$(UV) run hai-ontology diff $(BASE) ontology

migrate-plan: ## Additive SQL for the changes against BASE
	$(UV) run hai-ontology migrate-plan $(BASE) ontology

baseline: ## Rewrite db/migrations/0001_ontology_baseline.sql from the manifest
	$(UV) run hai-ontology baseline -o db/migrations/0001_ontology_baseline.sql

# ------------------------------------------------------------------ database
db: ## Start a throwaway Postgres 16 in Docker on DB_PORT (default 55432)
	@docker inspect $(DB_CONTAINER) >/dev/null 2>&1 || docker run -d --name $(DB_CONTAINER) -p $(DB_PORT):5432 \
		-e POSTGRES_USER=hai -e POSTGRES_PASSWORD=hai -e POSTGRES_DB=hai postgres:16-alpine >/dev/null
	@docker start $(DB_CONTAINER) >/dev/null
	@until docker exec $(DB_CONTAINER) pg_isready -U hai -d hai >/dev/null 2>&1; do sleep 1; done
	@echo "postgres ready: postgresql://hai:hai@localhost:$(DB_PORT)/hai (HAI_TEST_DATABASE_URL=$(HAI_TEST_DATABASE_URL))"

db-stop: ## Stop and remove the throwaway Postgres
	-docker rm -f $(DB_CONTAINER) >/dev/null 2>&1

migrate: ## Run migrations against HAI_DATABASE_URL
	$(UV) run hai-db wait && $(UV) run hai-db migrate

seed: ## Seed methodology and connector rows from the YAML
	$(UV) run hai-db seed

api-key: ## Create an API key: make api-key NAME=partner [SCOPES=a,b]
	$(UV) run hai-db create-api-key --name $(or $(NAME),local) $(if $(SCOPES),--scopes $(SCOPES),)

verify-audit: ## Verify the audit hash chain
	$(UV) run hai-db verify-audit

# ------------------------------------------------------------------ run
run-api: ## Run the API with reload
	$(UV) run uvicorn hai_api.main:app_factory --factory --reload --host 0.0.0.0 --port 8000

run-worker: ## Run the worker
	$(UV) run hai-worker

run-frontend: ## Run the Vite dev server (proxies /v1 to localhost:8000)
	cd frontend && $(NPM) run dev

dev: ## API, worker and frontend together with hot reload (Ctrl-C stops all)
	@trap 'kill 0' INT TERM; \
	$(MAKE) run-api & $(MAKE) run-worker & $(MAKE) run-frontend & wait

# ------------------------------------------------------------------ quality
fmt: ## Format Python
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

fmt-check: ## Check Python formatting
	$(UV) run ruff format --check .

lint: ## Ruff
	$(UV) run ruff check .

typecheck: ## mypy --strict on every package, service and test tree
	$(UV) run mypy $(PY_SRC) tests conftest.py
	@for d in $(PY_TESTS); do $(UV) run mypy $$d || exit 1; done

test-unit: ## Fast tests, no database
	$(UV) run pytest -q -m "not integration and not e2e"

test-integration: ## Postgres-backed tests (HAI_TEST_DATABASE_URL), roles not enforced
	HAI_ENFORCE_DB_ROLES=false $(UV) run pytest -q $(PG_TESTS)

test-enforced: ## Postgres-backed tests with SET LOCAL ROLE enforced
	HAI_ENFORCE_DB_ROLES=true $(UV) run pytest -q $(PG_TESTS)

test: test-unit test-integration test-enforced ## Everything

coverage: ## Unit and Postgres tests with coverage and JUnit output
	HAI_ENFORCE_DB_ROLES=true $(UV) run pytest -q --cov=packages --cov=services --cov-report=xml --cov-report=term-missing --junitxml=junit.xml

frontend-check: ## Typecheck, lint, test and build the console
	cd frontend && $(NPM) run typecheck && $(NPM) run lint && $(NPM) run test && $(NPM) run build

check: fmt-check lint typecheck ontology-validate codegen-check test-unit test-integration test-enforced ## The full gate

# ------------------------------------------------------------------ docker
build: ## Build the api, worker, tools and frontend images
	$(COMPOSE) build

up: ## Start the stack (postgres, migrate, api, worker, frontend)
	$(COMPOSE) up -d --build
	@echo "console http://localhost:$${FRONTEND_PORT:-8080}  api http://localhost:$${API_PORT:-8000}/docs"

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Follow logs
	$(COMPOSE) logs -f --tail=200

reset: ## Stop the stack and delete its volumes
	$(COMPOSE) down -v --remove-orphans

smoke: ## Compose smoke test: /health, /ready, /v1/ontology through the console proxy
	@for i in $$(seq 1 60); do curl -fsS http://localhost:$${API_PORT:-8000}/ready >/dev/null 2>&1 && break; sleep 2; done
	curl -fsS http://localhost:$${API_PORT:-8000}/health
	curl -fsS http://localhost:$${API_PORT:-8000}/ready
	curl -fsS http://localhost:$${FRONTEND_PORT:-8080}/v1/ontology | head -c 300; echo
	curl -fsS http://localhost:$${FRONTEND_PORT:-8080}/healthz; echo

# ------------------------------------------------------------------ release
bundle: ## git bundle of this branch relative to origin/main (push fallback)
	git bundle create hai-platform.bundle origin/main..HEAD

clean: ## Remove caches, build output and coverage
	rm -rf .mypy_cache .ruff_cache .pytest_cache coverage.xml junit.xml htmlcov frontend/dist frontend/*.tsbuildinfo
	find . -name __pycache__ -type d -prune -not -path "./node_modules/*" -exec rm -rf {} +
