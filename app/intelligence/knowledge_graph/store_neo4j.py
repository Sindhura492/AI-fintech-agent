from __future__ import annotations

from typing import Any

from app.core import (
    ExtractedInvoice,
    GateDecision,
    PurchaseOrder,
    Settlement,
    ValidationResult,
)
from app.intelligence.knowledge_graph.context import _utc_now, empty_vendor_context
from app.intelligence.knowledge_graph.memory import _MemoryGraph
from app.intelligence.knowledge_graph.neo4j_client import (
    execute_write,
    run_cypher_read,
    tx_run,
    verify_invoice_exists,
)


def seed_neo4j(driver: Any, memory: _MemoryGraph) -> None:
    """Insert historical rows in one write transaction when the graph is empty."""
    memory.ensure_seed()

    def _seed(tx: Any) -> None:
        for vendor in memory.vendors:
            tx_run(tx, "MERGE (v:Vendor {name: $name})", {"name": vendor})
        for inv_id, inv in memory.invoices.items():
            ts = _utc_now()
            tx_run(
                tx,
                """
                MERGE (v:Vendor {name: $vendor})
                MERGE (i:Invoice {id: $id})
                SET i.amount = $amount,
                    i.vendor_name = $vendor,
                    i.discrepancy = $disc,
                    i.updated_at = $ts,
                    i.gate_action = coalesce(i.gate_action, 'seed')
                MERGE (v)-[r:INVOICED]->(i)
                SET r.timestamp = $ts
                """,
                {
                    "vendor": inv["vendor_name"],
                    "id": inv_id,
                    "amount": inv["amount"],
                    "disc": inv.get("discrepancy", 0.0),
                    "ts": ts,
                },
            )
        for po_id, po in memory.pos.items():
            tx_run(
                tx,
                """
                MERGE (p:PO {po_id: $po_id})
                SET p.vendor_name = $vendor
                """,
                {"po_id": po_id, "vendor": po["vendor_name"]},
            )
        for typ, src, dst, props in memory.edges:
            ts = props.get("timestamp", _utc_now())
            if typ == "MATCHED_AGAINST":
                tx_run(
                    tx,
                    """
                    MATCH (i:Invoice {id: $src})
                    MERGE (p:PO {po_id: $dst})
                    MERGE (i)-[r:MATCHED_AGAINST]->(p)
                    SET r.timestamp = $ts
                    """,
                    {"src": src, "dst": dst, "ts": ts},
                )
            elif typ == "HAD_DISPUTE":
                d = memory.disputes[dst]
                tx_run(
                    tx,
                    """
                    MATCH (i:Invoice {id: $src})
                    MERGE (d:Dispute {id: $dst})
                    SET d.discrepancy_amount = $disc,
                        d.vendor_name = $vendor,
                        d.updated_at = $ts
                    MERGE (i)-[r:HAD_DISPUTE]->(d)
                    SET r.timestamp = $ts
                    """,
                    {
                        "src": src,
                        "dst": dst,
                        "disc": d["discrepancy_amount"],
                        "vendor": d["vendor_name"],
                        "ts": ts,
                    },
                )
            elif typ == "RESOLVED_AS":
                s = memory.settlements[dst]
                tx_run(
                    tx,
                    """
                    MATCH (d:Dispute {id: $src})
                    MERGE (s:Settlement {id: $dst})
                    SET s.final_amount = $amount,
                        s.agreed_by_both = $agreed,
                        s.vendor_name = $vendor,
                        s.updated_at = $ts
                    MERGE (d)-[r:RESOLVED_AS]->(s)
                    SET r.timestamp = $ts
                    """,
                    {
                        "src": src,
                        "dst": dst,
                        "amount": s["final_amount"],
                        "agreed": s["agreed_by_both"],
                        "vendor": s["vendor_name"],
                        "ts": ts,
                    },
                )

    execute_write(driver, _seed, describe="seed graph")


