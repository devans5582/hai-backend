"""Connectors, fetcher and entity resolution against the fake internet (httpx.MockTransport)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from hai_ontology.loader import find_repo_root
from hai_pipeline.config import load_connectors
from hai_pipeline.connectors import CONNECTORS, build_connector
from hai_pipeline.connectors.base import ConnectorContext
from hai_pipeline.connectors.edgar import filer_matches
from hai_pipeline.connectors.news import parse_rss
from hai_pipeline.entity_resolution import EntityResolver, name_match_score
from hai_pipeline.http import Budget, Fetcher
from tests.fixtures.fake_internet import (
    CIK,
    GITHUB_HANDLE,
    LEI,
    ORG_DOMAIN,
    ORG_NAME,
    ORG_SITE,
    WIKIDATA_QID,
    FakeInternet,
)

REPO = find_repo_root()
CONFIG = load_connectors(REPO / "config" / "connectors.yaml")


def fetcher(net: FakeInternet) -> Fetcher:
    return Fetcher(
        user_agent="hai-test",
        min_interval_seconds=0.0,
        transport=net.transport,
        max_retries=1,
        block_markers=("access denied",),
    )


def ctx(**overrides: object) -> ConnectorContext:
    base = ConnectorContext(
        organization_name=ORG_NAME,
        organization_domain=ORG_DOMAIN,
        website_url=ORG_SITE,
        direct_urls=[],
        org_id="org",
        assessment_id="a",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def budget() -> Budget:
    return Budget(time_seconds=30, pages=50)


async def test_http_errors_are_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /secret\n")
        codes = {"/ok": 200, "/forbidden": 403, "/limited": 429, "/missing": 404, "/down": 503}
        if path == "/challenge":
            return httpx.Response(
                200, text="<html><title>Just a moment...</title></html>", headers={"content-type": "text/html"}
            )
        return httpx.Response(codes.get(path, 500), text="body", headers={"content-type": "text/html"})

    async with Fetcher(
        user_agent="t",
        min_interval_seconds=0,
        transport=httpx.MockTransport(handler),
        max_retries=1,
        block_markers=("just a moment",),
    ) as f:
        assert (await f.fetch("https://h.example/ok")).outcome == "succeeded"
        assert (await f.fetch("https://h.example/forbidden")).outcome == "blocked"
        assert (await f.fetch("https://h.example/limited")).outcome == "rate_limited"
        missing = await f.fetch("https://h.example/missing")
        assert missing.outcome == "failed" and missing.error_code == "http_404"
        down = await f.fetch("https://h.example/down")
        assert down.outcome == "failed" and down.error_code == "http_503"
        assert (await f.fetch("https://h.example/challenge")).outcome == "blocked"
        robots = await f.fetch("https://h.example/secret/page")
        assert robots.outcome == "blocked" and robots.error_code == "robots_disallow"
        b = Budget(time_seconds=30, pages=1)
        await f.fetch("https://h.example/ok", budget=b)
        from hai_pipeline.http import BudgetExhausted

        with pytest.raises(BudgetExhausted):
            await f.fetch("https://h.example/ok", budget=b)


async def test_every_connector_runs_and_is_recorded_offline() -> None:
    """Every configured connector has an implementation and returns a recorded outcome, even when empty."""
    net = FakeInternet()
    assert set(CONFIG.codes) == set(CONNECTORS)
    async with fetcher(net) as f:
        for cfg in CONFIG.enabled:
            result = await build_connector(cfg.code).run(ctx(github_handle=GITHUB_HANDLE, cik=CIK), f, cfg, budget())
            assert result.outcome in ("succeeded", "blocked", "failed", "rate_limited"), cfg.code


async def test_website_connector_discovers_and_skips() -> None:
    net = FakeInternet(inject=True)
    async with fetcher(net) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, CONFIG.get("WEBSITE"), budget())
    urls = [d.url for d in result.documents]
    assert result.outcome == "succeeded"
    assert f"{ORG_SITE}/responsible-ai" in urls and f"{ORG_SITE}/blog/approach" in urls
    assert not any("/privacy" in u or "/careers" in u for u in urls)
    assert any(f"{ORG_SITE}/ethics" in u for u in result.attempted_urls)


async def test_blocked_website_is_blocked_not_empty() -> None:
    net = FakeInternet(block_website=True)
    async with fetcher(net) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, CONFIG.get("WEBSITE"), budget())
    assert result.outcome == "blocked" and result.documents == [] and result.error_code == "http_403"


async def test_direct_urls_are_fetched_and_recorded() -> None:
    net = FakeInternet()
    async with fetcher(net) as f:
        result = await build_connector("DIRECT_URL").run(
            ctx(direct_urls=[f"{ORG_SITE}/governance", f"{ORG_SITE}/governance", f"{ORG_SITE}/nope"]),
            f,
            CONFIG.get("DIRECT_URL"),
            budget(),
        )
    assert result.outcome == "succeeded" and len(result.documents) == 1
    assert result.attempted_urls == [f"{ORG_SITE}/governance", f"{ORG_SITE}/nope"]


async def test_news_items_carry_real_dates_and_publishers() -> None:
    net = FakeInternet()
    async with fetcher(net) as f:
        result = await build_connector("NEWS").run(ctx(), f, CONFIG.get("NEWS"), budget())
    assert result.outcome == "succeeded"
    docs = {d.url: d for d in result.documents}
    lawsuit = docs["https://dailywire.example/acme-lawsuit"]
    assert lawsuit.published_at == date(2026, 4, 2) and lawsuit.publisher_hint == "Daily Wire Example"
    assert docs["https://techpress.example/acme-transparency"].published_at == date(2026, 3, 9)
    assert len(docs) == 3  # the duplicate link across both queries counts once
    feed = parse_rss(
        "<rss><channel><item><title>T</title><link>https://x.example/a</link><pubDate>bad</pubDate></item></channel></rss>"
    )
    assert feed[0].published_at is None and feed[0].source_name is None


async def test_github_requires_a_verified_handle() -> None:
    net = FakeInternet()
    async with fetcher(net) as f:
        none = await build_connector("GITHUB").run(ctx(), f, CONFIG.get("GITHUB"), budget())
        assert none.outcome == "succeeded" and none.documents == [] and "no verified GitHub handle" in none.notes[0]
        assert not any("api.github.com" in u for u in net.requests)
        some = await build_connector("GITHUB").run(ctx(github_handle=GITHUB_HANDLE), f, CONFIG.get("GITHUB"), budget())
    assert len(some.documents) == 1 and "responsible-ai-toolkit" in some.documents[0].url
    assert some.documents[0].published_at == date(2026, 1, 10)


async def test_academic_requires_entity_match() -> None:
    net = FakeInternet()
    async with fetcher(net) as f:
        result = await build_connector("ACADEMIC").run(ctx(), f, CONFIG.get("ACADEMIC"), budget())
    assert len(result.documents) == 1 and "Acme Corporation" in result.documents[0].title  # type: ignore[operator]
    assert result.documents[0].url == "https://doi.org/10.1000/acme-audit"


async def test_wayback_fetches_the_archived_page() -> None:
    net = FakeInternet()
    async with fetcher(net) as f:
        result = await build_connector("WAYBACK").run(ctx(), f, CONFIG.get("WAYBACK"), budget())
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.archived_original_url == f"{ORG_SITE}/responsible-ai"
    assert doc.published_at == date(2024, 1, 15)
    assert b"first published in 2024" in doc.content
    assert any("older than 2015" in n for n in result.notes)


async def test_edgar_matches_the_filer_not_the_mention() -> None:
    assert filer_matches("ACME CORP (ACME)", "Acme Corp")
    assert not filer_matches("ACME GROWTH FUND TRUST", "Acme Corp")  # a fund that references the company
    assert not filer_matches(
        "ACME GROWTH FUND TRUST", "Acme Corp", cik=CIK, entity_id="9999999"
    )  # ...so the CIK decides
    assert filer_matches("whatever", "Acme Corp", cik=CIK, entity_id="1234567")
    assert not filer_matches("WELLS FARGO FUND", "Wells Fargo & Company")
    net = FakeInternet()
    async with fetcher(net) as f:
        result = await build_connector("EDGAR").run(ctx(cik=CIK), f, CONFIG.get("EDGAR"), budget())
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.published_at == date(2026, 2, 20) and "1234567/000123456726000012/acme-10k.htm" in doc.url
    assert doc.publisher_type_hint == "regulator_record"


async def test_iso_registry_without_url_records_an_empty_run() -> None:
    net = FakeInternet()
    async with fetcher(net) as f:
        result = await build_connector("ISO_42001").run(ctx(), f, CONFIG.get("ISO_42001"), budget())
    assert result.outcome == "succeeded" and result.documents == [] and result.notes


async def test_wikidata_properties_are_the_right_ones() -> None:
    net = FakeInternet()
    async with fetcher(net) as f:
        profile = await EntityResolver(f).resolve(ORG_NAME, ORG_DOMAIN)
    assert profile.wikidata_qid == WIKIDATA_QID and profile.resolved_name == "Acme Corporation"
    assert profile.cik == CIK  # from P5531, not the GeoNames id in P1566
    assert profile.lei == LEI and profile.github_handle == GITHUB_HANDLE
    assert profile.domain_verified and profile.verified_identifiers == {
        "wikidata_qid": WIKIDATA_QID,
        "cik": CIK,
        "lei": LEI,
        "github_handle": GITHUB_HANDLE,
    }
    assert profile.confidence >= 0.9


async def test_identifiers_verified_only_on_domain_match() -> None:
    net = FakeInternet(wikidata_domain="other.example")
    async with fetcher(net) as f:
        profile = await EntityResolver(f).resolve(ORG_NAME, ORG_DOMAIN)
    assert profile.cik == CIK  # resolved...
    assert not profile.domain_verified and profile.verified_identifiers == {}  # ...but not stored
    assert any("does not match" in w for w in profile.warnings)
    assert name_match_score("Acme Corp", "Acme Corporation") == 1.0
    assert name_match_score("Acme Corp", "Acme Growth Fund") < 0.6
