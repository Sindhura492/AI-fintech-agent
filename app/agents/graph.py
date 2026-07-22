"""LangGraph assembly and runners for buyer ↔ supplier negotiation."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.bounds import (
    BOUNDS_PCT,
    bounds_reject_buyer,
    bounds_reject_supplier,
    compute_bounds,
    route_after_buyer,
    route_after_supplier,
)
from app.agents.buyer_agent import buyer_agent
from app.agents.cash_optimization import run_cash_optimization
from app.agents.demo_negotiate import _demo_negotiate
from app.agents.llm import _emit
from app.agents.negotiation_state import NegotiationState
from app.agents.settlement import bump_round, escalate_settlement, finalize_settlement
from app.agents.supplier_agent import supplier_agent
from app.observability.audit import write_audit_entry
from app.core.schemas_audit import AuditEntry
from app.core.schemas_documents import (
    ExtractedInvoice,
    GoodsReceipt,
    PurchaseOrder,
    ValidationResult,
)
from app.core.schemas_negotiation import Settlement
from app.seed.demo_mode import demo_mode_enabled

# Re-export for callers that import cash opt from graph.
__all__ = [
    "build_negotiation_graph",
    "run_cash_optimization",
    "run_negotiation",
]


def build_negotiation_graph():
    """Compile the buyer ↔ supplier LangGraph with bound-enforcing edges."""
    graph = StateGraph(NegotiationState)

    graph.add_node("supplier_agent", supplier_agent)
    graph.add_node("buyer_agent", buyer_agent)
    graph.add_node("finalize_settlement", finalize_settlement)
    graph.add_node("escalate_settlement", escalate_settlement)
    graph.add_node("bump_round", bump_round)
    graph.add_node("bounds_reject_supplier", bounds_reject_supplier)
    graph.add_node("bounds_reject_buyer", bounds_reject_buyer)

    graph.add_edge(START, "supplier_agent")
    graph.add_conditional_edges(
        "supplier_agent",
        route_after_supplier,
        {
            "buyer_agent": "buyer_agent",
            "escalate_settlement": "escalate_settlement",
            "bounds_reject_supplier": "bounds_reject_supplier",
        },
    )
    graph.add_edge("bounds_reject_supplier", "escalate_settlement")

    graph.add_conditional_edges(
        "buyer_agent",
        route_after_buyer,
        {
            "finalize_settlement": "finalize_settlement",
            "bump_round": "bump_round",
            "escalate_settlement": "escalate_settlement",
            "bounds_reject_buyer": "bounds_reject_buyer",
        },
    )
    graph.add_edge("bounds_reject_buyer", "escalate_settlement")
    graph.add_edge("bump_round", "supplier_agent")
    graph.add_edge("finalize_settlement", END)
    graph.add_edge("escalate_settlement", END)

    return graph.compile()


def run_negotiation(
    invoice: ExtractedInvoice,
    po: PurchaseOrder,
    receipt: GoodsReceipt,
    validation: ValidationResult,
    max_rounds: int = 3,
    vendor_context: dict | None = None,
    similar_disputes: list[str] | None = None,
) -> tuple[Settlement, list[AuditEntry]]:
    """Run the bounded negotiation graph and return settlement + audit trail."""
    if validation.matched:
        settlement = Settlement(
            final_amount=invoice.invoice_amount,
            agreed_by_both=True,
            within_bounds=True,
        )
        audit = _emit(
            step_name="negotiation_short_circuit",
            step_type="deterministic",
            input_summary="validation.matched=True — skip negotiation",
            output_summary=f"Settlement ${settlement.final_amount:.2f} agreed",
            details={
                "final_amount": settlement.final_amount,
                "agreed_by_both": True,
                "within_bounds": True,
            },
        )
        return settlement, audit

    min_a, max_a = compute_bounds(po)
    bounds_audit = write_audit_entry(
        step_name="compute_bounds",
        step_type="deterministic",
        input_summary=f"PO {po.po_id} agreed=${po.agreed_amount:.2f}",
        output_summary=f"MIN_ACCEPTABLE=${min_a:.2f} MAX_ACCEPTABLE=${max_a:.2f}",
        details={
            "min_acceptable": min_a,
            "max_acceptable": max_a,
            "po_amount": po.agreed_amount,
            "bounds_pct": BOUNDS_PCT,
        },
    )

    if demo_mode_enabled():
        return _demo_negotiate(
            invoice=invoice,
            po=po,
            validation=validation,
            min_a=min_a,
            max_a=max_a,
            bounds_audit=bounds_audit,
            vendor_context=vendor_context,
            similar_disputes=similar_disputes,
        )

    initial: NegotiationState = {
        "invoice": invoice,
        "po": po,
        "receipt": receipt,
        "validation_result": validation,
        "round_number": 1,
        "proposals": [],
        "settlement": None,
        "max_rounds": max_rounds,
        "min_acceptable": min_a,
        "max_acceptable": max_a,
        "audit_trail": [bounds_audit],
        "buyer_accepted": False,
        "last_verification_ok": False,
        "escalate": False,
        "vendor_context": vendor_context or {},
        "similar_disputes": list(similar_disputes or []),
    }

    compiled = build_negotiation_graph()
    final_state = compiled.invoke(initial)

    settlement = final_state.get("settlement")
    if settlement is None:
        settlement = Settlement(
            final_amount=invoice.invoice_amount,
            agreed_by_both=False,
            within_bounds=False,
        )
    return settlement, list(final_state.get("audit_trail") or [bounds_audit])
