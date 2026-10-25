"""Remote providers implemented directly on httpx (no vendor SDKs).

* OpenAI-compatible chat completions with strict JSON Schema output (OpenAI,
  Azure OpenAI, vLLM, LM Studio via ``base_url``).
* Anthropic messages with a forced tool call whose input schema is the finding schema.
* Ollama chat with the schema as the ``format`` and fenced JSON tolerated.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from hai_engine.llm.base import ProviderError, ProviderResponse, parse_json_object
from hai_engine.llm.prompts import PromptBundle, build_messages
from hai_engine.packs import EvidencePack


class _HttpProvider:
    name = "remote"

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout_seconds
        self.transport = transport
        self.extra_headers = extra_headers or {}

    @property
    def model_id(self) -> str:
        return f"{self.name}:{self.model}"

    async def _post(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(self.timeout)) as client:
            try:
                resp = await client.post(self.base_url + path, json=body, headers={**headers, **self.extra_headers})
            except httpx.HTTPError as exc:
                raise ProviderError(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{self.name}: response is not JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError(f"{self.name}: unexpected response shape")
        return data


class OpenAIProvider(_HttpProvider):
    name = "openai"

    def __init__(self, model: str, *, base_url: str = "https://api.openai.com/v1", **kw: Any) -> None:
        super().__init__(model, base_url=base_url, **kw)

    async def propose(
        self, pack: EvidencePack, prompt: PromptBundle, *, previous_errors: list[str] | None = None
    ) -> ProviderResponse:
        body = {
            "model": self.model,
            "messages": build_messages(prompt, pack, previous_errors),
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "criterion_finding", "strict": True, "schema": _strict_schema(prompt.schema)},
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = await self._post("/chat/completions", body, headers)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("openai: no message content") from exc
        text = content if isinstance(content, str) else json.dumps(content)
        return ProviderResponse(
            raw=parse_json_object(text),
            raw_text=text,
            usage=dict(data.get("usage") or {}),
            provider=self.name,
            model=self.model,
        )


class AnthropicProvider(_HttpProvider):
    name = "anthropic"
    TOOL_NAME = "submit_criterion_finding"

    def __init__(self, model: str, *, base_url: str = "https://api.anthropic.com", **kw: Any) -> None:
        super().__init__(model, base_url=base_url, **kw)

    async def propose(
        self, pack: EvidencePack, prompt: PromptBundle, *, previous_errors: list[str] | None = None
    ) -> ProviderResponse:
        messages = build_messages(prompt, pack, previous_errors)
        body = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0,
            "system": messages[0]["content"],
            "messages": [{"role": "user", "content": messages[1]["content"]}],
            "tools": [
                {
                    "name": self.TOOL_NAME,
                    "description": "Submit the criterion finding.",
                    "input_schema": _strict_schema(prompt.schema),
                }
            ],
            "tool_choice": {"type": "tool", "name": self.TOOL_NAME},
        }
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        data = await self._post("/v1/messages", body, headers)
        for block in data.get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == self.TOOL_NAME:
                raw = block.get("input")
                return ProviderResponse(
                    raw=raw if isinstance(raw, dict) else None,
                    raw_text=json.dumps(raw),
                    usage=dict(data.get("usage") or {}),
                    provider=self.name,
                    model=self.model,
                )
        raise ProviderError("anthropic: the forced tool call was not returned")


class OllamaProvider(_HttpProvider):
    name = "ollama"

    def __init__(self, model: str, *, base_url: str = "http://localhost:11434", **kw: Any) -> None:
        super().__init__(model, base_url=base_url, **kw)

    async def propose(
        self, pack: EvidencePack, prompt: PromptBundle, *, previous_errors: list[str] | None = None
    ) -> ProviderResponse:
        body = {
            "model": self.model,
            "messages": build_messages(prompt, pack, previous_errors),
            "stream": False,
            "format": _strict_schema(prompt.schema),
            "options": {"temperature": 0},
        }
        data = await self._post("/api/chat", body, {"Content-Type": "application/json"})
        try:
            text = str(data["message"]["content"])
        except (KeyError, TypeError) as exc:
            raise ProviderError("ollama: no message content") from exc
        usage: dict[str, Any] = {k: data[k] for k in ("prompt_eval_count", "eval_count") if k in data}
        return ProviderResponse(
            raw=parse_json_object(text), raw_text=text, usage=usage, provider=self.name, model=self.model
        )


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The generated schema without the metadata keys that strict decoders reject."""
    return {k: v for k, v in schema.items() if not k.startswith("x-") and k not in ("$schema", "$id")}
