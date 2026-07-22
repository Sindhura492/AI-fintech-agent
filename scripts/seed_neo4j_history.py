from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Prefer local PDF text extract over LlamaParse for this batch seed.
os.environ["LLAMA_CLOUD_API_KEY"] = ""
if "DEMO_MODE" not in os.environ:
    os.environ["DEMO_MODE"] = "1"

from app.config import clear_settings_cache  # noqa: E402

clear_settings_cache()

from app.observability.console_logging import setup_logging  # noqa: E402

setup_logging()

from app.seed.demo_mode import demo_mode_enabled, enable_demo_mode  # noqa: E402

if os.environ.get("DEMO_MODE", "").strip() in {"1", "true", "True", "yes"}:
    enable_demo_mode()

from app.intelligence.knowledge_graph import (  # noqa: E402
    get_knowledge_graph,
    reset_knowledge_graph,
)
from app.pipeline.orchestrator import run_pipeline  # noqa: E402

SAMPLE_DOCS = ROOT / "sample_docs"
_PO_RE = re.compile(
    r"(?:PO\s*(?:Reference|Ref|#)|Your\s+PO\s*#?|Purchase\s+Order)\s*[:.]?\s*(PO-\d+)",
    re.IGNORECASE,
)
_PO_FALLBACK = re.compile(r"\b(PO-\d+)\b", re.IGNORECASE)


def _list_pdfs() -> list[Path]:
    if not SAMPLE_DOCS.is_dir():
        return []
    return sorted(SAMPLE_DOCS.glob("*.pdf"))


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _infer_po_id(path: Path) -> str | None:
    """Best-effort PO id from PDF text (demo extract does not return po_id)."""
    try:
        text = _pdf_text(path)
    except Exception:  # noqa: BLE001
        return None
    m = _PO_RE.search(text) or _PO_FALLBACK.search(text)
    return m.group(1) if m else None


def _summarize(path: Path, result: dict) -> str:
    invoice = result.get("invoice") or {}
    decision = result.get("decision") or {}
    vendor = invoice.get("vendor_name") or "?"
    amount = invoice.get("invoice_amount")
    amount_txt = f"${amount:,.2f}" if isinstance(amount, (int, float)) else "?"
    outcome = decision.get("action") if isinstance(decision, dict) else None
    if not outcome:
        outcome = result.get("status") or "unknown"
    return f"{path.name:42s}  {vendor:28s}  {amount_txt:>10s}  {outcome}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Seconds between pipeline runs (default: 0.5 in DEMO_MODE, else 2.0)",
    )
    args = parser.parse_args()
    delay = args.delay
    if delay is None:
        delay = 0.5 if demo_mode_enabled() else 2.0

    pdfs = _list_pdfs()
    if not pdfs:
        print(f"No PDFs found in {SAMPLE_DOCS}/", flush=True)
        return 1

    reset_knowledge_graph()
    kg = get_knowledge_graph()
    print("=" * 88, flush=True)
    print("NEO4J HISTORY SEED (sample_docs/*.pdf)", flush=True)
    print("=" * 88, flush=True)
    print(f"  Backend   : {kg.source}", flush=True)
    print(f"  DEMO_MODE : {demo_mode_enabled()}", flush=True)
    print(f"  PDFs      : {len(pdfs)}", flush=True)
    print(f"  Delay     : {delay}s between runs", flush=True)
    if kg.source != "neo4j":
        print(
            "  WARNING: not on Neo4j — check NEO4J_* / NEO4J_TRUST_ALL=1",
            flush=True,
        )
    print("-" * 88, flush=True)
    print(
        f"{'file':42s}  {'vendor':28s}  {'amount':>10s}  outcome",
        flush=True,
    )
    print("-" * 88, flush=True)

    outcomes: Counter[str] = Counter()
    errors = 0

    for i, path in enumerate(pdfs):
        po_id = _infer_po_id(path)
        try:
            result = run_pipeline(
                str(path),
                po_id,
                session_id=f"seed-pdf-{path.stem}",
            )
            line = _summarize(path, result)
            print(line, flush=True)
            decision = (result.get("decision") or {}).get("action") or "unknown"
            outcomes[str(decision)] += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            outcomes["error"] += 1
            print(f"{path.name:42s}  ERROR: {type(exc).__name__}: {exc}", flush=True)

        if i < len(pdfs) - 1 and delay > 0:
            time.sleep(delay)

    print("-" * 88, flush=True)
    print(
        f"Done — {len(pdfs)} PDFs | "
        + " ".join(f"{k}={v}" for k, v in sorted(outcomes.items())),
        flush=True,
    )
    print("=" * 88, flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
