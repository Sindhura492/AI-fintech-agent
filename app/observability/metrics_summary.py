from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.observability.metrics_store import MetricsStore


def empty_metrics_summary() -> dict[str, Any]:
    return {
        "total_runs": 0,
        "runs_by_outcome": {
            "approved": 0,
            "denied": 0,
            "escalated": 0,
            "failed": 0,
        },
        "step_counts_by_type": {"llm": 0, "deterministic": 0, "ml": 0},
        "avg_latency_per_step_type_ms": {
            "llm": None,
            "deterministic": None,
            "ml": None,
        },
        "total_llm_calls": 0,
        "escalation_rate": 0.0,
        "anomaly_flag_rate": 0.0,
        "anomaly_flags": 0,
        "updated_at": None,
        "recent_runs": [],
        "rate_series": {
            "labels": [],
            "escalation_rate": [],
            "anomaly_flag_rate": [],
        },
        "health": [],
    }


def build_metrics_summary(store: MetricsStore, *, recent_limit: int = 25) -> dict[str, Any]:
    """JSON payload for ``GET /metrics`` and the Monitoring tab."""
    with store._lock:
        with store._connect() as conn:
            row = conn.execute("SELECT * FROM metrics WHERE id = 1").fetchone()
            runs = conn.execute(
                """
                SELECT session_id, timestamp, outcome, vendor, amount,
                       success, anomaly_flagged, payment_executed
                FROM runs
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (recent_limit,),
            ).fetchall()
            log_count = conn.execute(
                "SELECT COUNT(*) AS c FROM metrics_log"
            ).fetchone()

    if row is None:
        empty = empty_metrics_summary()
        empty["db_path"] = store.absolute_path()
        empty["metrics_log_count"] = 0
        return empty

    total = int(row["total_runs"] or 0)
    escalated = int(row["escalated"] or 0)
    anomaly_flags = int(row["anomaly_flags"] or 0)

    def avg(sum_ms: float, count: int) -> float | None:
        if count <= 0:
            return None
        return round(float(sum_ms) / count, 2)

    step_counts = {
        "llm": int(row["llm_steps"] or 0),
        "deterministic": int(row["deterministic_steps"] or 0),
        "ml": int(row["ml_steps"] or 0),
    }
    avg_latency = {
        "llm": avg(row["llm_latency_sum_ms"], row["llm_latency_count"]),
        "deterministic": avg(
            row["deterministic_latency_sum_ms"],
            row["deterministic_latency_count"],
        ),
        "ml": avg(row["ml_latency_sum_ms"], row["ml_latency_count"]),
    }

    recent = [dict(r) for r in runs]
    recent_rev = list(reversed(recent))
    esc_series: list[float] = []
    anom_series: list[float] = []
    esc_cum = anom_cum = n = 0
    for r in recent_rev:
        n += 1
        if r["outcome"] == "escalated":
            esc_cum += 1
        if r["anomaly_flagged"]:
            anom_cum += 1
        esc_series.append(round(esc_cum / n, 4))
        anom_series.append(round(anom_cum / n, 4))

    health = [
        {
            "session_id": r["session_id"],
            "timestamp": r["timestamp"],
            "success": bool(r["success"]),
            "outcome": r["outcome"],
        }
        for r in recent[:15]
    ]

    return {
        "db_path": store.absolute_path(),
        "metrics_log_count": int(log_count["c"] if log_count else 0),
        "total_runs": total,
        "runs_by_outcome": {
            "approved": int(row["approved"] or 0),
            "denied": int(row["denied"] or 0),
            "escalated": escalated,
            "failed": int(row["failed"] or 0),
        },
        "step_counts_by_type": step_counts,
        "avg_latency_per_step_type_ms": avg_latency,
        "total_llm_calls": int(row["total_llm_calls"] or 0),
        "escalation_rate": round(escalated / total, 4) if total else 0.0,
        "anomaly_flag_rate": (
            round(anomaly_flags / total, 4) if total else 0.0
        ),
        "anomaly_flags": anomaly_flags,
        "updated_at": row["updated_at"],
        "recent_runs": recent,
        "rate_series": {
            "labels": [
                r["timestamp"][11:19] if r.get("timestamp") else ""
                for r in recent_rev
            ],
            "escalation_rate": esc_series,
            "anomaly_flag_rate": anom_series,
        },
        "health": health,
    }
