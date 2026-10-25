"""WAYBACK: fetch the archived page itself, not merely its existence."""

from __future__ import annotations

from datetime import date
from urllib.parse import quote, urlsplit

from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher
from hai_pipeline.urls import canonical_url


class WaybackConnector:
    code = "WAYBACK"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        availability = str(config.opt("availability_url"))
        snapshot_tpl = str(config.opt("snapshot_url"))
        min_year = int(config.opt("min_year", 2015))
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(canonical_url(ctx.website_url)))
        paths = [str(p) for p in config.opt("paths", [])][: int(config.opt("max_paths", 5))]
        outcomes: list[str] = []
        for path in paths:
            target = origin + path
            url = availability.replace("{url}", quote(target, safe=""))
            result.attempted_urls.append(url)
            try:
                fetched, data = await fetcher.get_json(url, budget=budget)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            outcomes.append(fetched.outcome)
            if not isinstance(data, dict):
                continue
            closest = (data.get("archived_snapshots") or {}).get("closest") or {}
            ts = str(closest.get("timestamp") or "")
            if not closest.get("available") or str(closest.get("status")) != "200" or len(ts) < 8:
                continue
            year = int(ts[:4])
            if year < min_year:
                result.notes.append(f"snapshot of {path} from {year} is older than {min_year}; skipped")
                continue
            snap_url = snapshot_tpl.replace("{timestamp}", ts).replace("{url}", target)
            try:
                page = await fetcher.fetch(snap_url, budget=budget)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            result.attempted_urls.append(snap_url)
            outcomes.append(page.outcome)
            if not page.ok or not page.content:
                continue
            result.documents.append(
                FetchedDocument(
                    url=page.final_url or snap_url,
                    content=page.content,
                    content_type=page.content_type or "text/html",
                    publisher_hint="Internet Archive",
                    publisher_type_hint=config.publisher_type,
                    published_at=date(year, int(ts[4:6]), int(ts[6:8])),
                    note=f"archived copy of {target} captured {ts[:8]}",
                    archived_original_url=target,
                )
            )
        if outcomes and all(o != "succeeded" for o in outcomes):
            result.outcome = outcomes[0]
            result.error_code = "archive_" + outcomes[0]
        result.notes.append(f"{len(paths)} paths checked, {len(result.documents)} archived pages fetched")
        return result
