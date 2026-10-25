"""Build a provider from settings or explicit arguments."""

from __future__ import annotations

import httpx

from hai_core.settings import Settings
from hai_engine.llm.base import Provider
from hai_engine.llm.heuristic import HeuristicProvider
from hai_engine.llm.remote import AnthropicProvider, OllamaProvider, OpenAIProvider

PROVIDERS = ("heuristic", "openai", "anthropic", "ollama")


def build_provider(
    name: str,
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_seconds: float = 60.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Provider:
    if name == "heuristic":
        return HeuristicProvider(model or "ladder-1")
    kw = {"api_key": api_key, "timeout_seconds": timeout_seconds, "transport": transport}
    if name == "openai":
        return OpenAIProvider(model, base_url=base_url or "https://api.openai.com/v1", **kw)
    if name == "anthropic":
        return AnthropicProvider(model, base_url=base_url or "https://api.anthropic.com", **kw)
    if name == "ollama":
        return OllamaProvider(model, base_url=base_url or "http://localhost:11434", **kw)
    raise ValueError(f"unknown LLM provider {name!r}; choose one of {PROVIDERS}")


def provider_from_settings(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> Provider:
    return build_provider(
        settings.llm_provider,
        settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
        timeout_seconds=settings.llm_timeout_seconds,
        transport=transport,
    )


def second_opinion_from_settings(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> Provider | None:
    if not settings.llm_second_opinion_provider:
        return None
    return build_provider(
        settings.llm_second_opinion_provider,
        settings.llm_second_opinion_model or "",
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
        timeout_seconds=settings.llm_timeout_seconds,
        transport=transport,
    )
