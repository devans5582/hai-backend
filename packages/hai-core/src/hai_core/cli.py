"""The ``hai-db`` command line: wait, migrate, status, seed, create-api-key, revoke-api-key, verify-audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hai_core.audit import verify_chain
from hai_core.auth import Scope, create_api_key, list_api_keys, revoke_api_key
from hai_core.db.engine import Database
from hai_core.db.migrate import MigrationError, migrate, migration_status, schema_version, wait_for_database
from hai_core.logging import configure_logging
from hai_core.manifest import get_manifest, role_codes, verify_generated_code
from hai_core.seed import seed_all
from hai_core.settings import get_settings
from hai_ontology.loader import find_repo_root


def _db() -> Database:
    s = get_settings()
    return Database(
        s.database_url, enforce_roles=s.enforce_db_roles, allowed_roles=role_codes(get_manifest(s.ontology_dir))
    )


def _migrations_dir() -> Path:
    s = get_settings()
    p = Path(s.migrations_dir)
    if p.is_absolute():
        return p
    try:
        return find_repo_root() / p
    except Exception:
        return p.resolve()


def cmd_wait(args: argparse.Namespace) -> int:
    ok = wait_for_database(get_settings().database_url, timeout_seconds=args.timeout)
    print("database reachable" if ok else "database not reachable")
    return 0 if ok else 1


def cmd_migrate(_args: argparse.Namespace) -> int:
    db = _db()
    try:
        applied = migrate(db, _migrations_dir())
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for name in applied:
        print(f"applied {name}")
    print(f"{len(applied)} migration(s) applied")
    sv = schema_version(db)
    if sv:
        print(f"schema at ontology {sv[0]}, methodology {sv[1]}, manifest {sv[2][:12]}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    db = _db()
    for st in migration_status(db, _migrations_dir()):
        flag = "applied" if st.applied else "pending"
        if st.applied and not st.checksum_ok:
            flag = "CHECKSUM MISMATCH"
        print(f"{flag:18} {st.filename} {st.applied_at or ''}")
    sv = schema_version(db)
    manifest = get_manifest(get_settings().ontology_dir)
    if sv:
        match = "matches" if sv[2] == manifest.hash else "DIFFERS FROM"
        print(f"schema manifest {sv[2][:12]} {match} the shipped manifest {manifest.hash[:12]}")
    return 0


def cmd_seed(_args: argparse.Namespace) -> int:
    s = get_settings()
    manifest = get_manifest(s.ontology_dir)
    verify_generated_code(manifest)
    cfg = Path(s.connectors_config)
    if not cfg.is_absolute():
        cfg = find_repo_root() / cfg
    db = _db()
    with db.transaction("hai-db", "hai_admin") as conn:
        counts = seed_all(conn, manifest, cfg)
    print(", ".join(f"{k}={v}" for k, v in counts.items() if k != "seeded_at"))
    return 0


def cmd_create_api_key(args: argparse.Namespace) -> int:
    s = get_settings()
    scopes = frozenset(args.scopes.split(",")) if args.scopes else Scope.PARTNER_DEFAULT
    unknown = scopes - Scope.ALL
    if unknown:
        print(f"unknown scopes: {sorted(unknown)}", file=sys.stderr)
        return 1
    db = _db()
    with db.transaction("hai-db", "hai_admin") as conn:
        plaintext, rec = create_api_key(
            conn, s.api_key_pepper.get_secret_value(), name=args.name, scopes=scopes, created_by="hai-db"
        )
    print(f"key id: {rec.key_id}")
    print(f"scopes: {', '.join(rec.scopes)}")
    print(f"api key (shown once): {plaintext}")
    return 0


def cmd_revoke_api_key(args: argparse.Namespace) -> int:
    db = _db()
    with db.transaction("hai-db", "hai_admin") as conn:
        ok = revoke_api_key(conn, args.key_id)
    print("revoked" if ok else "no active key with that id")
    return 0 if ok else 1


def cmd_list_api_keys(_args: argparse.Namespace) -> int:
    db = _db()
    with db.connect() as conn:
        for rec in list_api_keys(conn):
            state = "revoked" if rec.revoked_at else "active"
            print(f"{rec.key_id} {state:8} {rec.name} [{', '.join(rec.scopes)}]")
    return 0


def cmd_verify_audit(_args: argparse.Namespace) -> int:
    db = _db()
    with db.connect() as conn:
        result = verify_chain(conn)
    print(f"{result.message} ({result.events} events)")
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hai-db", description="HAI database tools")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("wait", help="wait for the database")
    s.add_argument("--timeout", type=float, default=60.0)
    s.set_defaults(func=cmd_wait)
    sub.add_parser("migrate", help="apply pending migrations").set_defaults(func=cmd_migrate)
    sub.add_parser("status", help="show migration status").set_defaults(func=cmd_status)
    sub.add_parser("seed", help="seed methodology and connector rows from YAML").set_defaults(func=cmd_seed)
    s = sub.add_parser("create-api-key", help="create an API key (plaintext shown once)")
    s.add_argument("--name", required=True)
    s.add_argument("--scopes", help="comma-separated scopes (default: partner scopes)")
    s.set_defaults(func=cmd_create_api_key)
    s = sub.add_parser("revoke-api-key", help="revoke an API key by key id")
    s.add_argument("key_id")
    s.set_defaults(func=cmd_revoke_api_key)
    sub.add_parser("list-api-keys", help="list API keys").set_defaults(func=cmd_list_api_keys)
    sub.add_parser("verify-audit", help="verify the audit hash chain").set_defaults(func=cmd_verify_audit)
    return p


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    configure_logging(s.log_level, "hai-db", s.log_json)
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
