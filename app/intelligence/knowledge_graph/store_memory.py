from __future__ import annotations

from typing import Any

from app.core import (
    ExtractedInvoice,
    GateDecision,
    PurchaseOrder,
    Settlement,
    ValidationResult,
)
from app.intelligence.knowledge_graph.memory import _MemoryGraph
from app.observability.console_logging import get_logger

logger = get_logger(__name__)


def record_memory(
    memory: _MemoryGraph,
    *,
    inv_id: str,
    invoice: ExtractedInvoice,
    po: PurchaseOrder | None,
    validation_result: ValidationResult | None,
    settlement: Settlement | None,
    decision: GateDecision | None,
    ts: str,
) -> None:
    matched = True if validation_result is None else bool(validation_result.matched)
    discrepancy = (
        0.0 if validation_result is None else float(validation_result.discrepancy_amount)
    )
    reason = "" if validation_result is None else validation_result.reason
    write_dispute = (not matched) or (
        decision is not None and decision.action in ("deny", "escalate")
    )

    with memory._lock:
        memory.vendors[invoice.vendor_name] = {
            "name": invoice.vendor_name,
            "last_updated": ts,
        }
        memory.invoices[inv_id] = {
            "id": inv_id,
            "vendor_name": invoice.vendor_name,
            "amount": invoice.invoice_amount,
            "discrepancy": discrepancy,
            "matched": matched,
            "updated_at": ts,
            "gate_action": decision.action if decision else None,
            "gate_rule": decision.rule_fired if decision else None,
            "po_id": po.po_id if po else None,
        }
        # Drop prior edges/nodes for this invoice so re-runs stay idempotent
        d_id = f"dispute:{inv_id}"
        s_id = f"settlement:{inv_id}"
        memory.disputes.pop(d_id, None)
        memory.settlements.pop(s_id, None)
        memory.edges = [
            e
            for e in memory.edges
            if not (
                (e[0] == "INVOICED" and e[2] == inv_id)
                or (e[0] == "MATCHED_AGAINST" and e[1] == inv_id)
                or (e[0] == "HAD_DISPUTE" and e[1] == inv_id)
                or (e[0] == "SETTLED_AS" and e[1] == inv_id)
                or (e[0] == "RESOLVED_AS" and e[1] == d_id)
                or (e[2] == s_id)
            )
        ]
        memory.edges.append(
            ("INVOICED", invoice.vendor_name, inv_id, {"timestamp": ts})
        )
        if po is not None:
            memory.pos[po.po_id] = {
                "po_id": po.po_id,
                "vendor_name": invoice.vendor_name,
                "updated_at": ts,
            }
            memory.edges.append(
                ("MATCHED_AGAINST", inv_id, po.po_id, {"timestamp": ts})
            )

        if write_dispute:
            memory.disputes[d_id] = {
                "id": d_id,
                "discrepancy_amount": discrepancy,
                "vendor_name": invoice.vendor_name,
                "updated_at": ts,
                "gate_action": decision.action if decision else None,
                "reason": reason or (decision.reason if decision else ""),
            }
            memory.edges.append(
                ("HAD_DISPUTE", inv_id, d_id, {"timestamp": ts})
            )

        if settlement is not None:
            memory.settlements[s_id] = {
                "id": s_id,
                "final_amount": settlement.final_amount,
                "agreed_by_both": settlement.agreed_by_both,
                "vendor_name": invoice.vendor_name,
                "updated_at": ts,
                "gate_action": decision.action if decision else None,
            }
            if write_dispute:
                memory.edges.append(
                    ("RESOLVED_AS", d_id, s_id, {"timestamp": ts})
                )
            else:
                memory.edges.append(
                    ("SETTLED_AS", inv_id, s_id, {"timestamp": ts})
                )

    # Verify read-back (same contract as Neo4j path)
    with memory._lock:
        if inv_id not in memory.invoices:
            raise RuntimeError(
                f"Post-write verification failed — Invoice id={inv_id!r} not found"
            )
    logger.info(
        "[NEO4J] Verified: node exists (Invoice id=%s vendor=%s gate=%s) [memory]",
        inv_id,
        invoice.vendor_name,
        decision.action if decision else None,
    )


def query_memory(memory: _MemoryGraph, vendor_name: str) -> dict[str, Any]:
    memory.ensure_seed()
    with memory._lock:
        invoices = [
            i
            for i in memory.invoices.values()
            if i["vendor_name"] == vendor_name
        ]
        disputes = [
            d
            for d in memory.disputes.values()
            if d["vendor_name"] == vendor_name
        ]
        settlements = [
            s
            for s in memory.settlements.values()
            if s["vendor_name"] == vendor_name
        ]
        vendor = memory.vendors.get(vendor_name) or {}
    amounts = [float(i["amount"]) for i in invoices]
    discs = [float(d["discrepancy_amount"]) for d in disputes]
    settle_amts = [float(s["final_amount"]) for s in settlements]
    agreed = sum(1 for s in settlements if s.get("agreed_by_both"))
    updated_times = [
        t
        for t in (
            [i.get("updated_at") for i in invoices]
            + [vendor.get("last_updated")]
        )
        if t
    ]
    last_updated = max(updated_times) if updated_times else None
    return {
        "vendor_name": vendor_name,
        "invoice_count": len(invoices),
        "dispute_count": len(disputes),
        "avg_discrepancy": round(sum(discs) / len(discs), 2) if discs else 0.0,
        "avg_invoice_amount": (
            round(sum(amounts) / len(amounts), 2) if amounts else 0.0
        ),
        "invoice_amounts": amounts,
        "settlement_outcomes": {
            "agreed_count": agreed,
            "not_agreed_count": len(settlements) - agreed,
            "avg_settlement_amount": (
                round(sum(settle_amts) / len(settle_amts), 2)
                if settle_amts
                else None
            ),
            "recent": [
                {
                    "final_amount": float(s["final_amount"]),
                    "agreed_by_both": bool(s["agreed_by_both"]),
                    "updated_at": s.get("updated_at"),
                    "gate_action": s.get("gate_action"),
                }
                for s in settlements[-5:]
            ],
        },
        "last_updated": last_updated,
        "source": "memory",
        "available": True,
    }
