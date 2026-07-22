from __future__ import annotations

from app.core import ExtractedInvoice, PurchaseOrder
from app.pipeline.pipeline_helpers import _audit, _timer
from app.pipeline.validation import check_anomaly


def run_anomaly_checks(
    invoice: ExtractedInvoice,
    po: PurchaseOrder,
    history: list[float],
) -> dict[str, bool | float]:
    """Run z-score then IsolationForest; enqueue human review when ML flags."""
    with _timer() as t:
        anomaly = check_anomaly(invoice, history)
    _audit(
        "check_anomaly_zscore",
        "deterministic",
        f"vendor={invoice.vendor_name} history_n={len(history)}",
        f"is_anomaly={anomaly['is_anomaly']} z_score={anomaly['z_score']}",
        duration_ms=t["ms"],
        is_anomaly=bool(anomaly["is_anomaly"]),
        z_score=float(anomaly["z_score"]),
    )

    # Standalone ML step — IsolationForest (authoritative anomaly flag for review)
    from app.human_loop.review_queue import anomaly_review_queue
    from app.intelligence.anomaly import explain_anomaly, get_anomaly_detector

    detector = get_anomaly_detector()
    with _timer() as t:
        ml_result = detector.check(invoice.invoice_amount, invoice.vendor_name)
    _audit(
        "isolation_forest_anomaly",
        "ml",
        (
            f"vendor={invoice.vendor_name} amount=${invoice.invoice_amount:.2f} "
            f"history_n={len(history)} method=isolation_forest"
        ),
        (
            f"is_anomaly={ml_result.is_anomaly} "
            f"anomaly_score={ml_result.anomaly_score} "
            f"method={ml_result.method}"
        ),
        duration_ms=t["ms"],
        is_anomaly=ml_result.is_anomaly,
        anomaly_score=ml_result.anomaly_score,
        method=ml_result.method,
    )

    if ml_result.is_anomaly:
        with _timer() as t:
            explanation = explain_anomaly(invoice, ml_result, history)
        _audit(
            "explain_anomaly",
            "llm",
            (
                f"vendor={invoice.vendor_name} score={ml_result.anomaly_score} "
                f"(ML already decided is_anomaly=True)"
            ),
            explanation[:240],
            duration_ms=t["ms"],
            is_anomaly=True,
            anomaly_score=ml_result.anomaly_score,
        )
        anomaly_review_queue.enqueue(
            invoice=invoice,
            anomaly_result=ml_result,
            explanation=explanation,
            po_id=po.po_id,
        )

    return anomaly
