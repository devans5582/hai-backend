"""Connectors, fetcher and entity resolution against the fake internet (httpx.MockTransport)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from urllib.parse import parse_qs

import httpx
import pytest

from hai_ontology.loader import find_repo_root
from hai_pipeline.config import ConnectorConfig, load_connectors
from hai_pipeline.connectors import CONNECTORS, build_connector
from hai_pipeline.connectors.base import ConnectorContext
from hai_pipeline.connectors.edgar import filer_matches, own_site_mentions
from hai_pipeline.connectors.news import parse_rss
from hai_pipeline.connectors.website import LinkRanker, is_foreign_locale, section_of
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


def links_only(**overrides: object) -> ConnectorConfig:
    """The WEBSITE configuration with sitemaps, corporate hosts and edition probes switched off, so a
    test sees link following alone."""
    base = {"sitemap_paths": [], "corporate_hosts": [], "english_paths": [], "read_whole_site_below_documents": 0}
    return CONFIG.get("WEBSITE").model_copy(update={**base, **overrides})


def site(pages: dict[str, str], *, default: int = 404) -> httpx.MockTransport:
    """A one-host site: path -> HTML. PDFs are served for paths ending in .pdf."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path if request.url.host == ORG_DOMAIN else f"{request.url.host}{request.url.path}"
        if key not in pages:
            return httpx.Response(default, text="")
        return httpx.Response(200, text=pages[key], headers={"content-type": "text/html"})

    return httpx.MockTransport(handler)


def plain_fetcher(transport: httpx.MockTransport) -> Fetcher:
    return Fetcher(user_agent="t", respect_robots=False, min_interval_seconds=0, max_retries=0, transport=transport)


PROSE = (
    "<main><p>"
    + "We are committed to responsible AI and human oversight across every product we build. " * 3
    + "</p></main>"
)


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
    config = links_only(seed_paths=["/guessed"], min_text_chars=0)

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
    config = links_only(max_discovered_links=1, seed_paths=[], min_text_chars=0)

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


# ------------------------------------------------------------------ crawl ranking (methodology 6.0.0, ADR 0021)


def test_governance_links_outrank_storefront_and_career_pages() -> None:
    ranker = LinkRanker.from_config(CONFIG.get("WEBSITE"))
    responsible_ai = ranker.rank("Responsible AI", "https://x.example/en/about/responsible-ai")
    ethics = ranker.rank("Code of Conduct", "https://x.example/ethics/code-of-conduct")
    about = ranker.rank("Leadership", "https://x.example/company/leadership")
    locations = ranker.rank("Locations", "https://x.example/en/about/location")
    shop = ranker.rank("Shop AI glasses", "https://x.example/ai-glasses/shop-all")
    assert responsible_ai == 0 and ethics == 1 and about == 2
    assert locations is not None and shop is not None and min(locations, shop) > about
    assert ranker.rank("Winter sale", "https://x.example/deals/winter") is None
    # a link naming more governance topics is fetched first
    several = ranker.score("Ethics and compliance", "https://x.example/ethics-compliance")
    one = ranker.score("Ethics", "https://x.example/ethics")
    assert several is not None and one is not None and several < one


def test_locale_section_and_dated_path_helpers() -> None:
    assert is_foreign_locale("/de-de/ai") and is_foreign_locale("/zh-tw") and is_foreign_locale("/fr/ethique")
    assert not is_foreign_locale("/en-us/ai") and not is_foreign_locale("/us-en/about") and not is_foreign_locale("/ai")
    assert section_of("https://x.example/about/history/timeline") == "x.example/about"
    assert section_of("https://x.example/en-us/about/ethics") == "x.example/about"
    assert section_of("https://x.example/governance") is None  # a top-level page is in no section


