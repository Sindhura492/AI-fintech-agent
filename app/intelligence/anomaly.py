"""ML anomaly detection (IsolationForest) + optional LLM explanation.
"""

from __future__ import annotations

import statistics
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from sklearn.ensemble import IsolationForest

from app.core import ExtractedInvoice
from app.observability.console_logging import get_logger
from app.seed.demo_mode import demo_mode_enabled
from app.seed.mock_data import get_vendor_billing_cadence, get_vendor_history

logger = get_logger(__name__)


class AnomalyResult(BaseModel):
    """Outcome of the IsolationForest check for one invoice amount."""

    is_anomaly: bool = Field(..., description="True when the ML model flags the amount.")
    anomaly_score: float = Field(
        ...,
        description=(
            "Higher = more anomalous. Derived from -decision_function so "
            "outliers score above inliers."
        ),
    )
    method: Literal["isolation_forest"] = Field(
        default="isolation_forest",
        description="Detector identifier for the audit trail / UI.",
    )


class AnomalyDetector:
    """Per-vendor IsolationForest models trained on historical invoice amounts."""

    def __init__(
        self,
        vendor_histories: dict[str, list[float]] | None = None,
        *,
        contamination: float = 0.1,
        random_state: int = 42,
    ) -> None:
        histories = vendor_histories if vendor_histories is not None else get_vendor_history()
        self._models: dict[str, IsolationForest] = {}
        self._thresholds: dict[str, float] = {}
        self._histories: dict[str, list[float]] = {
            name: list(amounts) for name, amounts in histories.items()
        }
        for vendor, amounts in self._histories.items():
            self._fit_vendor(vendor, amounts, contamination, random_state)

    def _fit_vendor(
        self,
        vendor: str,
        amounts: list[float],
        contamination: float,
        random_state: int,
    ) -> None:
        if len(amounts) < 3:
            logger.warning(
                "Skipping IsolationForest for %s — need ≥3 history points, got %d",
                vendor,
                len(amounts),
            )
            return
        X = np.asarray(amounts, dtype=float).reshape(-1, 1)
        # Ensure ≥1 expected outlier in fit.
        cont = min(max(contamination, 1.0 / len(amounts)), 0.5)
        model = IsolationForest(
            n_estimators=100,
            contamination=cont,
            random_state=random_state,
        )
        model.fit(X)
        self._models[vendor] = model
        # Flag bottom ~15% novelty scores (tiny demos).
        train_decisions = model.decision_function(X)
        self._thresholds[vendor] = float(np.percentile(train_decisions, 15))

    def history_for(self, vendor_name: str) -> list[float]:
        return list(self._histories.get(vendor_name, []))

    def check(self, invoice_amount: float, vendor_name: str) -> AnomalyResult:
        """Score ``invoice_amount`` against the vendor's trained IsolationForest."""
        logger.info(
            "[ML - ISOLATION FOREST] Scoring invoice against %s's history...",
            vendor_name,
        )
        model = self._models.get(vendor_name)
        if model is None:
            result = AnomalyResult(
                is_anomaly=False,
                anomaly_score=0.0,
                method="isolation_forest",
            )
            logger.info(
                "[ML - ISOLATION FOREST] Result: is_anomaly=%s score=%s "
                "(no model for vendor)",
                result.is_anomaly,
                result.anomaly_score,
            )
            return result

        X = np.asarray([[float(invoice_amount)]], dtype=float)
        decision = float(model.decision_function(X)[0])
        anomaly_score = round(-decision, 4)
        threshold = self._thresholds.get(vendor_name, 0.0)
        history = self._histories.get(vendor_name, [])
        hist_max = max(history) if history else invoice_amount
        pred_outlier = int(model.predict(X)[0]) == -1
        below_threshold = decision < threshold
        beyond_history = invoice_amount > hist_max * 1.08
        is_anomaly = pred_outlier or below_threshold or beyond_history
        result = AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_score=anomaly_score,
            method="isolation_forest",
        )
        logger.info(
            "[ML - ISOLATION FOREST] Result: is_anomaly=%s score=%s "
            "(pred_outlier=%s below_threshold=%s beyond_history=%s)",
            result.is_anomaly,
            result.anomaly_score,
            pred_outlier,
            below_threshold,
            beyond_history,
        )
        return result

