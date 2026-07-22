"""Hard financial bounds and cash-discount math (deterministic)."""

from __future__ import annotations

from typing import Literal

from app.agents.llm import _amounts_equal, _emit, _last_proposal
from app.agents.negotiation_state import NegotiationState
from app.core.schemas_audit import AuditEntry
from app.core.schemas_documents import GoodsReceipt, PurchaseOrder
from app.core.schemas_negotiation import DisputeProposal

BOUNDS_PCT = 0.05  # PO amount ± 5%
AMOUNT_EQ_TOLERANCE = 0.01  # $0.01 — treat as same offer

# How far a new settlement may drift from this vendor's past agreed settlements
# before we treat it as "out of historical range" (escalate after negotiation).
# Tight on purpose: PO±5% is the hard policy band; this catches "we've never
# accepted a settlement like this for this vendor before."
HISTORICAL_PAD_PCT = 0.03
HISTORICAL_MIN_SAMPLES = 2
HISTORICAL_MIN_PAD_USD = 25.0

DEFAULT_DAYS_EARLY = 10
DISCOUNT_MATH_TOLERANCE = 0.01  # $0.01


def compute_bounds(po: PurchaseOrder) -> tuple[float, float]:
    """Return (MIN_ACCEPTABLE, MAX_ACCEPTABLE) as PO agreed_amount ± 5%."""
    mid = po.agreed_amount
    return round(mid * (1 - BOUNDS_PCT), 2), round(mid * (1 + BOUNDS_PCT), 2)


def within_bounds(amount: float, min_acceptable: float, max_acceptable: float) -> bool:
    """Deterministic inclusive range check."""
    return min_acceptable <= amount <= max_acceptable


def historical_settlement_band(
    vendor_context: dict | None,
    *,
    min_samples: int = HISTORICAL_MIN_SAMPLES,
    pad_pct: float = HISTORICAL_PAD_PCT,
) -> dict[str, float | int] | None:
    """Band from this vendor's past *agreed* settlements.

    Returns None when there is not enough history. Used to detect settlements
    that do not match what this vendor has accepted before.
    """
    if not vendor_context:
        return None
    outcomes = vendor_context.get("settlement_outcomes") or {}
    recent = outcomes.get("recent") or []
    amounts: list[float] = []
    for row in recent:
        if not row.get("agreed_by_both"):
            continue
        try:
            amounts.append(float(row.get("final_amount")))
        except (TypeError, ValueError):
            continue
    avg = outcomes.get("avg_settlement_amount")
    if avg is not None and not amounts:
        try:
            amounts.append(float(avg))
        except (TypeError, ValueError):
            pass
    # Prefer unique agreed samples; duplicate avg if only one recent point.
    if len(amounts) < min_samples and avg is not None:
        try:
            a = float(avg)
            if a not in amounts:
                amounts.append(a)
        except (TypeError, ValueError):
            pass
    if len(amounts) < min_samples:
        return None

    lo = min(amounts)
    hi = max(amounts)
    mid = sum(amounts) / len(amounts)
    # Tight pad around past accepted amounts (not as wide as PO ±5%).
    pad = max(mid * pad_pct, HISTORICAL_MIN_PAD_USD)
    return {
        "min": round(lo - pad, 2),
        "max": round(hi + pad, 2),
        "avg": round(mid, 2),
        "n": len(amounts),
        "raw_min": round(lo, 2),
        "raw_max": round(hi, 2),
    }


def outside_historical_range(
    amount: float,
    vendor_context: dict | None,
    *,
    po_amount: float | None = None,
    receipt_amount: float | None = None,
) -> tuple[bool, dict[str, float | int] | None]:
    """True when ``amount`` is outside this vendor's past settlement band.

    Settling at the verified PO or goods-receipt amount is never an outlier -
    that is the contract baseline, even if recent history is mostly discounted
    early-pay settlements.
    """
    if po_amount is not None and abs(amount - float(po_amount)) <= AMOUNT_EQ_TOLERANCE:
        return False, historical_settlement_band(vendor_context)
    if receipt_amount is not None and abs(amount - float(receipt_amount)) <= AMOUNT_EQ_TOLERANCE:
        return False, historical_settlement_band(vendor_context)

    band = historical_settlement_band(vendor_context)
    if band is None:
        return False, None
    out = not within_bounds(amount, float(band["min"]), float(band["max"]))
    return out, band


