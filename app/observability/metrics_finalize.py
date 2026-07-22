from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.core import AuditEntry


def finalize_run(
    store: Any,
    conn: sqlite3.Connection,
    session_id: str,
    entry: AuditEntry,
    *,
    success: bool,
) -> None:
    scratch = store._scratch.pop(session_id, {})
    d = entry.details or {}
    action = scratch.get("action") or d.get("action") or (
        "error" if not success else "unknown"
    )
    if isinstance(action, str):
        action = action.lower()
    else:
        action = "unknown"

    outcome_map = {
        "approve": "approved",
        "approved": "approved",
        "deny": "denied",
        "denied": "denied",
        "escalate": "escalated",
        "escalated": "escalated",
        "error": "failed",
    }
    outcome = outcome_map.get(action, "failed" if not success else "unknown")

    existing = conn.execute(
        "SELECT 1 FROM runs WHERE session_id = ?", (session_id,)
    ).fetchone()
    if existing:
        return

    conn.execute(
        "UPDATE metrics SET total_runs = total_runs + 1 WHERE id = 1"
    )
    if outcome == "approved":
        conn.execute("UPDATE metrics SET approved = approved + 1 WHERE id = 1")
    elif outcome == "denied":
        conn.execute("UPDATE metrics SET denied = denied + 1 WHERE id = 1")
    elif outcome == "escalated":
        conn.execute("UPDATE metrics SET escalated = escalated + 1 WHERE id = 1")
    else:
        conn.execute("UPDATE metrics SET failed = failed + 1 WHERE id = 1")

    ts = entry.timestamp
    if isinstance(ts, datetime):
        ts_str = ts.isoformat()
    else:
        ts_str = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO runs (
            session_id, timestamp, outcome, vendor, amount,
            success, anomaly_flagged, payment_executed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            ts_str,
            outcome,
            scratch.get("vendor"),
            scratch.get("amount"),
            1 if success and outcome != "failed" else 0,
            1 if scratch.get("anomaly_flagged") else 0,
            1 if scratch.get("payment_executed") or d.get("payment_executed") else 0,
        ),
    )
