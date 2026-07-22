from __future__ import annotations

from typing import Any, Callable

from app.observability.console_logging import get_logger, truncate_for_log

logger = get_logger(__name__)


class Neo4jWriteError(RuntimeError):
    """Raised when a write transaction fails or post-write verification fails."""


def tx_run(tx: Any, cypher: str, parameters: dict[str, Any] | None = None) -> Any:
    """Run one Cypher statement inside an open write transaction."""
    compact = truncate_for_log(" ".join(cypher.split()), 180)
    logger.info("[NEO4J] Cypher: %s", compact)
    return tx.run(cypher, parameters or {})


def execute_write(
    driver: Any,
    work: Callable[[Any], Any],
    *,
    describe: str | None = None,
) -> Any:
    """Run ``work(tx)`` inside ``session.execute_write`` (all-or-nothing)."""
    label = describe or "write"
    logger.info("[NEO4J] Writing transaction node/relationships... (%s)", label)

    def _unit(tx: Any) -> Any:
        return work(tx)

    try:
        with driver.session() as session:
            result = session.execute_write(_unit)
    except Exception as exc:  # noqa: BLE001
        raise Neo4jWriteError(f"Neo4j write failed ({label}): {exc}") from exc

    logger.info("[NEO4J] Write confirmed")
    return result


def verify_invoice_exists(driver: Any, inv_id: str) -> dict[str, Any]:
    """MATCH the just-written Invoice; raise if missing."""
    with driver.session() as session:
        row = session.run(
            """
            MATCH (i:Invoice {id: $inv_id})
            OPTIONAL MATCH (v:Vendor)-[:INVOICED]->(i)
            RETURN i.id AS id,
                   i.vendor_name AS vendor_name,
                   i.amount AS amount,
                   i.updated_at AS updated_at,
                   i.gate_action AS gate_action,
                   v.name AS vendor
            """,
            inv_id=inv_id,
        ).single()

    if row is None or not row.get("id"):
        raise Neo4jWriteError(
            f"Post-write verification failed — Invoice id={inv_id!r} not found"
        )

    logger.info(
        "[NEO4J] Verified: node exists (Invoice id=%s vendor=%s gate=%s)",
        row["id"],
        row.get("vendor_name") or row.get("vendor"),
        row.get("gate_action"),
    )
    return dict(row)


def run_cypher_read(
    session: Any,
    cypher: str,
    parameters: dict[str, Any] | None = None,
    *,
    describe: str | None = None,
) -> Any:
    """Run a read Cypher with a lighter log line."""
    label = describe or "read"
    compact = truncate_for_log(" ".join(cypher.split()), 180)
    logger.info("[NEO4J] Query (%s): %s", label, compact)
    return session.run(cypher, parameters or {})
