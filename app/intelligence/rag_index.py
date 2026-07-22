"""LlamaIndex RAG over past invoices / disputes for negotiation grounding.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any, Sequence

import numpy as np
from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.base.embeddings.base import BaseEmbedding, Embedding
from llama_index.core.schema import TextNode

from app.core import ExtractedInvoice, Settlement, ValidationResult
from app.observability.audit import write_audit_entry
from app.observability.console_logging import get_logger

logger = get_logger(__name__)

_EMBED_DIM = 256


class HashBagEmbedding(BaseEmbedding):
    """Deterministic hashing embedder — no cloud / no model download."""

    dim: int = _EMBED_DIM

    @classmethod
    def class_name(cls) -> str:
        return "HashBagEmbedding"

    def _embed(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = [
            t
            for t in "".join(c.lower() if c.isalnum() else " " for c in text).split()
            if t
        ]
        if not tokens:
            return vec.tolist()
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h // self.dim) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()

    def _get_query_embedding(self, query: str) -> Embedding:
        return self._embed(query)

    def _get_text_embedding(self, text: str) -> Embedding:
        return self._embed(text)

    def _get_text_embeddings(self, texts: list[str]) -> list[Embedding]:
        return [self._embed(t) for t in texts]

    async def _aget_query_embedding(self, query: str) -> Embedding:
        return self._embed(query)

    async def _aget_text_embedding(self, text: str) -> Embedding:
        return self._embed(text)


_SEED_DISPUTES: list[dict[str, Any]] = [
    {
        "id": "seed-cascade-1",
        "text": (
            "Dispute: Cascade Industrial Parts invoiced $3,180 vs PO $3,200 "
            "(~2% under). Parties settled at PO amount $3,200 after one round. "
            "Small price variance, clean goods receipt."
        ),
    },
    {
        "id": "seed-cascade-2",
        "text": (
            "Dispute: Cascade Industrial Parts billed $3,290 against PO $3,200 "
            "(~2.8%). Buyer countered to PO; supplier conceded. Settlement $3,200 agreed."
        ),
    },
    {
        "id": "seed-northwind-1",
        "text": (
            "Dispute: Northwind Components invoiced $13,200 vs PO $12,500 "
            "(~$700 gap). Settled at PO $12,500 after negotiation; supplier "
            "had history of occasional over-billing on components."
        ),
    },
    {
        "id": "seed-northwind-2",
        "text": (
            "Dispute: Northwind Components claimed $14,100 vs PO $12,500 "
            "(large ~13% discrepancy). No convergence within policy band; "
            "escalated for human review. Similar large-gap pattern."
        ),
    },
    {
        "id": "seed-meridian-1",
        "text": (
            "Clean match: Meridian Office Supply invoice $4,850 matched PO "
            "and goods receipt. No dispute. Early-payment discount eligible."
        ),
    },
]


class DisputeRAGIndex:
    """In-memory LlamaIndex vector store over historical dispute narratives."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._embed = HashBagEmbedding()
        Settings.embed_model = self._embed
        Settings.llm = None  # retrieval-only; never call an LLM from the index
        self._docs: list[Document] = []
        self._index: VectorStoreIndex | None = None
        self._seeded = False

    def ensure_seeded(self) -> None:
        with self._lock:
            if self._seeded:
                return
            for item in _SEED_DISPUTES:
                self._docs.append(
                    Document(
                        text=item["text"],
                        metadata={"doc_id": item["id"], "source": "seed"},
                    )
                )
            self._rebuild_unlocked()
            self._seeded = True

    def _rebuild_unlocked(self) -> None:
        if not self._docs:
            self._index = None
            return
        self._index = VectorStoreIndex.from_documents(
            self._docs,
            embed_model=self._embed,
            show_progress=False,
        )

    def add_dispute_record(
        self,
        *,
        invoice: ExtractedInvoice,
        validation: ValidationResult,
        settlement: Settlement | None,
        po_id: str | None = None,
    ) -> None:
        """Index a newly processed invoice/dispute for future similarity search."""
        self.ensure_seeded()
        status = (
            "matched clean"
            if validation.matched
            else (
                f"disputed gap ${validation.discrepancy_amount:,.2f}; "
                + (
                    f"settled ${settlement.final_amount:,.2f} "
                    f"agreed={settlement.agreed_by_both}"
                    if settlement
                    else "no settlement yet"
                )
            )
        )
        text = (
            f"Vendor {invoice.vendor_name} invoice ${invoice.invoice_amount:,.2f} "
            f"on {invoice.invoice_date.isoformat()} "
            f"(PO {po_id or 'unknown'}). {validation.reason} Outcome: {status}."
        )
        doc = Document(
            text=text,
            metadata={
                "vendor_name": invoice.vendor_name,
                "amount": invoice.invoice_amount,
                "po_id": po_id or "",
                "source": "pipeline",
            },
        )
        with self._lock:
            self._docs.append(doc)
            # Incremental insert when possible; rebuild is fine for demo scale.
            if self._index is not None:
                self._index.insert(doc)
            else:
                self._rebuild_unlocked()

    def query_similar_disputes(
        self,
        current_invoice: ExtractedInvoice,
        *,
        top_k: int = 3,
    ) -> list[str]:
        """Return the ``top_k`` most similar past dispute narratives."""
        self.ensure_seeded()
        logger.info(
            "[LLAMAINDEX] Querying similarity index for %s candidates...",
            top_k,
        )
        query = (
            f"Vendor {current_invoice.vendor_name} invoice amount "
            f"${current_invoice.invoice_amount:,.2f} dated "
            f"{current_invoice.invoice_date.isoformat()}. "
            f"Line items: "
            + "; ".join(
                f"{li.description} (${li.amount:,.2f})"
                for li in (current_invoice.line_items or [])[:8]
            )
        )

        hits: list[str] = []
        with self._lock:
            if self._index is None:
                hits = [d.text for d in self._docs[:top_k]]
            else:
                retriever = self._index.as_retriever(similarity_top_k=top_k)
                nodes: Sequence[Any] = retriever.retrieve(query)
                for node in nodes:
                    if isinstance(node, TextNode):
                        hits.append(node.get_content().strip())
                    else:
                        text = getattr(node, "text", None) or str(node)
                        hits.append(str(text).strip())

        logger.info(
            "[LLAMAINDEX] Found %s similar past disputes",
            len(hits),
        )

        write_audit_entry(
            step_name="rag_similar_disputes",
            step_type="deterministic",
            input_summary=(
                f"vendor={current_invoice.vendor_name} "
                f"amount=${current_invoice.invoice_amount:.2f} top_k={top_k}"
            ),
            output_summary=(
                f"retrieved {len(hits)} similar disputes: "
                + " | ".join(h[:80] for h in hits)
            )[:500],
            details={
                "vendor_name": current_invoice.vendor_name,
                "hit_count": len(hits),
                "top_k": top_k,
            },
        )
        return hits


_rag: DisputeRAGIndex | None = None
_rag_lock = threading.Lock()


def get_rag_index() -> DisputeRAGIndex:
    global _rag
    with _rag_lock:
        if _rag is None:
            _rag = DisputeRAGIndex()
            _rag.ensure_seeded()
        return _rag


def query_similar_disputes(current_invoice: ExtractedInvoice) -> list[str]:
    """Module-level helper used by the orchestrator / agents."""
    return get_rag_index().query_similar_disputes(current_invoice)


def format_similar_disputes_for_prompt(hits: list[str]) -> str:
    if not hits:
        return "SIMILAR PAST DISPUTES (RAG): none on file."
    lines = "\n".join(f"  {i}. {h}" for i, h in enumerate(hits, start=1))
    return (
        "SIMILAR PAST DISPUTES (LlamaIndex RAG — top semantic matches):\n"
        f"{lines}\n"
        "Use these as precedent only; current PO/GR verification still governs."
    )
