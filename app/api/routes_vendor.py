"""Sample documents and vendor knowledge-graph routes."""

from __future__ import annotations

import asyncio
from urllib.parse import unquote

from fastapi import APIRouter

from app.api.deps import SAMPLES

router = APIRouter(tags=["samples"])


@router.get("/samples")
async def list_samples() -> list[dict[str, str]]:
    labels = {
        "po1001": "PO-1001 — Clean match (Meridian)",
        "po1002": "PO-1002 — Small mismatch ~2% (Cascade)",
        "po1003": "PO-1003 — Large mismatch ~18% (Northwind)",
    }
    return [
        {
            "id": sid,
            "label": labels[sid],
            "po_id": po_id,
            "file": filename,
        }
        for sid, (filename, po_id) in SAMPLES.items()
    ]


@router.get("/vendor-graph/{vendor_name}")
async def vendor_graph(vendor_name: str) -> dict:
    """Live vendor context from Neo4j/memory, including ``last_updated``."""
    from app.intelligence.knowledge_graph import get_knowledge_graph

    name = unquote(vendor_name)
    kg = get_knowledge_graph()
    return await asyncio.to_thread(kg.get_vendor_context, name)