def has_favorable_precedent(
    vendor_context: dict | None,
    amount: float,
    *,
    po_amount: float | None = None,
    tolerance_pct: float = 0.03,
) -> bool:
    """True when Neo4j already has a similar *approved* settlement for this vendor.

    Used so repeat favorable cases (same PO amount / prior auto-pay) do not
    keep escalating.
    """
    if not vendor_context:
        return False
    outcomes = vendor_context.get("settlement_outcomes") or {}
    recent = outcomes.get("recent") or []
    tol = max(abs(amount) * tolerance_pct, 1.0)
    for row in recent:
        gate = str(row.get("gate_action") or "").lower()
        if gate != "approve":
            continue
        if row.get("agreed_by_both") is False:
            continue
        try:
            prior = float(row.get("final_amount"))
        except (TypeError, ValueError):
            continue
        if abs(prior - amount) <= tol:
            return True
        if po_amount is not None and abs(prior - float(po_amount)) <= AMOUNT_EQ_TOLERANCE:
            if abs(amount - float(po_amount)) <= AMOUNT_EQ_TOLERANCE:
                return True
    return False


def verify_against_source(
    proposal: DisputeProposal,
    po: PurchaseOrder,
    receipt: GoodsReceipt,
) -> dict[str, float | bool | str]:
    """Deterministically check a supplier proposal against buyer source records."""
    proposed = proposal.proposed_amount
    po_amt = po.agreed_amount
    gr_amt = receipt.received_amount
    floor = min(po_amt, gr_amt)
    ceiling = max(po_amt, gr_amt)

    return {
        "proposed_amount": proposed,
        "po_amount": po_amt,
        "receipt_amount": gr_amt,
        "source_floor": floor,
        "source_ceiling": ceiling,
        "delta_vs_po": round(proposed - po_amt, 2),
        "delta_vs_receipt": round(proposed - gr_amt, 2),
        "matches_po": abs(proposed - po_amt) <= AMOUNT_EQ_TOLERANCE,
        "matches_receipt": abs(proposed - gr_amt) <= AMOUNT_EQ_TOLERANCE,
        "within_source_range": floor - AMOUNT_EQ_TOLERANCE
        <= proposed
        <= ceiling + AMOUNT_EQ_TOLERANCE,
        "po_id": po.po_id,
    }


def compute_discount_math(
    invoice_amount: float,
    discount_rate: float,
) -> dict[str, float]:
    """Deterministic early-payment math — never delegated to the LLM."""
    discount_amount = round(invoice_amount * discount_rate, 2)
    net_payable = round(invoice_amount - discount_amount, 2)
    return {
        "discount_amount": discount_amount,
        "net_payable": net_payable,
        "discount_rate": discount_rate,
        "original_amount": invoice_amount,
    }


def verify_discount_math(
    original_amount: float,
    discount_rate: float,
    discount_amount: float,
    net_payable: float,
) -> dict[str, float | bool]:
    """Buyer-side deterministic verification of supplier discount figures."""
    expected = compute_discount_math(original_amount, discount_rate)
    amount_ok = abs(discount_amount - expected["discount_amount"]) <= DISCOUNT_MATH_TOLERANCE
    net_ok = abs(net_payable - expected["net_payable"]) <= DISCOUNT_MATH_TOLERANCE
    return {
        **expected,
        "claimed_discount_amount": discount_amount,
        "claimed_net_payable": net_payable,
        "math_ok": amount_ok and net_ok,
    }


