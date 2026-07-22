from __future__ import annotations

import sqlite3

METRICS_DDL = """
CREATE TABLE IF NOT EXISTS metrics_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT,
    step_name TEXT,
    step_type TEXT,
    duration_ms REAL,
    outcome TEXT,
    vendor_name TEXT,
    amount REAL
);
CREATE INDEX IF NOT EXISTS idx_metrics_log_ts
    ON metrics_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_log_session
    ON metrics_log(session_id);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    total_runs INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0,
    denied INTEGER NOT NULL DEFAULT 0,
    escalated INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    llm_steps INTEGER NOT NULL DEFAULT 0,
    deterministic_steps INTEGER NOT NULL DEFAULT 0,
    ml_steps INTEGER NOT NULL DEFAULT 0,
    llm_latency_sum_ms REAL NOT NULL DEFAULT 0,
    deterministic_latency_sum_ms REAL NOT NULL DEFAULT 0,
    ml_latency_sum_ms REAL NOT NULL DEFAULT 0,
    llm_latency_count INTEGER NOT NULL DEFAULT 0,
    deterministic_latency_count INTEGER NOT NULL DEFAULT 0,
    ml_latency_count INTEGER NOT NULL DEFAULT 0,
    total_llm_calls INTEGER NOT NULL DEFAULT 0,
    anomaly_flags INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
INSERT OR IGNORE INTO metrics (id) VALUES (1);

CREATE TABLE IF NOT EXISTS runs (
    session_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    outcome TEXT NOT NULL,
    vendor TEXT,
    amount REAL,
    success INTEGER NOT NULL DEFAULT 1,
    anomaly_flagged INTEGER NOT NULL DEFAULT 0,
    payment_executed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(timestamp DESC);
"""


def init_metrics_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(METRICS_DDL)
    conn.commit()
