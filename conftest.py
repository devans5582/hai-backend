"""Root pytest fixtures.

Postgres-backed tests take the ``db`` fixture. It creates a throwaway database
from ``HAI_TEST_DATABASE_URL`` (an admin URL such as
``postgresql://hai:hai@localhost:5432/postgres``) once per session, runs the
migrations and the seed, and truncates the data tables between tests. Without
the variable those tests skip. Set ``HAI_ENFORCE_DB_ROLES=true`` to run them
with ``SET LOCAL ROLE`` enforced.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from hai_core.db.engine import Database
from hai_core.db.migrate import migrate
from hai_core.manifest import role_codes
from hai_core.seed import seed_all
from hai_core.settings import Settings
from hai_ontology.loader import load_manifest
from hai_ontology.meta import Manifest

REPO = Path(__file__).parent
ENFORCE_ROLES = os.environ.get("HAI_ENFORCE_DB_ROLES", "").lower() in ("1", "true", "yes")

# Tables that hold seeded or schema state and survive truncation between tests.
KEEP_TABLES = {
    "schema_versions",
    "methodology_versions",
    "pillars",
    "criteria",
    "level_descriptors",
    "criterion_applicability",
    "rules",
    "connectors",
    "schema_migrations",
}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: needs PostgreSQL (set HAI_TEST_DATABASE_URL)")
    config.addinivalue_line("markers", "e2e: end-to-end against the fake internet (needs PostgreSQL)")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture(scope="session")
def manifest() -> Manifest:
    return load_manifest(REPO / "ontology")


def _sqlalchemy(url: str) -> str:
    return "postgresql+psycopg://" + url.split("://", 1)[1] if "://" in url else url


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    admin_url = os.environ.get("HAI_TEST_DATABASE_URL")
    if not admin_url:
        pytest.skip("integration test: set HAI_TEST_DATABASE_URL to run")
    name = f"hai_test_{secrets.token_hex(4)}"
    admin = create_engine(_sqlalchemy(admin_url), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = admin_url.rpartition("/")
    url = f"{base}/{name}"
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n AND pid <> pg_backend_pid()"  # noqa: E501
                ),
                {"n": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@pytest.fixture(scope="session")
def settings(test_database_url: str, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    blobs = tmp_path_factory.mktemp("blobs")
    return Settings(
        env="test",
        database_url=test_database_url,
        enforce_db_roles=ENFORCE_ROLES,
        blob_store_url=f"file://{blobs}",
        connectors_config=str(REPO / "config" / "connectors.yaml"),
        migrations_dir=str(REPO / "db" / "migrations"),
        llm_provider="heuristic",
        llm_model="ladder-1",
    )


@pytest.fixture(scope="session")
def db(settings: Settings, manifest: Manifest) -> Iterator[Database]:
    database = Database(
        settings.database_url, enforce_roles=settings.enforce_db_roles, allowed_roles=role_codes(manifest)
    )
    migrate(database, REPO / "db" / "migrations")
    with database.engine.begin() as conn:
        user = conn.execute(text("SELECT current_user")).scalar_one()
        roles = ", ".join(sorted(role_codes(manifest)))
        conn.execute(text(f'GRANT {roles} TO "{user}"'))
    with database.transaction("pytest", "hai_admin") as conn:
        seed_all(conn, manifest, REPO / "config" / "connectors.yaml", actor="pytest")
    try:
        yield database
    finally:
        database.dispose()


@pytest.fixture
def clean_db(db: Database) -> Iterator[Database]:
    """The shared database with data tables truncated before the test."""
    _truncate(db)
    yield db


def _truncate(db: Database) -> None:
    with db.engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema IN ('hai', 'hai_ops') AND table_type = 'BASE TABLE'"
            )
        ).all()
        targets = [f"{s}.{t}" for s, t in rows if t not in KEEP_TABLES]
        if targets:
            conn.execute(text("TRUNCATE " + ", ".join(targets) + " CASCADE"))
