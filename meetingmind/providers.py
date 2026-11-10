"""Bring-your-own-key LLM provider (any OpenAI-compatible chat completions API).

Works with OpenAI, Azure OpenAI-compatible gateways, Groq, Together, OpenRouter,
or a local Ollama / vLLM server, because they all speak `POST /chat/completions`.
Standard library only (no SDK), so the core package keeps zero dependencies.

The key is read from the environment and is never logged, stored, or put in an
error message. Retries cover rate limits (429) and server errors (5xx) with
exponential backoff plus jitter, and honor `Retry-After`. Anything else raises,
and `extract_with_llm` falls back to the rule engine so a meeting is never lost.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

RETRYABLE = {408, 409, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """Provider call failed. Message never contains the API key."""


@dataclass
class OpenAICompatible:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str = field(default="", repr=False)
    timeout: float = 30.0
    max_retries: int = 3
    backoff: float = 0.5
    temperature: float = 0.0
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    calls: int = 0  # requests sent, including retries (useful for cost tracking)

    def _request(self, prompt: str) -> urllib.request.Request:
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": "You return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:  # local servers (Ollama, vLLM) often need no key
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = self.base_url.rstrip("/") + "/chat/completions"
        return urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(30.0, float(retry_after))
            except ValueError:
                pass
        return self.backoff * (2**attempt) * (0.5 + random.random() / 2)

    def __call__(self, prompt: str) -> str:
        last = "no attempt made"
        for attempt in range(self.max_retries + 1):
            self.calls += 1
            try:
                with urllib.request.urlopen(self._request(prompt), timeout=self.timeout) as r:
                    data = json.loads(r.read().decode())
                return data["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code not in RETRYABLE:
                    raise ProviderError(f"{last} from {self.base_url}") from None
                wait = self._delay(attempt, e.headers.get("Retry-After") if e.headers else None)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = type(e).__name__
                wait = self._delay(attempt, None)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                raise ProviderError(f"unexpected response shape from {self.base_url}") from None
            if attempt < self.max_retries:
                self.sleep(wait)
        raise ProviderError(f"gave up after {self.max_retries + 1} attempts ({last})")


def from_env(env: dict[str, str] | None = None) -> OpenAICompatible | None:
    """Build a provider from MEETINGMIND_LLM_* variables, or None if not configured.

    MEETINGMIND_LLM_API_KEY   key (optional for local servers if BASE_URL is set)
    MEETINGMIND_LLM_BASE_URL  default https://api.openai.com/v1
    MEETINGMIND_LLM_MODEL     default gpt-4o-mini
    """
    env = os.environ if env is None else env
    key = env.get("MEETINGMIND_LLM_API_KEY", "").strip()
    base = env.get("MEETINGMIND_LLM_BASE_URL", "").strip()
    if not key and not base:
        return None
    return OpenAICompatible(
        base_url=base or "https://api.openai.com/v1",
        model=env.get("MEETINGMIND_LLM_MODEL", "").strip() or "gpt-4o-mini",
        api_key=key,
    )
