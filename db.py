"""
db.py – FalkorDB connection and Cypher MERGE helper (The Registrar's toolkit).

Uses the official `falkordb` Python client which speaks the Redis protocol.
All writes use MERGE (not CREATE) to ensure idempotency — safe to re-run.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import falkordb

from config import get_settings

logger = logging.getLogger(__name__)
cfg = get_settings()


@lru_cache(maxsize=1)
def get_graph() -> falkordb.Graph:
    """Return a cached FalkorDB Graph handle.

    FalkorDB exposes a Redis-compatible interface.  The ``falkordb`` Python
    client wraps redis-py under the hood.
    """
    client = falkordb.FalkorDB(host=cfg.falkordb_host, port=cfg.falkordb_port)
    graph = client.select_graph(cfg.falkordb_graph_name)
    logger.info(
        "Connected to FalkorDB graph '%s' at %s:%s",
        cfg.falkordb_graph_name,
        cfg.falkordb_host,
        cfg.falkordb_port,
    )
    return graph


def _escape(value: str) -> str:
    """Escape single quotes inside Cypher string literals."""
    return value.replace("'", "\\'")


def merge_triplet(triplet: dict[str, str]) -> None:
    """Persist a single (subject, predicate, object) triplet via MERGE.

    Parameters
    ----------
    triplet:
        Dict with keys: subject, subject_type, predicate, object, object_type.
    """
    subject = _escape(triplet.get("subject", "Unknown"))
    s_type = triplet.get("subject_type", "Entity")
    predicate = triplet.get("predicate", "RELATED_TO").replace(" ", "_").upper()
    obj = _escape(triplet.get("object", "Unknown"))
    o_type = triplet.get("object_type", "Entity")

    # Sanitise types: strip XSD namespace for property nodes
    if o_type.startswith("xsd:"):
        # Object is a literal value — store as a property, not a node
        cypher = (
            f"MERGE (s:{s_type} {{name: '{subject}'}}) "
            f"SET s.{predicate.lower()} = '{obj}'"
        )
    else:
        cypher = (
            f"MERGE (s:{s_type} {{name: '{subject}'}}) "
            f"MERGE (o:{o_type} {{name: '{obj}'}}) "
            f"MERGE (s)-[:{predicate}]->(o)"
        )

    try:
        get_graph().query(cypher)
        logger.debug("MERGE OK: (%s)-[:%s]->(%s)", subject, predicate, obj)
    except Exception as exc:
        logger.error("FalkorDB MERGE failed for triplet %s — %s", triplet, exc)
        raise


def merge_triplets(triplets: list[dict[str, str]]) -> int:
    """Persist a list of triplets. Returns the count of successful writes."""
    success = 0
    for triplet in triplets:
        try:
            merge_triplet(triplet)
            success += 1
        except Exception:
            # Individual failures logged inside merge_triplet; continue batch.
            pass
    logger.info("Registrar: %d/%d triplets persisted.", success, len(triplets))
    return success


def get_graph_stats() -> dict[str, Any]:
    """Return basic counts from the graph for progress reporting."""
    graph = get_graph()
    node_count = graph.query("MATCH (n) RETURN count(n) AS c").result_set[0][0]
    edge_count = graph.query("MATCH ()-[r]->() RETURN count(r) AS c").result_set[0][0]
    return {"nodes": node_count, "edges": edge_count}
