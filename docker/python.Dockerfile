# Multi-stage image for the HAI Score platform. Targets: api, worker, tools.
# The ontology, connector config and migrations are copied in, so one image pins one ontology version.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.9.30

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------- builder
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# Dependency layer first: lockfile and every workspace manifest.
COPY pyproject.toml uv.lock README.md ./
COPY packages/hai-ontology/pyproject.toml packages/hai-ontology/
COPY packages/hai-core/pyproject.toml packages/hai-core/
COPY packages/hai-pipeline/pyproject.toml packages/hai-pipeline/
COPY packages/hai-engine/pyproject.toml packages/hai-engine/
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace
# Then the sources.
COPY packages ./packages
COPY services ./services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------- runtime base
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="HAI Score platform" \
      org.opencontainers.image.vendor="Humaital"
ARG ONTOLOGY_VERSION=unknown
ARG METHODOLOGY_VERSION=unknown
LABEL com.humaital.ontology.version="${ONTOLOGY_VERSION}" \
      com.humaital.methodology.version="${METHODOLOGY_VERSION}"
# No apt packages: the base image has CA certificates and the health check uses Python.
RUN groupadd --gid 10001 hai && useradd --uid 10001 --gid hai --create-home --shell /usr/sbin/nologin hai
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HAI_ONTOLOGY_DIR=/app/ontology HAI_MIGRATIONS_DIR=/app/db/migrations HAI_CONNECTORS_CONFIG=/app/config/connectors.yaml \
    HAI_BLOB_STORE_URL=file:///var/lib/hai/blobs
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# The manifest, connector config and migrations ride with the code (IC-18: one image, one ontology version).
COPY ontology ./ontology
COPY config ./config
COPY db ./db
RUN mkdir -p /var/lib/hai/blobs && chown -R hai:hai /var/lib/hai /app
USER hai

# ---------------------------------------------------------------- api
FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]
CMD ["hai-api"]

# ---------------------------------------------------------------- worker
FROM runtime AS worker
CMD ["hai-worker"]

# ---------------------------------------------------------------- tools (migrate, seed, validate, keys)
FROM runtime AS tools
CMD ["hai-db", "status"]
