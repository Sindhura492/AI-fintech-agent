"""Deterministic enforcement gate (sole payment chokepoint)."""

from __future__ import annotations

from typing import Any

from app.agents.bounds import (
    AMOUNT_EQ_TOLERANCE,
    has_favorable_precedent,
    outside_historical_range,
)
from app.core import (
    CashOptimizationProposal,
    GateDecision,
    Settlement,
    ValidationResult,
)
from app.observability.console_logging import get_logger
from app.seed.mock_data import get_vendor_payment_terms

logger = get_logger(__name__)

AUTO_APPROVAL_THRESHOLD = 5000.0


def _amounts_close(a: float, b: float, *, tol: float = AMOUNT_EQ_TOLERANCE) -> bool:
    return abs(float(a) - float(b)) <= tol


def _payment_terms_mismatch(
    *,
    settlement: Settlement,
    invoice_amount: float | None,
    cash_opt: CashOptimizationProposal | None,
    vendor_name: str | None,
) -> str | None:
    """Return a reason when early-pay settlement breaks vendor payment terms."""
    if cash_opt is None or not cash_opt.accepted:
        return None
    if invoice_amount is None:
        return None
    terms = get_vendor_payment_terms(vendor_name or "") if vendor_name else None
    if not terms:
        return "early-pay accepted but vendor payment terms not on file"
    rate = float(terms.get("early_payment_discount_rate") or 0)
    if rate <= 0:
        return "early-pay accepted but vendor is not discount-eligible"
    expected_net = round(float(invoice_amount) * (1.0 - rate), 2)
    if _amounts_close(settlement.final_amount, expected_net, tol=0.05):
        return None
    if _amounts_close(settlement.final_amount, float(invoice_amount), tol=0.05):
        # Fell back to full invoice - fine, terms not violated
        return None
    return (
        f"early-pay net ${settlement.final_amount:,.2f} does not match "
        f"contract discount {rate:.1%} (expected ~${expected_net:,.2f})"
    )


def _contract_terms_mismatch(
    *,
    settlement: Settlement,
    validation: ValidationResult,
    po_amount: float | None,
    receipt_amount: float | None,
) -> str | None:
    """Return a reason when settlement still disagrees with verified contract docs."""
    if validation.matched:
        return None

    def _near_contract(target: float | None) -> bool:
        if target is None or float(target) == 0:
            return False
        # Same 1% tolerance as three-way match - "close enough" to contract.
        return abs(settlement.final_amount - float(target)) / abs(float(target)) <= 0.01

    if _near_contract(po_amount) or _near_contract(receipt_amount):
        return None
    return (
        f"settlement ${settlement.final_amount:,.2f} does not match "
        f"PO/receipt contract amounts "
        f"(PO={po_amount if po_amount is not None else 'n/a'}, "
        f"GR={receipt_amount if receipt_amount is not None else 'n/a'})"
    )


