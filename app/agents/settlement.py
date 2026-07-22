"""Settlement and round-control graph nodes."""

from __future__ import annotations

from app.agents.bounds import within_bounds
from app.agents.llm import _amounts_equal, _emit, _last_proposal
from app.agents.negotiation_state import NegotiationState
from app.observability.audit_events import emit_settlement_banner
from app.core.schemas_negotiation import Settlement


def finalize_settlement(state: NegotiationState) -> dict:
    """Build an agreed Settlement (only reached when bounds edge allows it)."""
    proposals = state.get("proposals") or []
    buyer = _last_proposal(proposals, "buyer")
    supplier = _last_proposal(proposals, "supplier")

    if state.get("buyer_accepted") and supplier is not None:
        final_amount = supplier.proposed_amount
    elif buyer is not None and supplier is not None and _amounts_equal(
        buyer.proposed_amount, supplier.proposed_amount
    ):
        final_amount = buyer.proposed_amount
    elif buyer is not None:
        final_amount = buyer.proposed_amount
    elif supplier is not None:
        final_amount = supplier.proposed_amount
    else:
        final_amount = state["po"].agreed_amount

    in_bounds = within_bounds(
        final_amount, state["min_acceptable"], state["max_acceptable"]
    )
    settlement = Settlement(
        final_amount=final_amount,
        agreed_by_both=True,
        within_bounds=in_bounds,
    )
    emit_settlement_banner(converged=True, amount=final_amount)
    audit = _emit(
        step_name="finalize_settlement",
        step_type="deterministic",
        input_summary=f"converged amount ${final_amount:.2f}",
        output_summary=f"Settlement agreed_by_both=True within_bounds={in_bounds}",
        details={
            "final_amount": final_amount,
            "agreed_by_both": True,
            "within_bounds": in_bounds,
        },
    )
    return {"settlement": settlement, "escalate": False, "audit_trail": audit}


def escalate_settlement(state: NegotiationState) -> dict:
    """No convergence (or OOB) — Settlement with agreed_by_both=False."""
    proposals = state.get("proposals") or []
    buyer = _last_proposal(proposals, "buyer")
    supplier = _last_proposal(proposals, "supplier")

    if buyer is not None:
        final_amount = buyer.proposed_amount
    elif supplier is not None:
        final_amount = supplier.proposed_amount
    else:
        final_amount = state["invoice"].invoice_amount

    in_bounds = within_bounds(
        final_amount, state["min_acceptable"], state["max_acceptable"]
    )
    settlement = Settlement(
        final_amount=final_amount,
        agreed_by_both=False,
        within_bounds=in_bounds,
    )
    emit_settlement_banner(converged=False, amount=final_amount)
    audit = _emit(
        step_name="escalate_settlement",
        step_type="deterministic",
        input_summary=(
            f"round={state['round_number']}/{state['max_rounds']} "
            f"no convergence; amount ${final_amount:.2f}"
        ),
        output_summary=(
            f"Settlement agreed_by_both=False within_bounds={in_bounds} → escalate"
        ),
        details={
            "final_amount": final_amount,
            "agreed_by_both": False,
            "within_bounds": in_bounds,
            "round_number": state["round_number"],
        },
    )
    return {"settlement": settlement, "escalate": True, "audit_trail": audit}


def bump_round(state: NegotiationState) -> dict:
    """Advance to the next negotiation round before the supplier speaks again."""
    new_round = state["round_number"] + 1
    audit = _emit(
        step_name="bump_round",
        step_type="deterministic",
        input_summary=f"completed round {state['round_number']}",
        output_summary=f"starting round {new_round}",
        details={"round_number": new_round},
    )
    return {"round_number": new_round, "buyer_accepted": False, "audit_trail": audit}
