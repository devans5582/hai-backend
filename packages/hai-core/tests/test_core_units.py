"""Unit tests for hai-core: settings, freshness, blob store, queue backoff, auth, audit hashing."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hai_core.audit import GENESIS_HASH, event_hash
from hai_core.auth import Scope, hmac_secret, mint_jwt, new_plaintext_key, parse_plaintext_key, verify_jwt
from hai_core.blobstore import BlobStore
from hai_core.errors import IntegrityViolationError, NotFoundError, UnauthorizedError
from hai_core.freshness import certificate_active, decay, decay_multiplier, freshness_label, is_stale, months_between
from hai_core.queue import backoff_seconds
from hai_core.settings import Settings
from hai_ontology.meta import Manifest

STRONG = "x" * 40


def test_production_refuses_unsafe_settings() -> None:
    with pytest.raises(ValidationError, match="development secret"):
        Settings(env="production")
    with pytest.raises(ValidationError, match="HAI_AUTH_DISABLED"):
        Settings(
            env="production",
            auth_disabled=True,
            api_key_pepper=STRONG,
            jwt_secret=STRONG,
            cert_signing_key=STRONG,
            webhook_signing_key=STRONG,
        )
    with pytest.raises(ValidationError, match="shorter than 32"):
        Settings(
            env="production",
            api_key_pepper="short",
            jwt_secret=STRONG,
            cert_signing_key=STRONG,
            webhook_signing_key=STRONG,
        )
    ok = Settings(
        env="production", api_key_pepper=STRONG, jwt_secret=STRONG, cert_signing_key=STRONG, webhook_signing_key=STRONG
    )
    assert ok.is_production
    assert Settings(env="development").auth_disabled is False


def test_sqlalchemy_url_uses_psycopg() -> None:
    assert Settings(database_url="postgresql://u:p@h/db").sqlalchemy_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="postgres://u:p@h/db").sqlalchemy_url == "postgresql+psycopg://u:p@h/db"


def test_freshness_decay_and_certificates(manifest: Manifest) -> None:
    md = manifest.methodology
    as_of = date(2026, 10, 24)
    assert decay(12, 0.3, 0) == 1.0
    assert decay(12, 0.3, 12) == pytest.approx(0.5, abs=0.001)
    assert decay(12, 0.3, 120) == 0.3  # floor
    fresh = decay_multiplier(md, "press", date(2026, 10, 1), as_of)
    old = decay_multiplier(md, "press", date(2025, 10, 1), as_of)
    assert fresh > old >= 0.1
    assert decay_multiplier(md, "standards_registry", None, as_of, certificate_valid_until=date(2027, 1, 1)) == 1.0
    expired = decay_multiplier(md, "standards_registry", None, as_of, certificate_valid_until=date(2024, 1, 1))
    assert 0.6 <= expired < 1.0
    assert decay_multiplier(md, "press", date(2026, 1, 1), as_of, contradicting_press=True) > decay_multiplier(
        md, "press", date(2026, 1, 1), as_of
    )
    assert decay_multiplier(md, "unknown_type", date(2026, 1, 1), as_of) == decay(
        18, 0.3, months_between(date(2026, 1, 1), as_of)
    )


def test_undated_evidence_is_never_stale(manifest: Manifest) -> None:
    as_of = datetime(2026, 10, 24, tzinfo=UTC)
    assert is_stale(None, as_of, 24) is False
    assert is_stale(date(2023, 1, 1), as_of, 24) is True
    assert is_stale(date(2026, 1, 1), as_of, 24) is False
    undated = decay_multiplier(manifest.methodology, "org_disclosure", None, as_of)
    assert undated == decay(12, 0.3, 18)
    assert undated < 1.0


def test_certificate_and_labels(manifest: Manifest) -> None:
    today = date(2026, 10, 24)
    assert certificate_active(today + timedelta(days=1), today)
    assert not certificate_active(today - timedelta(days=1), today)
    assert not certificate_active(None, today)
    assert freshness_label(manifest.methodology, 85) == "Current"
    assert freshness_label(manifest.methodology, 65) == "Mostly current"
    assert freshness_label(manifest.methodology, 45) == "Mixed age"
    assert freshness_label(manifest.methodology, 10) == "Largely stale"
    assert freshness_label(manifest.methodology, None) == "Not assessed"


def test_blob_store_is_content_addressed(tmp_path: Path) -> None:
    store = BlobStore(f"file://{tmp_path}")
    ref = store.put(b"hello evidence")
    again = store.put(b"hello evidence")
    assert ref == again
    assert ref.uri.endswith(ref.sha256) and ref.size == 14
    assert store.get(ref.uri) == b"hello evidence"
    assert store.get(ref.sha256) == b"hello evidence"
    assert store.exists(ref.uri)
    with pytest.raises(NotFoundError):
        store.get("0" * 64)
    with pytest.raises(NotFoundError):
        store.get("file:///not/a/blob")


def test_blob_tampering_is_detected(tmp_path: Path) -> None:
    store = BlobStore(f"file://{tmp_path}")
    ref = store.put(b"original")
    path = Path(ref.uri[len("file://") :])
    path.write_bytes(b"altered!")
    with pytest.raises(IntegrityViolationError, match="tampered"):
        store.get(ref.uri)


def test_backoff_is_exponential_and_capped() -> None:
    assert [backoff_seconds(n) for n in (1, 2, 3, 4)] == [5.0, 10.0, 20.0, 40.0]
    assert backoff_seconds(20) == 600.0


def test_api_key_format_and_hmac() -> None:
    key_id, secret, plaintext = new_plaintext_key()
    assert parse_plaintext_key(plaintext) == (key_id, secret)
    assert parse_plaintext_key("nope") is None
    assert parse_plaintext_key("hai_abc") is None
    assert hmac_secret("pepper", secret) != hmac_secret("other", secret)
    assert hmac_secret("pepper", secret) == hmac_secret("pepper", secret)


def test_jwt_round_trip_and_rejections() -> None:
    token = mint_jwt("s" * 40, subject="rev-1", name="Reviewer One", role="reviewer", scopes=Scope.REVIEWER_DEFAULT)
    principal = verify_jwt("s" * 40, token)
    assert principal.kind == "reviewer" and principal.id == "rev-1" and principal.is_reviewer
    assert principal.has(Scope.CERTIFICATION_SIGN) and not principal.has(Scope.ADMIN)
    admin = verify_jwt("s" * 40, mint_jwt("s" * 40, subject="adm", name="A", role="admin", scopes=frozenset()))
    assert admin.has(Scope.ADMIN) and admin.has(Scope.CERTIFICATION_SIGN)
    with pytest.raises(UnauthorizedError):
        verify_jwt("wrong" * 10, token)
    expired = mint_jwt(
        "s" * 40,
        subject="x",
        name="x",
        role="reviewer",
        scopes=frozenset(),
        ttl_minutes=1,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    with pytest.raises(UnauthorizedError):
        verify_jwt("s" * 40, expired)


def test_audit_hash_is_canonical_and_chained() -> None:
    payload = {"seq": 1, "actor": "a", "action": "insert", "after": {"b": 1, "a": 2}}
    h1 = event_hash(GENESIS_HASH, payload)
    h2 = event_hash(GENESIS_HASH, {"after": {"a": 2, "b": 1}, "action": "insert", "actor": "a", "seq": 1})
    assert h1 == h2 and len(h1) == 64
    assert event_hash(h1, payload) != h1
