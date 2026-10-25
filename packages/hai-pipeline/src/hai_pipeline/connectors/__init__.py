"""Connector registry. A connector is enabled by a row in config/connectors.yaml."""

from __future__ import annotations

from hai_pipeline.connectors.academic import AcademicConnector
from hai_pipeline.connectors.base import Connector, ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.connectors.direct_url import DirectUrlConnector
from hai_pipeline.connectors.edgar import EdgarConnector
from hai_pipeline.connectors.github import GitHubConnector
from hai_pipeline.connectors.iso42001 import Iso42001Connector
from hai_pipeline.connectors.news import NewsConnector
from hai_pipeline.connectors.upload import UploadConnector
from hai_pipeline.connectors.wayback import WaybackConnector
from hai_pipeline.connectors.website import WebsiteConnector

CONNECTORS: dict[str, type[Connector]] = {
    "WEBSITE": WebsiteConnector,
    "DIRECT_URL": DirectUrlConnector,
    "EDGAR": EdgarConnector,
    "NEWS": NewsConnector,
    "GITHUB": GitHubConnector,
    "ACADEMIC": AcademicConnector,
    "WAYBACK": WaybackConnector,
    "UPLOAD": UploadConnector,
    "ISO_42001": Iso42001Connector,
}


def build_connector(code: str) -> Connector:
    try:
        return CONNECTORS[code]()
    except KeyError as exc:
        raise KeyError(f"no connector implementation for {code}") from exc


__all__ = [
    "CONNECTORS",
    "Connector",
    "ConnectorContext",
    "ConnectorResult",
    "FetchedDocument",
    "build_connector",
]