_detector: AnomalyDetector | None = None


def get_anomaly_detector() -> AnomalyDetector:
    """Process-wide detector (trained once on seed vendor histories)."""
    global _detector
    if _detector is None:
        _detector = AnomalyDetector()
    return _detector


def explain_anomaly(
    invoice: ExtractedInvoice,
    anomaly_result: AnomalyResult,
    vendor_history: list[float],
) -> str:
    """Generate a short plain-language explanation for a human reviewer.

    IMPORTANT: The LLM (or demo stub) only *explains* an anomaly the ML model
    already flagged. It does NOT decide whether the invoice is a real problem —
    ``anomaly_result.is_anomaly`` from IsolationForest is authoritative.
    """
    if not anomaly_result.is_anomaly:
        return "Not flagged by IsolationForest — no explanation needed."

    if demo_mode_enabled():
        return _demo_explain(invoice, anomaly_result, vendor_history)

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage, SystemMessage

        cadence = get_vendor_billing_cadence(invoice.vendor_name)
        mean = statistics.mean(vendor_history) if vendor_history else 0.0
        std = statistics.stdev(vendor_history) if len(vendor_history) > 1 else 0.0
        ratio = (invoice.invoice_amount / mean) if mean else 0.0

        system = (
            "You write one or two plain-language sentences for an AP reviewer. "
            "Explain WHY an ML model flagged this invoice as anomalous, using only "
            "the stats provided. Do not decide if it is fraud or if payment should "
            "stop — the IsolationForest already made the anomaly call. Be concrete "
            "with multiples, dollar amounts, and billing cadence."
        )
        human = (
            f"Vendor: {invoice.vendor_name}\n"
            f"Invoice amount: ${invoice.invoice_amount:,.2f}\n"
            f"History mean: ${mean:,.2f} (n={len(vendor_history)}, std=${std:,.2f})\n"
            f"Amount vs mean: {ratio:.2f}x\n"
            f"IsolationForest anomaly_score: {anomaly_result.anomaly_score} "
            f"(method={anomaly_result.method})\n"
            f"Typical billing gap: {cadence.get('typical_gap_days')} days; "
            f"days since last invoice: {cadence.get('days_since_last')}\n"
            "Write the reviewer explanation now."
        )
        llm = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            temperature=0,
            max_tokens=200,
        )
        raw = llm.invoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        text = getattr(raw, "content", None) or str(raw)
        if isinstance(text, list):
            text = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in text
            )
        return str(text).strip() or _demo_explain(invoice, anomaly_result, vendor_history)
    except Exception as exc:  # noqa: BLE001 — explanation must not break the pipeline
        logger.warning("explain_anomaly LLM failed (%s); using heuristic", exc)
        return _demo_explain(invoice, anomaly_result, vendor_history)


def _demo_explain(
    invoice: ExtractedInvoice,
    anomaly_result: AnomalyResult,
    vendor_history: list[float],
) -> str:
    """Deterministic explanation used in DEMO_MODE or when Claude is unavailable."""
    mean = statistics.mean(vendor_history) if vendor_history else 0.0
    ratio = (invoice.invoice_amount / mean) if mean else 0.0
    cadence = get_vendor_billing_cadence(invoice.vendor_name)
    typical = cadence.get("typical_gap_days", 30)
    since = cadence.get("days_since_last", 30)
    return (
        f"This invoice is {ratio:.1f}x the vendor's typical amount "
        f"(${mean:,.0f} average over {len(vendor_history)} invoices), "
        f"and the vendor hasn't invoiced in {since} days versus their usual "
        f"{typical}-day cycle. IsolationForest score={anomaly_result.anomaly_score:.3f}."
    )