def record_neo4j(
    driver: Any,
    *,
    inv_id: str,
    invoice: ExtractedInvoice,
    po: PurchaseOrder | None,
    validation_result: ValidationResult | None,
    settlement: Settlement | None,
    decision: GateDecision | None,
    ts: str,
) -> None:
    """Atomically MERGE vendor/invoice/(po)/(dispute)/(settlement), then verify."""
    matched = True if validation_result is None else bool(validation_result.matched)
    discrepancy = (
        0.0 if validation_result is None else float(validation_result.discrepancy_amount)
    )
    reason = "" if validation_result is None else validation_result.reason
    gate_action = decision.action if decision else None
    gate_rule = decision.rule_fired if decision else None
    gate_reason = decision.reason if decision else None

    write_dispute = (not matched) or (
        decision is not None and decision.action in ("deny", "escalate")
    )

    def _write(tx: Any) -> None:
        tx_run(
            tx,
            """
            MERGE (v:Vendor {name: $vendor})
            ON CREATE SET v.created_at = $ts
            SET v.last_updated = $ts
            MERGE (i:Invoice {id: $inv_id})
            ON CREATE SET i.created_at = $ts
            SET i.amount = $amount,
                i.currency = $currency,
                i.invoice_date = $invoice_date,
                i.vendor_name = $vendor,
                i.discrepancy = $disc,
                i.matched = $matched,
                i.updated_at = $ts,
                i.gate_action = $gate_action,
                i.gate_rule = $gate_rule,
                i.gate_reason = $gate_reason,
                i.po_id = $po_id
            MERGE (v)-[r1:INVOICED]->(i)
            SET r1.timestamp = $ts
            """,
            {
                "vendor": invoice.vendor_name,
                "inv_id": inv_id,
                "amount": invoice.invoice_amount,
                "currency": invoice.currency,
                "invoice_date": invoice.invoice_date.isoformat(),
                "disc": discrepancy,
                "matched": matched,
                "ts": ts,
                "gate_action": gate_action,
                "gate_rule": gate_rule,
                "gate_reason": gate_reason,
                "po_id": po.po_id if po else None,
            },
        )

        if po is not None:
            tx_run(
                tx,
                """
                MATCH (i:Invoice {id: $inv_id})
                MERGE (p:PO {po_id: $po_id})
                SET p.vendor_name = $vendor,
                    p.agreed_amount = $po_amount,
                    p.updated_at = $ts
                MERGE (i)-[r2:MATCHED_AGAINST]->(p)
                SET r2.timestamp = $ts
                """,
                {
                    "inv_id": inv_id,
                    "po_id": po.po_id,
                    "vendor": invoice.vendor_name,
                    "po_amount": po.agreed_amount,
                    "ts": ts,
                },
            )

        d_id = f"dispute:{inv_id}"
        if write_dispute:
            tx_run(
                tx,
                """
                MATCH (i:Invoice {id: $inv_id})
                MERGE (d:Dispute {id: $d_id})
                ON CREATE SET d.created_at = $ts
                SET d.discrepancy_amount = $disc,
                    d.reason = $reason,
                    d.vendor_name = $vendor,
                    d.gate_action = $gate_action,
                    d.gate_rule = $gate_rule,
                    d.updated_at = $ts
                MERGE (i)-[r:HAD_DISPUTE]->(d)
                SET r.timestamp = $ts
                """,
                {
                    "inv_id": inv_id,
                    "d_id": d_id,
                    "disc": discrepancy,
                    "reason": (reason or gate_reason or "dispute")[:500],
                    "vendor": invoice.vendor_name,
                    "gate_action": gate_action,
                    "gate_rule": gate_rule,
                    "ts": ts,
                },
            )

        if settlement is not None:
            s_id = f"settlement:{inv_id}"
            if write_dispute:
                tx_run(
                    tx,
                    """
                    MATCH (d:Dispute {id: $d_id})
                    MERGE (s:Settlement {id: $s_id})
                    ON CREATE SET s.created_at = $ts
                    SET s.final_amount = $amount,
                        s.agreed_by_both = $agreed,
                        s.within_bounds = $bounds,
                        s.vendor_name = $vendor,
                        s.gate_action = $gate_action,
                        s.updated_at = $ts
                    MERGE (d)-[r:RESOLVED_AS]->(s)
                    SET r.timestamp = $ts
                    """,
                    {
                        "d_id": d_id,
                        "s_id": s_id,
                        "amount": settlement.final_amount,
                        "agreed": settlement.agreed_by_both,
                        "bounds": settlement.within_bounds,
                        "vendor": invoice.vendor_name,
                        "gate_action": gate_action,
                        "ts": ts,
                    },
                )
            else:
                tx_run(
                    tx,
                    """
                    MATCH (i:Invoice {id: $inv_id})
                    MERGE (s:Settlement {id: $s_id})
                    ON CREATE SET s.created_at = $ts
                    SET s.final_amount = $amount,
                        s.agreed_by_both = $agreed,
                        s.within_bounds = $bounds,
                        s.vendor_name = $vendor,
                        s.gate_action = $gate_action,
                        s.updated_at = $ts
                    MERGE (i)-[r:SETTLED_AS]->(s)
                    SET r.timestamp = $ts
                    """,
                    {
                        "inv_id": inv_id,
                        "s_id": s_id,
                        "amount": settlement.final_amount,
                        "agreed": settlement.agreed_by_both,
                        "bounds": settlement.within_bounds,
                        "vendor": invoice.vendor_name,
                        "gate_action": gate_action,
                        "ts": ts,
                    },
                )

    execute_write(driver, _write, describe=f"invoice {inv_id}")
    verify_invoice_exists(driver, inv_id)


