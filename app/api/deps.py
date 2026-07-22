"""Shared FastAPI path constants and sample invoice map."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
UI_DIR = ROOT / "ui"
SAMPLE_DOCS = ROOT / "sample_docs"

SAMPLES: dict[str, tuple[str, str]] = {
    "po1001": ("invoice_po1001_clean.txt", "PO-1001"),
    "po1002": ("invoice_po1002_small_mismatch.txt", "PO-1002"),
    "po1003": ("invoice_po1003_large_mismatch.txt", "PO-1003"),
}

VENDOR_BY_SAMPLE = {
    "po1001": "Meridian Office Supply",
    "po1002": "Cascade Industrial Parts",
    "po1003": "Northwind Components",
}
