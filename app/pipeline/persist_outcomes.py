from __future__ import annotations

from app.core import (
    ExtractedInvoice,
    GateDecision,
    PurchaseOrder,
    Settlement,
    ValidationResult,
)
from app.pipeline.pipeline_helpers import _audit


def persist_pipeline_outcomes(
    *,
    invoice: ExtractedInvoice,
    po: PurchaseOrder | None,
    validation: ValidationResult | None,
    settlement: Settlement | None,
    decision: GateDecision | None = None,
    recorded_at: str | None = None,
) -> None:
    """Write every pipeline outcome to the graph (approve / deny / escalate)."""
    try:
        from app.intelligence.knowledge_graph import get_knowledge_graph

        get_knowledge_graph().record_transaction(
            invoice=invoice,
            po=po,
            validation_result=validation,
            settlement=settlement,
            decision=decision,
            recorded_at=recorded_at,
        )
    except Exception as exc:  # noqa: BLE001 — graph must never break the pipeline
        _audit(
            "knowledge_graph_write",
            "deterministic",
            f"vendor={invoice.vendor_name}",
            f"skipped: {type(exc).__name__}: {exc}",
        )

    if validation is None:
        return

    try:
        from app.intelligence.rag_index import get_rag_index

        get_rag_index().add_dispute_record(
            invoice=invoice,
            validation=validation,
            settlement=settlement,
            po_id=po.po_id if po else None,
        )
        _audit(
            "rag_index_write",
            "deterministic",
            f"vendor={invoice.vendor_name} amount=${invoice.invoice_amount:.2f}",
            "indexed invoice/dispute narrative for future similarity search",
        )
    except Exception as exc:  # noqa: BLE001
        _audit(
            "rag_index_write",
            "deterministic",
            f"vendor={invoice.vendor_name}",
            f"skipped: {type(exc).__name__}: {exc}",
        )