def enforce(
    settlement: Settlement,
    validation_result: ValidationResult,
    *,
    vendor_context: dict[str, Any] | None = None,
    po_amount: float | None = None,
    receipt_amount: float | None = None,
    invoice_amount: float | None = None,
    vendor_name: str | None = None,
    cash_opt: CashOptimizationProposal | None = None,
) -> GateDecision:
    """Apply ordered deterministic rules and return a GateDecision.

    Escalate only for real risk:
      - no agreement
      - payment-terms math broken
      - contract terms still unmatched after negotiation
      - true amount outlier with no prior favorable approve
      - large first-time pays (>$5k) with no similar approved precedent

    Favorable repeats (PO/GR match, or prior Neo4j approve near this amount)
    auto-approve when otherwise in bounds.
    """
    logger.info("[ENFORCEMENT GATE] Checking rule 1/5 (agreed_by_both)...")
    if not settlement.agreed_by_both:
        decision = GateDecision(
            action="escalate",
            reason="no convergence after negotiation rounds",
            rule_fired="NO_CONVERGENCE",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s - %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    logger.info("[ENFORCEMENT GATE] Checking rule 2/5 (PO policy bounds)...")
    if not settlement.within_bounds:
        decision = GateDecision(
            action="deny",
            reason="outside negotiation bounds",
            rule_fired="OUTSIDE_BOUNDS",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s - %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    logger.info("[ENFORCEMENT GATE] Checking rule 3/5 (payment / contract terms)...")
    terms_reason = _payment_terms_mismatch(
        settlement=settlement,
        invoice_amount=invoice_amount,
        cash_opt=cash_opt,
        vendor_name=vendor_name,
    )
    if terms_reason:
        decision = GateDecision(
            action="escalate",
            reason=terms_reason,
            rule_fired="PAYMENT_TERMS_MISMATCH",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s - %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    contract_reason = _contract_terms_mismatch(
        settlement=settlement,
        validation=validation_result,
        po_amount=po_amount,
        receipt_amount=receipt_amount,
    )
    favorable = has_favorable_precedent(
        vendor_context,
        settlement.final_amount,
        po_amount=po_amount,
    )
    if contract_reason and not favorable:
        decision = GateDecision(
            action="escalate",
            reason=contract_reason,
            rule_fired="CONTRACT_TERMS_MISMATCH",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s - %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    at_contract = (
        po_amount is not None and _amounts_close(settlement.final_amount, po_amount)
    ) or (
        receipt_amount is not None
        and _amounts_close(settlement.final_amount, receipt_amount)
    )
    clean_contract = bool(validation_result.matched and at_contract)

    logger.info("[ENFORCEMENT GATE] Checking rule 4/5 (true outliers)...")
    out_hist, band = outside_historical_range(
        settlement.final_amount,
        vendor_context,
        po_amount=po_amount,
        receipt_amount=receipt_amount,
    )
    if out_hist and band is not None and not favorable and not clean_contract:
        decision = GateDecision(
            action="escalate",
            reason=(
                f"outlier settlement ${settlement.final_amount:,.2f} unlike "
                f"past approved range "
                f"(${float(band['min']):,.2f}-${float(band['max']):,.2f}, "
                f"n={int(band['n'])})"
            ),
            rule_fired="AMOUNT_OUTLIER",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s - %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    logger.info(
        "[ENFORCEMENT GATE] Checking rule 5/5 (large pay > $%.0f without precedent)...",
        AUTO_APPROVAL_THRESHOLD,
    )
    if settlement.final_amount > AUTO_APPROVAL_THRESHOLD and not favorable:
        # First-time (or dissimilar) large payment - human review.
        # Repeat favorable large settles auto-approve.
        decision = GateDecision(
            action="escalate",
            reason="above $5000 threshold with no similar approved precedent",
            rule_fired="ABOVE_AUTO_APPROVAL_THRESHOLD",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s - %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    if favorable or clean_contract:
        reason = (
            "favorable precedent / contract match - auto-approve"
            if favorable
            else "clean PO/receipt match - auto-approve"
        )
    else:
        reason = "within bounds, terms, and risk checks"
    decision = GateDecision(
        action="approve",
        reason=reason,
        rule_fired="WITHIN_BOUNDS_AND_THRESHOLD",
    )
    logger.info(
        "[ENFORCEMENT GATE] Decision: %s - %s",
        decision.action,
        decision.rule_fired,
    )
    return decision


def execute_payment(settlement: Settlement, decision: GateDecision) -> None:
    """Mock payment execution - the only function allowed to "pay"."""
    if decision.action != "approve":
        raise PermissionError(
            f"execute_payment blocked: GateDecision.action={decision.action!r} "
            f"(rule_fired={decision.rule_fired}). Only action='approve' may pay."
        )

    amount = settlement.final_amount
    logger.info("[ENFORCEMENT GATE] PAYMENT EXECUTED: %s", amount)
