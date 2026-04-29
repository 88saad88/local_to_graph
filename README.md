# Local-to-Graph 🕸

> A **Hierarchical Multi-Agent** Knowledge Graph construction pipeline built with
> **LangGraph** + **FalkorDB**, optimised for free-tier Llama APIs.

---

## Architecture

```
Document → Ingestion → [Chunks]
                          │
              ┌───────────▼───────────┐
              │    LangGraph Loop     │
              │                       │
              │  ┌─────────────────┐  │
              │  │  The Architect  │  │  Llama 3.3 70B (Groq)
              │  │  (Ontology Gov.)│  │  – Enforces 80% Rule
              │  └────────┬────────┘  │
              │           │           │
              │  ┌────────▼────────┐  │
              │  │  The Extractor  │  │  Llama 4 Scout (Together)
              │  │  (S→P→O mining) │  │  – High-throughput extraction
              │  └────────┬────────┘  │
              │           │           │
              │  ┌────────▼────────┐  │
              │  │  The Resolver   │  │  Llama 3.3 70B (Groq)
              │  │  (Entity Dedup) │  │  – Coreference resolution
              │  └────────┬────────┘  │
              │           │           │
              │  ┌────────▼────────┐  │
              │  │  The Registrar  │  │  Pure tool (no LLM)
              │  │  (FalkorDB MERGE)│ │  – Cypher MERGE writes
              │  └────────┬────────┘  │
              │           │           │
              │    more chunks? ──────┤
              └───────────────────────┘
                          │
                       FalkorDB
```

---

## Quick Start

### 1 – Clone & install

```bash
git clone <this-repo>
cd local_to_graph

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
```

### 2 – Configure API keys

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # Linux/Mac
```

Edit `.env` and add your keys:
| Key | Where to get it |
|-----|-----------------|
| `GROQ_API_KEY` | https://console.groq.com/ |
| `TOGETHER_API_KEY` | https://api.together.xyz/ |

### 3 – Spin up FalkorDB

```bash
docker compose up -d
```

FalkorDB Browser UI → http://localhost:3000

### 4 – Run the pipeline

```bash
python main.py --file path/to/your/document.pdf
```

Options:
```
  --file     / -f    Path to document (PDF, TXT, MD)
  --graph-name / -g  FalkorDB graph name (default: knowledge_graph)
  --verbose  / -v    Enable DEBUG logging
```

---

## File Structure

```
local_to_graph/
├── main.py            # CLI entry-point (typer + rich)
├── graph.py           # LangGraph StateGraph assembly
├── agents.py          # Four agent nodes
├── state.py           # GraphState TypedDict
├── prompts.py         # System & human prompts for all agents
├── llm_clients.py     # Groq/Together clients + tenacity retry
├── ingestion.py       # PDF/text chunking (Unstructured + PyPDF)
├── db.py              # FalkorDB MERGE helper (The Registrar's toolkit)
├── config.py          # Settings from .env
├── requirements.txt
├── docker-compose.yml
└── .env.example
```

---

## Agent Roles

| Agent | Model | Provider | Purpose |
|-------|-------|----------|---------|
| **Architect** | Llama 3.3 70B | Groq | Ontology governance (80% Rule) |
| **Extractor** | Llama 4 Scout 17B | Together AI | Triplet extraction (S→P→O) |
| **Resolver** | Llama 3.3 70B | Groq | Entity de-duplication / coreference |
| **Registrar** | *(no LLM)* | FalkorDB | Cypher MERGE writes |

---

## Rate Limiting Strategy

All LLM calls use **tenacity** with **randomised exponential backoff**:

```
Attempt 1: immediate
Attempt 2: wait  4–8 s
Attempt 3: wait  8–16 s
...
Attempt 6: wait up to 60 s
```

`MAX_RETRIES=6` is tunable via `.env`. The Groq free tier allows ~30 RPM,
so the backoff typically recovers without hitting the 6-attempt cap.

---

## FalkorDB Schema

Entities are stored as typed nodes, relationships as directed edges:

```cypher
// Example — what gets written per triplet
MERGE (p:Person {name: 'Steve Jobs'})
MERGE (c:Organization {name: 'Apple Inc.'})
MERGE (p)-[:FOUNDED]->(c)
```

Literal values become node properties:
```cypher
MERGE (p:Person {name: 'Steve Jobs'})
SET p.birthYear = '1955'
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `429 Too Many Requests` | Increase `MAX_RETRIES` in `.env`; the backoff handles it |
| `FalkorDB connection refused` | Run `docker compose up -d` first |
| `JSON decode error` | Enable `--verbose` to see raw model output; retry usually fixes it |
| Ontology growing too large | Lower `max_iterations` or increase the 80% Rule strictness in `prompts.py` |
