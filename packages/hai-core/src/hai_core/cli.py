"""The ``hai-db`` command line: wait, migrate, status, seed, create-owner, create-api-key, revoke-api-key,
verify-audit."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import URL, make_url

from hai_core.accounts import (
    DEMO_USER_EMAIL,
    DEMO_USER_PASSWORD,
    bootstrap_owner,
    find_user_by_email,
    is_bootstrapped,
    verify_password,
)
from hai_core.audit import verify_chain
from hai_core.auth import DEMO_API_KEY, Scope, create_api_key, list_api_keys, revoke_api_key
from hai_core.db.engine import Database
from hai_core.db.migrate import MigrationError, migrate, migration_status, schema_version, wait_for_database
from hai_core.logging import configure_logging
from hai_core.manifest import get_manifest, role_codes, verify_generated_code
from hai_core.seed import seed_all
from hai_core.settings import Settings, get_settings
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


def _print_info(blocks: list[tuple[str, list[tuple[str, str]]]]) -> None:
    """Use the same aligned, plain-text layout in terminals and captured logs."""
    label_width = max(len(label) for _, rows in blocks for label, _ in rows)
    content = [(title, [f"{label:<{label_width}} : {value}" for label, value in rows]) for title, rows in blocks]
    width = max(64, *(len(line) for title, rows in content for line in [title, *rows]))
    border = "+-" + "-" * width + "-+"
    for title, rows in content:
        print()
        print(border)
        print(f"| {title:<{width}} |")
        print(border)
        for line in rows:
            print(f"| {line:<{width}} |")
        print(border)
    print()


def _connection_rows(url: URL) -> list[tuple[str, str]]:
    return [
        ("Host", url.host or "(local socket)"),
        ("Port", str(url.port or 5432)),
        ("Database", url.database or "(default)"),
        ("Username", url.username or "(current user)"),
        ("Password", url.password if url.password is not None else "(not set)"),
        ("Connection URL", url.render_as_string(hide_password=False)),
    ]


def _login_rows(settings: Settings, console_url: str) -> list[tuple[str, str]]:
    rows = [("Console URL", console_url)]
    if settings.is_production:
        return [*rows, ("Account", "Use your existing account or Set up the platform on a new installation.")]
    db = _db()
    try:
        with db.connect() as conn:
            user = find_user_by_email(conn, DEMO_USER_EMAIL)
            ready = is_bootstrapped(conn)
    finally:
        db.dispose()
    if (
        user is not None
        and user.status == "active"
        and (user.locked_until is None or user.locked_until <= datetime.now(UTC))
        and verify_password(DEMO_USER_PASSWORD, user.password_hash)
    ):
        rows.extend(
            [
                ("Email", DEMO_USER_EMAIL),
                ("Password", DEMO_USER_PASSWORD),
                ("Role", user.role.replace("_", " ").title()),
            ]
        )
    elif not ready:
        rows.append(("Next step", "Choose Set up the platform to create your first owner account."))
    else:
        rows.append(("Account", "Use your existing account; the development demo login is unavailable."))
    return rows


def cmd_connection_info(args: argparse.Namespace) -> int:
    """Print the configured login without connecting; local dev can supply its default port."""
    settings = get_settings()
    if settings.is_production:
        if args.url_only:
            print("make dev is unavailable with HAI_ENV=production; use make up for production.", file=sys.stderr)
            return 1
        return 0
    url = make_url(settings.database_url)
    if args.dev_port is not None and "database_url" not in settings.model_fields_set:
        url = url.set(port=args.dev_port)
    if args.url_only:
        print(url.render_as_string(hide_password=False))
        return 0
    _print_info([("Database Connection", _connection_rows(url))])
    return 0


def cmd_login_info(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.is_production:
        return 0
    console_url = getattr(args, "console_url", None) or settings.console_base_url
    _print_info([("Console Login", _login_rows(settings, console_url))])
    return 0


def cmd_startup_info(args: argparse.Namespace) -> int:
    settings = get_settings()
    console_url = args.console_url or settings.console_base_url
    api_url = (args.api_url or settings.public_base_url).rstrip("/")
    if settings.is_production:
        _print_info([("Service URLs", [("Console", console_url), ("API", api_url), ("API Docs", f"{api_url}/docs")])])
        return 0
    url = make_url(settings.database_url)
    if args.database_host is not None:
        url = url.set(host=args.database_host)
    if args.database_port is not None:
        url = url.set(port=args.database_port)
    _print_info(
        [
            ("Console Login", _login_rows(settings, console_url)),
            ("Service URLs", [("API", api_url), ("API Docs", f"{api_url}/docs")]),
            ("Database Connection", _connection_rows(url)),
        ]
    )
    return 0


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
        counts = seed_all(conn, manifest, cfg, settings=s)
    print(", ".join(f"{k}={v}" for k, v in counts.items() if k != "seeded_at"))
    if counts.get("demo_api_keys"):
        print(f"development API key: {DEMO_API_KEY} (sign-in page > Use an API key or reviewer token instead)")
    if "demo_users" in counts and not s.is_production:
        print(f"development console sign-in: {DEMO_USER_EMAIL} / {DEMO_USER_PASSWORD} (platform owner)")
    return 0


def cmd_create_owner(args: argparse.Namespace) -> int:
    """Create the platform account and its first owner without the console (first run only)."""
    password = os.environ.get("HAI_OWNER_PASSWORD") or secrets.token_urlsafe(18)
    db = _db()
    with db.transaction("hai-db", "hai_api") as conn:
        if is_bootstrapped(conn):
            print("the platform already has users; invite more from the console Team page", file=sys.stderr)
            return 1
        user = bootstrap_owner(
            conn, email=args.email, name=args.name, password=password, platform_name=args.platform, created_by="hai-db"
        )
    print(f"owner: {user.email} ({user.name})")
    if os.environ.get("HAI_OWNER_PASSWORD"):
        print("password: from HAI_OWNER_PASSWORD")
    else:
        print(f"password (shown once): {password}")
    print("sign in at the console and change it under Settings > Security")
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
    s = sub.add_parser("connection-info", help="show the configured database login without connecting")
    s.add_argument("--dev-port", type=int, help="default local port when HAI_DATABASE_URL is not configured")
    s.add_argument("--url-only", action="store_true", help="print only the connection URL")
    s.set_defaults(func=cmd_connection_info)
    s = sub.add_parser("login-info", help="show console sign-in details")
    s.add_argument("--console-url", help="console URL exposed by the selected startup command")
    s.set_defaults(func=cmd_login_info)
    s = sub.add_parser("startup-info", help="show formatted console login, service URLs and database connection")
    s.add_argument("--console-url")
    s.add_argument("--api-url")
    s.add_argument("--database-host", help="database host exposed outside Docker")
    s.add_argument("--database-port", type=int, help="database port exposed outside Docker")
    s.set_defaults(func=cmd_startup_info)
    s = sub.add_parser("wait", help="wait for the database")
    s.add_argument("--timeout", type=float, default=60.0)
    s.set_defaults(func=cmd_wait)
    sub.add_parser("migrate", help="apply pending migrations").set_defaults(func=cmd_migrate)
    sub.add_parser("status", help="show migration status").set_defaults(func=cmd_status)
    sub.add_parser("seed", help="seed methodology, connectors and development demo access").set_defaults(func=cmd_seed)
    s = sub.add_parser(
        "create-owner", help="create the first platform owner (password from HAI_OWNER_PASSWORD or generated)"
    )
    s.add_argument("--email", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--platform", default="Humaital", help="platform account name")
    s.set_defaults(func=cmd_create_owner)
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
