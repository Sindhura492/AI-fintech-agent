"""Supplier node for early-payment cash optimization."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.bounds import compute_discount_math
from app.agents.llm import _emit, _llm
from app.agents.negotiation_state import CashOptState
from app.observability.audit_events import emit_agent_message, emit_agent_thinking
from app.seed.demo_mode import demo_mode_enabled


def cash_supplier_agent(state: CashOptState) -> dict:
    """Supplier proposes early pay using the *source* discount_rate only."""
    invoice = state["invoice"]
    rate = state["discount_rate"]
    days_early = state["days_early"]
    terms_days = state["standard_terms_days"]
    math = compute_discount_math(invoice.invoice_amount, rate)

    emit_agent_thinking("supplier", 1)

    if demo_mode_enabled():
        pitch = (
            f"Pay within {days_early} days (vs standard net {terms_days}) "
            f"for a {rate:.1%} discount — save ${math['discount_amount']:.2f}, "
            f"net payable ${math['net_payable']:.2f}."
        )
        emit_agent_message(
            speaker="supplier",
            text=pitch,
            round_number=1,
            amount=math["net_payable"],
            verified=False,
        )
        audit = _emit(
            step_name="cash_supplier_agent",
            step_type="deterministic",
            input_summary=(
                f"DEMO vendor={invoice.vendor_name} rate={rate} "
                f"(source) amount=${invoice.invoice_amount:.2f}"
            ),
            output_summary=pitch,
            details={
                "discount_rate": rate,
                "discount_amount": math["discount_amount"],
                "net_payable": math["net_payable"],
                "days_early": days_early,
                "demo_mode": True,
            },
        )
        return {"supplier_pitch": pitch, "audit_trail": audit}

    system = f"""You are the supplier AR agent for {invoice.vendor_name}.
Propose an early-payment discount offer to the buyer.

HARD CONSTRAINTS (do not invent or change these — they come from our contracts):
- early_payment_discount_rate = {rate}  ({rate:.1%})
- standard_payment_terms_days = {terms_days}
- days_early for the offer = {days_early}
- invoice_amount = {invoice.invoice_amount}
- discount_amount = {math['discount_amount']}  (already computed)
- net_payable = {math['net_payable']}  (already computed)

Write a short persuasive pitch (2-4 sentences) that quotes these exact figures.
Do NOT propose a different discount rate or different math.
Return ONLY the pitch text, no JSON.
"""
    raw = _llm().invoke(
        [
            SystemMessage(content=system),
            HumanMessage(content="Draft the early-payment offer pitch now."),
        ]
    )
    pitch = getattr(raw, "content", None) or str(raw)
    if isinstance(pitch, list):
        pitch = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in pitch
        )
    pitch = str(pitch).strip()

    emit_agent_message(
        speaker="supplier",
        text=pitch,
        round_number=1,
        amount=math["net_payable"],
        verified=False,
    )

    audit = _emit(
        step_name="cash_supplier_agent",
        step_type="llm",
        input_summary=(
            f"vendor={invoice.vendor_name} source_rate={rate} "
            f"amount=${invoice.invoice_amount:.2f}"
        ),
        output_summary=pitch[:240],
        details={
            "discount_rate": rate,
            "discount_amount": math["discount_amount"],
            "net_payable": math["net_payable"],
            "days_early": days_early,
        },
    )
    return {"supplier_pitch": pitch, "audit_trail": audit}

