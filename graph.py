"""
graph.py – LangGraph StateGraph assembly.

Architecture
────────────
                 ┌─────────────┐
   START ──────► │  Architect  │ (updates ontology)
                 └──────┬──────┘
                        │
                 ┌──────▼──────┐
                 │  Extractor  │ (extracts raw triplets)
                 └──────┬──────┘
                        │
                 ┌──────▼──────┐
                 │  Resolver   │ (entity de-duplication)
                 └──────┬──────┘
                        │
                 ┌──────▼──────┐
                 │  Registrar  │ (writes to FalkorDB)
                 └──────┬──────┘
                        │
              ┌─────────▼──────────┐
              │  should_continue?  │ (conditional edge)
              └──────┬──────┬──────┘
                     │      │
               more  │      │ done / error
               chunks│      │
                     ▼      ▼
                 Architect  END
"""
from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from state import GraphState
from agents import architect_node, extractor_node, registrar_node, resolver_node
from config import get_settings

logger = logging.getLogger(__name__)
cfg = get_settings()


# ─── Conditional routing ──────────────────────────────────────────────────────


def should_continue(state: GraphState) -> str:
    """Routing function called after the Registrar.

    Returns
    -------
    "continue" → loop back to Architect with the next chunk
    "end"       → terminate the graph
    """
    if state.get("error") and "Registrar" in (state.get("error") or ""):
        # Hard DB error — abort
        logger.error("Hard stop: %s", state["error"])
        return "end"

    if state["iteration_count"] >= cfg.max_iterations:
        logger.warning("Max iterations (%d) reached — stopping.", cfg.max_iterations)
        return "end"

    # The pipeline orchestrator sets raw_text="" to signal no more chunks
    if not state.get("raw_text", "").strip():
        return "end"

    return "continue"


# ─── Graph builder ────────────────────────────────────────────────────────────


def build_graph() -> StateGraph:
    """Assemble and compile the LangGraph StateGraph.

    Returns a compiled graph ready to be invoked with an initial GraphState.
    """
    builder = StateGraph(GraphState)

    # Register nodes
    builder.add_node("architect", architect_node)
    builder.add_node("extractor", extractor_node)
    builder.add_node("resolver", resolver_node)
    builder.add_node("registrar", registrar_node)

    # Linear edges
    builder.set_entry_point("architect")
    builder.add_edge("architect", "extractor")
    builder.add_edge("extractor", "resolver")
    builder.add_edge("resolver", "registrar")

    # Conditional edge: loop or terminate
    builder.add_conditional_edges(
        "registrar",
        should_continue,
        {"continue": "architect", "end": END},
    )

    return builder.compile()
