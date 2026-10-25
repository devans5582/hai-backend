"""Connector configuration from ``config/connectors.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pages: int = 20
    time_seconds: float = 60.0


class ConnectorConfig(BaseModel):
    """One connector row. Connector-specific keys are kept in ``options``."""

    model_config = ConfigDict(extra="allow")
    code: str
    name: str
    enabled: bool = True
    publisher_type: str = "press"
    access_terms: str | None = None
    limits: Limits = Field(default_factory=Limits)

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: float = 15.0
    max_retries: int = 2
    min_interval_seconds: float = 0.5
    respect_robots: bool = True
    max_document_bytes: int = 3_000_000


class ConnectorsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    defaults: Defaults = Field(default_factory=Defaults)
    connectors: list[ConnectorConfig]

    def get(self, code: str) -> ConnectorConfig:
        for c in self.connectors:
            if c.code == code:
                return c
        raise KeyError(code)

    @property
    def enabled(self) -> list[ConnectorConfig]:
        return [c for c in self.connectors if c.enabled]

    @property
    def codes(self) -> list[str]:
        return [c.code for c in self.connectors]


def load_connectors(path: str | Path) -> ConnectorsFile:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ConnectorsFile.model_validate(data)
