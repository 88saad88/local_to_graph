"""
ingestion.py – Document loading and text chunking utilities.

Supports PDF (via PyPDF + Unstructured fallback) and plain text.
Chunks are sized to respect the MAX_CHUNK_TOKENS budget for free-tier LLMs.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from config import get_settings

logger = logging.getLogger(__name__)
cfg = get_settings()

# Rough chars-per-token estimate (conservative for Llama tokeniser)
_CHARS_PER_TOKEN = 3.5


def _chunk_text(text: str, max_tokens: int) -> list[str]:
    """Split text into chunks that fit within max_tokens.

    Splits on paragraph boundaries where possible to preserve context.
    """
    max_chars = int(max_tokens * _CHARS_PER_TOKEN)
    paragraphs = re.split(r"\n{2,}", text.strip())

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        plen = len(para)
        if current_len + plen > max_chars and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_len = plen
        else:
            current.append(para)
            current_len += plen

    if current:
        chunks.append("\n\n".join(current))

    return chunks or [text[:max_chars]]


def load_pdf(path: Path) -> list[str]:
    """Load a PDF and return a list of text chunks."""
    # Try Unstructured first (richer extraction)
    try:
        from unstructured.partition.pdf import partition_pdf  # type: ignore

        elements = partition_pdf(filename=str(path))
        full_text = "\n\n".join(str(el) for el in elements if str(el).strip())
        logger.info("[Ingestion] Loaded PDF via Unstructured: %d chars", len(full_text))
        return _chunk_text(full_text, cfg.max_chunk_tokens)
    except ImportError:
        logger.warning("[Ingestion] Unstructured not available, falling back to PyPDF.")

    # PyPDF fallback
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
        full_text = "\n\n".join(pages)
        logger.info("[Ingestion] Loaded PDF via PyPDF: %d chars", len(full_text))
        return _chunk_text(full_text, cfg.max_chunk_tokens)
    except ImportError as exc:
        raise RuntimeError(
            "Neither 'unstructured' nor 'pypdf' is installed. "
            "Run: pip install pypdf"
        ) from exc


def load_text(path: Path) -> list[str]:
    """Load a plain text / markdown file and return chunks."""
    full_text = path.read_text(encoding="utf-8", errors="replace")
    logger.info("[Ingestion] Loaded text file: %d chars", len(full_text))
    return _chunk_text(full_text, cfg.max_chunk_tokens)


def load_document(path: str | Path) -> list[str]:
    """Auto-detect file type and return a list of text chunks.

    Supported: .pdf, .txt, .md
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path)
    elif suffix in {".txt", ".md", ".rst"}:
        return load_text(path)
    else:
        # Attempt generic text load
        logger.warning("[Ingestion] Unknown extension '%s', attempting text load.", suffix)
        return load_text(path)
