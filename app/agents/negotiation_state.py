"""TypedDict state for negotiation and cash-optimization graphs."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from app.core.schemas_audit import AuditEntry
from app.core.schemas_documents import (
    ExtractedInvoice,
    GoodsReceipt,
    PurchaseOrder,
    ValidationResult,
)
from app.core.schemas_negotiation import (
    CashOptimizationProposal,
    DisputeProposal,
    Settlement,
)


class NegotiationState(TypedDict):
    """Shared state for the buyer ↔ supplier negotiation graph."""

    invoice: ExtractedInvoice
    po: PurchaseOrder
    receipt: GoodsReceipt
    validation_result: ValidationResult
    round_number: int
    proposals: Annotated[list[DisputeProposal], operator.add]
    settlement: Settlement | None
    max_rounds: int
    min_acceptable: float
    max_acceptable: float
    audit_trail: Annotated[list[AuditEntry], operator.add]
    buyer_accepted: bool
    last_verification_ok: bool
    escalate: bool
    vendor_context: dict
    similar_disputes: list


class CashOptState(TypedDict):
    """State for the early-payment discount negotiation graph."""

    invoice: ExtractedInvoice
    discount_rate: float  # from source data only
    standard_terms_days: int
    days_early: int
    available_cash: float
    supplier_pitch: str
    proposal: CashOptimizationProposal | None
    math_ok: bool
    audit_trail: Annotated[list[AuditEntry], operator.add]
