from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from app.core import (
    CashOptimizationProposal,
    DisputeRequest,
    DisputeResponse,
    ExtractedInvoice,
    GateDecision,
    Settlement,
    TraceEvent,
    ValidationResult,
)
from app.observability.audit import audit_log, reset_session_id, set_session_id
from app.pipeline.email_pipeline import run_pipeline_from_email
from app.pipeline.extraction import extract_invoice
from app.pipeline.match_validate_enforce import _run_match_validate_enforce
from app.pipeline.pipeline_helpers import _audit, _result_dict, _timer
from app.pipeline.sandbox import parse_document
from app.seed.mock_data import get_po_by_id, get_receipts_for_po

__all__ = [
    "run_pipeline_from_email",
    "run_pipeline",
    "resolve_dispute",
    "resolve_dispute_stream",
]


def run_pipeline(
    file_path: str,
    po_id: str | None = None,
    *,
    session_id: str | None = None,
    sender_email: str | None = None,
) -> dict[str, Any]:
    """Run the full dispute-resolution flow (manual / known-po_id entry point).

    When ``po_id`` is omitted, delegates to ``run_pipeline_from_email`` so the
    match → escalate-or-continue path stays consistent.
    """
    if not po_id:
        return run_pipeline_from_email(
            file_path,
            sender_email or "",
            session_id=session_id,
        )

    session_id = session_id or str(uuid.uuid4())
    token = set_session_id(session_id)

    invoice: ExtractedInvoice | None = None
    validation: ValidationResult | None = None
    anomaly: dict[str, bool | float] | None = None
    settlement: Settlement | None = None
    decision: GateDecision | None = None
    payment_executed = False
    cash_opt: CashOptimizationProposal | None = None
    status = "ok"

    try:
        _audit(
            "pipeline_start",
            "deterministic",
            f"file_path={file_path} po_id={po_id!r}",
            f"session_id={session_id}",
            po_id=po_id,
        )

        with _timer() as t:
            raw_text = parse_document(file_path)
        _audit(
            "llamaparse_document",
            "llm",
            f"file_path={file_path}",
            f"parsed {len(raw_text)} chars of markdown/text via sandboxed LlamaParse",
            duration_ms=t["ms"],
            chars=len(raw_text),
        )

        with _timer() as t:
            invoice = extract_invoice(raw_text)
        _audit(
            "extract_invoice",
            "llm",
            f"llamaparse_markdown[{len(raw_text)} chars]",
            (
                f"vendor={invoice.vendor_name} amount=${invoice.invoice_amount:.2f} "
                f"{invoice.currency} confidence={invoice.confidence:.2f}"
            ),
            duration_ms=t["ms"],
            invoice_amount=invoice.invoice_amount,
            confidence=invoice.confidence,
            vendor_name=invoice.vendor_name,
        )

        po = get_po_by_id(po_id)
        if po is None:
            raise ValueError(f"Unknown po_id: {po_id}")
        receipts = get_receipts_for_po(po_id)
        if not receipts:
            raise ValueError(f"No goods receipt for po_id: {po_id}")
        receipt = receipts[0]
        _audit(
            "lookup_po_receipt",
            "deterministic",
            f"po_id={po_id}",
            (
                f"PO ${po.agreed_amount:.2f} / GR ${receipt.received_amount:.2f} "
                f"vendor={po.vendor_name}"
            ),
            po_amount=po.agreed_amount,
            received_amount=receipt.received_amount,
        )

        validation, anomaly, settlement, decision, payment_executed, cash_opt = (
            _run_match_validate_enforce(
                invoice=invoice,
                po=po,
                receipt=receipt,
            )
        )

    except Exception as exc:
        _audit(
            "pipeline_error",
            "deterministic",
            f"file_path={file_path} po_id={po_id!r}",
            f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        reset_session_id(token)

    return _result_dict(
        session_id=session_id,
        file_path=file_path,
        status=status,
        po_id=po_id,
        invoice=invoice,
        validation=validation,
        anomaly=anomaly,
        settlement=settlement,
        decision=decision,
        payment_executed=payment_executed,
        cash_optimization=cash_opt,
    )


async def resolve_dispute(request: DisputeRequest) -> DisputeResponse:
    """FastAPI adapter: map DisputeRequest → run_pipeline → DisputeResponse."""
    if not request.document_path:
        raise ValueError("document_path is required")
    if not request.po_id:
        raise ValueError("po_id is required")

    result = await asyncio.to_thread(
        run_pipeline, request.document_path, request.po_id
    )
    return DisputeResponse(
        dispute_id=result["session_id"],
        invoice=result["invoice"],
        validation=result["validation"],
        settlement=result["settlement"],
        gate=result["decision"],
        audit_trail=audit_log.get_trace(result["session_id"]),
    )


async def resolve_dispute_stream(
    request: DisputeRequest,
) -> AsyncGenerator[TraceEvent, None]:
    """Subscribe to live audit events, run the pipeline, yield TraceEvents."""
    if not request.document_path or not request.po_id:
        yield TraceEvent(
            timestamp=datetime.now(timezone.utc),
            step_name="orchestrator",
            message="document_path and po_id are required",
        )
        return

    session_id = str(uuid.uuid4())
    queue = audit_log.subscribe(session_id=session_id)

    loop = asyncio.get_running_loop()
    task = loop.run_in_executor(
        ThreadPoolExecutor(max_workers=1),
        lambda: run_pipeline(
            request.document_path,  # type: ignore[arg-type]
            request.po_id,  # type: ignore[arg-type]
            session_id=session_id,
        ),
    )

    try:
        while not task.done():
            try:
                entry = await asyncio.wait_for(queue.get(), timeout=0.25)
            except TimeoutError:
                continue
            yield TraceEvent(
                timestamp=entry.timestamp,
                step_name=entry.step_name,
                message=f"[{entry.step_type}] {entry.output_summary}",
            )
        while not queue.empty():
            entry = queue.get_nowait()
            yield TraceEvent(
                timestamp=entry.timestamp,
                step_name=entry.step_name,
                message=f"[{entry.step_type}] {entry.output_summary}",
            )
        await task
    finally:
        audit_log.unsubscribe(queue)
