"""WEBSITE: the organization's own site. Seed governance paths plus links discovered on the homepage."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from hai_ontology.terms import compile_term
from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument, summarise
from hai_pipeline.extraction import extract_html
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher, FetchResult
from hai_pipeline.urls import canonical_url, same_registrable_domain


class WebsiteConnector:
    code = "WEBSITE"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        fetches: list[FetchResult] = []
        home_url = canonical_url(ctx.website_url)
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(home_url))
        skip = [str(p) for p in config.opt("skip_paths", [])]
        min_chars = int(config.opt("min_text_chars", 300))
        keywords = [str(k) for k in config.opt("link_keywords", [])]
        patterns = [compile_term(k) for k in keywords]
        max_discovered = int(config.opt("max_discovered_links", 10))

        home = await fetcher.fetch(home_url, budget=budget)
        fetches.append(home)
        result.attempted_urls.append(home_url)
        candidates: list[str] = []
        if home.ok:
            result.documents.append(self._doc(home, config))
            doc = extract_html(home.content, base_url=home.final_url)
            discovered = 0
            for href, anchor in doc.links:
                if discovered >= max_discovered:
                    break
                absolute = canonical_url(urljoin(home.final_url, href))
                if not same_registrable_domain(absolute, home_url):
                    continue
                path = urlsplit(absolute).path.lower()
                probe = f"{anchor} {path.replace('-', ' ').replace('/', ' ')}"
                if any(p.search(probe) for p in patterns) and absolute not in candidates and absolute != home_url:
                    candidates.append(absolute)
                    discovered += 1
            result.notes.append(f"homepage ok, {discovered} governance links discovered")
        else:
            result.notes.append(f"homepage {home.outcome}: {home.error_code}")
        for path in config.opt("seed_paths", []):
            url = canonical_url(origin + str(path))
            if url not in candidates and url != home_url:
                candidates.append(url)
        for url in candidates:
            path = urlsplit(url).path.lower()
            if any(path.startswith(s) for s in skip):
                continue
            try:
                fetched = await fetcher.fetch(url, budget=budget)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            fetches.append(fetched)
            result.attempted_urls.append(url)
            if fetched.ok and len(fetched.content) >= min_chars and _is_distinct_page(fetched, home):
                result.documents.append(self._doc(fetched, config))
        result.outcome = summarise(list(fetches))
        if result.outcome != "succeeded":
            result.error_code = next((f.error_code for f in fetches if f.outcome == result.outcome), None)
        return result

    @staticmethod
    def _doc(fetched: FetchResult, config: ConnectorConfig) -> FetchedDocument:
        return FetchedDocument(
            url=fetched.final_url or fetched.url,
            content=fetched.content,
            content_type=fetched.content_type or "text/html",
            publisher_type_hint=config.publisher_type,
        )


def _is_distinct_page(page: FetchResult, home: FetchResult) -> bool:
    """A seed path that silently redirects to the homepage is not new evidence."""
    if not home.ok:
        return True
    if canonical_url(page.final_url) == canonical_url(home.final_url):
        return False
    return page.content != home.content
