from __future__ import annotations

from app.core import GateDecision, Settlement, ValidationResult
from app.observability.console_logging import get_logger

logger = get_logger(__name__)

AUTO_APPROVAL_THRESHOLD = 5000.0


def enforce(
    settlement: Settlement,
    validation_result: ValidationResult,
) -> GateDecision:
    """Apply ordered deterministic rules and return a GateDecision."""
    _ = validation_result

    logger.info("[ENFORCEMENT GATE] Checking rule 1/3 (agreed_by_both)...")
    if not settlement.agreed_by_both:
        decision = GateDecision(
            action="escalate",
            reason="no convergence after 3 rounds",
            rule_fired="NO_CONVERGENCE",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s — %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    logger.info("[ENFORCEMENT GATE] Checking rule 2/3 (within_bounds)...")
    if not settlement.within_bounds:
        decision = GateDecision(
            action="deny",
            reason="outside negotiation bounds",
            rule_fired="OUTSIDE_BOUNDS",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s — %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    logger.info(
        "[ENFORCEMENT GATE] Checking rule 3/3 (amount > $%.0f)...",
        AUTO_APPROVAL_THRESHOLD,
    )
    if settlement.final_amount > AUTO_APPROVAL_THRESHOLD:
        decision = GateDecision(
            action="escalate",
            reason="above $5000 threshold",
            rule_fired="ABOVE_AUTO_APPROVAL_THRESHOLD",
        )
        logger.info(
            "[ENFORCEMENT GATE] Decision: %s — %s",
            decision.action,
            decision.rule_fired,
        )
        return decision

    decision = GateDecision(
        action="approve",
        reason="within bounds and threshold",
        rule_fired="WITHIN_BOUNDS_AND_THRESHOLD",
    )
    logger.info(
        "[ENFORCEMENT GATE] Decision: %s — %s",
        decision.action,
        decision.rule_fired,
    )
    return decision


def execute_payment(settlement: Settlement, decision: GateDecision) -> None:
    """Mock payment execution — the only function allowed to "pay"."""
    if decision.action != "approve":
        raise PermissionError(
            f"execute_payment blocked: GateDecision.action={decision.action!r} "
            f"(rule_fired={decision.rule_fired}). Only action='approve' may pay."
        )

    amount = settlement.final_amount
    logger.info("[ENFORCEMENT GATE] PAYMENT EXECUTED: %s", amount)
