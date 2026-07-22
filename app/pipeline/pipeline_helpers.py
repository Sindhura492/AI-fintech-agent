from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core import (
    CashOptimizationProposal,
    ExtractedInvoice,
    GateDecision,
    Settlement,
    ValidationResult,
)
from app.observability.audit import audit_log, get_session_id


@contextmanager
def _timer() -> Iterator[dict[str, float]]:
    """Capture wall-clock duration_ms for a pipeline step."""
    box: dict[str, float] = {"ms": 0.0}
    t0 = time.perf_counter()
    try:
        yield box
    finally:
        box["ms"] = round((time.perf_counter() - t0) * 1000, 2)


def _audit(
    step_name: str,
    step_type: str,
    input_summary: str,
    output_summary: str,
    *,
    duration_ms: float | None = None,
    **details: str | int | float | bool | None,
) -> None:
    """Write one clearly typed audit entry for the active session."""
    audit_log.append(
        step_name=step_name,
        step_type=step_type,  # type: ignore[arg-type]
        input_summary=input_summary,
        output_summary=output_summary,
        session_id=get_session_id(),
        details=details or None,
        duration_ms=duration_ms,
    )


def _result_dict(
    *,
    session_id: str,
    file_path: str,
    status: str,
    po_id: str | None,
    invoice: ExtractedInvoice | None,
    validation: ValidationResult | None,
    anomaly: dict[str, bool | float] | None,
    settlement: Settlement | None,
    decision: GateDecision | None,
    payment_executed: bool,
    cash_optimization: CashOptimizationProposal | None = None,
) -> dict[str, Any]:
    trace = audit_log.get_trace(session_id)
    return {
        "session_id": session_id,
        "po_id": po_id,
        "file_path": file_path,
        "status": status,
        "invoice": invoice.model_dump(mode="json") if invoice else None,
        "validation": validation.model_dump(mode="json") if validation else None,
        "anomaly": anomaly,
        "settlement": settlement.model_dump(mode="json") if settlement else None,
        "cash_optimization": (
            cash_optimization.model_dump(mode="json") if cash_optimization else None
        ),
        "decision": decision.model_dump(mode="json") if decision else None,
        "payment_executed": payment_executed,
        "trace": [e.model_dump(mode="json") for e in trace],
    }
