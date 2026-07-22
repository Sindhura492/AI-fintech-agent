"""Cash-optimization graph wiring and entrypoint."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.bounds import DEFAULT_DAYS_EARLY, compute_discount_math
from app.agents.cash_buyer_agent import cash_buyer_agent
from app.agents.cash_supplier_agent import cash_supplier_agent
from app.agents.negotiation_state import CashOptState
from app.core.schemas_documents import ExtractedInvoice
from app.core.schemas_audit import AuditEntry
from app.core.schemas_negotiation import CashOptimizationProposal
from app.observability.audit import write_audit_entry
from app.seed.mock_data import get_buyer_profile, get_vendor_payment_terms


def build_cash_optimization_graph():
    """Compile supplier → buyer cash-optimization LangGraph."""
    graph = StateGraph(CashOptState)
    graph.add_node("cash_supplier_agent", cash_supplier_agent)
    graph.add_node("cash_buyer_agent", cash_buyer_agent)
    graph.add_edge(START, "cash_supplier_agent")
    graph.add_edge("cash_supplier_agent", "cash_buyer_agent")
    graph.add_edge("cash_buyer_agent", END)
    return graph.compile()


def run_cash_optimization(
    invoice: ExtractedInvoice,
    *,
    days_early: int = DEFAULT_DAYS_EARLY,
) -> tuple[CashOptimizationProposal, list[AuditEntry]]:
    """Run early-payment negotiation grounded in vendor source terms + buyer cash."""
    terms = get_vendor_payment_terms(invoice.vendor_name)
    if not terms or float(terms.get("early_payment_discount_rate", 0)) <= 0:
        raise ValueError(
            f"Vendor {invoice.vendor_name!r} is not early-payment eligible"
        )

    rate = float(terms["early_payment_discount_rate"])
    terms_days = int(terms["standard_payment_terms_days"])
    buyer = get_buyer_profile()
    available_cash = float(buyer["available_cash"])

    start_audit = write_audit_entry(
        step_name="cash_optimization_start",
        step_type="deterministic",
        input_summary=(
            f"vendor={invoice.vendor_name} amount=${invoice.invoice_amount:.2f} "
            f"source_rate={rate} terms={terms_days}d"
        ),
        output_summary=(
            f"Starting cash-opt graph (days_early={days_early}, "
            f"available_cash=${available_cash:.2f})"
        ),
        details={
            "discount_rate": rate,
            "standard_payment_terms_days": terms_days,
            "days_early": days_early,
            "available_cash": available_cash,
        },
    )

    initial: CashOptState = {
        "invoice": invoice,
        "discount_rate": rate,
        "standard_terms_days": terms_days,
        "days_early": days_early,
        "available_cash": available_cash,
        "supplier_pitch": "",
        "proposal": None,
        "math_ok": False,
        "audit_trail": [start_audit],
    }
    final_state = build_cash_optimization_graph().invoke(initial)
    proposal = final_state.get("proposal")
    if proposal is None:
        math = compute_discount_math(invoice.invoice_amount, rate)
        proposal = CashOptimizationProposal(
            original_amount=invoice.invoice_amount,
            discount_rate=rate,
            discount_amount=math["discount_amount"],
            net_payable=math["net_payable"],
            days_early=days_early,
            accepted=False,
            reasoning="Cash optimization graph produced no proposal.",
        )
    return proposal, list(final_state.get("audit_trail") or [start_audit])

