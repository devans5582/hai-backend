"""WEBSITE: bounded discovery of governance pages on the organization's own sites.

The crawl spends a fixed page budget, so what it fetches first decides what the
assessment can see. Links are ranked before they are fetched:

* rank 0, AI governance: responsible AI, AI principles, model cards.
* rank 1, governance: ethics, privacy, risk, oversight, sustainability, impact.
* rank 2, general: about, company, investors.

A link that also looks like a storefront, career, location or help page drops
three ranks, and no section of a site may take more than its share of the
budget. Sitemaps and the organization's corporate hosts (``corporate.``,
``about.``, ``investor.``) are read as well, because the submitted domain is
often a storefront whose governance pages live elsewhere. Every request uses the
platform's own User-Agent and honours robots.txt; a host that refuses the
homepage is not probed further.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import unquote, urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from hai_core.generated.enums import ConnectorRunOutcome
from hai_ontology.terms import compile_term
from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument, summarise
from hai_pipeline.extraction import extract, extract_html
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher, FetchResult
from hai_pipeline.publishers import (
    ACADEMIC_DOMAINS,
    ARCHIVE_DOMAINS,
    AUDIT_DOMAINS,
    REGULATOR_DOMAINS,
    REPO_DOMAINS,
    SOCIAL_DOMAINS,
    STANDARDS_DOMAINS,
)
from hai_pipeline.spans import MIN_SPAN_CHARS
from hai_pipeline.urls import canonical_url, is_subdomain_of, registrable_domain, same_registrable_domain

RANK_AI = 0
RANK_GOVERNANCE = 1
RANK_GENERAL = 2
LOW_VALUE_PENALTY = 3
SEED_RANK = 3
RANK_OTHER = 7  # a link that matches no keyword: read only while a small site has budget left

_LOCALE = re.compile(r"^/([a-z]{2})[-_]([a-z]{2})(?=/|$)", re.IGNORECASE)
_LANGUAGE_ONLY = re.compile(r"^/(de|fr|es|it|pt|ja|jp|zh|ko|kr|nl|ru|pl|tr|sv|ar|cn|tw|br|mx)(?=/|$)", re.IGNORECASE)
_EDITIONS = frozenset({"global", "gx", "intl", "international", "worldwide", "home"})
_LOC = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", re.IGNORECASE)
_ENGLISH_ANCHOR = re.compile(r"^(english|en|eng|english \(us\)|global \(english\)|global)$", re.IGNORECASE)
_PATH_YEAR = re.compile(r"(?<=/)((?:19|20)\d\d)(?=[/-])")
_BINARY = re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|mp4|mp3|zip|xlsx?|pptx?|docx?|ics|css|js|woff2?)$", re.IGNORECASE)


@dataclass(frozen=True)
class LinkRanker:
    """Rank a link from its anchor text and URL path; None means it is not worth a fetch."""

    ai: tuple[re.Pattern[str], ...]
    governance: tuple[re.Pattern[str], ...]
    general: tuple[re.Pattern[str], ...]
    low_value: tuple[re.Pattern[str], ...]

    @classmethod
    def from_config(cls, config: ConnectorConfig) -> LinkRanker:
        def compiled(key: str) -> tuple[re.Pattern[str], ...]:
            return tuple(compile_term(str(k)) for k in config.opt(key, []))

        return cls(
            ai=compiled("priority_link_keywords"),
            governance=compiled("governance_link_keywords"),
            general=compiled("link_keywords"),
            low_value=compiled("low_value_link_keywords"),
        )

    def rank(self, anchor: str, url: str) -> int | None:
        scored = self.score(anchor, url)
        return scored[0] if scored and scored[0] < RANK_OTHER else None

    def score(self, anchor: str, url: str) -> tuple[int, int] | None:
        """``(rank, -matches)``: the rank, then how many governance terms the link matches. A link that
        names three governance topics is fetched before one that happens to contain one."""
        parts = urlsplit(url)
        path = unquote(parts.path)
        words = path.replace("-", " ").replace("_", " ").replace("/", " ").replace(".", " ")
        probe = f"{anchor} {words}"
        ai = sum(1 for p in self.ai if p.search(probe))
        governance = sum(1 for p in self.governance if p.search(probe))
        if ai:
            base = RANK_AI
        elif governance:
            base = RANK_GOVERNANCE
        elif any(p.search(probe) for p in self.general):
            base = RANK_GENERAL
        else:
            # Unranked. A small organization's methodology page may be called anything.
            return None if any(p.search(probe) for p in self.low_value) else (RANK_OTHER, 0)
        if any(p.search(probe) for p in self.low_value):
            base += LOW_VALUE_PENALTY
        return base, -(2 * ai + governance)


def is_foreign_locale(path: str) -> bool:
    """A path under a locale that is not English (``/de-de/``, ``/zh-tw/``, ``/fr/``)."""
    m = _LOCALE.match(path)
    if m:
        return "en" not in (m.group(1).lower(), m.group(2).lower())
    return bool(_LANGUAGE_ONLY.match(path))


def section_of(url: str) -> str | None:
    """The host and first path segment of a page that sits inside a section: the unit the
    per-section page cap applies to. A top-level page belongs to no section and is never capped,
    so a small site with flat URLs is not cut off after a handful of pages."""
    parts = urlsplit(url)
    segments = _without_edition([s for s in parts.path.split("/") if s])
    if len(segments) < 2:
        return None
    return f"{parts.netloc.lower()}/{segments[0].lower()}"


def _without_edition(segments: list[str]) -> list[str]:
    """Drop the country and language prefix of a path (``/en-us``, ``/en``, ``/us/en``, ``/global/en``,
    ``/en/global``): it names an edition of the site, not a section of it. Without this every
    page of a country-structured site falls into one section and the cap starves the crawl."""
    lowered = [s.lower() for s in segments]
    if not lowered:
        return segments
    if _LOCALE.match("/" + lowered[0]):
        skip = 1
    elif lowered[0] == "en":
        skip = 2 if len(lowered) > 1 and lowered[1] in _EDITIONS else 1
    elif len(lowered) > 1 and lowered[1] == "en" and (len(lowered[0]) == 2 or lowered[0] in _EDITIONS):
        skip = 2
    else:
        skip = 0
    return segments[skip:]


def english_alternate(page: FetchResult) -> str | None:
    """The English edition a non-English page points at (hreflang, then an "English" link)."""
    if "html" not in page.content_type.lower():
        return None
    tree = LexborHTMLParser(page.content)
    root = tree.css_first("html")
    lang = ((root.attributes.get("lang") if root is not None else None) or "").lower()
    if not lang or lang.startswith("en"):
        return None
    for node in tree.css('link[rel="alternate"][hreflang]'):
        code = (node.attributes.get("hreflang") or "").lower()
        href = node.attributes.get("href")
        if href and (code == "en" or code.startswith("en-") or code == "x-default"):
            return urljoin(page.final_url, href)
    for node in tree.css("a[href]"):
        text = " ".join(node.text().split())
        href = node.attributes.get("href")
        if href and _ENGLISH_ANCHOR.match(text):
            return urljoin(page.final_url, href)
    return None


def english_editions(page: FetchResult, english_paths: list[str]) -> list[str]:
    """Where to look for the English edition of a page served in another language."""
    out: list[str] = []
    declared = english_alternate(page)
    if declared:
        out.append(canonical_url(declared))
    parts = urlsplit(page.final_url)
    unreadable = not _readable_text(page)[0]  # a JavaScript shell at the root; an edition path may be rendered
    if unreadable or is_foreign_locale(parts.path) or (declared is None and _declared_language(page) not in ("", "en")):
        root = f"{parts.scheme}://{parts.netloc}"
        out.extend(canonical_url(root + p) for p in english_paths)
    return list(dict.fromkeys(out))


def _declared_language(page: FetchResult) -> str:
    if "html" not in page.content_type.lower():
        return ""
    root = LexborHTMLParser(page.content).css_first("html")
    return ((root.attributes.get("lang") if root is not None else None) or "")[:2].lower()


class WebsiteConnector:
    code = "WEBSITE"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        fetches: list[FetchResult] = []
        home_url = canonical_url(ctx.website_url)
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(home_url))
        domain = registrable_domain(home_url)
        skip = [str(p) for p in config.opt("skip_paths", [])]
        min_chars = int(config.opt("min_text_chars", 300))
        ranker = LinkRanker.from_config(config)
        max_discovered = int(config.opt("max_discovered_links", 10))
        max_depth = int(config.opt("max_discovery_depth", 2))
        section_cap = int(config.opt("max_pages_per_section", 0))
        max_sitemap_links = int(config.opt("max_sitemap_links", 40))
        max_offsite = int(config.opt("max_offsite_reports", 0))
        fill_below = int(config.opt("read_whole_site_below_documents", 0))
        # A page filed under a year older than the freshness window would be stale on arrival.
        oldest_year = (ctx.as_of or date.today()).year - max(1, -(-ctx.freshness_window_months // 12))
        sitemap_hosts_skipped = {str(h) for h in config.opt("no_sitemap_hosts", [])}
        offsite_urls: set[str] = set()
        candidates: dict[str, tuple[int, int, int, int]] = {}
        probes: set[str] = set()  # guessed URLs: a miss is refunded, not charged to the page budget
        visited = {home_url}
        paths_seen: set[str] = {_path_key(home_url)}  # one fetch per page, whatever its query string
        discovered_urls: set[str] = set()
        blocked_hosts: set[str] = set()
        section_pages: dict[str, int] = {}
        seen_text: set[int] = set()
        sequence = 0

        def usable(absolute: str) -> bool:
            parts = urlsplit(absolute)
            path = parts.path.lower()
            return not (
                any(path.startswith(s) for s in skip)
                or is_foreign_locale(path)
                or _BINARY.search(path)
                or parts.hostname in blocked_hosts
                or _dated_before(path, oldest_year)
            )

        def offer(absolute: str, rank: int, depth: int, weight: int = 0) -> None:
            nonlocal sequence
            if absolute in visited or not usable(absolute):
                return
            key = _path_key(absolute)
            if key in paths_seen and absolute not in candidates:
                return  # ?country=au, ?icid=footer: the same page under another query string
            paths_seen.add(key)
            current = candidates.get(absolute)
            if current is None or (rank, weight, depth) < current[:3]:
                candidates[absolute] = (rank, weight, depth, sequence)
                sequence += 1

        def discover(page: FetchResult, depth: int) -> None:
            if depth >= max_depth or not same_registrable_domain(page.final_url, home_url):
                return
            if "html" not in page.content_type.lower():
                return
            doc = extract_html(page.content, base_url=page.final_url)
            links: dict[str, tuple[int, int]] = {}
            offsite: dict[str, tuple[int, int]] = {}
            for href, anchor in doc.links:
                try:
                    target = urljoin(page.final_url, href)
                    if urlsplit(target).scheme.lower() not in ("http", "https"):
                        continue
                    absolute = canonical_url(target)
                except ValueError:
                    # One malformed anchor must not discard a collected page.
                    continue
                if absolute in visited or not usable(absolute):
                    continue
                scored = ranker.score(anchor, absolute)
                if scored is None:
                    continue
                if scored[0] >= RANK_OTHER and (
                    fill_below <= 0 or urlsplit(absolute).netloc != urlsplit(origin).netloc
                ):
                    continue
                if not same_registrable_domain(absolute, home_url):
                    # A governance report the organization links to but hosts elsewhere.
                    if scored[0] <= RANK_GOVERNANCE and _is_offsite_report(absolute):
                        offsite[absolute] = min(scored, offsite.get(absolute, scored))
                    continue
                links[absolute] = min(scored, links.get(absolute, scored))
            # Rank real links before applying the discovery limit. Navigation
            # order must not hide an AI policy behind generic footer links.
            for absolute, (rank, weight) in sorted(links.items(), key=lambda item: item[1])[:max_discovered]:
                discovered_urls.add(absolute)
                offer(absolute, rank, depth + 1, weight)
            for absolute, (rank, weight) in sorted(offsite.items(), key=lambda item: item[1]):
                if len(offsite_urls) >= max_offsite or absolute in offsite_urls:
                    continue
                offsite_urls.add(absolute)
                offer(absolute, rank, max_depth, weight)  # a leaf: its own links are never followed

        def keep(page: FetchResult, *, floor: int, published_by_organization: bool = False) -> bool:
            text, language = _readable_text(page)
            if len(text) < max(MIN_SPAN_CHARS, floor):
                return False
            if language and not language.startswith("en"):
                return False  # the evidence lexicons are English; a translated copy adds nothing
            digest = hash(text)
            if digest in seen_text:
                return False
            seen_text.add(digest)
            result.documents.append(self._doc(page, config, published_by_organization=published_by_organization))
            return True

        async def read_sitemap(root: str) -> None:
            added = 0
            for path in config.opt("sitemap_paths", []):
                if added:
                    break
                url = canonical_url(root + str(path))
                try:
                    fetched = await fetcher.fetch(url, budget=budget, max_retries=0)
                except BudgetExhausted:
                    return
                result.attempted_urls.append(url)
                if not fetched.ok:
                    budget.refund()
                    continue
                locations = _LOC.findall(fetched.text)
                children = [u for u in locations if u.lower().split("?")[0].endswith((".xml", ".xml.gz"))]
                if children and len(children) >= len(locations) / 2:
                    # A sitemap index: read the child that lists pages, preferring English and corporate ones.
                    children.sort(key=lambda u: (is_foreign_locale(urlsplit(u).path), "page" not in u.lower(), len(u)))
                    for child in children[: int(config.opt("max_sitemap_files", 2))]:
                        if child.lower().endswith(".gz"):
                            continue
                        try:
                            sub = await fetcher.fetch(child, budget=budget, max_retries=0)
                        except (BudgetExhausted, ValueError):
                            return
                        result.attempted_urls.append(child)
                        if sub.ok:
                            locations.extend(_LOC.findall(sub.text))
                        else:
                            budget.refund()
                ranked: list[tuple[int, int, str]] = []
                for loc in locations:
                    try:
                        absolute = canonical_url(loc.strip())
                    except ValueError:
                        continue
                    if not same_registrable_domain(absolute, home_url) or absolute.lower().endswith(".xml"):
                        continue
                    scored = ranker.score("", absolute)
                    # A sitemap lists every page; only governance pages are worth the budget.
                    if scored is not None and scored[0] <= RANK_GOVERNANCE:
                        ranked.append((*scored, absolute))
                ranked.sort(key=lambda item: (item[0], item[1], item[2].count("/"), len(item[2])))
                for rank, weight, absolute in ranked[:max_sitemap_links]:
                    if absolute not in visited and usable(absolute):
                        discovered_urls.add(absolute)
                        offer(absolute, rank, 1, weight)
                        added += 1
                if added:
                    result.notes.append(f"{added} governance pages listed by {url}")

        home = await fetcher.fetch(home_url, budget=budget, max_retries=1)
        fetches.append(home)
        result.attempted_urls.append(home_url)
        if home.ok:
            for alternate in english_editions(home, [str(p) for p in config.opt("english_paths", [])]):
                if alternate in visited or not same_registrable_domain(alternate, home_url):
                    continue
                # The site answered in another language; evidence lexicons are English.
                english = await fetcher.fetch(alternate, budget=budget, max_retries=0)
                fetches.append(english)
                result.attempted_urls.append(alternate)
                if (
                    english.ok
                    and _readable_text(english)[0]
                    and not is_foreign_locale(urlsplit(english.final_url).path)
                ):
                    result.notes.append(f"English edition used: {english.final_url}")
                    visited.add(canonical_url(home.final_url))
                    home = english
                    break
                budget.refund()
            keep(home, floor=MIN_SPAN_CHARS)
            visited.add(canonical_url(home.final_url))
            if same_registrable_domain(home.final_url, home_url):
                origin = "{0.scheme}://{0.netloc}".format(urlsplit(home.final_url))
            discover(home, 0)
            await read_sitemap(origin)
        else:
            result.notes.append(f"homepage {home.outcome}: {home.error_code}")
            if home.outcome == ConnectorRunOutcome.BLOCKED.value:
                # The host refused the platform's crawler. Do not probe its other paths.
                blocked_hosts.add(urlsplit(home_url).hostname or "")
                blocked_hosts.add(urlsplit(home.final_url).hostname or "")
        if (urlsplit(origin).hostname or "") not in blocked_hosts:
            for path in config.opt("seed_paths", []):
                url = canonical_url(origin + str(path))
                if url not in candidates and url not in visited:
                    probes.add(url)
                    offer(url, SEED_RANK, 1)
        for prefix in config.opt("corporate_hosts", []):
            url = canonical_url(f"https://{prefix}.{domain}/")
            if url not in visited and url not in candidates and urlsplit(url).netloc != urlsplit(origin).netloc:
                probes.add(url)
                offer(url, RANK_GOVERNANCE, 0)
        while candidates:
            url = min(candidates, key=lambda candidate: candidates[candidate])
            rank, _, depth, _ = candidates.pop(url)
            if url in visited or not usable(url):
                continue
            if rank >= RANK_OTHER and len(result.documents) >= fill_below:
                break  # governance pages are exhausted and the site is not small: stop
            section = section_of(url)
            if section and section_cap and rank > RANK_AI and section_pages.get(section, 0) >= section_cap:
                continue
            is_probe = url in probes
            try:
                fetched = await fetcher.fetch(url, budget=budget, max_retries=0 if is_probe else None)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            fetches.append(fetched)
            visited.add(url)
            result.attempted_urls.append(url)
            if not fetched.ok:
                if is_probe:
                    budget.refund()
                if fetched.outcome == ConnectorRunOutcome.BLOCKED.value and depth == 0:
                    blocked_hosts.add(urlsplit(url).hostname or "")
                continue
            final = canonical_url(fetched.final_url)
            if final in visited and final != url:
                if is_probe:
                    budget.refund()
                continue
            visited.add(final)
            if url in offsite_urls:
                if "pdf" in fetched.content_type.lower() or fetched.content[:5] == b"%PDF-":
                    keep(fetched, floor=min_chars, published_by_organization=True)
                continue
            if not same_registrable_domain(final, home_url):
                continue
            if depth == 0:
                # A corporate host that answered: it is a second entry point into the organization's pages.
                result.notes.append(f"corporate host found: {urlsplit(final).netloc}")
                english_edition = english_alternate(fetched)
                if english_edition and same_registrable_domain(english_edition, home_url):
                    offer(canonical_url(english_edition), RANK_GOVERNANCE, 0)
                if (urlsplit(final).hostname or "").split(".")[0] not in sitemap_hosts_skipped:
                    await read_sitemap("{0.scheme}://{0.netloc}".format(urlsplit(final)))
            # A seed path that silently served the homepage again is not new evidence.
            if _is_distinct_page(fetched, home) and keep(fetched, floor=min_chars) and section:
                section_pages[section] = section_pages.get(section, 0) + 1
            discover(fetched, depth)
        result.notes.append(f"{len(discovered_urls)} governance links discovered across up to {max_depth} link levels")
        result.outcome = summarise(list(fetches))
        if not result.documents and home.outcome == ConnectorRunOutcome.BLOCKED.value:
            # A sibling host that answered with nothing readable does not change what happened:
            # the organization's site refused the crawler.
            result.outcome = ConnectorRunOutcome.BLOCKED.value
            result.error_code = home.error_code
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
    def _doc(
        fetched: FetchResult, config: ConnectorConfig, *, published_by_organization: bool = False
    ) -> FetchedDocument:
        return FetchedDocument(
            url=fetched.final_url or fetched.url,
            content=fetched.content,
            content_type=fetched.content_type or "text/html",
            publisher_type_hint=config.publisher_type,
            published_by_organization=published_by_organization,
            note="report linked from the organization's governance pages and hosted elsewhere"
            if published_by_organization
            else None,
        )


def _is_offsite_report(url: str) -> bool:
    """A PDF on a host that is not a regulator, standards body, journal, audit firm, repository,
    social network or archive: those publish their own documents, not the organization's."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not parts.path.lower().endswith(".pdf"):
        return False
    third_party = (
        *REGULATOR_DOMAINS,
        *STANDARDS_DOMAINS,
        *ACADEMIC_DOMAINS,
        *AUDIT_DOMAINS,
        *SOCIAL_DOMAINS,
        *REPO_DOMAINS,
        *ARCHIVE_DOMAINS,
    )
    return not (any(is_subdomain_of(host, d) for d in third_party) or host.endswith((".gov", ".edu", ".int")))


def _dated_before(path: str, oldest_year: int) -> bool:
    """A path filed under a year (``/2019/``, ``/2021-06/``) older than ``oldest_year``."""
    years = [int(y) for y in _PATH_YEAR.findall(path)]
    return bool(years) and max(years) < oldest_year


def _path_key(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.netloc.lower()}{parts.path.rstrip('/').lower()}"


def _readable_text(page: FetchResult) -> tuple[str, str | None]:
    try:
        doc = extract(page.content, page.content_type, base_url=page.final_url)
    except Exception:
        return "", None
    return doc.text.strip(), doc.language


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
