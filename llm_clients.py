"""
llm_clients.py – Pre-built LLM client factories with rate-limit retry logic.

All calls are wrapped in tenacity retry decorators that handle:
  - HTTP 429  (Too Many Requests)
  - HTTP 503  (Service Unavailable / overloaded)
  - Generic connection errors
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_together import ChatTogether
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
    before_sleep_log,
)

from config import get_settings

logger = logging.getLogger(__name__)
cfg = get_settings()

# ─── Exception helpers ────────────────────────────────────────────────────────


def _is_rate_limit(exc: BaseException) -> bool:
    """Return True for 429 / 503 / RateLimit errors from any provider."""
    msg = str(exc).lower()
    return any(
        tok in msg
        for tok in ("429", "rate limit", "rate_limit", "too many requests", "503", "overloaded")
    )


# ─── Retry decorator factory ──────────────────────────────────────────────────


def _make_retry(max_attempts: int):
    """Return a tenacity retry decorator tuned for free-tier LLM APIs.

    Uses *randomised exponential backoff* to avoid thundering-herd when
    multiple pipeline instances share the same key.
    """
    return retry(
        reraise=True,
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(multiplier=1, min=4, max=60),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


# ─── LLM Client wrappers ──────────────────────────────────────────────────────


class GroqClient:
    """Groq-backed chat client (Llama 3.3 70B) with automatic retry."""

    def __init__(self, model: str = cfg.architect_model, temperature: float = 0.0):
        self._llm = ChatGroq(
            model=model,
            temperature=temperature,
            api_key=cfg.groq_api_key,
        )
        self._retry = _make_retry(cfg.max_retries)

    def invoke(self, system: str, human: str) -> str:
        """Call the model and return the raw text response."""
        messages = [SystemMessage(content=system), HumanMessage(content=human)]

        @self._retry
        def _call() -> str:
            response = self._llm.invoke(messages)
            return response.content  # type: ignore[return-value]

        return _call()

    def invoke_json(self, system: str, human: str) -> Any:
        """Call the model and parse the response as JSON."""
        raw = self.invoke(system, human)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Attempt to extract JSON from markdown fences the model snuck in
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
            if match:
                return json.loads(match.group(1))
            raise ValueError(f"Model returned non-JSON output:\n{raw[:500]}")


class TogetherClient:
    """Together AI-backed chat client (Llama 4 Scout) with automatic retry."""

    def __init__(self, model: str = cfg.extractor_model, temperature: float = 0.0):
        self._llm = ChatTogether(
            model=model,
            temperature=temperature,
            together_api_key=cfg.together_api_key,
        )
        self._retry = _make_retry(cfg.max_retries)

    def invoke(self, system: str, human: str) -> str:
        messages = [SystemMessage(content=system), HumanMessage(content=human)]

        @self._retry
        def _call() -> str:
            response = self._llm.invoke(messages)
            return response.content  # type: ignore[return-value]

        return _call()

    def invoke_json(self, system: str, human: str) -> Any:
        raw = self.invoke(system, human)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
            if match:
                return json.loads(match.group(1))
            raise ValueError(f"Model returned non-JSON output:\n{raw[:500]}")


# ─── Singleton accessors ──────────────────────────────────────────────────────
# Import these in agents.py to avoid re-instantiating on every call.

_architect_client: GroqClient | None = None
_resolver_client: GroqClient | None = None
_extractor_client: TogetherClient | None = None


def get_architect_client() -> GroqClient:
    global _architect_client
    if _architect_client is None:
        _architect_client = GroqClient(model=cfg.architect_model)
    return _architect_client


def get_resolver_client() -> GroqClient:
    global _resolver_client
    if _resolver_client is None:
        _resolver_client = GroqClient(model=cfg.resolver_model)
    return _resolver_client


def get_extractor_client() -> TogetherClient:
    global _extractor_client
    if _extractor_client is None:
        _extractor_client = TogetherClient(model=cfg.extractor_model)
    return _extractor_client
