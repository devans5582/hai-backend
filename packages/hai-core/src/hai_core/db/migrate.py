"""Migration runner with a checksum ledger.

Migrations are numbered SQL files in ``db/migrations``. The ledger in
``hai_ops.schema_migrations`` records each file's SHA-256; a file whose checksum
changed after it was applied is refused.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

from hai_core.db.engine import Database, _sqlalchemy_url

LEDGER_DDL = """
CREATE SCHEMA IF NOT EXISTS hai_ops;
CREATE TABLE IF NOT EXISTS hai_ops.schema_migrations (
    filename text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    filename: str
    path: Path
    checksum: str

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class MigrationStatus:
    filename: str
    applied: bool
    checksum_ok: bool
    applied_at: str | None


def discover(migrations_dir: Path) -> list[Migration]:
    out: list[Migration] = []
    for p in sorted(migrations_dir.glob("*.sql")):
        checksum = hashlib.sha256(p.read_bytes()).hexdigest()
        out.append(Migration(p.name, p, checksum))
    return out


def _run_script(conn: Connection, sql: str) -> None:
    """Run a multi-statement SQL script verbatim (no parameter interpolation, so % is safe)."""
    raw = conn.connection.dbapi_connection
    assert raw is not None
    cursor = raw.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def _ledger(conn: Connection) -> dict[str, tuple[str, str]]:
    rows = conn.execute(text("SELECT filename, checksum, applied_at::text FROM hai_ops.schema_migrations")).all()
    return {str(r[0]): (str(r[1]), str(r[2])) for r in rows}


def migrate(db: Database, migrations_dir: Path, actor: str = "hai-db") -> list[str]:
    """Apply pending migrations in order. Returns the filenames applied."""
    with db.engine.begin() as conn:
        _run_script(conn, LEDGER_DDL)
    applied: list[str] = []
    for m in discover(migrations_dir):
        with db.transaction(actor) as conn:
            ledger = _ledger(conn)
            if m.filename in ledger:
                recorded, _ = ledger[m.filename]
                if recorded != m.checksum:
                    raise MigrationError(
                        f"{m.filename} was applied with checksum {recorded[:12]} but the file now hashes to "
                        f"{m.checksum[:12]}; migrations are never edited after they are applied"
                    )
                continue
            _run_script(conn, m.sql)
            conn.execute(
                text("INSERT INTO hai_ops.schema_migrations (filename, checksum) VALUES (:f, :c)"),
                {"f": m.filename, "c": m.checksum},
            )
            applied.append(m.filename)
    return applied


def migration_status(db: Database, migrations_dir: Path) -> list[MigrationStatus]:
    with db.engine.begin() as conn:
        _run_script(conn, LEDGER_DDL)
        ledger = _ledger(conn)
    out: list[MigrationStatus] = []
    for m in discover(migrations_dir):
        rec = ledger.get(m.filename)
        out.append(
            MigrationStatus(m.filename, rec is not None, rec is None or rec[0] == m.checksum, rec[1] if rec else None)
        )
    for name in sorted(set(ledger) - {m.filename for m in discover(migrations_dir)}):
        out.append(MigrationStatus(name, True, False, ledger[name][1]))
    return out


def schema_version(db: Database) -> tuple[str, str, str] | None:
    """(ontology_version, methodology_version, manifest_hash) recorded by the baseline, if applied."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT ontology_version, methodology_version, manifest_hash FROM hai.schema_versions")
            ).first()
    except DBAPIError:
        return None
    if row is None:
        return None
    return str(row[0]), str(row[1]), str(row[2])


def wait_for_database(url: str, timeout_seconds: float = 60.0, interval: float = 1.0) -> bool:
    engine = create_engine(_sqlalchemy_url(url), pool_pre_ping=True)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return True
            except DBAPIError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(interval)
    finally:
        engine.dispose()