def query_neo4j(driver: Any, vendor_name: str) -> dict[str, Any]:
    with driver.session() as session:
        row = run_cypher_read(
            session,
            """
            MATCH (v:Vendor {name: $vendor})
            OPTIONAL MATCH (v)-[:INVOICED]->(i:Invoice)
            OPTIONAL MATCH (i)-[:HAD_DISPUTE]->(d:Dispute)
            OPTIONAL MATCH (d)-[:RESOLVED_AS]->(s:Settlement)
            OPTIONAL MATCH (i)-[:SETTLED_AS]->(s2:Settlement)
            RETURN
              count(DISTINCT i) AS invoice_count,
              count(DISTINCT d) AS dispute_count,
              avg(i.amount) AS avg_invoice_amount,
              avg(d.discrepancy_amount) AS avg_discrepancy,
              collect(DISTINCT s) + collect(DISTINCT s2) AS settlements,
              max(i.updated_at) AS last_updated,
              v.last_updated AS vendor_last_updated
            """,
            {"vendor": vendor_name},
            describe="vendor context",
        ).single()

    if row is None:
        return empty_vendor_context(vendor_name, source="neo4j")

    settlements = [s for s in (row["settlements"] or []) if s is not None]
    seen: set[str] = set()
    unique_settlements: list[Any] = []
    for s in settlements:
        sid = str(s.get("id") or id(s))
        if sid in seen:
            continue
        seen.add(sid)
        unique_settlements.append(s)
    settlements = unique_settlements

    agreed = sum(1 for s in settlements if s.get("agreed_by_both"))
    not_agreed = len(settlements) - agreed
    amounts = [float(s.get("final_amount") or 0) for s in settlements]
    recent = [
        {
            "final_amount": float(s.get("final_amount") or 0),
            "agreed_by_both": bool(s.get("agreed_by_both")),
            "updated_at": s.get("updated_at"),
            "gate_action": s.get("gate_action"),
        }
        for s in settlements[-5:]
    ]
    avg_disc = row["avg_discrepancy"]
    avg_inv = row["avg_invoice_amount"]
    last_updated = row["last_updated"] or row["vendor_last_updated"]
    return {
        "vendor_name": vendor_name,
        "invoice_count": int(row["invoice_count"] or 0),
        "dispute_count": int(row["dispute_count"] or 0),
        "avg_discrepancy": round(float(avg_disc or 0), 2),
        "avg_invoice_amount": round(float(avg_inv or 0), 2),
        "settlement_outcomes": {
            "agreed_count": agreed,
            "not_agreed_count": not_agreed,
            "avg_settlement_amount": (
                round(sum(amounts) / len(amounts), 2) if amounts else None
            ),
            "recent": recent,
        },
        "last_updated": last_updated,
        "source": "neo4j",
        "available": True,
    }


def count_graph_nodes(driver: Any) -> dict[str, int]:
    """Return total Vendor / Invoice / Dispute / Settlement counts."""
    with driver.session() as session:
        row = session.run(
            """
            OPTIONAL MATCH (v:Vendor)
            WITH count(v) AS vendors
            OPTIONAL MATCH (i:Invoice)
            WITH vendors, count(i) AS invoices
            OPTIONAL MATCH (d:Dispute)
            WITH vendors, invoices, count(d) AS disputes
            OPTIONAL MATCH (s:Settlement)
            RETURN vendors, invoices, disputes, count(s) AS settlements
            """
        ).single()
    if row is None:
        return {"vendors": 0, "invoices": 0, "disputes": 0, "settlements": 0}
    return {
        "vendors": int(row["vendors"] or 0),
        "invoices": int(row["invoices"] or 0),
        "disputes": int(row["disputes"] or 0),
        "settlements": int(row["settlements"] or 0),
    }


def recent_transactions(driver: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    """Most recent Invoice writes by updated_at."""
    with driver.session() as session:
        rows = session.run(
            """
            MATCH (i:Invoice)
            RETURN i.id AS id,
                   i.vendor_name AS vendor_name,
                   i.amount AS amount,
                   i.gate_action AS gate_action,
                   i.matched AS matched,
                   i.updated_at AS updated_at,
                   i.po_id AS po_id
            ORDER BY i.updated_at DESC
            LIMIT $limit
            """,
            limit=limit,
        )
        return [dict(r) for r in rows]
