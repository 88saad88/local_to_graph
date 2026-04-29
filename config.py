"""
config.py – Centralised settings loaded from environment / .env file.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@lru_cache(maxsize=1)
def get_settings() -> "Settings":
    return Settings()


class Settings:
    # ── LLM ───────────────────────────────────────────────────────────────────
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    together_api_key: str = os.getenv("TOGETHER_API_KEY", "")

    architect_model: str = os.getenv("ARCHITECT_MODEL", "llama-3.3-70b-versatile")
    resolver_model: str = os.getenv("RESOLVER_MODEL", "llama-3.3-70b-versatile")
    extractor_model: str = os.getenv(
        "EXTRACTOR_MODEL",
        "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    )

    # ── FalkorDB ──────────────────────────────────────────────────────────────
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    falkordb_graph_name: str = os.getenv("FALKORDB_GRAPH_NAME", "knowledge_graph")

    # ── Pipeline ──────────────────────────────────────────────────────────────
    max_retries: int = int(os.getenv("MAX_RETRIES", "6"))
    max_chunk_tokens: int = int(os.getenv("MAX_CHUNK_TOKENS", "2048"))
    max_iterations: int = 10  # hard cap on the main loop
