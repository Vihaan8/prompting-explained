"""Provider-agnostic async LLM client, a call budget, and a deterministic fake for tests.

Every provider implements `LLM.complete`. To add OpenAI, write an `OpenAILLM` with the
same signature and register it in `make_llm`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import Counter
from typing import Any, Callable, Protocol

from .config import Config
from .types import LLMResponse

log = logging.getLogger("prompting_explained.llm")


class BudgetExceeded(RuntimeError):
    """Raised when an analysis would go over `max_calls_per_analysis`."""


class LLM(Protocol):
    """The interface every provider implements."""

    model: str

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send one user message and return the text answer.

        When `json_schema` is given, the provider constrains the answer to that schema.
        """
        ...


class AnthropicLLM:
    """Claude via the official `anthropic` SDK, with tenacity retries on transient errors."""

    def __init__(self, config: Config, api_key: str | None = None):
        import anthropic

        self._anthropic = anthropic
        self.config = config
        self.model = config.model
        # Retries are handled by tenacity below so backoff and logging live in one place.
        self.client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    async def aclose(self) -> None:
        """Close the HTTP client. Call it inside the event loop that made the requests."""
        await self.client.close()

    def _request(self, prompt: str, max_tokens: int, json_schema: dict | None) -> dict:
        cfg = self.config
        req: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": cfg.thinking},
        }
        output_config: dict[str, Any] = {}
        if cfg.effort:
            output_config["effort"] = cfg.effort
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if output_config:
            req["output_config"] = output_config
        if cfg.temperature is not None:
            req["temperature"] = cfg.temperature
        return req

    def _retryable(self, exc: BaseException) -> bool:
        a = self._anthropic
        if isinstance(exc, a.APIConnectionError):
            return True
        return isinstance(exc, a.APIStatusError) and exc.status_code in {408, 409, 429, 500, 502, 503, 504, 529}

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Call the Messages API once, retrying rate limits and server errors with backoff."""
        from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential

        req = self._request(prompt, max_tokens or self.config.max_tokens, json_schema)
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(self._retryable),
            wait=wait_random_exponential(multiplier=1, max=30),
            stop=stop_after_attempt(6),
            reraise=True,
            before_sleep=lambda rs: log.warning(
                "retrying after %s (attempt %d)", type(rs.outcome.exception()).__name__, rs.attempt_number
            ),
        ):
            with attempt:
                msg = await self.client.messages.create(**req)
        text = "".join(b.text for b in msg.content if b.type == "text")
        resp = LLMResponse(
            text=text,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            model=msg.model,
            stop_reason=msg.stop_reason,
        )
        log.info("call model=%s in=%d out=%d stop=%s", resp.model, resp.input_tokens, resp.output_tokens, resp.stop_reason)
        return resp


class FakeLLM:
    """Deterministic stand-in for tests and offline development.

    `responder(prompt, json_schema)` returns the answer text. Every prompt is recorded
    in `self.prompts`. Token counts are word counts so cost tracking can be tested.
    """

    def __init__(self, responder: Callable[[str, dict | None], str], model: str = "fake-llm"):
        self.responder = responder
        self.model = model
        self.prompts: list[str] = []

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Return the responder's answer for this prompt."""
        self.prompts.append(prompt)
        text = self.responder(prompt, json_schema)
        return LLMResponse(
            text=text,
            input_tokens=len(prompt.split()),
            output_tokens=len(text.split()),
            model=self.model,
            stop_reason="end_turn",
        )


class BudgetedLLM:
    """Wraps an LLM with a concurrency limit, a hard call budget, and usage counters.

    One instance per analysis. Each call is tagged with a `kind` (segment, baseline,
    ablation, explain, ...) so the cost breakdown can be reported.
    """

    def __init__(self, inner: LLM, max_calls: int, max_concurrency: int = 8):
        self.inner = inner
        self.model = inner.model
        self.max_calls = max_calls
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.by_kind: Counter[str] = Counter()
        self._sem = asyncio.Semaphore(max_concurrency)

    def reserve(self, n: int) -> None:
        """Fail before spending anything if `n` more calls would exceed the budget."""
        if self.calls + n > self.max_calls:
            raise BudgetExceeded(
                f"this analysis needs {self.calls + n} model calls but the limit is {self.max_calls} "
                f"(max_calls_per_analysis in config.yaml)"
            )

    async def complete(self, prompt: str, *, kind: str = "other", **kwargs) -> LLMResponse:
        """Make one call, counting it against the budget."""
        self.reserve(1)
        self.calls += 1  # counted at reservation so concurrent calls can't overshoot
        self.by_kind[kind] += 1
        async with self._sem:
            resp = await self.inner.complete(prompt, **kwargs)
        self.input_tokens += resp.input_tokens
        self.output_tokens += resp.output_tokens
        return resp


def make_llm(config: Config, api_key: str | None = None) -> LLM:
    """Build the configured provider. Reads ANTHROPIC_API_KEY from .env if not given."""
    from dotenv import load_dotenv

    load_dotenv()
    if config.provider == "anthropic":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add a key.")
        return AnthropicLLM(config, api_key=key)
    raise ValueError(f"unknown provider: {config.provider}")


def parse_json(text: str) -> Any:
    """json.loads that returns None instead of raising."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
