from __future__ import annotations

import uuid
from typing import Any

from app.core import (
    CashOptimizationProposal,
    ExtractedInvoice,
    GateDecision,
    Settlement,
    ValidationResult,
)
from app.observability.audit import audit_log, reset_session_id, set_session_id
from app.pipeline.extraction import extract_invoice
from app.pipeline.match_validate_enforce import _run_match_validate_enforce
from app.pipeline.matching import extract_email_address, match_to_po
from app.pipeline.persist_outcomes import persist_pipeline_outcomes
from app.pipeline.pipeline_helpers import _audit, _result_dict, _timer
from app.pipeline.sandbox import parse_document
from app.seed.mock_data import get_po_by_id, get_receipts_for_po


def run_pipeline_from_email(
    file_path: str,
    sender_email: str,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Email-ingest entry point: sandbox → extract → match_to_po → … or escalate.

    If ``match_to_po`` returns None, short-circuits to a GateDecision with
    ``action="escalate"`` / ``reason="no matching PO found"`` — never runs
    three-way match without a PO.
    """
    session_id = session_id or str(uuid.uuid4())
    token = set_session_id(session_id)
    bare = extract_email_address(sender_email)

    invoice: ExtractedInvoice | None = None
    validation: ValidationResult | None = None
    anomaly: dict[str, bool | float] | None = None
    settlement: Settlement | None = None
    decision: GateDecision | None = None
    payment_executed = False
    cash_opt: CashOptimizationProposal | None = None
    resolved_po_id: str | None = None
    status = "ok"

    try:
        _audit(
            "pipeline_start",
            "deterministic",
            f"source=email file_path={file_path} sender={bare or sender_email!r}",
            f"session_id={session_id}",
            sender_email=bare or None,
            source="email",
        )

        # 1. Sandboxed LlamaParse → markdown (llm-backed parse service)
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

        # 2. Extraction (llm)
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

        # 3. Match PO (deterministic) — match_to_po also writes its own AuditEntry
        matched = match_to_po(invoice, sender_email)
        _audit(
            "match_to_po_step",
            "deterministic",
            f"sender={bare or '(none)'} vendor={invoice.vendor_name}",
            (
                f"matched {matched.po_id}"
                if matched
                else "no matching PO — escalate (no three-way match)"
            ),
            matched=matched is not None,
            po_id=matched.po_id if matched else None,
        )

        if matched is None:
            status = "needs_manual_po_matching"
            decision = GateDecision(
                action="escalate",
                reason="no matching PO found",
                rule_fired="NO_MATCHING_PO",
            )
            _audit(
                "gate_decision",
                "deterministic",
                "match_to_po returned None",
                f"action=escalate rule_fired={decision.rule_fired} — {decision.reason}",
                action=decision.action,
                rule_fired=decision.rule_fired,
                reason=decision.reason,
            )
            from app.human_loop.escalations import escalation_store

            escalation_store.register(
                session_id=session_id,
                vendor_name=invoice.vendor_name,
                amount=invoice.invoice_amount,
                decision=decision,
                settlement=None,
                po_id=None,
            )
            persist_pipeline_outcomes(
                invoice=invoice,
                po=None,
                validation=None,
                settlement=None,
                decision=decision,
            )
            _audit(
                "pipeline_complete",
                "deterministic",
                f"session_id={session_id}",
                "short-circuit escalate — no PO; three-way match skipped",
                action=decision.action,
                payment_executed=False,
            )
            return _result_dict(
                session_id=session_id,
                file_path=file_path,
                status=status,
                po_id=None,
                invoice=invoice,
                validation=None,
                anomaly=None,
                settlement=None,
                decision=decision,
                payment_executed=False,
            )

        # 4. Matched → normal validate / negotiate / enforce flow
        resolved_po_id = matched.po_id
        receipts = get_receipts_for_po(resolved_po_id)
        if not receipts:
            raise ValueError(f"No goods receipt for po_id: {resolved_po_id}")
        receipt = receipts[0]
        _audit(
            "lookup_po_receipt",
            "deterministic",
            f"po_id={resolved_po_id}",
            (
                f"PO ${matched.agreed_amount:.2f} / GR ${receipt.received_amount:.2f} "
                f"vendor={matched.vendor_name}"
            ),
            po_amount=matched.agreed_amount,
            received_amount=receipt.received_amount,
        )

        validation, anomaly, settlement, decision, payment_executed, cash_opt = (
            _run_match_validate_enforce(
                invoice=invoice,
                po=matched,
                receipt=receipt,
            )
        )

    except Exception as exc:
        _audit(
            "pipeline_error",
            "deterministic",
            f"file_path={file_path} sender={bare or sender_email!r}",
            f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        reset_session_id(token)

    return _result_dict(
        session_id=session_id,
        file_path=file_path,
        status=status,
        po_id=resolved_po_id,
        invoice=invoice,
        validation=validation,
        anomaly=anomaly,
        settlement=settlement,
        decision=decision,
        payment_executed=payment_executed,
        cash_optimization=cash_opt,
    )

