"""ISO_42001: certificate registry lookup.

There is no universal public registry API, so the registry URL is configuration.
The configured endpoint must return JSON of the form
``{"certificates": [{"standard", "certificate_number", "holder", "valid_until", "url", "body"}]}``.
Without a registry URL the run is recorded as succeeded with zero items.
"""

from __future__ import annotations

from urllib.parse import quote

from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.extraction import parse_date
from hai_pipeline.http import Budget, Fetcher


class Iso42001Connector:
    code = "ISO_42001"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        registry = config.opt("registry_url")
        if not registry:
            result.notes.append("no certificate registry configured; nothing fetched")
            return result
        url = (
            str(registry)
            .replace("{name}", quote(ctx.organization_name))
            .replace("{domain}", quote(ctx.organization_domain))
        )
        result.attempted_urls.append(url)
        fetched, data = await fetcher.get_json(url, budget=budget)
        if not fetched.ok or not isinstance(data, dict):
            result.outcome = fetched.outcome if fetched.outcome != "succeeded" else "failed"
            result.error_code = fetched.error_code or "bad_json"
            return result
        for cert in data.get("certificates", []):
            if not isinstance(cert, dict):
                continue
            holder = str(cert.get("holder") or "")
            body = (
                f"{cert.get('standard', 'ISO/IEC 42001')} certificate {cert.get('certificate_number', '')} "
                f"held by {holder}, issued by {cert.get('body', 'an accredited certification body')}, "
                f"valid until {cert.get('valid_until', 'unknown')}."
            )
            result.documents.append(
                FetchedDocument(
                    url=str(cert.get("url") or url),
                    content=body.encode("utf-8"),
                    content_type="text/plain; charset=utf-8",
                    publisher_hint=str(cert.get("body") or "certificate registry"),
                    publisher_type_hint=config.publisher_type,
                    published_at=parse_date(str(cert.get("issued_at") or "")),
                    certificate_valid_until=parse_date(str(cert.get("valid_until") or "")),
                    title=f"{cert.get('standard', 'ISO/IEC 42001')} certificate for {holder}",
                )
            )
        result.notes.append(f"{len(result.documents)} certificates")
        return result
