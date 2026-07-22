"""Buyer node for early-payment cash optimization."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.bounds import compute_discount_math, verify_discount_math
from app.agents.llm import _emit, _llm
from app.agents.negotiation_state import CashOptState
from app.core.schemas_negotiation import CashOptimizationProposal
from app.observability.audit_events import emit_agent_message, emit_agent_thinking, emit_settlement_banner
from app.seed.demo_mode import demo_mode_enabled


def cash_buyer_agent(state: CashOptState) -> dict:
    """Buyer verifies discount math deterministically, then decides on cash."""
    invoice = state["invoice"]
    rate = state["discount_rate"]
    days_early = state["days_early"]
    available_cash = state["available_cash"]
    pitch = state.get("supplier_pitch") or ""

    emit_agent_thinking("buyer", 1)

    math = compute_discount_math(invoice.invoice_amount, rate)
    verification = verify_discount_math(
        original_amount=invoice.invoice_amount,
        discount_rate=rate,
        discount_amount=math["discount_amount"],
        net_payable=math["net_payable"],
    )
    verify_audit = _emit(
        step_name="verify_discount_math",
        step_type="deterministic",
        input_summary=(
            f"amount=${invoice.invoice_amount:.2f} rate={rate} "
            f"claimed_discount=${math['discount_amount']:.2f}"
        ),
        output_summary=(
            f"math_ok={verification['math_ok']} "
            f"net=${verification['net_payable']:.2f}"
        ),
        details={
            "math_ok": bool(verification["math_ok"]),
            "discount_amount": float(verification["discount_amount"]),
            "net_payable": float(verification["net_payable"]),
            "discount_rate": rate,
        },
    )

    net = float(verification["net_payable"])
    cash_ok = available_cash >= net
    math_ok = bool(verification["math_ok"])

    if not math_ok:
        accepted = False
        reasoning = (
            "Declined — discount math failed buyer verification against source rate."
        )
    elif not cash_ok:
        accepted = False
        reasoning = (
            f"Declined — available_cash ${available_cash:,.2f} is less than "
            f"net_payable ${net:,.2f}; cannot fund early payment."
        )
    else:
        accepted = True
        reasoning = (
            f"Accepted — math verified; early pay within {days_early} days saves "
            f"${float(verification['discount_amount']):,.2f}. "
            f"Cash ${available_cash:,.2f} covers net ${net:,.2f}. "
            f"Supplier pitch noted: {pitch[:120]}"
        )

    if not demo_mode_enabled() and math_ok:
        try:
            polished = _llm().invoke(
                [
                    SystemMessage(
                        content=(
                            "You are the buyer treasury agent. The accept/decline "
                            f"decision is FIXED: accepted={accepted}. Rewrite the "
                            "reasoning in 2 sentences. Do not change the decision."
                        )
                    ),
                    HumanMessage(content=reasoning),
                ]
            )
            content = getattr(polished, "content", None) or reasoning
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                )
            reasoning = str(content).strip() or reasoning
            llm_audit = _emit(
                step_name="cash_buyer_agent",
                step_type="llm",
                input_summary=(
                    f"accepted={accepted} net=${net:.2f} cash=${available_cash:.2f}"
                ),
                output_summary=reasoning[:240],
                details={
                    "accepted": accepted,
                    "available_cash": available_cash,
                    "net_payable": net,
                },
            )
        except Exception as exc:
            llm_audit = _emit(
                step_name="cash_buyer_agent",
                step_type="deterministic",
                input_summary=f"LLM polish skipped: {type(exc).__name__}",
                output_summary=reasoning[:240],
                details={"accepted": accepted, "available_cash": available_cash},
            )
    else:
        llm_audit = _emit(
            step_name="cash_buyer_agent",
            step_type="deterministic",
            input_summary=(
                f"accepted={accepted} net=${net:.2f} cash=${available_cash:.2f}"
            ),
            output_summary=reasoning[:240],
            details={
                "accepted": accepted,
                "available_cash": available_cash,
                "net_payable": net,
                "demo_mode": demo_mode_enabled(),
            },
        )

    proposal = CashOptimizationProposal(
        original_amount=invoice.invoice_amount,
        discount_rate=rate,
        discount_amount=float(verification["discount_amount"]),
        net_payable=net,
        days_early=days_early,
        accepted=accepted,
        reasoning=reasoning,
    )
    emit_agent_message(
        speaker="buyer",
        text=reasoning,
        round_number=1,
        amount=net if accepted else invoice.invoice_amount,
        verified=True,
    )
    emit_settlement_banner(
        converged=accepted,
        amount=net if accepted else invoice.invoice_amount,
    )
    return {
        "proposal": proposal,
        "math_ok": math_ok,
        "audit_trail": verify_audit + llm_audit,
    }

