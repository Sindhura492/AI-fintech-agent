"""Desktop notifications for escalations and ML anomaly flags.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ESCALATION_TITLE = "⚠️ Action needed: Invoice requires approval"
ANOMALY_TITLE_PREFIX = "🔬 Anomaly flagged"


def _notify(title: str, message: str) -> bool:
    """Attempt a desktop toast; fall back to console. Never raises."""
    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=message,
            app_name="Agent Finance",
            timeout=10,
        )
        logger.info("Desktop notification sent: %s | %s", title, message)
        return True
    except Exception as exc:  # noqa: BLE001 — must not break the pipeline
        fallback = f"[NOTIFICATION] {title} — {message}"
        logger.warning(
            "Desktop notification unavailable (%s: %s). %s",
            type(exc).__name__,
            exc,
            fallback,
        )
        print(fallback)  # noqa: T201 — intentional console fallback for demos
        return False


def notify_escalation(
    *,
    vendor_name: str,
    amount: float | None,
    reason: str,
) -> bool:
    """Show a desktop notification for an escalated invoice."""
    amount_txt = f"${amount:,.2f}" if amount is not None else "amount unknown"
    vendor = vendor_name.strip() or "Unknown vendor"
    message = f"{vendor} · {amount_txt} — {reason}"
    return _notify(ESCALATION_TITLE, message)


def notify_anomaly(*, vendor_name: str, explanation: str) -> bool:
    """Show a desktop notification for an IsolationForest-flagged invoice."""
    vendor = vendor_name.strip() or "Unknown vendor"
    # Title carries vendor; body is the (possibly long) explanation.
    title = f"{ANOMALY_TITLE_PREFIX}: {vendor}"
    # Keep toast bodies short; full text is in the UI / audit log.
    message = (explanation or "ML model flagged this invoice.").strip()
    if len(message) > 180:
        message = message[:177] + "…"
    return _notify(title, message)
