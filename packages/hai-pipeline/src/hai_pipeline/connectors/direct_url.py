"""DIRECT_URL: governance pages supplied by the requester. Fetched once each, any host."""

from __future__ import annotations

from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument, summarise
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher, FetchResult
from hai_pipeline.urls import canonical_url


class DirectUrlConnector:
    code = "DIRECT_URL"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        if not ctx.direct_urls:
            result.notes.append("no direct URLs supplied")
            return result
        fetches: list[FetchResult] = []
        seen: set[str] = set()
        for raw in ctx.direct_urls:
            url = canonical_url(raw)
            if url in seen:
                continue
            seen.add(url)
            try:
                fetched = await fetcher.fetch(url, budget=budget)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            fetches.append(fetched)
            result.attempted_urls.append(url)
            if fetched.ok and fetched.content:
                result.documents.append(
                    FetchedDocument(
                        url=fetched.final_url or url,
                        content=fetched.content,
                        content_type=fetched.content_type or "text/html",
                        publisher_type_hint=config.publisher_type,
                        note="supplied by the requester",
                    )
                )
        result.outcome = summarise(list(fetches))
        if result.outcome != "succeeded":
            result.error_code = next((f.error_code for f in fetches if f.outcome == result.outcome), None)
        return result
