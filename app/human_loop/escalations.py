"""In-memory store for escalated invoices awaiting human approve/deny."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from app.core import (
    ExtractedInvoice,
    GateDecision,
    PurchaseOrder,
    Settlement,
    ValidationResult,
)
from app.human_loop.notifications import notify_escalation
from app.observability.audit import audit_log, get_session_id, write_audit_entry
from app.pipeline.enforcement import execute_payment

EscalationStatus = Literal["pending", "approved", "denied"]

# Friendlier copy for terse gate reasons.
REASON_DISPLAY: dict[str, str] = {
    "no convergence": "no convergence after negotiation rounds",
    "no convergence after 3 rounds": "no convergence after negotiation rounds",
    "no convergence after negotiation rounds": "no convergence after negotiation rounds",
    "above auto-approval threshold": "above $5000 with no similar approved precedent",
    "above $5000 threshold": "above $5000 with no similar approved precedent",
    "above $5000 threshold with no similar approved precedent": (
        "above $5000 with no similar approved precedent"
    ),
    "no matching PO found": "no matching PO found",
    "outside negotiation bounds": "outside PO policy band",
}


def display_reason(reason: str) -> str:
    """Map internal gate reasons to human-facing notification text."""
    key = reason.strip().lower()
    if key in REASON_DISPLAY:
        return REASON_DISPLAY[key]
    if "outside vendor's past agreed range" in key or "outside vendor" in key:
        return "unlike past accepted settlements for this vendor"
    if "outlier settlement" in key:
        return "amount outlier vs past approved settlements"
    if "does not match po/receipt" in key or "contract" in key:
        return "contract terms still unmatched after negotiation"
    if "early-pay" in key or "discount" in key:
        return "payment terms mismatch"
    return reason


@dataclass
class EscalatedCase:
    session_id: str
    vendor_name: str
    amount: float | None
    reason: str
    rule_fired: str
    status: EscalationStatus = "pending"
    settlement: Settlement | None = None
    po_id: str | None = None
    invoice: ExtractedInvoice | None = None
    po: PurchaseOrder | None = None
    validation: ValidationResult | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    resolved_action: Literal["approve", "deny"] | None = None
    payment_executed: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "kind": "escalation",
            "session_id": self.session_id,
            "vendor_name": self.vendor_name,
            "amount": self.amount,
            "reason": self.reason,
            "display_reason": display_reason(self.reason),
            "rule_fired": self.rule_fired,
            "status": self.status,
            "po_id": self.po_id,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_action": self.resolved_action,
            "payment_executed": self.payment_executed,
        }


class EscalationStore:
    """Thread-safe session_id → EscalatedCase map."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cases: dict[str, EscalatedCase] = {}
        self._resolved: dict[str, threading.Event] = {}

    def register(
        self,
        *,
        session_id: str | None = None,
        vendor_name: str,
        amount: float | None,
        decision: GateDecision,
        settlement: Settlement | None = None,
        po_id: str | None = None,
        invoice: ExtractedInvoice | None = None,
        po: PurchaseOrder | None = None,
        validation: ValidationResult | None = None,
        notify: bool = True,
    ) -> EscalatedCase | None:
        """Record a pending escalation and optionally fire a desktop notification.

        No-ops (returns None) when ``decision.action`` is not ``escalate``.
        """
        if decision.action != "escalate":
            return None

        sid = session_id or get_session_id()
        if not sid:
            raise ValueError("session_id is required to register an escalation")

        case = EscalatedCase(
            session_id=sid,
            vendor_name=vendor_name or "Unknown vendor",
            amount=amount,
            reason=decision.reason,
            rule_fired=decision.rule_fired,
            settlement=settlement,
            po_id=po_id,
            invoice=invoice,
            po=po,
            validation=validation,
        )
        with self._lock:
            self._cases[sid] = case
            self._resolved[sid] = threading.Event()

        if notify:
            notify_escalation(
                vendor_name=case.vendor_name,
                amount=case.amount,
                reason=display_reason(case.reason),
            )

        audit_log.publish_live(
            {
                "type": "escalation_pending",
                "kind": "escalation",
                "session_id": sid,
                "vendor_name": case.vendor_name,
                "amount": case.amount,
                "reason": case.reason,
                "display_reason": display_reason(case.reason),
                "rule_fired": case.rule_fired,
                "po_id": case.po_id,
                "status": "pending",
            },
            session_id=sid,
        )
        write_audit_entry(
            step_name="escalation_pending",
            step_type="deterministic",
            input_summary=(
                f"vendor={case.vendor_name} amount="
                f"{case.amount if case.amount is not None else 'n/a'}"
            ),
            output_summary=(
                f"Awaiting human review - {display_reason(case.reason)} "
                f"(rule={case.rule_fired})"
            ),
            details={
                "session_id": sid,
                "vendor_name": case.vendor_name,
                "amount": case.amount,
                "reason": case.reason,
                "rule_fired": case.rule_fired,
                "status": "pending",
            },
            session_id=sid,
        )
        return case

    def get(self, session_id: str) -> EscalatedCase | None:
        with self._lock:
            return self._cases.get(session_id)

    def list_pending(self) -> list[EscalatedCase]:
        with self._lock:
            return [c for c in self._cases.values() if c.status == "pending"]

    def wait_until_resolved(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
    ) -> EscalatedCase | None:
        """Block until approve/deny for ``session_id`` (or timeout).

        Used by the email poller so multi-PDF messages do not continue while
        a prior attachment is still awaiting human review.
        """
        with self._lock:
            case = self._cases.get(session_id)
            if case is not None and case.status != "pending":
                return case
            event = self._resolved.get(session_id)
            if event is None:
                event = threading.Event()
                self._resolved[session_id] = event

        ok = event.wait(timeout=timeout)
        with self._lock:
            case = self._cases.get(session_id)
            if not ok:
                return case
            return case

    def resolve(
        self,
        session_id: str,
        action: Literal["approve", "deny"],
    ) -> EscalatedCase:
        """Apply a human approve/deny decision.

        On approve with a stored settlement, runs ``execute_payment``.
        Writes an AuditEntry and publishes ``escalation_resolved`` for the UI.
        """
        if action not in ("approve", "deny"):
            raise ValueError(f"action must be approve or deny, got {action!r}")

        with self._lock:
            case = self._cases.get(session_id)
            if case is None:
                raise KeyError(f"No escalated case for session_id={session_id!r}")
            if case.status != "pending":
                raise ValueError(
                    f"Case {session_id} already resolved as {case.status}"
                )
            case.status = "approved" if action == "approve" else "denied"
            case.resolved_action = action
            case.resolved_at = datetime.now(timezone.utc)
            settlement = case.settlement
            done = self._resolved.get(session_id)

        payment_executed = False
        if action == "approve" and settlement is not None:
            human_decision = GateDecision(
                action="approve",
                reason="human approval after escalation",
                rule_fired="HUMAN_APPROVE",
            )
            execute_payment(settlement, human_decision)
            payment_executed = True
            with self._lock:
                case.payment_executed = True
            # Rewrite Neo4j so future history includes this approved settlement.
            if case.invoice is not None:
                try:
                    from app.pipeline.persist_outcomes import persist_pipeline_outcomes

                    persist_pipeline_outcomes(
                        invoice=case.invoice,
                        po=case.po,
                        validation=case.validation,
                        settlement=settlement,
                        decision=human_decision,
                    )
                except Exception:  # noqa: BLE001
                    pass

        if done is not None:
            done.set()

        write_audit_entry(
            step_name="human_decision",
            step_type="deterministic",
            input_summary=(
                f"session_id={session_id} escalated reason={case.reason} "
                f"rule={case.rule_fired}"
            ),
            output_summary=(
                f"Human {action}d - vendor={case.vendor_name} "
                f"amount={case.amount if case.amount is not None else 'n/a'} "
                f"payment_executed={payment_executed}"
            ),
            details={
                "session_id": session_id,
                "action": action,
                "vendor_name": case.vendor_name,
                "amount": case.amount,
                "rule_fired": (
                    "HUMAN_APPROVE" if action == "approve" else "HUMAN_DENY"
                ),
                "payment_executed": payment_executed,
                "status": case.status,
            },
            session_id=session_id,
        )

        if payment_executed and settlement is not None:
            write_audit_entry(
                step_name="execute_payment",
                step_type="deterministic",
                input_summary=(
                    f"GateDecision.action=approve (human) "
                    f"amount=${settlement.final_amount:.2f}"
                ),
                output_summary=f"PAYMENT EXECUTED: {settlement.final_amount}",
                details={
                    "session_id": session_id,
                    "payment_executed": True,
                    "amount": settlement.final_amount,
                    "human": True,
                },
                session_id=session_id,
            )

        audit_log.publish_live(
            {
                "type": "escalation_resolved",
                "kind": "escalation",
                "session_id": session_id,
                "action": action,
                "vendor_name": case.vendor_name,
                "amount": case.amount,
                "reason": case.reason,
                "display_reason": display_reason(case.reason),
                "payment_executed": payment_executed,
                "status": case.status,
                "rule_fired": (
                    "HUMAN_APPROVE" if action == "approve" else "HUMAN_DENY"
                ),
            },
            session_id=session_id,
        )
        return case


escalation_store = EscalationStore()
