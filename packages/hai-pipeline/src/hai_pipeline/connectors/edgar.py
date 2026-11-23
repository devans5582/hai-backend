"""EDGAR: the registrant's own governance filings, then full-text search as a fallback.

The connector first settles which registrant, if any, the organization is:

1. the CIK verified by entity resolution, when there is one;
2. otherwise the registrant whose annual report cites the submitted domain as its
   own website (SEC full-text search for the domain, then a check of the filing);
3. otherwise the one registrant whose name equals the organization's name.

It then reads the SEC submissions index and fetches the latest proxy statement and
annual report: those are where a registrant describes board oversight, risk
management, its code of conduct and human capital. A one-word name can no longer
pull in another company's filings, and an organization that is not a registrant
gets an empty run rather than a neighbour's evidence.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from hai_core.freshness import DAYS_PER_MONTH
from hai_core.generated.enums import PublisherType
from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.entity_resolution import normalise_name
from hai_pipeline.extraction import parse_date
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher
from hai_pipeline.urls import registrable_domain

_FUND_WORDS = frozenset({"fund", "trust", "etf", "portfolio", "index"})
_PARENTHETICAL = re.compile(r"\([^)]*\)")
_FORMER = re.compile(r"/[A-Z]{2,}/?\s*$")
_TAGS = re.compile(r"<[^>]+>|&nbsp;|&#160;")
_POSSESSIVE = re.compile(r"\b(our|the company[\u2019']?s|company[\u2019']?s|its)\b", re.IGNORECASE)
_SITE_WORD = re.compile(r"\b(web ?sites?|internet (address|site)|investor relations|channel)\b", re.IGNORECASE)
OWN_SITE_WINDOW_BEFORE = 160
OWN_SITE_WINDOW_AFTER = 60
MIN_UNNAMED_MENTIONS = 5


def filer_matches(
    filer_name: str, organization_name: str, *, cik: str | None = None, entity_id: str | None = None
) -> bool:
    """With a verified CIK the filing's entity id must equal it. Otherwise the filer's name must be
    the organization's name once tickers, state suffixes and corporate forms are removed. Phase 6
    (supplementary-evidence.js:156-167) accepted any filer containing the words, so "Harvard"
    matched Harvard Bioscience and "Marriott" matched Marriott Vacations Worldwide."""
    if cik:
        return bool(entity_id) and str(entity_id).lstrip("0") == cik.lstrip("0")
    wanted = normalise_name(organization_name)
    if not wanted or not any(len(w) > 2 for w in wanted.split()):
        return False
    filer = normalise_name(_FORMER.sub("", _PARENTHETICAL.sub(" ", filer_name)))
    if any(w in _FUND_WORDS - set(wanted.split()) for w in filer.split()):
        return False  # a fund or trust that merely references the company
    return filer == wanted


def own_site_mentions(text: str, domain: str) -> tuple[int, int]:
    """How often ``text`` presents ``domain`` as the writer's own site, and how often it names it at all.

    "Our U.S. website is www.costco.com" and "our direct-to-consumer channel, Meta.com" count as
    own; "sold through Costco.com" does not.
    """
    mention = re.compile(rf"(?<![a-z0-9-]){re.escape(domain)}(?![a-z0-9-])", re.IGNORECASE)
    own = 0
    total = 0
    for m in mention.finditer(text):
        total += 1
        before = text[max(0, m.start() - OWN_SITE_WINDOW_BEFORE) : m.start()]
        window = before + text[m.start() : m.end() + OWN_SITE_WINDOW_AFTER]
        if _POSSESSIVE.search(before) and _SITE_WORD.search(window):
            own += 1
    return own, total


class EdgarConnector:
    code = "EDGAR"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        search_url = str(config.opt("search_url"))
        archive_url = str(config.opt("archive_url", "https://www.sec.gov/Archives/edgar/data")).rstrip("/")
        max_filings = int(config.opt("max_filings", 3))
        max_bytes = int(config.opt("max_filing_bytes", 0)) or None
        as_of = ctx.as_of or datetime.now(UTC).date()
        earliest = as_of - timedelta(days=int(ctx.freshness_window_months * DAYS_PER_MONTH))
        cik = ctx.cik
        if config.opt("submissions_url"):
            if not cik:
                cik = await self._registrant_by_domain(ctx, fetcher, config, budget, result, earliest, as_of)
            if not cik:
                cik = await self._registrant_by_name(ctx, fetcher, config, budget, result)
            if cik:
                await self._governance_filings(cik, ctx, fetcher, config, budget, result, earliest, as_of, archive_url)
                if result.documents:
                    return result
        forms = ",".join(str(f) for f in config.opt("forms", ["10-K"]))
        params = {
            "q": str(config.opt("query_terms", "")),
            "dateRange": "custom",
            "startdt": earliest.isoformat(),
            "enddt": as_of.isoformat(),
            "forms": forms,
            "sort": "desc",
        }
        if ctx.cik:
            params["ciks"] = ctx.cik
        else:
            params["entityName"] = ctx.organization_name
        url = f"{search_url}?{urlencode(params)}"
        result.attempted_urls.append(url)
        fetched, data = await fetcher.get_json(url, budget=budget)
        if not fetched.ok or not isinstance(data, dict):
            result.outcome = fetched.outcome if fetched.outcome != "succeeded" else "failed"
            result.error_code = fetched.error_code or "bad_json"
            result.notes.append(f"search {result.outcome}")
            return result
        hits: list[dict[str, Any]] = list(data.get("hits", {}).get("hits", []))
        # Defend the small filing budget even if the provider ignores its
        # requested date order. Old relevance hits must not crowd out current evidence.
        hits.sort(key=lambda hit: str(hit.get("_source", {}).get("file_date", "")), reverse=True)
        seen: set[str] = set()
        matched = 0
        rejected = 0
        outdated = 0
        for hit in hits:
            if matched >= max_filings:
                break
            src = hit.get("_source", {})
            published = parse_date(str(src.get("file_date", "")))
            if published is not None and not earliest <= published <= as_of:
                outdated += 1
                continue
            names = src.get("display_names") or []
            filer = str(names[0]) if names else ""
            if not filer_matches(filer, ctx.organization_name, cik=ctx.cik, entity_id=str(src.get("entity_id", ""))):
                rejected += 1
                continue
            adsh = str(src.get("adsh", ""))
            key = f"{adsh}|{src.get('period_of_report', '')}"
            if not adsh or key in seen:
                continue
            seen.add(key)
            hit_id = str(hit.get("_id", ""))
            filename = hit_id.split(":", 1)[1] if ":" in hit_id else ""
            ciks = src.get("ciks") or ([src.get("entity_id")] if src.get("entity_id") else [])
            if not filename or not ciks:
                continue
            cik_int = str(ciks[0]).lstrip("0") or "0"
            doc_url = f"{archive_url}/{cik_int}/{adsh.replace('-', '')}/{filename}"
            try:
                doc = await fetcher.fetch(doc_url, budget=budget)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            result.attempted_urls.append(doc_url)
            if not doc.ok:
                result.notes.append(f"filing {adsh} {doc.outcome}")
                continue
            result.documents.append(
                FetchedDocument(
                    url=doc.final_url or doc_url,
                    content=doc.content[:max_bytes],
                    content_type=doc.content_type or "text/html",
                    publisher_hint=ctx.organization_name,
                    publisher_type_hint=PublisherType.ORG_DISCLOSURE.value,
                    published_at=published,
                    title=f"SEC {src.get('form_type', '')} filing: {filer}".strip(),
                    note="Issuer-authored disclosure hosted by the SEC; not a regulator finding.",
                )
            )
            matched += 1
        result.notes.append(
            f"{len(hits)} hits, {matched} entity-matched filings fetched, {rejected} rejected, "
            f"{outdated} outside freshness window"
        )
        return result

    async def _registrant_by_domain(
        self,
        ctx: ConnectorContext,
        fetcher: Fetcher,
        config: ConnectorConfig,
        budget: Budget,
        result: ConnectorResult,
        earliest: date,
        as_of: date,
    ) -> str | None:
        """The registrant whose annual report names the submitted domain as its own website."""
        domain = registrable_domain(ctx.organization_domain)
        if not domain:
            return None
        params = {
            "q": f'"{domain}"',
            "dateRange": "custom",
            "startdt": earliest.isoformat(),
            "enddt": as_of.isoformat(),
            "forms": ",".join(str(f) for f in config.opt("annual_forms", ["10-K", "20-F", "40-F"])),
        }
        url = f"{config.opt('search_url')}?{urlencode(params)}"
        result.attempted_urls.append(url)
        try:
            fetched, data = await fetcher.get_json(url, budget=budget)
        except BudgetExhausted:
            return None
        if not fetched.ok or not isinstance(data, dict):
            return None
        wanted = {w for w in (*normalise_name(ctx.organization_name).split(), domain.split(".")[0]) if len(w) > 2}
        filers: dict[str, dict[str, Any]] = {}
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            ciks = src.get("ciks") or []
            names = src.get("display_names") or []
            hit_id = str(hit.get("_id", ""))
            if not ciks or not names or ":" not in hit_id:
                continue
            name = normalise_name(_FORMER.sub("", _PARENTHETICAL.sub(" ", str(names[0]))))
            if set(name.split()) & _FUND_WORDS:
                continue  # a fund that the organization manages is a different registrant
            entry = filers.setdefault(
                str(ciks[0]),
                {"name": name, "hits": 0, "adsh": str(src.get("adsh", "")), "file": hit_id.split(":", 1)[1]},
            )
            entry["hits"] += 1
        ranked = sorted(filers.items(), key=lambda kv: (not (set(kv[1]["name"].split()) & wanted), -int(kv[1]["hits"])))
        archive_url = str(config.opt("archive_url", "https://www.sec.gov/Archives/edgar/data")).rstrip("/")
        best: tuple[int, int, str] | None = None
        for cik, entry in ranked[: int(config.opt("max_registrant_checks", 3))]:
            doc_url = f"{archive_url}/{cik.lstrip('0') or '0'}/{entry['adsh'].replace('-', '')}/{entry['file']}"
            try:
                doc = await fetcher.fetch(doc_url, budget=budget)
            except BudgetExhausted:
                break
            result.attempted_urls.append(doc_url)
            if not doc.ok:
                continue
            text = " ".join(_TAGS.sub(" ", doc.text).split())
            own, mentions = own_site_mentions(text, domain)
            named = bool(set(entry["name"].split()) & wanted)
            # The filing must present the domain as the registrant's own site. A filer that only
            # mentions the domain (a retailer's supplier, an auditor's client) is someone else.
            if own and (named or mentions >= MIN_UNNAMED_MENTIONS) and (best is None or (own, mentions) > best[:2]):
                best = (own, mentions, cik)
        if best is not None:
            result.notes.append(
                f"registrant CIK {best[2]} identified: its annual report cites {domain} as its own website "
                f"({best[1]} mention(s))"
            )
            return best[2]
        if ranked:
            result.notes.append(f"{len(ranked)} filer(s) mention {domain}; none cites it as its own website")
        return None

    async def _registrant_by_name(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget, result: ConnectorResult
    ) -> str | None:
        """The single registrant whose name equals the organization's name."""
        url = str(config.opt("tickers_url", ""))
        if not url:
            return None
        result.attempted_urls.append(url)
        try:
            fetched, data = await fetcher.get_json(url, budget=budget)
        except BudgetExhausted:
            return None
        if not fetched.ok or not isinstance(data, dict):
            return None
        found = {
            str(row.get("cik_str", "")).zfill(10)
            for row in data.values()
            if isinstance(row, dict) and filer_matches(str(row.get("title", "")), ctx.organization_name)
        }
        if len(found) != 1:
            return None
        cik = found.pop()
        result.notes.append(f"registrant CIK {cik} identified by an exact name match in the SEC company list")
        return cik

    async def _governance_filings(
        self,
        cik_value: str,
        ctx: ConnectorContext,
        fetcher: Fetcher,
        config: ConnectorConfig,
        budget: Budget,
        result: ConnectorResult,
        earliest: date,
        as_of: date,
        archive_url: str,
    ) -> None:
        """The newest filing of each governance form from the registrant's submissions index."""
        max_bytes = int(config.opt("max_filing_bytes", 0)) or None
        cik = str(cik_value).lstrip("0") or "0"
        url = str(config.opt("submissions_url")).replace("{cik}", cik.zfill(10))
        result.attempted_urls.append(url)
        try:
            fetched, data = await fetcher.get_json(url, budget=budget)
        except BudgetExhausted as exc:
            result.notes.append(str(exc))
            return
        index: dict[str, Any] = data if isinstance(data, dict) else {}
        recent = index.get("filings", {}).get("recent", {})
        forms = [str(f) for f in recent.get("form", [])]
        if not fetched.ok or not forms:
            result.notes.append(f"submissions index {fetched.outcome if not fetched.ok else 'empty'}")
            return
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary = recent.get("primaryDocument", [])
        filer = str(index.get("name") or ctx.organization_name)
        wanted = [str(f) for f in config.opt("governance_forms", ["DEF 14A", "10-K"])]
        chosen: list[tuple[str, date, str, str]] = []
        for form in wanted:
            for i, name in enumerate(forms):
                if name != form or i >= len(dates) or i >= len(accessions) or i >= len(primary):
                    continue
                published = parse_date(str(dates[i]))
                if published is None or not earliest <= published <= as_of or not primary[i]:
                    continue
                chosen.append((form, published, str(accessions[i]), str(primary[i])))
                break  # the index is newest first
        for form, published, adsh, filename in chosen[: int(config.opt("max_filings", 3))]:
            doc_url = f"{archive_url}/{cik}/{adsh.replace('-', '')}/{filename}"
            try:
                doc = await fetcher.fetch(doc_url, budget=budget)
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            result.attempted_urls.append(doc_url)
            if not doc.ok:
                result.notes.append(f"filing {adsh} {doc.outcome}")
                continue
            result.documents.append(
                FetchedDocument(
                    url=doc.final_url or doc_url,
                    content=doc.content[:max_bytes],
                    content_type=doc.content_type or "text/html",
                    publisher_hint=ctx.organization_name,
                    publisher_type_hint=PublisherType.ORG_DISCLOSURE.value,
                    published_at=published,
                    title=f"SEC {form} filing: {filer}",
                    note="Issuer-authored disclosure hosted by the SEC; not a regulator finding.",
                )
            )
        result.notes.append(
            f"submissions index: {len(result.documents)} governance filing(s) fetched "
            f"({', '.join(c[0] for c in chosen) or 'none in the freshness window'})"
        )