async def test_one_section_cannot_take_the_page_budget() -> None:
    pages = {"/": "<main>" + "".join(f'<a href="/privacy/notice-{i}">Privacy notice {i}</a>' for i in range(12))}
    pages["/"] += '<a href="/ethics/code">Code of ethics</a></main>'
    pages.update({f"/privacy/notice-{i}": PROSE.replace("product", f"product {i}") for i in range(12)})
    pages["/ethics/code"] = PROSE.replace("product", "policy")
    async with plain_fetcher(site(pages)) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, links_only(seed_paths=[]), budget())
    urls = [d.url for d in result.documents]
    assert sum("/privacy/" in u for u in urls) == CONFIG.get("WEBSITE").opt("max_pages_per_section")
    assert f"{ORG_SITE}/ethics/code" in urls


async def test_a_flat_small_site_is_read_in_full() -> None:
    """Top-level pages are in no section, and a small site's oddly named pages are read too."""
    names = [
        "rating-scoring",
        "how-assessment-works",
        "why-us",
        "our-story",
        "method-notes",
        "scale-notes",
        "team-notes",
    ]
    pages = {"/": "<main>" + "".join(f'<a href="/{n}">{n}</a>' for n in names) + "</main>"}
    pages.update({f"/{n}": PROSE.replace("product", n) for n in names})
    config = links_only(seed_paths=[], read_whole_site_below_documents=20)
    async with plain_fetcher(site(pages)) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, config, budget())
    assert {d.url for d in result.documents} == {f"{ORG_SITE}/", *(f"{ORG_SITE}/{n}" for n in names)}
    # a large site stops at its governance pages: unranked links are not followed
    async with plain_fetcher(site(pages)) as f:
        bounded = await build_connector("WEBSITE").run(ctx(), f, links_only(seed_paths=[]), budget())
    assert {d.url for d in bounded.documents} <= {f"{ORG_SITE}/", f"{ORG_SITE}/our-story"}


async def test_query_variants_of_one_page_are_fetched_once() -> None:
    home = "<main>" + "".join(f'<a href="/responsible-ai?country={c}">Responsible AI</a>' for c in ("au", "be", "ca"))
    pages = {"/": home + "</main>", "/responsible-ai": PROSE}
    async with plain_fetcher(site(pages)) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, links_only(seed_paths=[]), budget())
    assert [u for u in result.attempted_urls if "responsible-ai" in u] == [f"{ORG_SITE}/responsible-ai?country=au"]


async def test_pages_filed_under_an_old_year_are_skipped() -> None:
    pages = {
        "/": '<main><a href="/news/1997/security-framework">Security framework</a>'
        '<a href="/news/2026/ai-governance-report">AI governance report</a></main>',
        "/news/1997/security-framework": PROSE,
        "/news/2026/ai-governance-report": PROSE.replace("product", "model"),
    }
    async with plain_fetcher(site(pages)) as f:
        result = await build_connector("WEBSITE").run(
            ctx(as_of=date(2026, 11, 22)), f, links_only(seed_paths=[]), budget()
        )
    assert [d.url for d in result.documents] == [f"{ORG_SITE}/news/2026/ai-governance-report"]


async def test_corporate_host_and_sitemap_are_read_when_the_storefront_has_no_governance() -> None:
    sitemap = "<urlset><url><loc>https://corporate.acme.example/purpose/ethics-integrity</loc></url></urlset>"

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == ORG_DOMAIN and path == "/":
            return httpx.Response(
                200, text="<main><a href='/deals'>Deals</a></main>", headers={"content-type": "text/html"}
            )
        if host == "corporate.acme.example" and path == "/":
            return httpx.Response(200, text=PROSE, headers={"content-type": "text/html"})
        if host == "corporate.acme.example" and path == "/sitemap.xml":
            return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})
        if host == "corporate.acme.example" and path == "/purpose/ethics-integrity":
            return httpx.Response(200, text=PROSE.replace("product", "store"), headers={"content-type": "text/html"})
        return httpx.Response(404)

    config = CONFIG.get("WEBSITE").model_copy(update={"seed_paths": [], "corporate_hosts": ["corporate"]})
    async with plain_fetcher(httpx.MockTransport(handler)) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, config, budget())
    assert result.outcome == "succeeded"
    assert "https://corporate.acme.example/purpose/ethics-integrity" in [d.url for d in result.documents]
    assert any("corporate host found" in n for n in result.notes)


