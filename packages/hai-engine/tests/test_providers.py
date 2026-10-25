"""Remote providers against mocked HTTP: request shapes and response parsing."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hai_engine.llm.base import ProviderError, parse_json_object
from hai_engine.llm.heuristic import propose_from_ladder
from hai_engine.llm.prompts import PromptBundle
from hai_engine.llm.registry import build_provider
from hai_engine.llm.remote import AnthropicProvider, OllamaProvider, OpenAIProvider
from hai_engine.packs import EvidencePack


def _capture(response: dict[str, Any], status: int = 200) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=response)

    return seen, httpx.MockTransport(handler)


async def test_openai_uses_strict_json_schema(pack: EvidencePack, prompt: PromptBundle) -> None:
    finding = propose_from_ladder(pack)
    seen, transport = _capture(
        {"choices": [{"message": {"content": json.dumps(finding)}}], "usage": {"total_tokens": 10}}
    )
    provider = OpenAIProvider("gpt-test", base_url="https://llm.example/v1", api_key="k", transport=transport)
    response = await provider.propose(pack, prompt)
    assert response.raw == finding and response.usage == {"total_tokens": 10} and provider.model_id == "openai:gpt-test"
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/chat/completions" and seen[0].headers["authorization"] == "Bearer k"
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    schema = rf["json_schema"]["schema"]
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    assert "x-manifest-hash" not in schema and "$schema" not in schema
    assert (
        body["messages"][0]["role"] == "system"
        and json.loads(body["messages"][1]["content"])["data"]["criterion"]["code"] == "SAF-01"
    )


async def test_anthropic_forces_the_tool_call(pack: EvidencePack, prompt: PromptBundle) -> None:
    finding = propose_from_ladder(pack)
    seen, transport = _capture(
        {
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "name": "submit_criterion_finding", "input": finding},
            ],
            "usage": {"input_tokens": 5},
        }
    )
    provider = AnthropicProvider("claude-test", api_key="k", transport=transport)
    response = await provider.propose(pack, prompt)
    assert response.raw == finding
    body = json.loads(seen[0].content)
    assert (
        seen[0].url.path == "/v1/messages"
        and seen[0].headers["x-api-key"] == "k"
        and seen[0].headers["anthropic-version"]
    )
    assert body["tool_choice"] == {"type": "tool", "name": "submit_criterion_finding"}
    assert body["tools"][0]["input_schema"]["properties"]["criterion_code"]["enum"]
    assert isinstance(body["system"], str) and body["messages"][0]["role"] == "user"
    _, no_tool = _capture({"content": [{"type": "text", "text": "I refuse"}]})
    with pytest.raises(ProviderError, match="forced tool call"):
        await AnthropicProvider("claude-test", api_key="k", transport=no_tool).propose(pack, prompt)


async def test_ollama_parses_fenced_json(pack: EvidencePack, prompt: PromptBundle) -> None:
    finding = propose_from_ladder(pack)
    seen, transport = _capture({"message": {"content": "```json\n" + json.dumps(finding) + "\n```"}, "eval_count": 7})
    provider = OllamaProvider("llama-test", transport=transport)
    response = await provider.propose(pack, prompt)
    assert response.raw == finding and response.usage == {"eval_count": 7}
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/api/chat" and body["stream"] is False and body["format"]["type"] == "object"


async def test_http_failures_become_provider_errors(pack: EvidencePack, prompt: PromptBundle) -> None:
    _, transport = _capture({"error": "rate limited"}, status=429)
    with pytest.raises(ProviderError, match="HTTP 429"):
        await OpenAIProvider("m", base_url="https://llm.example/v1", transport=transport).propose(pack, prompt)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ProviderError, match="ConnectError"):
        await OpenAIProvider("m", base_url="https://llm.example/v1", transport=httpx.MockTransport(boom)).propose(
            pack, prompt
        )


def test_parse_json_object_tolerates_prose_and_fences() -> None:
    assert parse_json_object('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('{"a": 1} trailing') == {"a": 1}
    assert parse_json_object("[1, 2]") is None
    assert parse_json_object("not json") is None


def test_registry() -> None:
    assert build_provider("heuristic", "").model_id == "heuristic:ladder-1"
    assert build_provider("openai", "gpt", base_url="https://vllm.example/v1").model_id == "openai:gpt"
    assert build_provider("anthropic", "claude").name == "anthropic"
    assert build_provider("ollama", "llama3").name == "ollama"
    with pytest.raises(ValueError, match="unknown LLM provider"):
        build_provider("gemini", "x")
