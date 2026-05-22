from __future__ import annotations
import os
import json
import httpx
from typing import AsyncIterator

DEFAULT_BASE = "https://openrouter.ai/api/v1"


class OpenRouterProvider:
    """Async OpenRouter API client for agent LLM calls."""

    def __init__(self, api_key: str | None = None, base_url: str = DEFAULT_BASE):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        if not self.api_key:
            print("  [red]╳ WARNING: OPENROUTER_API_KEY not set.[/]")
            print("  [dim]  Agents won't be able to think.[/]")
            print("  [dim]  Set it: export OPENROUTER_API_KEY='sk-...'[/]")
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=120.0)

    async def chat(
        self,
        messages: list[dict],
        model: str = "openrouter/openai/gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Send a chat completion request to OpenRouter."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/armanicunningham/ai-os",
            "X-Title": "AI-OS",
        }
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if stream:
            body["stream"] = True
            return self._stream_chat(headers, body)

        resp = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def _stream_chat(self, headers: dict, body: dict) -> AsyncIterator[str]:
        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def close(self):
        await self.client.aclose()