def audit_bounds_check(state: NegotiationState, side: str) -> list[AuditEntry]:
    """Emit a deterministic audit entry for a bounds edge evaluation."""
    prop = _last_proposal(state.get("proposals") or [], side)  # type: ignore[arg-type]
    amount = prop.proposed_amount if prop else -1.0
    ok = (
        within_bounds(amount, state["min_acceptable"], state["max_acceptable"])
        if prop
        else False
    )
    return _emit(
        step_name=f"bounds_check_{side}",
        step_type="deterministic",
        input_summary=(
            f"{side} amount ${amount:.2f} vs "
            f"[{state['min_acceptable']:.2f}, {state['max_acceptable']:.2f}]"
        ),
        output_summary=f"within_bounds={ok}",
        details={
            "proposed_amount": amount,
            "min_acceptable": state["min_acceptable"],
            "max_acceptable": state["max_acceptable"],
            "within_bounds": ok,
            "proposing_side": side,
            "round_number": state["round_number"],
        },
    )


def _converged(state: NegotiationState) -> bool:
    if state.get("buyer_accepted"):
        return True
    buyer = _last_proposal(state.get("proposals") or [], "buyer")
    supplier = _last_proposal(state.get("proposals") or [], "supplier")
    if buyer is None or supplier is None:
        return False
    return _amounts_equal(buyer.proposed_amount, supplier.proposed_amount)


def route_after_supplier(
    state: NegotiationState,
) -> Literal["buyer_agent", "escalate_settlement", "bounds_reject_supplier"]:
    """Accept supplier→buyer only if the proposal is inside PO ± 5%."""
    supplier = _last_proposal(state.get("proposals") or [], "supplier")
    if supplier is None:
        return "escalate_settlement"
    if not within_bounds(
        supplier.proposed_amount, state["min_acceptable"], state["max_acceptable"]
    ):
        return "bounds_reject_supplier"
    return "buyer_agent"


def route_after_buyer(
    state: NegotiationState,
) -> Literal[
    "finalize_settlement",
    "bump_round",
    "escalate_settlement",
    "bounds_reject_buyer",
]:
    """Settle only on in-bounds convergence; else loop or escalate."""
    buyer = _last_proposal(state.get("proposals") or [], "buyer")
    if buyer is None:
        return "escalate_settlement"

    if not within_bounds(
        buyer.proposed_amount, state["min_acceptable"], state["max_acceptable"]
    ):
        return "bounds_reject_buyer"

    if _converged(state):
        # Final amount must stay in bounds.
        supplier = _last_proposal(state.get("proposals") or [], "supplier")
        amount = (
            supplier.proposed_amount
            if state.get("buyer_accepted") and supplier
            else buyer.proposed_amount
        )
        if within_bounds(amount, state["min_acceptable"], state["max_acceptable"]):
            return "finalize_settlement"
        return "bounds_reject_buyer"

    if state["round_number"] >= state["max_rounds"]:
        return "escalate_settlement"

    return "bump_round"


def bounds_reject_supplier(state: NegotiationState) -> dict:
    """Deterministic rejection of an out-of-bounds supplier proposal."""
    audit = audit_bounds_check(state, "supplier")
    # Re-emit explicit reject, then fall through to escalate via edge.
    reject = _emit(
        step_name="bounds_reject_supplier",
        step_type="deterministic",
        input_summary="supplier proposal outside PO ± 5%",
        output_summary="proposal rejected by graph edge — cannot settle",
        details={"within_bounds": False, "round_number": state["round_number"]},
    )
    return {"audit_trail": audit + reject}


def bounds_reject_buyer(state: NegotiationState) -> dict:
    """Deterministic rejection of an out-of-bounds buyer proposal."""
    audit = audit_bounds_check(state, "buyer")
    reject = _emit(
        step_name="bounds_reject_buyer",
        step_type="deterministic",
        input_summary="buyer proposal outside PO ± 5%",
        output_summary="proposal rejected by graph edge — cannot settle",
        details={"within_bounds": False, "round_number": state["round_number"]},
    )
    return {"audit_trail": audit + reject}
