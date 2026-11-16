"""WEBSITE: bounded discovery of governance pages on the organization's own site."""

from __future__ import annotations

from urllib.parse import unquote, urljoin, urlsplit

from hai_core.generated.enums import ConnectorRunOutcome
from hai_ontology.terms import compile_term
from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument, summarise
from hai_pipeline.extraction import extract, extract_html
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher, FetchResult
from hai_pipeline.spans import MIN_SPAN_CHARS
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
        priority_patterns = [compile_term(str(k)) for k in config.opt("priority_link_keywords", [])]
        max_discovered = int(config.opt("max_discovered_links", 10))
        max_depth = int(config.opt("max_discovery_depth", 2))
        candidates: dict[str, tuple[int, int, int]] = {}
        visited = {home_url}
        discovered_urls: set[str] = set()
        sequence = 0

        def discover(page: FetchResult, depth: int) -> None:
            nonlocal sequence
            if depth >= max_depth or not same_registrable_domain(page.final_url, home_url):
                return
            if "html" not in page.content_type.lower():
                return
            doc = extract_html(page.content, base_url=page.final_url)
            links: dict[str, int] = {}
            for href, anchor in doc.links:
                try:
                    target = urljoin(page.final_url, href)
                    if urlsplit(target).scheme.lower() not in ("http", "https"):
                        continue
                    absolute = canonical_url(target)
                except ValueError:
                    # One malformed anchor must not discard a collected page.
                    continue
                if not same_registrable_domain(absolute, home_url) or absolute in visited:
                    continue
                path = urlsplit(absolute).path.lower()
                if any(path.startswith(s) for s in skip):
                    continue
                probe = f"{anchor} {unquote(path).replace('-', ' ').replace('_', ' ').replace('/', ' ')}"
                if any(p.search(probe) for p in patterns):
                    links[absolute] = 0 if any(p.search(probe) for p in priority_patterns) else 1
            # Rank real links before applying the discovery limit. Navigation
            # order must not hide an AI policy behind generic footer links.
            for absolute, priority in sorted(links.items(), key=lambda item: item[1])[:max_discovered]:
                discovered_urls.add(absolute)
                current = candidates.get(absolute)
                if current is None or priority < current[0]:
                    candidates[absolute] = (priority, depth + 1, sequence)
                    sequence += 1

        home = await fetcher.fetch(home_url, budget=budget)
        fetches.append(home)
        result.attempted_urls.append(home_url)
        if home.ok:
            if _has_readable_content(home):
                result.documents.append(self._doc(home, config))
            visited.add(canonical_url(home.final_url))
            if same_registrable_domain(home.final_url, home_url):
                origin = "{0.scheme}://{0.netloc}".format(urlsplit(home.final_url))
            discover(home, 0)
        else:
            result.notes.append(f"homepage {home.outcome}: {home.error_code}")
        for path in config.opt("seed_paths", []):
            url = canonical_url(origin + str(path))
            if url not in candidates and url not in visited:
                candidates[url] = (2, 1, sequence)
                sequence += 1
        while candidates:
            url = min(candidates, key=lambda candidate: candidates[candidate])
            _, depth, _ = candidates.pop(url)
            if url in visited:
                continue
            path = urlsplit(url).path.lower()
            if any(path.startswith(s) for s in skip):
                continue
            try:
                fetched = await fetcher.fetch(url, budget=budget)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            fetches.append(fetched)
            visited.add(url)
            result.attempted_urls.append(url)
            if fetched.ok:
                final = canonical_url(fetched.final_url)
                if final in visited and final != url:
                    continue
                visited.add(final)
                if _has_readable_content(fetched, min_chars=min_chars) and _is_distinct_page(fetched, home):
                    result.documents.append(self._doc(fetched, config))
                discover(fetched, depth)
        result.notes.append(f"{len(discovered_urls)} governance links discovered across up to {max_depth} link levels")
        result.outcome = summarise(list(fetches))
        if result.outcome == ConnectorRunOutcome.SUCCEEDED.value and not result.documents:
            result.outcome = ConnectorRunOutcome.FAILED.value
            result.error_code = "empty_content"
            result.notes.append("HTTP responses contained no readable evidence text (empty page or JavaScript shell)")
        if result.outcome != "succeeded":
            result.error_code = result.error_code or next(
                (f.error_code for f in fetches if f.outcome == result.outcome), None
            )
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


def _has_readable_content(page: FetchResult, *, min_chars: int = MIN_SPAN_CHARS) -> bool:
    """A successful HTTP fetch is distinct from obtaining text that can form evidence spans."""
    try:
        doc = extract(page.content, page.content_type, base_url=page.final_url)
    except Exception:
        return False
    return len(doc.text.strip()) >= max(MIN_SPAN_CHARS, min_chars)
