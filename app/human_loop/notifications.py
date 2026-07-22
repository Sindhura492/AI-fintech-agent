"""Desktop notifications + sounds for approvals, escalations, anomalies."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import threading

logger = logging.getLogger(__name__)

ESCALATION_TITLE = "Action needed: Invoice requires approval"
APPROVE_TITLE = "Payment approved"
ANOMALY_TITLE_PREFIX = "Anomaly flagged"

# macOS system sounds (afplay / osascript sound name)
_SOUND_APPROVE = "Glass"
_SOUND_ESCALATE = "Basso"
_SOUND_ANOMALY = "Purr"


def _play_sound(sound_name: str) -> None:
    """Best-effort system sound (macOS). Never raises."""

    def _run() -> None:
        try:
            if platform.system() != "Darwin":
                print("\a", end="", flush=True)
                return
            path = f"/System/Library/Sounds/{sound_name}.aiff"
            afplay = shutil.which("afplay")
            if afplay:
                subprocess.run(
                    [afplay, path],
                    check=False,
                    timeout=5,
                    capture_output=True,
                )
            else:
                print("\a", end="", flush=True)
        except Exception:  # noqa: BLE001
            try:
                print("\a", end="", flush=True)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_run, daemon=True).start()


def _osascript_notify(title: str, message: str, sound: str | None) -> bool:
    """Native macOS banner; optional attached sound name."""
    if platform.system() != "Darwin":
        return False
    osa = shutil.which("osascript")
    if not osa:
        return False

    def _esc(s: str) -> str:
        return (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", " ")
            .replace("\r", " ")
        )

    # Keep short - long bodies are often dropped by Notification Center.
    title_s = _esc(title)[:80]
    msg_s = _esc(message)[:160]
    sound_clause = f' sound name "{_esc(sound)}"' if sound else ""
    script = (
        f'display notification "{msg_s}" with title "{title_s}"{sound_clause}'
    )
    try:
        result = subprocess.run(
            [osa, "-e", script],
            check=False,
            timeout=5,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _notify(title: str, message: str, *, sound: str | None = None) -> bool:
    """Log + desktop toast + sound. Sound always attempted."""
    line = f"[NOTIFICATION] {title} - {message}"
    logger.info("%s", line)

    # Always play sound first so Focus Mode can't silence the alert entirely.
    if sound:
        _play_sound(sound)

    shown = _osascript_notify(title, message, sound=None)
    if not shown:
        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message[:200],
                app_name="Agent Finance",
                timeout=12,
            )
            shown = True
        except Exception:  # noqa: BLE001
            pass
    return shown


def notify_escalation(
    *,
    vendor_name: str,
    amount: float | None,
    reason: str,
) -> bool:
    """Desktop alert + sound for an escalated invoice."""
    amount_txt = f"${amount:,.2f}" if amount is not None else "amount unknown"
    vendor = vendor_name.strip() or "Unknown vendor"
    message = f"{vendor} | {amount_txt} - {reason}"
    return _notify(ESCALATION_TITLE, message, sound=_SOUND_ESCALATE)


def notify_auto_approved(
    *,
    vendor_name: str,
    amount: float | None,
) -> bool:
    """Success toast + sound when the gate auto-approves payment."""
    amount_txt = f"${amount:,.2f}" if amount is not None else "amount unknown"
    vendor = vendor_name.strip() or "Unknown vendor"
    message = f"{vendor} | {amount_txt} - payment executed"
    return _notify(APPROVE_TITLE, message, sound=_SOUND_APPROVE)


def notify_anomaly(*, vendor_name: str, explanation: str) -> bool:
    """Desktop notification for an IsolationForest-flagged invoice."""
    vendor = vendor_name.strip() or "Unknown vendor"
    title = f"{ANOMALY_TITLE_PREFIX}: {vendor}"
    message = (explanation or "ML model flagged this invoice.").strip()
    if len(message) > 180:
        message = message[:177] + "..."
    return _notify(title, message, sound=_SOUND_ANOMALY)
