"""Deterministic demo-mode stand-in for LangGraph negotiation."""

from __future__ import annotations

from app.agents.bounds import BOUNDS_PCT, within_bounds
from app.agents.llm import _emit
from app.core.schemas_audit import AuditEntry
from app.core.schemas_documents import ExtractedInvoice, PurchaseOrder, ValidationResult
from app.core.schemas_negotiation import Settlement
from app.observability.audit_events import (
    emit_agent_message,
    emit_agent_thinking,
    emit_settlement_banner,
)
from app.observability.console_logging import get_logger

logger = get_logger(__name__)


def _demo_negotiate(
    *,
    invoice: ExtractedInvoice,
    po: PurchaseOrder,
    validation: ValidationResult,
    min_a: float,
    max_a: float,
    bounds_audit: AuditEntry,
    vendor_context: dict | None = None,
    similar_disputes: list[str] | None = None,
) -> tuple[Settlement, list[AuditEntry]]:
    """Deterministic stand-in for LangGraph agents when DEMO_MODE=1."""
    ctx = vendor_context or {}
    past_disputes = int(ctx.get("dispute_count") or 0)
    rag_n = len(similar_disputes or [])
    kg_note = (
        f" (graph: {past_disputes} prior disputes, "
        f"avg disc ${float(ctx.get('avg_discrepancy') or 0):,.0f}; "
        f"RAG: {rag_n} similar)"
        if ctx or rag_n
        else ""
    )
    rel = (
        abs(invoice.invoice_amount - po.agreed_amount) / po.agreed_amount
        if po.agreed_amount
        else 1.0
    )
    audits: list[AuditEntry] = [bounds_audit]

    if rel <= BOUNDS_PCT:
        settlement = Settlement(
            final_amount=po.agreed_amount,
            agreed_by_both=True,
            within_bounds=True,
        )
        emit_agent_thinking("supplier", 1)
        logger.info(
            "[CLAUDE - SUPPLIER] Round 1: sending prompt... (DEMO_MODE stub)"
        )
        logger.info(
            "[CLAUDE - SUPPLIER] Proposed amount: %s",
            po.agreed_amount,
        )
        emit_agent_message(
            speaker="supplier",
            text=(
                f"We propose settling at the PO amount ${po.agreed_amount:,.2f}."
                f"{kg_note}"
            ),
            round_number=1,
            amount=po.agreed_amount,
            verified=False,
        )
        emit_agent_thinking("buyer", 1)
        logger.info(
            "[CLAUDE - BUYER] Round 1: sending prompt... (DEMO_MODE stub)"
        )
        logger.info(
            "[CLAUDE - BUYER] Proposed amount: %s",
            po.agreed_amount,
        )
        emit_agent_message(
            speaker="buyer",
            text=(
                f"Verified against PO/GR — accepting ${po.agreed_amount:,.2f}."
                f"{kg_note}"
            ),
            round_number=1,
            amount=po.agreed_amount,
            verified=True,
        )
        emit_settlement_banner(converged=True, amount=settlement.final_amount)
        audits.extend(
            _emit(
                step_name="demo_negotiation",
                step_type="deterministic",
                input_summary=(
                    f"DEMO_MODE discrepancy=${validation.discrepancy_amount:.2f} "
                    f"({rel:.1%} of PO)"
                ),
                output_summary=(
                    f"Agents converge on PO amount ${settlement.final_amount:.2f}"
                ),
                details={
                    "final_amount": settlement.final_amount,
                    "agreed_by_both": True,
                    "within_bounds": True,
                    "demo_mode": True,
                },
            )
        )
        return settlement, audits

    settlement = Settlement(
        final_amount=invoice.invoice_amount,
        agreed_by_both=False,
        within_bounds=within_bounds(invoice.invoice_amount, min_a, max_a),
    )
    emit_agent_thinking("supplier", 1)
    logger.info(
        "[CLAUDE - SUPPLIER] Round 1: sending prompt... (DEMO_MODE stub)"
    )
    logger.info(
        "[CLAUDE - SUPPLIER] Proposed amount: %s",
        invoice.invoice_amount,
    )
    emit_agent_message(
        speaker="supplier",
        text=(
            f"We stand by the invoice total ${invoice.invoice_amount:,.2f}."
            f"{kg_note}"
        ),
        round_number=1,
        amount=invoice.invoice_amount,
        verified=False,
    )
    emit_agent_thinking("buyer", 1)
    logger.info(
        "[CLAUDE - BUYER] Round 1: sending prompt... (DEMO_MODE stub)"
    )
    logger.info(
        "[CLAUDE - BUYER] Proposed amount: %s",
        po.agreed_amount,
    )
    emit_agent_message(
        speaker="buyer",
        text=(
            f"Verified against source — gap too large; counter at PO "
            f"${po.agreed_amount:,.2f}.{kg_note}"
        ),
        round_number=1,
        amount=po.agreed_amount,
        verified=True,
    )
    emit_agent_thinking("supplier", 2)
    logger.info(
        "[CLAUDE - SUPPLIER] Round 2: sending prompt... (DEMO_MODE stub)"
    )
    logger.info(
        "[CLAUDE - SUPPLIER] Proposed amount: %s",
        invoice.invoice_amount,
    )
    emit_agent_message(
        speaker="supplier",
        text="Unable to concede further within policy.",
        round_number=2,
        amount=invoice.invoice_amount,
        verified=False,
    )
    emit_settlement_banner(converged=False, amount=settlement.final_amount)
    audits.extend(
        _emit(
            step_name="demo_negotiation",
            step_type="deterministic",
            input_summary=(
                f"DEMO_MODE large gap ${validation.discrepancy_amount:.2f} "
                f"({rel:.1%} of PO)"
            ),
            output_summary=(
                "No convergence within max_rounds — escalate "
                f"(within_bounds={settlement.within_bounds})"
            ),
            details={
                "final_amount": settlement.final_amount,
                "agreed_by_both": False,
                "within_bounds": settlement.within_bounds,
                "demo_mode": True,
            },
        )
    )
    return settlement, audits
