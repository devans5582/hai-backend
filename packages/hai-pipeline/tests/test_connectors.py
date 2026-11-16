"""Connectors, fetcher and entity resolution against the fake internet (httpx.MockTransport)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from urllib.parse import parse_qs

import httpx
import pytest

from hai_ontology.loader import find_repo_root
from hai_pipeline.config import load_connectors
from hai_pipeline.connectors import CONNECTORS, build_connector
from hai_pipeline.connectors.base import ConnectorContext
from hai_pipeline.connectors.edgar import filer_matches
from hai_pipeline.connectors.news import parse_rss
from hai_pipeline.entity_resolution import EntityResolver, name_match_score
from hai_pipeline.http import Budget, Fetcher, _retry_after_seconds
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
        if path == "/limited":
            return httpx.Response(429, headers={"retry-after": "0"})
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


async def test_cdn_scripts_and_noscript_fallback_are_not_a_challenge() -> None:
    html = (
        "<html><head><title>Our responsible AI policy</title>"
        '<script src="https://cdnjs.cloudflare.com/library.js"></script>'
        '<script>const errors = ["Access Denied", "Just a moment..."];</script></head>'
        "<body><noscript>Please enable JavaScript to use search.</noscript>"
        "<main><h1>Our responsible AI policy</h1><p>We govern AI with human oversight.</p></main></body></html>"
    )
    async with Fetcher(
        user_agent="t",
        respect_robots=False,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html, headers={"content-type": "text/html"})),
        block_markers=tuple(str(m) for m in CONFIG.get("WEBSITE").opt("block_markers")),
    ) as f:
        result = await f.fetch("https://h.example/policy")
    assert result.ok and result.content


async def test_a_cloudflare_brand_mention_is_not_a_block() -> None:
    html = "<html><title>Cloudflare governance</title><body>Cloudflare publishes its AI policy.</body></html>"
    async with Fetcher(
        user_agent="t",
        respect_robots=False,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html, headers={"content-type": "text/html"})),
        block_markers=tuple(str(m) for m in CONFIG.get("WEBSITE").opt("block_markers")),
    ) as f:
        assert (await f.fetch("https://h.example/policy")).ok


async def test_short_ai_access_policy_is_not_a_challenge() -> None:
    html = (
        "<html><head><title>AI access control policy</title></head><body>"
        "<h1>AI access control policy</h1><p>Our systems log access denied events and require human approval "
        "for changes to model permissions. We review these events every quarter to confirm the controls "
        "remain effective and report findings to the AI governance board.</p></body></html>"
    )
    async with Fetcher(
        user_agent="t",
        respect_robots=False,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html, headers={"content-type": "text/html"})),
        block_markers=tuple(str(m) for m in CONFIG.get("WEBSITE").opt("block_markers")),
    ) as f:
        assert (await f.fetch("https://h.example/policy")).ok


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><header>Example</header><h1>Access Denied</h1><p>Request blocked.</p></body></html>",
        "<html><body>Access Denied. You do not have permission to view this resource.</body></html>",
        "<html><title>Just a moment...</title><body>Checking your browser.</body></html>",
    ],
)
async def test_visible_challenge_messages_remain_blocked(html: str) -> None:
    async with Fetcher(
        user_agent="t",
        respect_robots=False,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html, headers={"content-type": "text/html"})),
        block_markers=tuple(str(m) for m in CONFIG.get("WEBSITE").opt("block_markers")),
    ) as f:
        result = await f.fetch("https://h.example/policy")
    assert result.outcome == "blocked" and result.error_code == "challenge_page"


async def test_short_rate_limit_is_retried_and_long_cooldown_stops_host_probes() -> None:
    requests: list[str] = []
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if len(requests) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        if request.url.path == "/long":
            return httpx.Response(429, headers={"retry-after": "120"})
        return httpx.Response(200, text="AI policy")

    async def sleep(delay: float) -> None:
        waits.append(delay)

    async with Fetcher(
        user_agent="t",
        respect_robots=False,
        min_interval_seconds=0,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    ) as f:
        recovered = await f.fetch("https://h.example/short", budget=budget())
        limited = await f.fetch("https://h.example/long", budget=budget())
        suppressed = await f.fetch("https://h.example/another-policy", budget=budget())
        other_host = await f.fetch("https://other.example/policy", budget=budget())
    assert recovered.ok and other_host.ok
    assert limited.outcome == suppressed.outcome == "rate_limited"
    assert requests == ["/short", "/short", "/long", "/policy"]
    assert waits == [0]


def test_retry_after_supports_http_dates_and_invalid_values() -> None:
    assert _retry_after_seconds("2") == 2
    when = datetime.now(UTC) + timedelta(seconds=60)
    delay = _retry_after_seconds(format_datetime(when, usegmt=True))
    assert delay is not None and 58 <= delay <= 60
    assert _retry_after_seconds("bad") is None
    assert _retry_after_seconds("Infinity") is None
    assert _retry_after_seconds("NaN") is None


async def test_connector_time_budget_bounds_an_inflight_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, text="late")

    async with Fetcher(
        user_agent="t", respect_robots=False, transport=httpx.MockTransport(handler), timeout_seconds=15
    ) as f:
        result = await f.fetch("https://h.example/policy", budget=Budget(time_seconds=0.02, pages=1))
    assert result.outcome == "failed" and result.error_code == "time_budget_exhausted"


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
    assert f"{ORG_SITE}/privacy" in urls
    assert not any("/careers" in u for u in urls)
    assert any(f"{ORG_SITE}/ethics" in u for u in result.attempted_urls)


async def test_website_skips_malformed_links_and_seeds_the_redirected_origin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == ORG_DOMAIN:
            return httpx.Response(302, headers={"location": f"https://www.{ORG_DOMAIN}/"})
        if request.url.path == "/":
            html = (
                '<html><body><a href="https://bad.example:invalid/governance">Governance</a>'
                '<a href="data:text/plain,governance">Governance</a>'
                '<a href="/ai-policy">AI policy</a></body></html>'
            )
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        if request.url.path == "/ai-policy":
            return httpx.Response(
                200, text="<p>Our responsible AI policy. " * 30, headers={"content-type": "text/html"}
            )
        return httpx.Response(404)

    async with Fetcher(
        user_agent="t", respect_robots=False, min_interval_seconds=0, transport=httpx.MockTransport(handler)
    ) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, CONFIG.get("WEBSITE"), budget())
    assert result.outcome == "succeeded" and len(result.documents) == 1
    assert f"https://www.{ORG_DOMAIN}/ai-policy" in [d.url for d in result.documents]
    assert f"https://www.{ORG_DOMAIN}/responsible-ai" in result.attempted_urls


async def test_blocked_website_is_blocked_not_empty() -> None:
    net = FakeInternet(block_website=True)
    async with fetcher(net) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, CONFIG.get("WEBSITE"), budget())
    assert result.outcome == "blocked" and result.documents == [] and result.error_code == "http_403"


async def test_website_follows_governance_hubs_before_guessing_paths() -> None:
    pages = {
        "/": '<main><a href="/trust-center">Trust Center</a><a href="/privacy">Privacy policy</a></main>',
        "/trust-center": '<main><a href="/trust-center/responsible-ai/report">Responsible AI report</a></main>',
        "/trust-center/responsible-ai/report": "<main><p>We are committed to fairness and privacy in our AI systems. "
        "Our responsible AI board reviews every model release.</p></main>",
        "/privacy": "<main><p>Our privacy policy explains the categories of personal data used in AI training "
        "and how users may request deletion of their data.</p></main>",
    }
    config = CONFIG.get("WEBSITE")
    config = config.model_copy(update={"seed_paths": ["/guessed"], "min_text_chars": 0})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=pages.get(request.url.path, ""), headers={"content-type": "text/html"})

    async with Fetcher(
        user_agent="t", respect_robots=False, min_interval_seconds=0, transport=httpx.MockTransport(handler)
    ) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, config, Budget(time_seconds=5, pages=4))
    assert result.attempted_urls == [
        ORG_SITE + "/",
        ORG_SITE + "/trust-center",
        ORG_SITE + "/trust-center/responsible-ai/report",
        ORG_SITE + "/privacy",
    ]
    assert {d.url for d in result.documents} == {
        ORG_SITE + "/trust-center/responsible-ai/report",
        ORG_SITE + "/privacy",
    }


async def test_website_prioritises_ai_links_before_the_discovery_limit() -> None:
    home = (
        '<main><a href="/privacy">Privacy</a><a href="/legal">Legal</a>'
        '<a href="/responsible-ai-report">Responsible AI report</a></main>'
    )
    config = CONFIG.get("WEBSITE")
    config = config.model_copy(update={"max_discovered_links": 1, "seed_paths": [], "min_text_chars": 0})

    def handler(request: httpx.Request) -> httpx.Response:
        text = home if request.url.path == "/" else "<p>We are committed to responsible AI and human oversight.</p>"
        return httpx.Response(200, text=text, headers={"content-type": "text/html"})

    async with Fetcher(
        user_agent="t", respect_robots=False, min_interval_seconds=0, transport=httpx.MockTransport(handler)
    ) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, config, budget())
    assert result.attempted_urls == [ORG_SITE + "/", ORG_SITE + "/responsible-ai-report"]


async def test_http_success_with_only_a_javascript_shell_is_unavailable() -> None:
    shell = "<html><head><script src='/app.js'></script></head><body><div id='root'></div></body></html>"
    config = CONFIG.get("WEBSITE")
    config = config.model_copy(update={"seed_paths": []})
    async with Fetcher(
        user_agent="t",
        respect_robots=False,
        min_interval_seconds=0,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=shell, headers={"content-type": "text/html"})),
    ) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, config, budget())
    assert result.outcome == "failed" and result.error_code == "empty_content" and not result.documents


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
    assert doc.publisher_type_hint == "org_disclosure" and doc.publisher_hint == ORG_NAME


async def test_iso_registry_without_url_records_an_empty_run() -> None:
    net = FakeInternet()
    async with fetcher(net) as f:
        result = await build_connector("ISO_42001").run(ctx(), f, CONFIG.get("ISO_42001"), budget())
    assert result.outcome == "succeeded" and result.documents == [] and result.notes


async def test_edgar_prioritizes_current_filings_and_preserves_issuer_authorship() -> None:
    searches: list[dict[str, list[str]]] = []

    def hit(filename: str, filed: str) -> dict[str, object]:
        return {
            "_id": f"0001234567-26-000012:{filename}",
            "_source": {
                "adsh": "0001234567-26-000012",
                "entity_id": "1234567",
                "ciks": [CIK],
                "display_names": [ORG_NAME],
                "file_date": filed,
                "period_of_report": filed,
                "form_type": "10-K",
            },
        }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "efts.sec.gov":
            searches.append(parse_qs(request.url.query.decode()))
            return httpx.Response(
                200,
                json={"hits": {"hits": [hit("old.htm", "2018-10-24"), hit("new.htm", "2026-10-24")]}},
            )
        return httpx.Response(200, text="<p>Our AI governance board reviews the operation of every AI system.</p>")

    config = CONFIG.get("EDGAR")
    config = config.model_copy(update={"max_filings": 1})
    async with Fetcher(
        user_agent="t", respect_robots=False, min_interval_seconds=0, transport=httpx.MockTransport(handler)
    ) as f:
        result = await build_connector("EDGAR").run(ctx(cik=CIK, as_of=date(2026, 11, 10)), f, config, budget())
    assert searches[0]["sort"] == ["desc"] and searches[0]["enddt"] == ["2026-11-10"]
    assert searches[0]["ciks"] == [CIK] and " OR " in searches[0]["q"][0]
    assert len(result.documents) == 1 and result.documents[0].url.endswith("new.htm")
    assert result.documents[0].publisher_type_hint == "org_disclosure"
    assert result.documents[0].publisher_hint == ORG_NAME


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
