# Agent Finance

AP agent that reads invoices, matches them to POs, negotiates discrepancies, and only pays when a hard gate says yes.

## What it does

1. **Ingest** — sample files, `/run`, or Gmail PDF attachments  
2. **Parse** — sandboxed LlamaParse (local fallback for text/PDF)  
3. **Extract** — Claude → structured invoice  
4. **Match / validate** — three-way check vs PO + goods receipt  
5. **Negotiate** — buyer & supplier LangGraph agents (PO ±5% bounds)  
6. **Enforce** — deterministic approve / deny / escalate (sole payment chokepoint)  
7. **Remember** — Neo4j vendor graph + SQLite metrics + live UI trace  

Offline path: set `DEMO_MODE=1` (stub extract/negotiate, no Anthropic calls).

## Quick start

```bash
cd agent-finance
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # fill in keys — never commit .env
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the live trace UI.

```bash
# Offline demo scenarios (no API credits)
DEMO_MODE=1 python run_scenarios.py --demo
```

### Useful scripts

| Script | Purpose |
|--------|---------|
| `scripts/generate_fake_invoices.py` | Build demo + `invoice_hist_*.pdf` under `sample_docs/` |
| `scripts/seed_neo4j_history.py` | Run pipeline on every `sample_docs/*.pdf` → Neo4j |
| `scripts/verify_neo4j_data.py` | Print Aura/memory graph counts |

If Aura TLS fails behind a corporate proxy, set `NEO4J_TRUST_ALL=1` in `.env` (uses `neo4j+ssc`).

## Layout

```
agent-finance/
  app/
    config.py          # all settings (pydantic-settings)
    main.py            # FastAPI app + routers
    api/               # HTTP / WebSocket routes
    agents/            # buyer / supplier / bounds / cash-opt
    core/              # Pydantic schemas
    pipeline/          # sandbox → extract → match → enforce
    intelligence/      # anomaly ML, Neo4j KG, RAG
    human_loop/        # escalations + notifications
    observability/     # audit + metrics
    ingest/            # IMAP email intake
    seed/              # mock POs + DEMO_MODE stubs
  ui/                  # live negotiation SPA
  sample_docs/         # sample invoices (.txt / .pdf)
  scripts/             # generate / seed / verify helpers
  data/                # local SQLite (gitignored)
```

## Env (see `.env.example`)

| Variable | Used for |
|----------|----------|
| `ANTHROPIC_API_KEY` | Extraction + agent negotiation |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Aura knowledge graph |
| `NEO4J_TRUST_ALL` | Optional TLS bypass for MITM proxies |
| `EMAIL_*` | Gmail IMAP invoice polling |
| `LLAMA_CLOUD_API_KEY` | LlamaParse |
| `DEMO_MODE` | Stub LLM stages |
| `LOG_LEVEL` | Rich console logging |

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Trace viewer UI |
| GET | `/health` | Health check (`service: agent-finance`) |
| POST | `/run` | Run a sample invoice through the pipeline |
| POST | `/disputes/resolve` | Synchronous full-pipeline resolve |
| WS | `/ws` | Live audit + agent-chat stream |
| GET | `/metrics` | Aggregate monitoring summary |
| GET | `/metrics/history` | Raw SQLite metrics rows |

## Design notes

- **Financial bounds are code**, not prompt suggestions (`agents/bounds.py` — PO ±5%).
- **Untrusted PDFs never execute in the API process** — parse runs in a sandbox subprocess.
- **Config lives in `app/config.py`** — don’t sprinkle `os.getenv` for app settings.
- **The enforcement gate is the only path to payment.**

## Logging tags

`[SANDBOX]` `[LLAMAPARSE]` `[CLAUDE - EXTRACTION]` `[CLAUDE - BUYER]` `[CLAUDE - SUPPLIER]` `[LLAMAINDEX]` `[ML - ISOLATION FOREST]` `[ENFORCEMENT GATE]` `[NEO4J]`
