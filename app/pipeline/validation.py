from __future__ import annotations

import math
import statistics

from app.core import (
    ExtractedInvoice,
    GoodsReceipt,
    PurchaseOrder,
    ValidationResult,
)

# Amount tolerance (rounding / cents).
_AMOUNT_TOLERANCE = 0.01  # 1%

# Flag if amount is this many σ from vendor mean.
_ANOMALY_Z_THRESHOLD = 2.0


def _within_tolerance(actual: float, reference: float, tol: float = _AMOUNT_TOLERANCE) -> bool:
    """Return True if |actual - reference| is within `tol` of `reference`."""
    if reference == 0:
        return abs(actual) <= tol  # absolute cents-scale guard when ref is zero
    return abs(actual - reference) / abs(reference) <= tol


def _pct_delta(actual: float, reference: float) -> float:
    """Signed percent difference of actual vs reference (0.0 if reference is 0)."""
    if reference == 0:
        return 0.0 if actual == 0 else math.copysign(1.0, actual)
    return (actual - reference) / abs(reference)


def three_way_match(
    invoice: ExtractedInvoice,
    po: PurchaseOrder,
    receipt: GoodsReceipt,
) -> ValidationResult:
    """Compare invoice ↔ purchase order ↔ goods receipt amounts deterministically.

    Why deterministic: AP match outcomes drive payment. Soft LLM "looks fine"
    answers are not acceptable here - reviewers and auditors need a fixed
    rule (1% relative tolerance) they can recompute by hand.

    A match requires both:
      - invoice_amount ≈ po.agreed_amount (within 1%)
      - invoice_amount ≈ receipt.received_amount (within 1%)

    Anything beyond that tolerance is flagged as a discrepancy. The reported
    ``discrepancy_amount`` is the larger absolute gap vs PO and vs receipt.

    Args:
        invoice: Structured invoice from the extraction stage.
        po: Authoritative purchase order for this claim.
        receipt: Goods receipt confirming what was received.

    Returns:
        ValidationResult with matched, discrepancy_amount, and reason.
    """
    inv = invoice.invoice_amount
    po_amt = po.agreed_amount
    gr_amt = receipt.received_amount

    gap_po = abs(inv - po_amt)
    gap_gr = abs(inv - gr_amt)
    discrepancy_amount = round(max(gap_po, gap_gr), 2)

    po_ok = _within_tolerance(inv, po_amt)
    gr_ok = _within_tolerance(inv, gr_amt)
    matched = po_ok and gr_ok

    if matched:
        reason = (
            f"Three-way match within {_AMOUNT_TOLERANCE:.0%} tolerance: "
            f"invoice ${inv:,.2f} ≈ PO ${po_amt:,.2f} "
            f"≈ receipt ${gr_amt:,.2f}."
        )
        return ValidationResult(
            matched=True,
            discrepancy_amount=discrepancy_amount,
            reason=reason,
        )

    parts: list[str] = []
    if not po_ok:
        parts.append(
            f"invoice vs PO: ${inv:,.2f} vs ${po_amt:,.2f} "
            f"({_pct_delta(inv, po_amt):+.1%}, gap ${gap_po:,.2f})"
        )
    if not gr_ok:
        parts.append(
            f"invoice vs receipt: ${inv:,.2f} vs ${gr_amt:,.2f} "
            f"({_pct_delta(inv, gr_amt):+.1%}, gap ${gap_gr:,.2f})"
        )

    reason = (
        f"Discrepancy beyond {_AMOUNT_TOLERANCE:.0%} tolerance - "
        + "; ".join(parts)
        + "."
    )
    return ValidationResult(
        matched=False,
        discrepancy_amount=discrepancy_amount,
        reason=reason,
    )


def check_anomaly(
    invoice: ExtractedInvoice,
    vendor_history: list[float],
) -> dict[str, bool | float]:
    """Flag invoices that deviate statistically from a vendor's past amounts.

    Why statistical (not LLM): anomaly detection for finance must be
    reproducible. A z-score against the vendor's recent invoice amounts is a
    transparent baseline - mean, std, and threshold (2σ) can be audited -
    whereas an LLM cannot guarantee the same flag for the same inputs.

    Computes mean and sample standard deviation of ``vendor_history``. Marks
    ``is_anomaly=True`` when |z| > 2, where
    ``z = (invoice_amount - mean) / std``.

    Edge cases:
      - Fewer than 2 history points → no reliable std; returns
        ``is_anomaly=False``, ``z_score=0.0``.
      - Zero variance (all history equal) → anomaly iff invoice differs
        from that constant mean; ``z_score`` is 0.0 when equal, else a
        large finite sentinel (99.0) so callers stay JSON-safe.

    Args:
        invoice: Extracted invoice under review.
        vendor_history: Recent invoice totals for this vendor (naive baseline).

    Returns:
        ``{"is_anomaly": bool, "z_score": float}``
    """
    amount = invoice.invoice_amount

    if len(vendor_history) < 2:
        return {"is_anomaly": False, "z_score": 0.0}

    mean = statistics.mean(vendor_history)
    std = statistics.stdev(vendor_history)  # sample std (n-1)

    if std < 1e-12:
        if abs(amount - mean) < 1e-9:
            return {"is_anomaly": False, "z_score": 0.0}
        # Flat history + new amount → extreme outlier.
        return {"is_anomaly": True, "z_score": 99.0}

    z_score = (amount - mean) / std
    is_anomaly = abs(z_score) > _ANOMALY_Z_THRESHOLD
    return {"is_anomaly": is_anomaly, "z_score": round(z_score, 4)}
