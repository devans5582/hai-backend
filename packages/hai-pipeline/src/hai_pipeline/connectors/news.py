"""NEWS: Google News RSS with real publication dates and publishers; article pages fetched when allowed."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher
from hai_pipeline.urls import hostname

MIN_ARTICLE_BYTES = 1500


@dataclass(frozen=True)
class RssItem:
    title: str
    link: str
    published_at: date | None
    source_name: str | None
    source_url: str | None
    description: str


def parse_rss(xml_text: str) -> list[RssItem]:
    items: list[RssItem] = []
    try:
        root = ET.fromstring(xml_text)  # noqa: S314 - RSS text already fetched over HTTPS
    except ET.ParseError:
        return items
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        published: date | None = None
        if pub:
            try:
                published = parsedate_to_datetime(pub.strip()).date()
            except (TypeError, ValueError):
                published = None
        source = item.find("source")
        source_name = (source.text or "").strip() if source is not None and source.text else None
        source_url = source.get("url") if source is not None else None
        description = (item.findtext("description") or "").strip()
        if title and link:
            items.append(RssItem(title, link, published, source_name, source_url, description))
    return items


class NewsConnector:
    code = "NEWS"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        rss_template = str(config.opt("rss_url"))
        max_items = int(config.opt("max_items", 8))
        fetch_articles = bool(config.opt("fetch_articles", True))
        items: list[RssItem] = []
        feed_outcomes: list[str] = []
        for template in config.opt("queries", ['"{name}"']):
            query = str(template).replace("{name}", ctx.organization_name)
            url = rss_template.replace("{query}", quote(query))
            result.attempted_urls.append(url)
            try:
                feed = await fetcher.fetch(url, budget=budget)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            feed_outcomes.append(feed.outcome)
            if feed.ok:
                items.extend(parse_rss(feed.text))
        if not items and feed_outcomes and all(o != "succeeded" for o in feed_outcomes):
            result.outcome = feed_outcomes[0]
            result.error_code = "feed_" + feed_outcomes[0]
            return result
        seen: set[str] = set()
        count = 0
        for item in items:
            if count >= max_items:
                break
            if item.link in seen:
                continue
            seen.add(item.link)
            publisher_name = (
                item.source_name or (hostname(item.source_url) if item.source_url else None) or hostname(item.link)
            )
            doc: FetchedDocument | None = None
            if fetch_articles:
                try:
                    page = await fetcher.fetch(item.link, budget=budget)
                except BudgetExhausted as exc:
                    result.notes.append(str(exc))
                    break
                result.attempted_urls.append(item.link)
                if page.ok and len(page.content) >= MIN_ARTICLE_BYTES and "html" in page.content_type:
                    doc = FetchedDocument(
                        url=page.final_url or item.link,
                        content=page.content,
                        content_type=page.content_type,
                        publisher_hint=publisher_name,
                        publisher_type_hint=config.publisher_type,
                        published_at=item.published_at,
                        title=item.title,
                    )
            if doc is None:
                body = f"{item.title}\n\n{item.description}".strip()
                doc = FetchedDocument(
                    url=item.source_url or item.link
                    if item.source_url and item.link.startswith("https://news.google.com")
                    else item.link,
                    content=body.encode("utf-8"),
                    content_type="text/plain; charset=utf-8",
                    publisher_hint=publisher_name,
                    publisher_type_hint=config.publisher_type,
                    published_at=item.published_at,
                    title=item.title,
                    note="RSS item (article body not retrieved)",
                )
            result.documents.append(doc)
            count += 1
        result.notes.append(f"{len(items)} feed items, {count} documents")
        return result
