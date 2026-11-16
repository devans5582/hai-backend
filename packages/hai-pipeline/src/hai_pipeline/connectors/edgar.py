"""EDGAR: SEC full-text search, filer-name matched, then the filing document itself."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from hai_core.freshness import DAYS_PER_MONTH
from hai_core.generated.enums import PublisherType
from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.entity_resolution import normalise_name
from hai_pipeline.extraction import parse_date
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher

_FUND_WORDS = frozenset({"fund", "trust", "etf", "portfolio", "index"})


def filer_matches(
    filer_name: str, organization_name: str, *, cik: str | None = None, entity_id: str | None = None
) -> bool:
    """With a verified CIK the filing's entity id must equal it. Otherwise every significant word of
    the organization name must appear in the filer name as a whole word (Phase 6
    supplementary-evidence.js:156-167, made whole-word)."""
    if cik:
        return bool(entity_id) and str(entity_id).lstrip("0") == cik.lstrip("0")
    words = [w for w in normalise_name(organization_name).split() if len(w) > 2]
    if not words:
        return False
    filer = normalise_name(filer_name)
    if any(w in _FUND_WORDS - set(words) for w in filer.split()):
        return False  # a fund or trust that merely references the company
    return all(re.search(rf"\b{re.escape(w)}\b", filer) for w in words)


class EdgarConnector:
    code = "EDGAR"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        search_url = str(config.opt("search_url"))
        archive_url = str(config.opt("archive_url", "https://www.sec.gov/Archives/edgar/data")).rstrip("/")
        forms = ",".join(str(f) for f in config.opt("forms", ["10-K"]))
        max_filings = int(config.opt("max_filings", 3))
        as_of = ctx.as_of or datetime.now(UTC).date()
        earliest = as_of - timedelta(days=int(ctx.freshness_window_months * DAYS_PER_MONTH))
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
                    content=doc.content,
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
