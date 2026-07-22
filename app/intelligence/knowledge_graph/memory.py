"""Process-local stand-in when Neo4j Aura is not configured."""

from __future__ import annotations

import threading
from typing import Any

from app.intelligence.knowledge_graph.context import _utc_now


class _MemoryGraph:
    """Process-local stand-in when Neo4j Aura is not configured."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.vendors: dict[str, dict[str, Any]] = {}
        self.invoices: dict[str, dict[str, Any]] = {}
        self.pos: dict[str, dict[str, Any]] = {}
        self.disputes: dict[str, dict[str, Any]] = {}
        self.settlements: dict[str, dict[str, Any]] = {}
        # edges: (type, from_id, to_id, props)
        self.edges: list[tuple[str, str, str, dict[str, Any]]] = []

    def ensure_seed(self) -> None:
        """Seed a few historical disputes so first-run demos aren't empty."""
        with self._lock:
            if self.invoices:
                return
            now = _utc_now()
            seeds = [
                ("Meridian Office Supply", "PO-1001", 4850.0, 0.0, True, 4850.0, False),
                ("Cascade Industrial Parts", "PO-1002", 3180.0, 64.0, True, 3200.0, True),
                ("Cascade Industrial Parts", "PO-1002b", 3290.0, 90.0, True, 3200.0, True),
                ("Northwind Components", "PO-1003a", 13200.0, 700.0, True, 12500.0, True),
                ("Northwind Components", "PO-1003b", 14100.0, 1600.0, False, 14100.0, True),
            ]
            for vendor, po_id, amount, disc, agreed, settle_amt, had_dispute in seeds:
                inv_id = f"seed:{vendor}:{po_id}"
                self.vendors[vendor] = {"name": vendor}
                self.invoices[inv_id] = {
                    "id": inv_id,
                    "vendor_name": vendor,
                    "amount": amount,
                    "discrepancy": disc,
                }
                self.pos[po_id] = {"po_id": po_id, "vendor_name": vendor}
                self.edges.append(("INVOICED", vendor, inv_id, {"timestamp": now}))
                self.edges.append(("MATCHED_AGAINST", inv_id, po_id, {"timestamp": now}))
                if had_dispute:
                    d_id = f"dispute:{inv_id}"
                    self.disputes[d_id] = {
                        "id": d_id,
                        "discrepancy_amount": disc,
                        "vendor_name": vendor,
                    }
                    self.edges.append(("HAD_DISPUTE", inv_id, d_id, {"timestamp": now}))
                    s_id = f"settlement:{inv_id}"
                    self.settlements[s_id] = {
                        "id": s_id,
                        "final_amount": settle_amt,
                        "agreed_by_both": agreed,
                        "vendor_name": vendor,
                    }
                    self.edges.append(("RESOLVED_AS", d_id, s_id, {"timestamp": now}))
