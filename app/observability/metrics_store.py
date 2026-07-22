from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.core import AuditEntry
from app.observability.metrics_schema import init_metrics_schema

logger = logging.getLogger(__name__)


def _default_db_path() -> Path:
    return Path(get_settings().metrics_db_path)


# Project ``data/agent_finance.db`` via settings (not under ``app/``).
DEFAULT_DB_PATH = _default_db_path()


class MetricsStore:
    """Thread-safe SQLite store — durable inserts + aggregate counters."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Per-session scratch: vendor / amount / outcome before pipeline_complete
        self._scratch: dict[str, dict[str, Any]] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                init_metrics_schema(conn)

    def absolute_path(self) -> str:
        return str(self.path.resolve())

    def count_log_rows(self) -> int:
        """``COUNT(*)`` from ``metrics_log`` — used on startup to prove durability."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM metrics_log").fetchone()
                return int(row["c"] if row else 0)

    def log_startup_check(self) -> int:
        """Log DB path + row count. Returns count for callers."""
        count = self.count_log_rows()
        path = self.absolute_path()
        msg = (
            f"Metrics DB ready at {path} — metrics_log COUNT(*)={count} "
            f"(history survives restart)"
        )
        logger.info(msg)
        print(msg)  # noqa: T201 — intentional: show path during demos
        return count

    def on_audit_entry(self, entry: AuditEntry) -> None:
        """Commit one metrics_log INSERT and update aggregates."""
        sid = None
        if entry.details:
            raw = entry.details.get("session_id")
            if isinstance(raw, str):
                sid = raw

        with self._lock:
            with self._connect() as conn:
                try:
                    if sid:
                        self._update_scratch(sid, entry)
                    self._insert_log_row(conn, entry, sid)
                    self._bump_step(conn, entry)
                    if entry.step_name == "pipeline_complete" and sid:
                        self._finalize_run(conn, sid, entry, success=True)
                    elif entry.step_name == "pipeline_error" and sid:
                        self._finalize_run(conn, sid, entry, success=False)
                    conn.execute(
                        "UPDATE metrics SET updated_at = ? WHERE id = 1",
                        (datetime.now(timezone.utc).isoformat(),),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

    def _insert_log_row(
        self,
        conn: sqlite3.Connection,
        entry: AuditEntry,
        session_id: str | None,
    ) -> None:
        scratch = self._scratch.get(session_id or "", {})
        d = entry.details or {}

        vendor = scratch.get("vendor")
        if isinstance(d.get("vendor_name"), str):
            vendor = d["vendor_name"]

        amount: float | None = scratch.get("amount")
        for key in ("invoice_amount", "final_amount", "amount"):
            if isinstance(d.get(key), (int, float)):
                amount = float(d[key])
                break

        outcome = None
        if entry.step_name in ("pipeline_complete", "pipeline_error", "enforce", "gate_decision"):
            action = scratch.get("action") or d.get("action")
            if entry.step_name == "pipeline_error":
                outcome = "failed"
            elif isinstance(action, str):
                outcome = {
                    "approve": "approved",
                    "approved": "approved",
                    "deny": "denied",
                    "denied": "denied",
                    "escalate": "escalated",
                    "escalated": "escalated",
                }.get(action.lower(), action.lower())

        ts = entry.timestamp
        if isinstance(ts, datetime):
            ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """
            INSERT INTO metrics_log (
                timestamp, session_id, step_name, step_type,
                duration_ms, outcome, vendor_name, amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts_str,
                session_id,
                entry.step_name,
                entry.step_type,
                float(entry.duration_ms) if entry.duration_ms is not None else None,
                outcome,
                vendor,
                amount,
            ),
        )

    def history(
        self,
        *,
        since: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Query ``metrics_log`` from disk (optional ISO ``since`` filter)."""
        with self._lock:
            with self._connect() as conn:
                if since:
                    # Accept ISO or SQLite datetime; compare as text (ISO-ish order).
                    since_norm = since.replace("T", " ").replace("Z", "")[:19]
                    rows = conn.execute(
                        """
                        SELECT id, timestamp, session_id, step_name, step_type,
                               duration_ms, outcome, vendor_name, amount
                        FROM metrics_log
                        WHERE timestamp >= ?
                        ORDER BY id ASC
                        LIMIT ?
                        """,
                        (since_norm, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT id, timestamp, session_id, step_name, step_type,
                               duration_ms, outcome, vendor_name, amount
                        FROM metrics_log
                        ORDER BY id ASC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
        return [dict(r) for r in rows]

    def _bump_step(self, conn: sqlite3.Connection, entry: AuditEntry) -> None:
        st = entry.step_type
        col = {
            "llm": "llm_steps",
            "deterministic": "deterministic_steps",
            "ml": "ml_steps",
        }.get(st)
        if col:
            conn.execute(f"UPDATE metrics SET {col} = {col} + 1 WHERE id = 1")

        if st == "llm":
            conn.execute(
                "UPDATE metrics SET total_llm_calls = total_llm_calls + 1 WHERE id = 1"
            )

        if entry.duration_ms is not None and entry.duration_ms >= 0:
            sum_col = {
                "llm": "llm_latency_sum_ms",
                "deterministic": "deterministic_latency_sum_ms",
                "ml": "ml_latency_sum_ms",
            }.get(st)
            cnt_col = {
                "llm": "llm_latency_count",
                "deterministic": "deterministic_latency_count",
                "ml": "ml_latency_count",
            }.get(st)
            if sum_col and cnt_col:
                conn.execute(
                    f"UPDATE metrics SET {sum_col} = {sum_col} + ?, "
                    f"{cnt_col} = {cnt_col} + 1 WHERE id = 1",
                    (float(entry.duration_ms),),
                )

        if (
            entry.step_name == "isolation_forest_anomaly"
            and entry.details.get("is_anomaly") is True
        ):
            conn.execute(
                "UPDATE metrics SET anomaly_flags = anomaly_flags + 1 WHERE id = 1"
            )

    def _update_scratch(self, session_id: str, entry: AuditEntry) -> None:
        scratch = self._scratch.setdefault(session_id, {})
        d = entry.details or {}
        if entry.step_name == "extract_invoice":
            if isinstance(d.get("vendor_name"), str):
                scratch["vendor"] = d["vendor_name"]
            if isinstance(d.get("invoice_amount"), (int, float)):
                scratch["amount"] = float(d["invoice_amount"])
        if entry.step_name in ("enforce", "gate_decision"):
            if isinstance(d.get("final_amount"), (int, float)):
                scratch["amount"] = float(d["final_amount"])
            if isinstance(d.get("action"), str):
                scratch["action"] = d["action"]
        if (
            entry.step_name == "isolation_forest_anomaly"
            and d.get("is_anomaly") is True
        ):
            scratch["anomaly_flagged"] = True
        if entry.step_name == "pipeline_complete":
            if isinstance(d.get("action"), str):
                scratch["action"] = d["action"]
            if d.get("payment_executed") is True:
                scratch["payment_executed"] = True


    def _finalize_run(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        entry: AuditEntry,
        *,
        success: bool,
    ) -> None:
        from app.observability.metrics_finalize import finalize_run

        finalize_run(self, conn, session_id, entry, success=success)

    def summary(self, *, recent_limit: int = 25) -> dict[str, Any]:
        """JSON payload for ``GET /metrics`` and the Monitoring tab."""
        from app.observability.metrics_summary import build_metrics_summary

        return build_metrics_summary(self, recent_limit=recent_limit)


metrics_store = MetricsStore()
