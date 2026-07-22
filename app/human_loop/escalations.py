"""In-memory store for escalated invoices awaiting human approve/deny."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from app.observability.audit import audit_log, get_session_id, write_audit_entry
from app.pipeline.enforcement import execute_payment
from app.human_loop.notifications import notify_escalation
from app.core import GateDecision, Settlement

EscalationStatus = Literal["pending", "approved", "denied"]

# Friendlier copy for notifications / UI when gate reasons are terse.
REASON_DISPLAY: dict[str, str] = {
    "no convergence": "no convergence after 3 rounds",
    "above auto-approval threshold": "above $5000 threshold",
    "above $5000 threshold": "above $5000 threshold",
    "no matching PO found": "no matching PO found",
}


def display_reason(reason: str) -> str:
    """Map internal gate reasons to human-facing notification text."""
    key = reason.strip().lower()
    return REASON_DISPLAY.get(key, reason)


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

    def register(
        self,
        *,
        session_id: str | None = None,
        vendor_name: str,
        amount: float | None,
        decision: GateDecision,
        settlement: Settlement | None = None,
        po_id: str | None = None,
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
        )
        with self._lock:
            self._cases[sid] = case

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
                f"Awaiting human review — {display_reason(case.reason)} "
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
            # Work on the object under lock for status transition; payment outside.
            case.status = "approved" if action == "approve" else "denied"
            case.resolved_action = action
            case.resolved_at = datetime.now(timezone.utc)
            settlement = case.settlement

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

        write_audit_entry(
            step_name="human_decision",
            step_type="deterministic",
            input_summary=(
                f"session_id={session_id} escalated reason={case.reason} "
                f"rule={case.rule_fired}"
            ),
            output_summary=(
                f"Human {action}d — vendor={case.vendor_name} "
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
