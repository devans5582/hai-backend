"""WAYBACK: fetch the archived page itself, not merely its existence.

Two modes. When the organization's own site was collected, only a few fixed
governance paths are looked up, as before. When the site could not be read
(it refused the crawler, failed, or served an empty JavaScript shell) the
connector crawls the Internet Archive's most recent captures instead, ranking
links exactly as the WEBSITE connector does. Every document is marked as an
archived copy with its capture date, so the access limitation stays visible and
a capture older than the freshness window is stale like any other evidence.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote, urljoin, urlsplit

from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.connectors.website import LinkRanker, _path_key, _readable_text, is_foreign_locale, section_of
from hai_pipeline.extraction import extract_html
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher, FetchResult
from hai_pipeline.spans import MIN_SPAN_CHARS
from hai_pipeline.urls import canonical_url, registrable_domain, same_registrable_domain

_CAPTURE = re.compile(r"/web/(\d{14})")
_SCHEME = re.compile(r"^(https?):/+")
_BINARY = re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|mp4|mp3|zip|xlsx?|pptx?|docx?|ics|css|js|woff2?)$", re.IGNORECASE)


class WaybackConnector:
    code = "WAYBACK"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        min_primary = int(config.opt("fallback_below_documents", 0))
        if ctx.primary_outcome is not None and ctx.primary_documents < min_primary:
            fallback = Budget(
                time_seconds=float(config.opt("fallback_time_seconds", budget.time_seconds)),
                pages=int(config.opt("fallback_pages", budget.pages)),
            )
            return await self._crawl_archive(ctx, fetcher, config, fallback, result)
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

    async def _crawl_archive(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget, result: ConnectorResult
    ) -> ConnectorResult:
        """Crawl recent captures of the organization's site, governance pages first."""
        ranker = LinkRanker.from_config(config)
        snapshot_tpl = str(config.opt("snapshot_url"))
        availability = str(config.opt("availability_url"))
        min_year = int(config.opt("min_year", 2015))
        as_of = ctx.as_of or date.today()
        stamp = as_of.strftime("%Y%m%d")
        home = canonical_url(ctx.website_url)
        domain = registrable_domain(home)
        max_depth = int(config.opt("max_discovery_depth", 2))
        max_links = int(config.opt("max_discovered_links", 30))
        section_cap = int(config.opt("max_pages_per_section", 0))
        candidates: dict[str, tuple[int, int, int]] = {home: (0, 0, 0)}
        sequence = 1
        for prefix in config.opt("corporate_hosts", []):
            candidates[canonical_url(f"https://{prefix}.{domain}/")] = (1, 0, sequence)
            sequence += 1
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(home))
        for path in config.opt("paths", []):
            candidates.setdefault(canonical_url(origin + str(path)), (2, 1, sequence))
            sequence += 1
        seen_paths: set[str] = set()
        seen_text: set[int] = set()
        sections: dict[str, int] = {}
        outcomes: list[str] = []

        async def capture(target: str) -> FetchResult | None:
            """The capture closest to the assessment date; a refused capture falls back to the last good one."""
            url = snapshot_tpl.replace("{timestamp}", stamp).replace("{url}", target)
            page = await fetcher.fetch(url, budget=budget, max_retries=0)
            result.attempted_urls.append(url)
            outcomes.append(page.outcome)
            if page.ok and page.content:
                return page
            if page.status not in (401, 403, 406, 451):
                return None
            # The archive replays the refusal it met itself. Ask for the nearest successful capture.
            lookup = availability.replace("{url}", quote(target, safe="")) + f"&timestamp={stamp}"
            _, data = await fetcher.get_json(lookup, budget=budget)
            result.attempted_urls.append(lookup)
            closest = ((data or {}).get("archived_snapshots") or {}).get("closest") if isinstance(data, dict) else None
            ts = str((closest or {}).get("timestamp") or "")
            if not closest or str(closest.get("status")) != "200" or len(ts) < 14:
                return None
            good = await fetcher.fetch(
                snapshot_tpl.replace("{timestamp}", ts).replace("{url}", target), budget=budget, max_retries=0
            )
            outcomes.append(good.outcome)
            return good if good.ok and good.content else None

        while candidates:
            target = min(candidates, key=lambda c: candidates[c])
            rank, depth, _ = candidates.pop(target)
            key = _path_key(target)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            section = section_of(target)
            if section and section_cap and rank > 0 and sections.get(section, 0) >= section_cap:
                continue
            try:
                page = await capture(target)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            if page is None:
                if depth <= 1:
                    budget.refund()  # a guessed entry point that was never archived
                continue
            match = _CAPTURE.search(page.final_url)
            ts = match.group(1) if match else stamp + "000000"
            captured = date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
            # URL canonicalisation folds the "//" of the embedded address; restore it.
            original = _SCHEME.sub(r"\1://", page.final_url.split("id_/", 1)[1]) if "id_/" in page.final_url else target
            if captured.year < min_year:
                continue
            text, language = _readable_text(page)
            digest = hash(text)
            if len(text) >= MIN_SPAN_CHARS and digest not in seen_text and (not language or language.startswith("en")):
                seen_text.add(digest)
                if section:
                    sections[section] = sections.get(section, 0) + 1
                result.documents.append(
                    FetchedDocument(
                        url=page.final_url,
                        content=page.content,
                        content_type=page.content_type or "text/html",
                        publisher_hint="Internet Archive",
                        publisher_type_hint=config.publisher_type,
                        published_at=captured,
                        note=f"archived copy of {original} captured {ts[:8]}; the live site could not be read",
                        archived_original_url=original,
                    )
                )
            if depth >= max_depth or "html" not in page.content_type.lower():
                continue
            found: dict[str, int] = {}
            for href, anchor in extract_html(page.content, base_url=original).links:
                try:
                    absolute = canonical_url(urljoin(original, href))
                except ValueError:
                    continue
                parts = urlsplit(absolute)
                if (
                    not same_registrable_domain(absolute, home)
                    or _path_key(absolute) in seen_paths
                    or is_foreign_locale(parts.path.lower())
                    or _BINARY.search(parts.path)
                ):
                    continue
                link_rank = ranker.rank(anchor, absolute)
                if link_rank is not None and link_rank < found.get(absolute, 99):
                    found[absolute] = link_rank
            for absolute, link_rank in sorted(found.items(), key=lambda item: item[1])[:max_links]:
                current = candidates.get(absolute)
                if current is None or (link_rank, depth + 1) < current[:2]:
                    candidates[absolute] = (link_rank, depth + 1, sequence)
                    sequence += 1
        if not result.documents and outcomes and all(o != "succeeded" for o in outcomes):
            result.outcome = outcomes[0]
            result.error_code = "archive_" + outcomes[0]
        result.notes.append(
            f"live site unreadable ({ctx.primary_outcome}); {len(result.documents)} archived page(s) collected instead"
        )
        return result
