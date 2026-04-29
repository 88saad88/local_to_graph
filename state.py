"""
state.py – Shared TypedDict state passed between all LangGraph nodes.
"""
from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict):
    """Central state object for the Local-to-Graph pipeline.

    Fields
    ------
    raw_text:
        The current chunk of plain text being processed.
    ontology:
        The live schema managed by the Architect agent.
        Structure::

            {
              "classes": ["Person", "Organization", ...],
              "properties": {
                  "Person": ["name", "born", "role"],
                  ...
              },
              "relations": ["WORKS_AT", "FOUNDED", ...]
            }

    new_triplets:
        Raw (Subject, Predicate, Object) triplets produced by the Extractor.
        Each item is a dict with keys ``subject``, ``predicate``, ``object``,
        and optionally ``subject_type`` / ``object_type``.
    resolved_entities:
        De-duplicated / canonical triplets produced by the Resolver.
    iteration_count:
        Safety counter to prevent runaway loops.
    error:
        Optional error message from any node (triggers conditional routing).
    """

    raw_text: str
    ontology: dict[str, Any]
    new_triplets: list[dict[str, str]]
    resolved_entities: list[dict[str, str]]
    iteration_count: int
    error: str | None
