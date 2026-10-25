"""ACADEMIC: Semantic Scholar papers that demonstrably concern the organization."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.entity_resolution import normalise_name
from hai_pipeline.extraction import parse_date
from hai_pipeline.http import Budget, Fetcher
from hai_pipeline.urls import registrable_domain


def paper_is_about(paper: dict[str, Any], organization_name: str, organization_domain: str, aliases: list[str]) -> bool:
    """Whole-word organization name (or alias) in the title, abstract, venue or a requested author
    affiliation; or the verified domain in the paper URL. Topic overlap alone is not enough."""
    names = [normalise_name(organization_name), *(normalise_name(a) for a in aliases)]
    names = [n for n in names if len(n) >= 3]
    fields = [str(paper.get("title") or ""), str(paper.get("abstract") or ""), str(paper.get("venue") or "")]
    for author in paper.get("authors") or []:
        for aff in author.get("affiliations") or []:
            fields.append(str(aff if isinstance(aff, str) else aff.get("name", "")))
    haystack = normalise_name(" ".join(fields))
    if any(re.search(rf"\b{re.escape(n)}\b", haystack) for n in names):
        return True
    url = str(paper.get("url") or "")
    return (
        bool(organization_domain) and registrable_domain(url) == registrable_domain(organization_domain)
        if url
        else False
    )


class AcademicConnector:
    code = "ACADEMIC"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        api = str(config.opt("api_url"))
        query = str(config.opt("query", "{name} responsible AI governance")).replace("{name}", ctx.organization_name)
        fields = str(config.opt("fields", "title,year,authors,abstract,venue,externalIds,url,publicationDate"))
        url = f"{api}?query={quote(query)}&limit=10&fields={quote(fields)}"
        headers = {}
        token = ctx.api_tokens.get("SEMANTIC_SCHOLAR")
        if token:
            headers["x-api-key"] = token
        result.attempted_urls.append(url)
        fetched, data = await fetcher.get_json(url, budget=budget, headers=headers or None)
        if not fetched.ok or not isinstance(data, dict):
            result.outcome = fetched.outcome if fetched.outcome != "succeeded" else "failed"
            result.error_code = fetched.error_code or "bad_json"
            return result
        papers = [p for p in data.get("data", []) if isinstance(p, dict)]
        accepted = 0
        for paper in papers:
            if accepted >= int(config.opt("max_papers", 3)):
                break
            if not paper_is_about(paper, ctx.organization_name, ctx.organization_domain, ctx.aliases):
                continue
            title = str(paper.get("title") or "")
            abstract = str(paper.get("abstract") or "")
            if not abstract:
                continue
            doi = (paper.get("externalIds") or {}).get("DOI")
            link = f"https://doi.org/{doi}" if doi else str(paper.get("url") or url)
            authors = ", ".join(str(a.get("name", "")) for a in (paper.get("authors") or [])[:6])
            body = f"{title}\n\n{authors}\n\n{abstract}"
            result.documents.append(
                FetchedDocument(
                    url=link,
                    content=body.encode("utf-8"),
                    content_type="text/plain; charset=utf-8",
                    publisher_hint=str(paper.get("venue") or "Semantic Scholar"),
                    publisher_type_hint=config.publisher_type,
                    published_at=parse_date(str(paper.get("publicationDate") or ""))
                    or (parse_date(f"{paper.get('year')}-01-01") if paper.get("year") else None),
                    title=title,
                )
            )
            accepted += 1
        result.notes.append(f"{len(papers)} papers returned, {accepted} about the organization")
        return result
