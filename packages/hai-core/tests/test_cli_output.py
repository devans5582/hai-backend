"""Production startup never prints the development login or database credentials."""

from __future__ import annotations

from typing import Literal
from unittest.mock import Mock

import pytest

from hai_core import cli
from hai_core.accounts import DEMO_USER_EMAIL
from hai_core.settings import Settings


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["startup-info"], 0),
        (["login-info"], 0),
        (["connection-info"], 0),
        (["connection-info", "--url-only"], 1),
    ],
)
def test_production_commands_do_not_expose_credentials_or_read_demo_users(
    argv: list[str], expected: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(
        _env_file=None,
        env="production",
        database_url="postgresql://prod_user:private-db-password@private-db:5432/private_db",
        console_base_url="https://console.example",
        public_base_url="https://api.example",
        api_key_pepper="p" * 40,
        jwt_secret="j" * 40,
        cert_signing_key="c" * 40,
        webhook_signing_key="w" * 40,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    database = Mock(side_effect=AssertionError("production must not inspect demo users"))
    monkeypatch.setattr(cli, "_db", database)
    args = cli.build_parser().parse_args(argv)
    assert args.func(args) == expected
    captured = capsys.readouterr()
    output = captured.out + captured.err
    for hidden in (DEMO_USER_EMAIL, "private-db-password", "prod_user", "private_db", "Console Login", "Password"):
        assert hidden not in output
    database.assert_not_called()
    if argv == ["startup-info"]:
        assert "Service URLs" in output and "https://console.example" in output and "https://api.example/docs" in output
    if expected == 1:
        assert "HAI_ENV=production" in captured.err


@pytest.mark.parametrize("environment", ["development", "test"])
def test_development_connection_display_is_still_available(
    environment: Literal["development", "test"], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None, env=environment, database_url="postgresql://hai:hai@localhost:55432/hai")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    args = cli.build_parser().parse_args(["connection-info"])
    assert args.func(args) == 0
    output = capsys.readouterr().out
    assert "Database Connection" in output and "Password" in output
    assert "postgresql://hai:hai@localhost:55432/hai" in output
