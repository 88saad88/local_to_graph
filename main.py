"""
main.py – CLI entry-point for the Local-to-Graph pipeline.

Usage
-----
  python main.py --file path/to/document.pdf
  python main.py --file path/to/document.txt --graph-name my_graph

The script:
  1. Ingests the document into text chunks.
  2. Iterates through chunks, feeding each into the StateGraph.
  3. Reports final graph statistics on completion.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import track

from config import get_settings
from db import get_graph_stats
from graph import build_graph
from ingestion import load_document
from state import GraphState

# ─── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
logger = logging.getLogger(__name__)
console = Console()
cfg = get_settings()

# ─── CLI ──────────────────────────────────────────────────────────────────────
app = typer.Typer(help="Local-to-Graph: Build a Knowledge Graph from any document.")


@app.command()
def run(
    file: Path = typer.Option(..., "--file", "-f", help="Path to the document to process."),
    graph_name: str = typer.Option(
        cfg.falkordb_graph_name, "--graph-name", "-g",
        help="FalkorDB graph name to write to.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging."),
) -> None:
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    console.print(
        Panel.fit(
            "[bold cyan]Local-to-Graph Pipeline[/]\n"
            f"File : [green]{file}[/]\n"
            f"Graph: [yellow]{graph_name}[/]",
            title="🕸  Starting",
        )
    )

    # ── 1. Ingest document ────────────────────────────────────────────────────
    console.print("\n[bold]Step 1/3 — Ingesting document …[/]")
    try:
        chunks = load_document(file)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/] {exc}")
        raise typer.Exit(code=1)

    console.print(f"  ✓ {len(chunks)} chunk(s) created.")

    # ── 2. Build graph ────────────────────────────────────────────────────────
    console.print("\n[bold]Step 2/3 — Building LangGraph …[/]")
    pipeline = build_graph()

    # ── 3. Process each chunk ─────────────────────────────────────────────────
    console.print("\n[bold]Step 3/3 — Processing chunks …[/]")

    # Persistent state across chunks — ontology accumulates across the run
    current_ontology: dict = {
        "classes": [],
        "properties": {},
        "relations": [],
    }

    for i, chunk in enumerate(track(chunks, description="Processing chunks …")):
        console.print(f"\n[dim]─── Chunk {i + 1}/{len(chunks)} ───[/]")

        initial_state: GraphState = {
            "raw_text": chunk,
            "ontology": current_ontology,
            "new_triplets": [],
            "resolved_entities": [],
            "iteration_count": 0,
            "error": None,
        }

        try:
            final_state: GraphState = pipeline.invoke(initial_state)
        except Exception as exc:
            logger.error("Pipeline crashed on chunk %d: %s", i + 1, exc)
            console.print(f"  [red]✗ Chunk {i+1} failed: {exc}[/]")
            continue

        # Carry forward the ontology the Architect built
        current_ontology = final_state["ontology"]

        if final_state.get("error"):
            console.print(f"  [yellow]⚠ Non-fatal: {final_state['error']}[/]")
        else:
            console.print(f"  [green]✓ Chunk {i+1} done.[/]")

    # ── Summary ───────────────────────────────────────────────────────────────
    try:
        stats = get_graph_stats()
        console.print(
            Panel.fit(
                f"[bold green]Pipeline Complete[/]\n\n"
                f"Ontology classes : {current_ontology.get('classes', [])}\n"
                f"Graph nodes      : {stats['nodes']}\n"
                f"Graph edges      : {stats['edges']}",
                title="✅  Summary",
            )
        )
    except Exception:
        console.print("[yellow]⚠ Could not fetch graph stats (FalkorDB offline?).[/]")

    # Dump final ontology to a JSON sidecar
    ontology_out = file.with_suffix(".ontology.json")
    ontology_out.write_text(json.dumps(current_ontology, indent=2), encoding="utf-8")
    console.print(f"\nFinal ontology saved to [cyan]{ontology_out}[/]")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app()
