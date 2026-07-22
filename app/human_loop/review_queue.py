"""In-memory review queue for ML-flagged invoice anomalies."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from app.core import ExtractedInvoice
from app.human_loop.notifications import notify_anomaly
from app.intelligence.anomaly import AnomalyResult
from app.observability.audit import audit_log, get_session_id, write_audit_entry

AnomalyReviewStatus = Literal["pending_review", "approved", "denied"]


@dataclass
class AnomalyReviewItem:
    session_id: str
    vendor_name: str
    amount: float
    anomaly_score: float
    method: str
    explanation: str
    status: AnomalyReviewStatus = "pending_review"
    po_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    resolved_action: Literal["approve", "deny"] | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "kind": "anomaly",
            "session_id": self.session_id,
            "vendor_name": self.vendor_name,
            "amount": self.amount,
            "anomaly_score": self.anomaly_score,
            "method": self.method,
            "explanation": self.explanation,
            "status": self.status,
            "po_id": self.po_id,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_action": self.resolved_action,
        }


class AnomalyReviewQueue:
    """Thread-safe session_id → AnomalyReviewItem map."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, AnomalyReviewItem] = {}
        self._resolved: dict[str, threading.Event] = {}

    def enqueue(
        self,
        *,
        invoice: ExtractedInvoice,
        anomaly_result: AnomalyResult,
        explanation: str,
        session_id: str | None = None,
        po_id: str | None = None,
        notify: bool = True,
    ) -> AnomalyReviewItem | None:
        """Queue a flagged anomaly for human review. No-ops if not an anomaly."""
        if not anomaly_result.is_anomaly:
            return None

        sid = session_id or get_session_id()
        if not sid:
            raise ValueError("session_id is required to enqueue an anomaly review")

        item = AnomalyReviewItem(
            session_id=sid,
            vendor_name=invoice.vendor_name or "Unknown vendor",
            amount=invoice.invoice_amount,
            anomaly_score=anomaly_result.anomaly_score,
            method=anomaly_result.method,
            explanation=explanation,
            po_id=po_id,
        )
        with self._lock:
            self._items[sid] = item
            self._resolved[sid] = threading.Event()

        if notify:
            notify_anomaly(
                vendor_name=item.vendor_name,
                explanation=explanation,
            )

        audit_log.publish_live(
            {
                "type": "anomaly_pending",
                "kind": "anomaly",
                "session_id": sid,
                "vendor_name": item.vendor_name,
                "amount": item.amount,
                "anomaly_score": item.anomaly_score,
                "method": item.method,
                "explanation": item.explanation,
                "status": "pending_review",
                "po_id": item.po_id,
            },
            session_id=sid,
        )
        write_audit_entry(
            step_name="anomaly_review_queued",
            step_type="deterministic",
            input_summary=(
                f"vendor={item.vendor_name} amount=${item.amount:.2f} "
                f"score={item.anomaly_score}"
            ),
            output_summary=f"pending_review - {explanation[:200]}",
            details={
                "session_id": sid,
                "vendor_name": item.vendor_name,
                "amount": item.amount,
                "anomaly_score": item.anomaly_score,
                "method": item.method,
                "status": "pending_review",
                "explanation": explanation[:500],
            },
            session_id=sid,
        )
        return item

    def get(self, session_id: str) -> AnomalyReviewItem | None:
        with self._lock:
            return self._items.get(session_id)

    def list_pending(self) -> list[AnomalyReviewItem]:
        with self._lock:
            return [i for i in self._items.values() if i.status == "pending_review"]

    def wait_until_resolved(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
    ) -> AnomalyReviewItem | None:
        """Block until human approve/deny (or timeout)."""
        with self._lock:
            item = self._items.get(session_id)
            if item is not None and item.status != "pending_review":
                return item
            event = self._resolved.get(session_id)
            if event is None:
                event = threading.Event()
                self._resolved[session_id] = event

        event.wait(timeout=timeout)
        with self._lock:
            return self._items.get(session_id)

    def resolve(
        self,
        session_id: str,
        action: Literal["approve", "deny"],
    ) -> AnomalyReviewItem:
        """Human clears (approve → pipeline continues) or stops (deny)."""
        if action not in ("approve", "deny"):
            raise ValueError(f"action must be approve or deny, got {action!r}")

        with self._lock:
            item = self._items.get(session_id)
            if item is None:
                raise KeyError(f"No anomaly review for session_id={session_id!r}")
            if item.status != "pending_review":
                raise ValueError(
                    f"Anomaly review {session_id} already resolved as {item.status}"
                )
            item.status = "approved" if action == "approve" else "denied"
            item.resolved_action = action
            item.resolved_at = datetime.now(timezone.utc)
            done = self._resolved.get(session_id)

        if done is not None:
            done.set()

        write_audit_entry(
            step_name="anomaly_human_decision",
            step_type="deterministic",
            input_summary=(
                f"session_id={session_id} score={item.anomaly_score} "
                f"method={item.method}"
            ),
            output_summary=(
                f"Human {action}d anomaly - vendor={item.vendor_name} "
                f"amount=${item.amount:.2f} "
                f"({'pipeline resumes' if action == 'approve' else 'pipeline stopped'})"
            ),
            details={
                "session_id": session_id,
                "action": action,
                "vendor_name": item.vendor_name,
                "amount": item.amount,
                "anomaly_score": item.anomaly_score,
                "status": item.status,
                "kind": "anomaly",
            },
            session_id=session_id,
        )
        audit_log.publish_live(
            {
                "type": "anomaly_resolved",
                "kind": "anomaly",
                "session_id": session_id,
                "action": action,
                "vendor_name": item.vendor_name,
                "amount": item.amount,
                "anomaly_score": item.anomaly_score,
                "explanation": item.explanation,
                "status": item.status,
            },
            session_id=session_id,
        )
        return item


anomaly_review_queue = AnomalyReviewQueue()