async def test_a_refusing_host_is_not_probed_and_stays_blocked() -> None:
    """The homepage refused the crawler: no seed path is tried on that host, and a sibling host that
    answers with an empty shell does not turn the refusal into something else."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == ORG_DOMAIN:
            return httpx.Response(403, text="<title>Access Denied</title>", headers={"content-type": "text/html"})
        return httpx.Response(
            200, text="<html><body><div id='app'></div></body></html>", headers={"content-type": "text/html"}
        )

    config = CONFIG.get("WEBSITE").model_copy(update={"corporate_hosts": ["corporate"], "sitemap_paths": []})
    async with plain_fetcher(httpx.MockTransport(handler)) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, config, budget())
    assert result.outcome == "blocked" and result.error_code == "http_403" and not result.documents
    assert [u for u in seen if ORG_DOMAIN in u and "corporate" not in u] == [ORG_SITE + "/"]


async def test_a_report_hosted_elsewhere_is_the_organizations_own_disclosure() -> None:
    home = (
        '<main><a href="https://cdn.assets.example/reports/responsible-ai-transparency-report.pdf">'
        "Responsible AI Transparency Report</a>"
        '<a href="https://www.nist.gov/ai-rmf.pdf">AI risk framework</a>'
        '<a href="https://partner.example/ai-governance">AI governance at our partner</a></main>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == ORG_DOMAIN:
            return httpx.Response(200, text=home, headers={"content-type": "text/html"})
        if request.url.host == "cdn.assets.example":
            text = "We completed 14 model reviews in 2026 and published the results for every AI system. " * 5
            return httpx.Response(200, text=text, headers={"content-type": "text/plain"})
        return httpx.Response(200, text=PROSE, headers={"content-type": "text/html"})

    async with plain_fetcher(httpx.MockTransport(handler)) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, links_only(seed_paths=[]), budget())
    # the test host serves text, not a PDF: the link is followed but only a real PDF is kept
    assert "https://cdn.assets.example/reports/responsible-ai-transparency-report.pdf" in result.attempted_urls
    assert not any("nist.gov" in u or "partner.example" in u for u in result.attempted_urls)
    assert all(not d.published_by_organization for d in result.documents)


async def test_english_edition_is_used_when_the_site_answers_in_another_language() -> None:
    pages = {
        "/": '<html lang="zh-TW"><body><main><p>' + "鴻海科技集團 " * 30 + "</p></main></body></html>",
        "/en-us": '<html lang="en"><body>'
        + PROSE
        + '<a href="/en-us/governance">Corporate governance</a></body></html>',
        "/en-us/governance": PROSE.replace("product", "board"),
    }
    config = links_only(seed_paths=[], english_paths=["/en-us"])
    async with plain_fetcher(site(pages)) as f:
        result = await build_connector("WEBSITE").run(ctx(), f, config, budget())
    assert any("English edition used" in n for n in result.notes)
    assert f"{ORG_SITE}/en-us/governance" in [d.url for d in result.documents]


# ------------------------------------------------------------------ archive fallback


async def test_wayback_crawls_the_archive_when_the_live_site_is_unreadable() -> None:
    archived = {
        f"https://{ORG_DOMAIN}/": '<main><a href="/ethics/code-of-conduct">Code of conduct</a>'
        '<a href="/careers">Careers</a></main>' + PROSE,
        f"https://{ORG_DOMAIN}/ethics/code-of-conduct": PROSE.replace("product", "colleague"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host != "web.archive.org":
            return httpx.Response(404)
        original = url.split("id_/", 1)[1].replace("https:/a", "https://a")  # the fetcher folds "//"
        body = archived.get(original) or archived.get(original + "/")
        if body is None:
            return httpx.Response(404)
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/html", "content-location": url},
            request=request,
        )

    config = CONFIG.get("WAYBACK").model_copy(update={"corporate_hosts": [], "paths": []})
    context = ctx(as_of=date(2026, 11, 22), primary_outcome="blocked", primary_documents=0)
    async with plain_fetcher(httpx.MockTransport(handler)) as f:
        result = await build_connector("WAYBACK").run(context, f, config, budget())
    originals = sorted((d.archived_original_url or "").rstrip("/") for d in result.documents)
    assert originals == [f"https://{ORG_DOMAIN}", f"https://{ORG_DOMAIN}/ethics/code-of-conduct"]
    assert all(d.published_at == date(2026, 11, 22) and "archived copy" in (d.note or "") for d in result.documents)
    assert any("live site unreadable (blocked)" in n for n in result.notes)


async def test_wayback_keeps_to_fixed_paths_when_the_live_site_was_read() -> None:
    net = FakeInternet()
    context = ctx(primary_outcome="succeeded", primary_documents=12)
    async with fetcher(net) as f:
        result = await build_connector("WAYBACK").run(context, f, CONFIG.get("WAYBACK"), budget())
    assert len(result.documents) == 1 and not any("live site unreadable" in n for n in result.notes)


# ------------------------------------------------------------------ SEC registrant


def test_a_one_word_name_cannot_borrow_another_companys_filings() -> None:
    assert not filer_matches("HARVARD BIOSCIENCE INC  (HBIO)  (CIK 0001123494)", "Harvard")
    assert not filer_matches("MARRIOTT VACATIONS WORLDWIDE Corp  (VAC)", "Marriott")
    assert filer_matches("GOLDMAN SACHS GROUP INC", "Goldman Sachs")
    assert filer_matches("HOME DEPOT, INC.", "Home Depot")
    assert filer_matches("CHEVRON CORP /NEW/", "Chevron")


def test_own_site_mentions_tell_an_owner_from_a_mention() -> None:
    assert own_site_mentions("Available Information Our U.S. website is www.costco.com. We make", "costco.com") == (
        1,
        1,
    )
    assert own_site_mentions("We sell through Costco.com and other retailers.", "costco.com") == (0, 1)
    assert own_site_mentions("our direct-to-consumer channel, Meta.com, and our stores", "meta.com")[0] == 1
    assert own_site_mentions("Contact the auditor at partner@pwc.com for details.", "pwc.com") == (0, 1)
    assert own_site_mentions("see marriottvacationsworldwide.com for our website", "marriott.com") == (0, 0)


def _edgar_net(filings: dict[str, str]) -> httpx.MockTransport:
    """Full-text search returns two filers that mention aa.example; ``filings`` maps a CIK to its 10-K text."""

    def hit(cik: str, name: str) -> dict[str, object]:
        return {
            "_id": f"000{cik}-26-000001:annual.htm",
            "_source": {"adsh": f"000{cik}-26-000001", "ciks": [cik.zfill(10)], "display_names": [name]},
        }

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "efts.sec.gov":
            hits = [hit("111", "Regional Partner Airways Inc  (RPA)"), hit("222", "Skyline Airlines Group Inc.  (SKY)")]
            return httpx.Response(200, json={"hits": {"hits": hits}})
        if host == "data.sec.gov":
            cik = path.rsplit("CIK", 1)[1].split(".")[0].lstrip("0")
            recent = {
                "form": ["8-K", "DEF 14A", "10-K"],
                "filingDate": ["2026-10-01", "2026-04-20", "2026-02-18"],
                "accessionNumber": ["0000000000-26-000009", "0000000000-26-000002", "0000000000-26-000001"],
                "primaryDocument": ["earnings.htm", "proxy.htm", "annual.htm"],
            }
            return httpx.Response(200, json={"name": f"Filer {cik}", "filings": {"recent": recent}})
        if host == "www.sec.gov" and "/Archives/edgar/data/" in path:
            cik = path.split("/Archives/edgar/data/")[1].split("/")[0]
            body = filings.get(cik, "") if path.endswith("annual.htm") else "<p>Our Board oversees risk.</p>"
            return httpx.Response(200, text=body, headers={"content-type": "text/html"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_edgar_identifies_the_registrant_that_cites_the_domain_as_its_own() -> None:
    filings = {
        "111": "<p>We operate regional flights. Tickets are sold through aa.example and other carriers.</p>",
        "222": "<p>Our website is www.aa.example. Reports are available free of charge on our website "
        "at www.aa.example.</p>" + "<p>Customers book at aa.example.</p>" * 5,
    }
    context = ctx(organization_name="AA", organization_domain="aa.example", as_of=date(2026, 11, 22))
    async with plain_fetcher(_edgar_net(filings)) as f:
        result = await build_connector("EDGAR").run(context, f, CONFIG.get("EDGAR"), budget())
    assert any("CIK 0000000222 identified" in n for n in result.notes)
    # the proxy statement and the annual report, not the newest filing (an earnings release)
    assert [d.url.rsplit("/", 1)[1] for d in result.documents] == ["proxy.htm", "annual.htm"]
    assert all("/222/" in d.url and d.publisher_type_hint == "org_disclosure" for d in result.documents)


async def test_edgar_returns_nothing_when_no_filer_owns_the_domain() -> None:
    filings = {"111": "<p>Sold through aa.example.</p>", "222": "<p>Our auditor can be reached at x@aa.example.</p>"}
    context = ctx(organization_name="AA", organization_domain="aa.example", as_of=date(2026, 11, 22))
    async with plain_fetcher(_edgar_net(filings)) as f:
        result = await build_connector("EDGAR").run(context, f, CONFIG.get("EDGAR"), budget())
    assert result.documents == []
    assert any("none cites it as its own website" in n for n in result.notes)


# ------------------------------------------------------------------ entity resolution by domain


async def test_the_owner_of_the_submitted_domain_wins_over_a_better_name_match() -> None:
    def claims(site_url: str, cik: str) -> dict[str, object]:
        return {
            "P856": [{"mainsnak": {"datavalue": {"value": site_url}}}],
            "P5531": [{"mainsnak": {"datavalue": {"value": cik}}}],
        }

    entities = {
        "Q1": {"labels": {"en": {"value": "Delta"}}, "claims": claims("https://delta.gr", "0000000001")},
        "Q2": {
            "labels": {"en": {"value": "Delta Air Lines"}},
            "claims": claims("https://www.delta.example", "0000027904"),
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        host, query = request.url.host, parse_qs(request.url.query.decode())
        if host == "query.wikidata.org":
            binding = {"item": {"value": "http://www.wikidata.org/entity/Q2"}}
            return httpx.Response(200, json={"results": {"bindings": [binding]}})
        if host == "www.wikidata.org" and query.get("action") == ["wbsearchentities"]:
            return httpx.Response(200, json={"search": [{"id": "Q1", "label": "Delta", "description": "company"}]})
        if host == "www.wikidata.org":
            qid = query["ids"][0]
            return httpx.Response(200, json={"entities": {qid: entities[qid]}})
        return httpx.Response(200, json={"data": []})

    async with plain_fetcher(httpx.MockTransport(handler)) as f:
        profile = await EntityResolver(f).resolve("Delta", "delta.example")
    assert profile.wikidata_qid == "Q2" and profile.resolved_name == "Delta Air Lines"
    assert profile.domain_verified and profile.cik == "0000027904"
