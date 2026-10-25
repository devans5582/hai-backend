"""The HAI API (FastAPI). OpenAPI is generated from the same models the services use."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from hai_api.deps import AppState
from hai_api.errors import install_error_handlers
from hai_api.routers import assessments, ontology, organizations, reviews, system
from hai_core.logging import configure_logging
from hai_core.manifest import get_manifest, verify_generated_code
from hai_core.settings import Settings, get_settings
from hai_engine.rules import resolve
from hai_ontology.meta import Manifest

log = logging.getLogger("hai_api")

TAGS = [
    {
        "name": "assessments",
        "description": "Create and follow assessments; results, reports, decisions, findings, traces.",
    },
    {"name": "reviews", "description": "The review queue and reviewer decisions (JWT only)."},
    {"name": "certification", "description": "Reviewer-signed certification decisions and public verification."},
    {"name": "organizations", "description": "Organizations, their evidence ledger, monitoring and uploads."},
    {"name": "benchmarks", "description": "Peer benchmarks by industry, stage and size."},
    {"name": "ontology", "description": "The running ontology and methodology."},
    {"name": "system", "description": "Health, readiness, tokens, webhooks, audit."},
]


def create_app(
    settings: Settings | None = None, manifest: Manifest | None = None, state: AppState | None = None
) -> FastAPI:
    settings = settings or get_settings()
    manifest = manifest or get_manifest(settings.ontology_dir)
    verify_generated_code(manifest)
    resolve(manifest)  # refuse to start if a rule does not resolve
    configure_logging(settings.log_level, "hai-api", settings.log_json)
    app_state = state or AppState.build(settings, manifest)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.hai = app_state
        log.info(
            "hai-api starting",
            extra={
                "ontology": manifest.ontology_version,
                "methodology": manifest.methodology_version,
                "manifest_hash": manifest.hash[:12],
            },
        )
        yield
        app_state.db.dispose()

    app = FastAPI(
        title="Humaital HAI Score API",
        version=f"{manifest.ontology_version}+m{manifest.methodology_version}",
        description="Turns public and submitted evidence about an organization into an HAI Score that can be traced, reproduced and defended. The LLM proposes, rules decide, a reviewer signs.",  # noqa: E501
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    app.state.hai = app_state
    install_error_handlers(app)
    _install_cors(app, settings)

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        log.info(
            "request",
            extra={
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": int((time.monotonic() - started) * 1000),
            },
        )
        return response

    app.include_router(system.router)
    app.include_router(assessments.router)
    app.include_router(reviews.router)
    app.include_router(organizations.router)
    app.include_router(ontology.router)
    return app


def _install_cors(app: FastAPI, settings: Settings) -> None:
    suffixes = "|".join(re.escape(s) for s in settings.cors_origin_suffixes)
    regex = rf"^https?://([a-z0-9-]+\.)*({suffixes.replace(chr(92) + '.', '', 1)})$" if suffixes else None
    origin_regex = rf"^https://[a-z0-9.-]+({suffixes})$" if suffixes else None
    del regex
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=origin_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-Id", "Idempotency-Key"],
        expose_headers=["X-Request-Id"],
        max_age=86400,
    )


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "hai_api.main:app_factory", host=settings.api_host, port=settings.api_port, factory=True, log_config=None
    )


def app_factory() -> FastAPI:
    return create_app()
