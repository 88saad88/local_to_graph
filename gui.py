"""
gui.py – Graphical front-end for the Local-to-Graph pipeline.

Run with:
    python gui.py

Features:
  • File browser (PDF, TXT, MD, RST)
  • Editable graph-name field
  • Live scrolling log output
  • Progress bar per chunk
  • Run / Cancel controls
  • Final summary panel
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

# ── Colour palette ────────────────────────────────────────────────────────────
BG        = "#0f1117"   # near-black background
SURFACE   = "#1a1d2e"   # card / panel background
SURFACE2  = "#252840"   # slightly lighter surface
ACCENT    = "#6c63ff"   # violet accent
ACCENT2   = "#a78bfa"   # soft purple
SUCCESS   = "#22d3a5"   # teal green
WARNING   = "#f59e0b"   # amber
ERROR     = "#f87171"   # rose red
TEXT      = "#e2e8f0"   # near-white text
MUTED     = "#64748b"   # slate muted text
BORDER    = "#2d3157"   # border colour


# ── Queue-based log handler so background thread can write to the GUI ─────────
class _QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self._q = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self._q.put(("log", self.format(record)))


# ── Main application ──────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Local → Graph  •  Knowledge Graph Builder")
        self.geometry("900x720")
        self.minsize(800, 620)
        self.configure(bg=BG)
        self._set_icon()

        # Communication channel between the worker thread and the GUI
        self._q: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel_flag = threading.Event()

        self._build_ui()
        self._poll_queue()

    # ── Icon (graceful fallback if no icon file) ──────────────────────────────
    def _set_icon(self):
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

    # ── UI Construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_header()
        self._build_config_panel()
        # Footer MUST be packed before the log panel so it is never pushed off-screen
        self._build_footer()
        self._build_log_panel()

    def _build_header(self):
        header = tk.Frame(self, bg=SURFACE, pady=18)
        header.pack(fill="x")

        title_font = font.Font(family="Segoe UI", size=18, weight="bold")
        sub_font   = font.Font(family="Segoe UI", size=10)

        tk.Label(
            header,
            text="🕸  Local → Graph",
            font=title_font,
            fg=ACCENT2,
            bg=SURFACE,
        ).pack()
        tk.Label(
            header,
            text="Build a Knowledge Graph from any document",
            font=sub_font,
            fg=MUTED,
            bg=SURFACE,
        ).pack()

    def _build_config_panel(self):
        panel = tk.Frame(self, bg=BG, padx=24, pady=16)
        panel.pack(fill="x")

        label_font  = font.Font(family="Segoe UI", size=9, weight="bold")
        entry_font  = font.Font(family="Segoe UI Mono", size=10)
        btn_font    = font.Font(family="Segoe UI", size=10, weight="bold")

        # ── File row ─────────────────────────────────────────────────────────
        tk.Label(panel, text="DOCUMENT", font=label_font,
                 fg=ACCENT2, bg=BG).grid(row=0, column=0, sticky="w", pady=(0, 4))

        file_row = tk.Frame(panel, bg=BG)
        file_row.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        panel.columnconfigure(0, weight=1)
        file_row.columnconfigure(0, weight=1)

        self._file_var = tk.StringVar()
        file_entry = tk.Entry(
            file_row,
            textvariable=self._file_var,
            font=entry_font,
            bg=SURFACE2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        file_entry.grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 8))

        browse_btn = tk.Button(
            file_row,
            text="  Browse …  ",
            font=btn_font,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT2,
            activeforeground="white",
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._browse_file,
        )
        browse_btn.grid(row=0, column=1)
        self._add_hover(browse_btn, ACCENT, ACCENT2)

        # ── Graph name row ────────────────────────────────────────────────────
        tk.Label(panel, text="GRAPH NAME", font=label_font,
                 fg=ACCENT2, bg=BG).grid(row=2, column=0, sticky="w", pady=(0, 4))

        self._graph_var = tk.StringVar(value=self._default_graph_name())
        graph_entry = tk.Entry(
            panel,
            textvariable=self._graph_var,
            font=entry_font,
            bg=SURFACE2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        graph_entry.grid(row=3, column=0, sticky="ew", ipady=8, pady=(0, 20))

        # ── Progress bar ──────────────────────────────────────────────────────
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Graph.Horizontal.TProgressbar",
            troughcolor=SURFACE2,
            background=ACCENT,
            bordercolor=BG,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )

        self._progress_var = tk.DoubleVar(value=0)
        self._progress_bar = ttk.Progressbar(
            panel,
            variable=self._progress_var,
            maximum=100,
            style="Graph.Horizontal.TProgressbar",
            length=400,
        )
        self._progress_bar.grid(row=4, column=0, sticky="ew", pady=(0, 6))

        self._status_var = tk.StringVar(value="Ready — select a document to begin.")
        tk.Label(
            panel,
            textvariable=self._status_var,
            font=font.Font(family="Segoe UI", size=9),
            fg=MUTED,
            bg=BG,
            anchor="w",
        ).grid(row=5, column=0, sticky="w")

    def _build_log_panel(self):
        log_frame = tk.Frame(self, bg=BG, padx=24, pady=0)
        log_frame.pack(fill="both", expand=True)

        label_font = font.Font(family="Segoe UI", size=9, weight="bold")
        tk.Label(log_frame, text="PIPELINE LOG", font=label_font,
                 fg=ACCENT2, bg=BG).pack(anchor="w", pady=(0, 6))

        text_frame = tk.Frame(log_frame, bg=BORDER, bd=1)
        text_frame.pack(fill="both", expand=True)

        log_font = font.Font(family="Cascadia Code", size=9) \
            if "Cascadia Code" in font.families() \
            else font.Font(family="Courier New", size=9)

        self._log_text = tk.Text(
            text_frame,
            bg=SURFACE,
            fg=TEXT,
            font=log_font,
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            wrap="word",
            state="disabled",
            cursor="arrow",
        )
        scrollbar = tk.Scrollbar(text_frame, command=self._log_text.yview,
                                 bg=SURFACE2, troughcolor=SURFACE, bd=0)
        self._log_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

        # Colour tags for different log levels
        self._log_text.tag_config("INFO",    foreground=TEXT)
        self._log_text.tag_config("DEBUG",   foreground=MUTED)
        self._log_text.tag_config("WARNING", foreground=WARNING)
        self._log_text.tag_config("ERROR",   foreground=ERROR)
        self._log_text.tag_config("SUCCESS", foreground=SUCCESS)
        self._log_text.tag_config("CHUNK",   foreground=ACCENT2)
        self._log_text.tag_config("SYSTEM",  foreground=ACCENT)

    def _build_footer(self):
        footer = tk.Frame(self, bg=SURFACE, pady=14, padx=24)
        footer.pack(fill="x", side="bottom")

        btn_font = font.Font(family="Segoe UI", size=11, weight="bold")

        self._run_btn = tk.Button(
            footer,
            text="▶  Run Pipeline",
            font=btn_font,
            bg=SUCCESS,
            fg="#0f1117",
            activebackground="#1ab08b",
            activeforeground="#0f1117",
            relief="flat",
            bd=0,
            padx=24,
            pady=10,
            cursor="hand2",
            command=self._start_pipeline,
        )
        self._run_btn.pack(side="left", padx=(0, 12))
        self._add_hover(self._run_btn, SUCCESS, "#1ab08b")

        self._cancel_btn = tk.Button(
            footer,
            text="✕  Cancel",
            font=btn_font,
            bg=SURFACE2,
            fg=MUTED,
            activebackground=ERROR,
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            state="disabled",
            command=self._cancel_pipeline,
        )
        self._cancel_btn.pack(side="left")

        self._clear_btn = tk.Button(
            footer,
            text="Clear Log",
            font=font.Font(family="Segoe UI", size=9),
            bg=BG,
            fg=MUTED,
            activebackground=SURFACE2,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            cursor="hand2",
            command=self._clear_log,
        )
        self._clear_btn.pack(side="right")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _add_hover(self, widget: tk.Button, normal: str, hover: str):
        widget.bind("<Enter>", lambda _: widget.configure(bg=hover))
        widget.bind("<Leave>", lambda _: widget.configure(bg=normal))

    def _default_graph_name(self) -> str:
        try:
            from config import get_settings
            return get_settings().falkordb_graph_name
        except Exception:
            return "knowledge_graph"

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select a document",
            filetypes=[
                ("Supported documents", "*.pdf *.txt *.md *.rst *.docx"),
                ("PDF files",           "*.pdf"),
                ("Text files",          "*.txt *.md *.rst"),
                ("All files",           "*.*"),
            ],
        )
        if path:
            self._file_var.set(path)

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    # ── Log writing (must run on main thread via queue) ───────────────────────
    def _append_log(self, text: str, tag: str = "INFO"):
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text + "\n", tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    # ── Queue polling (runs on main thread every 50 ms) ───────────────────────
    def _poll_queue(self):
        try:
            while True:
                msg_type, payload = self._q.get_nowait()
                if msg_type == "log":
                    # Colour by log level keyword
                    tag = "INFO"
                    upper = payload.upper()
                    if "WARNING" in upper or "WARN" in upper:
                        tag = "WARNING"
                    elif "ERROR" in upper or "CRITICAL" in upper:
                        tag = "ERROR"
                    elif "DEBUG" in upper:
                        tag = "DEBUG"
                    elif "✓" in payload or "done" in payload.lower() or "success" in payload.lower():
                        tag = "SUCCESS"
                    elif "chunk" in payload.lower():
                        tag = "CHUNK"
                    self._append_log(payload, tag)

                elif msg_type == "status":
                    self._status_var.set(payload)

                elif msg_type == "progress":
                    self._progress_var.set(payload)

                elif msg_type == "done":
                    self._on_pipeline_done(payload)

                elif msg_type == "error":
                    self._on_pipeline_error(payload)

        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    # ── Pipeline control ──────────────────────────────────────────────────────
    def _start_pipeline(self):
        file_path = self._file_var.get().strip()
        graph_name = self._graph_var.get().strip()

        if not file_path:
            messagebox.showwarning("No file selected", "Please browse and select a document first.")
            return
        if not Path(file_path).exists():
            messagebox.showerror("File not found", f"Cannot find:\n{file_path}")
            return
        if not graph_name:
            messagebox.showwarning("Graph name empty", "Please enter a graph name.")
            return

        self._clear_log()
        self._progress_var.set(0)
        self._cancel_flag.clear()
        self._run_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._status_var.set("🚀  Pipeline running …")
        self._append_log(f"▶  Starting pipeline", "SYSTEM")
        self._append_log(f"   File  : {file_path}", "SYSTEM")
        self._append_log(f"   Graph : {graph_name}", "SYSTEM")
        self._append_log("", "INFO")

        self._worker = threading.Thread(
            target=self._run_pipeline,
            args=(file_path, graph_name),
            daemon=True,
        )
        self._worker.start()

    def _cancel_pipeline(self):
        self._cancel_flag.set()
        self._q.put(("log", "⚠  Cancellation requested — stopping after current chunk …"))
        self._cancel_btn.configure(state="disabled")

    def _on_pipeline_done(self, summary: dict):
        self._run_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._progress_var.set(100)

        nodes = summary.get("nodes", "?")
        edges = summary.get("edges", "?")
        classes = summary.get("classes", [])
        ontology_path = summary.get("ontology_path", "")

        self._status_var.set(f"✅  Done — {nodes} nodes, {edges} edges in graph.")
        self._append_log("", "INFO")
        self._append_log("─" * 60, "SYSTEM")
        self._append_log("✅  PIPELINE COMPLETE", "SUCCESS")
        self._append_log(f"   Nodes          : {nodes}", "SUCCESS")
        self._append_log(f"   Edges          : {edges}", "SUCCESS")
        self._append_log(f"   Ontology classes: {classes}", "SUCCESS")
        if ontology_path:
            self._append_log(f"   Ontology JSON  : {ontology_path}", "SUCCESS")
        self._append_log("─" * 60, "SYSTEM")

    def _on_pipeline_error(self, error: str):
        self._run_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._status_var.set(f"❌  Error: {error}")
        self._append_log(f"❌  FATAL ERROR: {error}", "ERROR")

    # ── Worker thread ─────────────────────────────────────────────────────────
    def _run_pipeline(self, file_path: str, graph_name: str):
        """Runs entirely on a background thread. Communicates via self._q."""

        # Redirect logging to the GUI queue
        q_handler = _QueueHandler(self._q)
        q_handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s — %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(q_handler)

        def emit(msg_type, payload):
            self._q.put((msg_type, payload))

        try:
            # ── Step 1: Import pipeline modules ───────────────────────────────
            emit("log", "⚙  Importing pipeline modules …")
            from config import get_settings
            from db import get_graph_stats
            from graph import build_graph
            from ingestion import load_document
            from state import GraphState

            cfg = get_settings()

            # Override graph name from GUI
            cfg.__class__.falkordb_graph_name = graph_name  # type: ignore

            # ── Step 2: Ingest ─────────────────────────────────────────────────
            emit("log", "📄  Step 1/3 — Ingesting document …")
            emit("status", "Ingesting document …")
            try:
                chunks = load_document(Path(file_path))
            except FileNotFoundError as exc:
                emit("error", str(exc))
                return

            emit("log", f"✓  {len(chunks)} chunk(s) created from document.")
            emit("progress", 10)

            # ── Step 3: Build graph ────────────────────────────────────────────
            emit("log", "🔧  Step 2/3 — Building LangGraph pipeline …")
            emit("status", "Building pipeline …")
            pipeline = build_graph()
            emit("progress", 15)

            # ── Step 4: Process chunks ─────────────────────────────────────────
            emit("log", f"🔄  Step 3/3 — Processing {len(chunks)} chunk(s) …")
            current_ontology: dict = {"classes": [], "properties": {}, "relations": []}

            for i, chunk in enumerate(chunks):
                if self._cancel_flag.is_set():
                    emit("log", "⚠  Cancelled by user.")
                    emit("status", "Cancelled.")
                    self._run_btn.configure(state="normal")
                    self._cancel_btn.configure(state="disabled")
                    return

                pct = 15 + int(80 * (i / len(chunks)))
                emit("progress", pct)
                emit("status", f"Processing chunk {i + 1} of {len(chunks)} …")
                emit("log", f"─── Chunk {i + 1}/{len(chunks)} ───")

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
                    emit("log", f"✗  Chunk {i + 1} failed: {exc}")
                    continue

                current_ontology = final_state["ontology"]

                if final_state.get("error"):
                    emit("log", f"⚠  Non-fatal on chunk {i + 1}: {final_state['error']}")
                else:
                    emit("log", f"✓  Chunk {i + 1} processed successfully.")

            # ── Step 5: Stats & ontology sidecar ──────────────────────────────
            emit("progress", 97)
            try:
                stats = get_graph_stats()
            except Exception:
                stats = {"nodes": "?", "edges": "?"}

            ontology_out = Path(file_path).with_suffix(".ontology.json")
            try:
                ontology_out.write_text(
                    json.dumps(current_ontology, indent=2), encoding="utf-8"
                )
            except Exception:
                ontology_out = None

            emit("done", {
                "nodes": stats["nodes"],
                "edges": stats["edges"],
                "classes": current_ontology.get("classes", []),
                "ontology_path": str(ontology_out) if ontology_out else "",
            })

        except Exception as exc:
            emit("error", str(exc))
        finally:
            root_logger.removeHandler(q_handler)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
