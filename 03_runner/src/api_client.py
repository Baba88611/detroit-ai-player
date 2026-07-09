from __future__ import annotations

import json
import os
import time
from typing import Any

import requests


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str = "openai",
        temperature: float = 0.7,
        max_retries: int = 3,
    ):
        self.base_url = (base_url or os.environ["LLM_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["LLM_API_KEY"]
        self.model = model or os.environ["LLM_MODEL"]
        self.provider = provider
        self.temperature = temperature
        self.max_retries = max_retries
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_creation_input_tokens = 0
        self.total_cache_read_input_tokens = 0

    def choose(
        self,
        node_id: str,
        _context: str,
        choices: list[dict[str, str]],
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        raw_text = self._call_api(messages)
        return self._parse_response(raw_text, node_id, choices)

    def token_usage(self) -> dict[str, int]:
        usage = {
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }
        input_tokens = getattr(self, "total_input_tokens", 0)
        cache_creation_tokens = getattr(self, "total_cache_creation_input_tokens", 0)
        cache_read_tokens = getattr(self, "total_cache_read_input_tokens", 0)
        output_tokens = getattr(self, "total_output_tokens", 0)
        anthropic_usage = {
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "output_tokens": output_tokens,
            "total_input_tokens": input_tokens + cache_creation_tokens + cache_read_tokens,
        }
        if any(anthropic_usage.values()):
            usage.update(anthropic_usage)
        return usage

    def _call_api(self, messages: list[dict[str, str]]) -> str:
        if self.provider == "anthropic":
            return self._call_anthropic_api(messages)
        return self._call_openai_compatible_api(messages)

    def _call_openai_compatible_api(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                self.total_prompt_tokens += usage.get("prompt_tokens", 0)
                self.total_completion_tokens += usage.get("completion_tokens", 0)
                return data["choices"][0]["message"]["content"]
            except (requests.RequestException, KeyError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"API call failed after {self.max_retries} attempts: {e}") from e
                time.sleep(2 ** attempt)

        raise RuntimeError("API call failed unexpectedly")

    def _call_anthropic_api(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        system_content, anthropic_messages = self._split_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": 1024,
            "temperature": self.temperature,
            "cache_control": {"type": "ephemeral"},
        }
        if system_content:
            payload["system"] = system_content

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
                cache_read_tokens = usage.get("cache_read_input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                total_input_tokens = input_tokens + cache_creation_tokens + cache_read_tokens

                self.total_input_tokens += input_tokens
                self.total_cache_creation_input_tokens += cache_creation_tokens
                self.total_cache_read_input_tokens += cache_read_tokens
                self.total_output_tokens += output_tokens
                self.total_prompt_tokens += total_input_tokens
                self.total_completion_tokens += output_tokens
                return self._anthropic_text_content(data)
            except (requests.RequestException, KeyError, ValueError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"API call failed after {self.max_retries} attempts: {e}") from e
                time.sleep(2 ** attempt)

        raise RuntimeError("API call failed unexpectedly")

    def _split_anthropic_messages(self, messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
        system_parts = [message["content"] for message in messages if message["role"] == "system"]
        anthropic_messages = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
            if message["role"] in {"user", "assistant"}
        ]
        return "\n\n".join(system_parts), anthropic_messages

    def _anthropic_text_content(self, data: dict[str, Any]) -> str:
        parts = data["content"]
        text_parts = [part.get("text", "") for part in parts if part.get("type") == "text"]
        text = "".join(text_parts).strip()
        if not text:
            raise ValueError("Anthropic response did not contain text content")
        return text

    def _parse_response(
        self,
        raw_text: str,
        node_id: str,
        choices: list[dict[str, str]],
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_text)
            choice_index = int(parsed["choice"]) - 1
            reasoning = parsed.get("reasoning", "")
            if 0 <= choice_index < len(choices):
                return {
                    "choice_id": choices[choice_index]["id"],
                    "reasoning": reasoning,
                    "raw": raw_text,
                }
        except (json.JSONDecodeError, KeyError, ValueError, IndexError):
            pass

        for i, choice in enumerate(choices, start=1):
            if str(i) in raw_text:
                return {
                    "choice_id": choice["id"],
                    "reasoning": raw_text,
                    "raw": raw_text,
                    "_parse_warning": "fallback: extracted number from text",
                }

        return {
            "choice_id": choices[0]["id"],
            "reasoning": raw_text,
            "raw": raw_text,
            "_parse_warning": f"failed to parse, defaulted to first choice at node {node_id}",
        }
