"""Async HTTP fetching with robots.txt, per-host pacing, budgets and retries.

Connectors fetch through :class:`Fetcher`. Every fetch is classified into a
connector-run outcome (succeeded, blocked, failed, rate_limited) so nothing is
silently dropped. A transport can be injected for tests (the fake internet).
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib import robotparser
from urllib.parse import urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser

from hai_core.generated.enums import ConnectorRunOutcome
from hai_pipeline.urls import canonical_url

BLOCK_STATUS = frozenset({401, 403, 406, 451})
RATE_LIMIT_STATUS = frozenset({429})
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class BudgetExhausted(Exception):  # noqa: N818 - domain-named exception
    """The time or page budget for this run is spent."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status: int | None
    content: bytes
    content_type: str
    outcome: str  # succeeded | blocked | failed | rate_limited
    error_code: str | None = None
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.outcome == "succeeded" and self.status is not None and 200 <= self.status < 300

    @property
    def text(self) -> str:
        if not self.content:
            return ""
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


@dataclass
class Budget:
    time_seconds: float
    pages: int
    started: float = field(default_factory=time.monotonic)
    used_pages: int = 0

    @property
    def remaining_seconds(self) -> float:
        return self.time_seconds - (time.monotonic() - self.started)

    def check(self) -> None:
        if self.remaining_seconds <= 0:
            raise BudgetExhausted("time budget exhausted")
        if self.used_pages >= self.pages:
            raise BudgetExhausted("page budget exhausted")

    def spend(self) -> None:
        self.used_pages += 1


class Fetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 15.0,
        min_interval_seconds: float = 0.5,
        max_retries: int = 2,
        respect_robots: bool = True,
        max_bytes: int = 3_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
        block_markers: tuple[str, ...] = (),
        block_status_codes: frozenset[int] = BLOCK_STATUS,
        sleep: object | None = None,
        retry_backoff_seconds: float = 2.0,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout_seconds
        self.min_interval = min_interval_seconds
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.max_bytes = max_bytes
        self.block_markers = tuple(m.lower() for m in block_markers)
        self.block_status_codes = block_status_codes
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/pdf,application/json,application/rss+xml,text/xml;q=0.9,*/*;q=0.8",  # noqa: E501
            },
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._rate_limited_until: dict[str, float] = {}
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self.retry_backoff = retry_backoff_seconds
        self.requests_made = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ robots
    async def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
            try:
                resp = await self._client.get(origin + "/robots.txt")
                self.requests_made += 1
                if resp.status_code == 200 and parser is not None:
                    parser.parse(resp.text.splitlines())
                else:
                    parser = None
            except httpx.HTTPError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url) or parser.can_fetch("*", url)

    async def _pace(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                await self._sleep(wait)  # type: ignore[operator]
        self._last_hit[host] = time.monotonic()

    # ------------------------------------------------------------------- fetch
    async def fetch(
        self, url: str, *, budget: Budget | None = None, method: str = "GET", headers: dict[str, str] | None = None
    ) -> FetchResult:
        canonical = canonical_url(url)
        if budget is not None:
            budget.check()
            budget.spend()
        started = time.monotonic()
        if budget is None:
            return await self._fetch(canonical, budget=budget, method=method, headers=headers)
        try:
            # The connector's deadline includes robots, pacing and retry sleeps,
            # not just the time before its first request.
            async with asyncio.timeout(budget.remaining_seconds):
                return await self._fetch(canonical, budget=budget, method=method, headers=headers)
        except TimeoutError:
            elapsed = int((time.monotonic() - started) * 1000)
            return FetchResult(canonical, canonical, None, b"", "", "failed", "time_budget_exhausted", elapsed)

    async def _fetch(
        self, canonical: str, *, budget: Budget | None, method: str, headers: dict[str, str] | None
    ) -> FetchResult:
        host = urlsplit(canonical).hostname or ""
        started = time.monotonic()
        if self._rate_limited_until.get(host, 0) > started:
            return FetchResult(
                canonical, canonical, 429, b"", "", ConnectorRunOutcome.RATE_LIMITED.value, "http_429", 0
            )
        if not await self._allowed(canonical):
            return FetchResult(canonical, canonical, None, b"", "", "blocked", "robots_disallow", 0)
        attempt = 0
        last_error = "unknown"
        while attempt <= self.max_retries:
            attempt += 1
            await self._pace(host)
            try:
                resp = await self._client.request(method, canonical, headers=headers)
                self.requests_made += 1
            except httpx.TimeoutException:
                last_error = "timeout"
                if attempt <= self.max_retries:
                    await self._sleep(min(self.retry_backoff * attempt, 5.0))  # type: ignore[operator]
                    continue
                break
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__.lower()
                if attempt <= self.max_retries:
                    await self._sleep(min(self.retry_backoff * attempt, 5.0))  # type: ignore[operator]
                    continue
                break
            elapsed = int((time.monotonic() - started) * 1000)
            ctype = resp.headers.get("content-type", "")
            content = resp.content[: self.max_bytes]
            if resp.status_code in RATE_LIMIT_STATUS:
                delay = _retry_after_seconds(resp.headers.get("retry-after"))
                if delay is None:
                    delay = min(self.retry_backoff * attempt, 5.0)
                self._rate_limited_until[host] = time.monotonic() + delay
                # Honour short server-requested waits. A long cooldown should
                # stop probes to this host rather than consume the entire run.
                if (
                    attempt <= self.max_retries
                    and delay <= 5.0
                    and (budget is None or delay < budget.remaining_seconds)
                ):
                    await self._sleep(delay)  # type: ignore[operator]
                    continue
                return FetchResult(
                    canonical,
                    str(resp.url),
                    resp.status_code,
                    b"",
                    ctype,
                    ConnectorRunOutcome.RATE_LIMITED.value,
                    "http_429",
                    elapsed,
                )
            self._rate_limited_until.pop(host, None)
            if resp.status_code in self.block_status_codes:
                return FetchResult(
                    canonical,
                    str(resp.url),
                    resp.status_code,
                    b"",
                    ctype,
                    "blocked",
                    f"http_{resp.status_code}",
                    elapsed,
                )
            if resp.status_code in RETRYABLE_STATUS and attempt <= self.max_retries:
                last_error = f"http_{resp.status_code}"
                await self._sleep(min(self.retry_backoff * attempt, 5.0))  # type: ignore[operator]
                continue
            if resp.status_code >= 400:
                return FetchResult(
                    canonical,
                    str(resp.url),
                    resp.status_code,
                    b"",
                    ctype,
                    "failed",
                    f"http_{resp.status_code}",
                    elapsed,
                )
            if "text/html" in ctype and self._looks_blocked(content):
                return FetchResult(
                    canonical, str(resp.url), resp.status_code, b"", ctype, "blocked", "challenge_page", elapsed
                )
            return FetchResult(canonical, str(resp.url), resp.status_code, content, ctype, "succeeded", None, elapsed)
        elapsed = int((time.monotonic() - started) * 1000)
        return FetchResult(canonical, canonical, None, b"", "", "failed", last_error, elapsed)

    def _looks_blocked(self, content: bytes) -> bool:
        if not self.block_markers:
            return False
        tree = LexborHTMLParser(content)
        headings = [" ".join(node.text().lower().split()) for node in tree.css("title, h1, h2")]
        tree.strip_tags(["head", "script", "style", "noscript", "template", "svg"])
        body = tree.body or tree.root
        visible = " ".join(body.text(separator=" ").lower().split()) if body is not None else ""
        # CDN script URLs and a noscript fallback occur on ordinary content
        # pages too. Challenge pages lead with the denial in a heading or a
        # short visible message. Policy prose may legitimately discuss access
        # denied events, so an embedded body-text mention is not a challenge.
        messages = [*headings, *([visible] if len(visible) < 2000 else [])]
        return any(_starts_with_marker(message, marker) for message in messages for marker in self.block_markers)

    async def get_json(
        self, url: str, *, budget: Budget | None = None, headers: dict[str, str] | None = None
    ) -> tuple[FetchResult, object | None]:
        import json

        result = await self.fetch(url, budget=budget, headers=headers)
        if not result.ok:
            return result, None
        try:
            return result, json.loads(result.text)
        except json.JSONDecodeError:
            return FetchResult(
                result.url,
                result.final_url,
                result.status,
                result.content,
                result.content_type,
                "failed",
                "bad_json",
                result.elapsed_ms,
            ), None


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _starts_with_marker(message: str, marker: str) -> bool:
    return message.startswith(marker) and (len(message) == len(marker) or not message[len(marker)].isalnum())
