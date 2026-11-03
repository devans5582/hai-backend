"""The seeded demo credential remains a scoped, revocable database-backed key."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from hai_core.auth import DEMO_API_KEY, Scope, hmac_secret, revoke_api_key, verify_api_key
from hai_core.db.engine import Database
from hai_core.seed import seed_all, seed_demo_api_key
from hai_core.settings import Settings
from hai_ontology.meta import Manifest

pytestmark = pytest.mark.integration


def _demo_row(db: Database) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute(text("SELECT * FROM hai_ops.api_keys WHERE key_id = 'demo'")).mappings().one()
        return dict(row)


def _production_settings(settings: Settings) -> Settings:
    return Settings(
        **(
            settings.model_dump()
            | {
                "env": "production",
                "api_key_pepper": "p" * 40,
                "jwt_secret": "j" * 40,
                "cert_signing_key": "c" * 40,
                "webhook_signing_key": "w" * 40,
            }
        )
    )


def test_seed_all_creates_a_hashed_scoped_demo_key_idempotently(
    clean_db: Database, settings: Settings, manifest: Manifest
) -> None:
    pepper = settings.api_key_pepper.get_secret_value()
    with clean_db.transaction("pytest", "hai_admin") as conn:
        seed_all(conn, manifest, Path(settings.connectors_config), settings=settings)
    row = _demo_row(clean_db)
    assert row["name"] == "demo" and row["created_by"] == "hai-db:demo"
    assert row["key_hmac"] == hmac_secret(pepper, DEMO_API_KEY)
    assert row["key_hmac"] != DEMO_API_KEY
    assert frozenset(row["scopes"]) == Scope.PARTNER_DEFAULT
    with clean_db.transaction("pytest", "hai_api") as conn:
        for credential in (DEMO_API_KEY, "hai_demo.demo"):
            principal = verify_api_key(conn, pepper, credential, allow_demo=True)
            assert principal is not None and principal.id == "demo" and principal.name == "demo"
            assert principal.has(Scope.ASSESSMENTS_WRITE)
            assert not principal.has(Scope.ADMIN) and not principal.is_reviewer
            assert verify_api_key(conn, pepper, credential) is None
        assert verify_api_key(conn, pepper, "demo-wrong", allow_demo=True) is None
        assert verify_api_key(conn, pepper, "hai_demo.wrong", allow_demo=True) is None
    before = _demo_row(clean_db)
    assert before["last_used_at"] is not None
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert seed_demo_api_key(conn, settings) == 1
    assert _demo_row(clean_db) == before
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM hai_ops.api_keys WHERE key_id = 'demo'")).scalar_one() == 1


def test_reseeding_uses_current_pepper_without_rotating_the_demo_identity(
    clean_db: Database, settings: Settings
) -> None:
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert seed_demo_api_key(conn, settings) == 1
    before = _demo_row(clean_db)
    changed = settings.model_copy(update={"api_key_pepper": SecretStr("replacement-pepper-" * 3)})
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert seed_demo_api_key(conn, changed) == 1
    after = _demo_row(clean_db)
    assert after["id"] == before["id"] and after["created_at"] == before["created_at"]
    assert after["key_hmac"] != before["key_hmac"]
    with clean_db.transaction("pytest", "hai_api") as conn:
        assert verify_api_key(conn, settings.api_key_pepper.get_secret_value(), DEMO_API_KEY, allow_demo=True) is None
        assert (
            verify_api_key(conn, changed.api_key_pepper.get_secret_value(), DEMO_API_KEY, allow_demo=True) is not None
        )


def test_reseeding_never_reactivates_a_revoked_demo_key(clean_db: Database, settings: Settings) -> None:
    with clean_db.transaction("pytest", "hai_admin") as conn:
        seed_demo_api_key(conn, settings)
        assert revoke_api_key(conn, "demo")
    before = _demo_row(clean_db)
    assert before["revoked_at"] is not None
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert seed_demo_api_key(conn, settings) == 0
    assert _demo_row(clean_db) == before
    with clean_db.transaction("pytest", "hai_api") as conn:
        for credential in (DEMO_API_KEY, "hai_demo.demo"):
            assert verify_api_key(conn, settings.api_key_pepper.get_secret_value(), credential, allow_demo=True) is None


def test_production_seed_skips_demo_even_with_a_stale_development_row(clean_db: Database, settings: Settings) -> None:
    production = _production_settings(settings)
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert seed_demo_api_key(conn, production) == 0
        assert conn.execute(text("SELECT count(*) FROM hai_ops.api_keys WHERE key_id = 'demo'")).scalar_one() == 0
        seed_demo_api_key(conn, production.model_copy(update={"env": "test"}))
    before = _demo_row(clean_db)
    with clean_db.transaction("pytest", "hai_admin") as conn:
        assert seed_demo_api_key(conn, production) == 0
    assert _demo_row(clean_db) == before
    with clean_db.transaction("pytest", "hai_api") as conn:
        for credential in (DEMO_API_KEY, "hai_demo.demo"):
            assert verify_api_key(conn, production.api_key_pepper.get_secret_value(), credential) is None
