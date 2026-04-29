"""
agents.py – The four pipeline nodes wired into the LangGraph StateGraph.

Node overview
─────────────
  architect_node   → Updates ontology (Llama 3.3 70B / Groq)
  extractor_node   → Extracts raw triplets (Llama 4 Scout / Together)
  resolver_node    → De-duplicates entities (Llama 3.3 70B / Groq)
  registrar_node   → Writes to FalkorDB (pure tool, no LLM)
"""
from __future__ import annotations

import json
import logging

from state import GraphState
from prompts import (
    ARCHITECT_SYSTEM, ARCHITECT_HUMAN,
    EXTRACTOR_SYSTEM, EXTRACTOR_HUMAN,
    RESOLVER_SYSTEM, RESOLVER_HUMAN,
)
from llm_clients import get_architect_client, get_extractor_client, get_resolver_client
from db import merge_triplets, get_graph_stats
from config import get_settings

logger = logging.getLogger(__name__)
cfg = get_settings()

# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECT NODE
# ─────────────────────────────────────────────────────────────────────────────


def architect_node(state: GraphState) -> GraphState:
    """Governs the ontology.

    Reads the current ontology + new raw_text, then returns a (possibly)
    updated ontology that respects the 80% Rule.
    """
    logger.info("[Architect] Updating ontology …")

    client = get_architect_client()

    human_prompt = ARCHITECT_HUMAN.format(
        current_ontology=json.dumps(state["ontology"], indent=2),
        raw_text=state["raw_text"][:3000],  # cap to stay within context
    )

    try:
        updated_ontology = client.invoke_json(ARCHITECT_SYSTEM, human_prompt)
        logger.info(
            "[Architect] Ontology classes: %s",
            updated_ontology.get("classes", []),
        )
        return {**state, "ontology": updated_ontology, "error": None}
    except Exception as exc:
        logger.error("[Architect] Failed: %s", exc)
        return {**state, "error": f"Architect failed: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTOR NODE
# ─────────────────────────────────────────────────────────────────────────────


def extractor_node(state: GraphState) -> GraphState:
    """Extracts (S→P→O) triplets from raw_text using the current ontology.

    Uses the lighter Llama 4 Scout model on Together AI for cost efficiency.
    """
    logger.info("[Extractor] Extracting triplets …")

    client = get_extractor_client()

    human_prompt = EXTRACTOR_HUMAN.format(
        ontology=json.dumps(state["ontology"], indent=2),
        raw_text=state["raw_text"][:3000],
    )

    try:
        triplets = client.invoke_json(EXTRACTOR_SYSTEM, human_prompt)

        # Validate structure
        if not isinstance(triplets, list):
            raise ValueError(f"Expected list, got {type(triplets)}")

        # Sanitise: keep only dicts with required keys
        valid = [
            t for t in triplets
            if isinstance(t, dict) and {"subject", "predicate", "object"}.issubset(t)
        ]

        logger.info("[Extractor] Raw triplets extracted: %d", len(valid))
        return {**state, "new_triplets": valid, "error": None}
    except Exception as exc:
        logger.error("[Extractor] Failed: %s", exc)
        return {**state, "new_triplets": [], "error": f"Extractor failed: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# RESOLVER NODE
# ─────────────────────────────────────────────────────────────────────────────


def resolver_node(state: GraphState) -> GraphState:
    """De-duplicates and normalises entity names across the triplet list.

    Uses the larger Llama 3.3 70B model for accurate coreference resolution.
    """
    logger.info("[Resolver] Resolving entities …")

    raw_triplets = state["new_triplets"]
    if not raw_triplets:
        logger.info("[Resolver] No triplets to resolve — skipping.")
        return {**state, "resolved_entities": [], "error": None}

    client = get_resolver_client()

    human_prompt = RESOLVER_HUMAN.format(
        triplets=json.dumps(raw_triplets, indent=2)
    )

    try:
        resolved = client.invoke_json(RESOLVER_SYSTEM, human_prompt)

        if not isinstance(resolved, list):
            raise ValueError(f"Expected list, got {type(resolved)}")

        logger.info("[Resolver] Resolved triplets: %d", len(resolved))
        return {**state, "resolved_entities": resolved, "error": None}
    except Exception as exc:
        logger.error("[Resolver] Failed: %s — falling back to raw triplets", exc)
        # Graceful degradation: use raw triplets if resolution fails
        return {
            **state,
            "resolved_entities": raw_triplets,
            "error": f"Resolver failed (fallback used): {exc}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRAR NODE  (Tool — no LLM)
# ─────────────────────────────────────────────────────────────────────────────


def registrar_node(state: GraphState) -> GraphState:
    """Persists resolved triplets to FalkorDB via Cypher MERGE queries.

    This is a pure tool node — it calls no LLM.  Designed to be the final
    step in each iteration.
    """
    logger.info("[Registrar] Writing triplets to FalkorDB …")

    triplets = state["resolved_entities"]
    if not triplets:
        logger.info("[Registrar] Nothing to write.")
        return {**state, "iteration_count": state["iteration_count"] + 1}

    try:
        written = merge_triplets(triplets)
        stats = get_graph_stats()
        logger.info(
            "[Registrar] Written %d triplets. Graph: %d nodes, %d edges.",
            written, stats["nodes"], stats["edges"],
        )
    except Exception as exc:
        logger.error("[Registrar] DB error: %s", exc)
        return {
            **state,
            "iteration_count": state["iteration_count"] + 1,
            "error": f"Registrar failed: {exc}",
        }

    return {
        **state,
        "new_triplets": [],
        "resolved_entities": [],
        "iteration_count": state["iteration_count"] + 1,
        "error": None,
    }
