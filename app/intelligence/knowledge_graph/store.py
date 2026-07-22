from __future__ import annotations

import threading
from typing import Any
from urllib.parse import quote

from app.config import get_settings
from app.core import (
    ExtractedInvoice,
    GateDecision,
    PurchaseOrder,
    Settlement,
    ValidationResult,
)
from app.intelligence.knowledge_graph.context import (
    _invoice_key,
    empty_vendor_context,
    get_recorded_at,
)
from app.intelligence.knowledge_graph.memory import _MemoryGraph
from app.intelligence.knowledge_graph.store_memory import query_memory, record_memory
from app.intelligence.knowledge_graph.store_neo4j import (
    query_neo4j,
    record_neo4j,
    seed_neo4j,
)
from app.observability.audit import audit_log, get_session_id, write_audit_entry
from app.observability.console_logging import get_logger

logger = get_logger(__name__)


class KnowledgeGraph:
    """Vendor / Invoice / Dispute / Settlement graph (Neo4j or memory)."""

    def __init__(self) -> None:
        self._driver = None
        self._memory = _MemoryGraph()
        self._source = "memory"
        self._ready = False
        self._lock = threading.Lock()

    @property
    def source(self) -> str:
        return self._source

    def connect(self) -> bool:
        """Open Neo4j Aura if credentials exist; otherwise use memory."""
        s = get_settings()
        uri = (s.neo4j_uri or "").strip()
        user = s.resolved_neo4j_user()
        password = (s.neo4j_password or "").strip()

        if (
            not uri
            or not password
            or "REPLACE" in uri.upper()
            or "YOUR_INSTANCE" in uri.upper()
            or "XXXX" in uri.upper()
        ):
            logger.warning(
                "Neo4j Aura not configured (set NEO4J_URI / NEO4J_USER / "
                "NEO4J_PASSWORD). Using in-memory knowledge graph."
            )
            self._memory.ensure_seed()
            self._source = "memory"
            self._ready = True
            return False

        try:
            from neo4j import GraphDatabase

            connect_uri = uri
            if s.neo4j_trust_all:
                # neo4j+s / bolt+s forbid TrustAll; +ssc skips cert verification.
                connect_uri = (
                    uri.replace("neo4j+s://", "neo4j+ssc://")
                    .replace("bolt+s://", "bolt+ssc://")
                )
                if connect_uri == uri and "+ssc://" not in uri:
                    logger.warning(
                        "NEO4J_TRUST_ALL=1 but URI is not neo4j+s/bolt+s — "
                        "leaving scheme unchanged"
                    )
                else:
                    logger.warning(
                        "NEO4J_TRUST_ALL=1 — using self-signed-capable URI scheme "
                        "(+ssc)"
                    )
            driver = GraphDatabase.driver(connect_uri, auth=(user, password))
            driver.verify_connectivity()
            self._driver = driver
            self._source = "neo4j"
            self._ready = True
            # Log host only — never URI userinfo or password.
            host = uri.split("@")[-1] if "@" in uri else uri.split("://")[-1]
            logger.info("Connected to Neo4j Aura at %s", host)
            return True
        except Exception as exc:  # noqa: BLE001 — never block the pipeline
            logger.warning(
                "Neo4j connection failed (%s). Falling back to in-memory graph.",
                type(exc).__name__,
            )
            self._driver = None
            self._memory.ensure_seed()
            self._source = "memory"
            self._ready = True
            return False

    def init_schema(self) -> None:
        """Create uniqueness constraints / indexes for core node types."""
        if not self._ready:
            self.connect()

        if self._driver is None:
            self._memory.ensure_seed()
            write_audit_entry(
                step_name="knowledge_graph_schema",
                step_type="deterministic",
                input_summary="init constraints Vendor/Invoice/Dispute/Settlement",
                output_summary="memory backend — schema is implicit",
                details={"source": "memory"},
            )
            return

        statements = [
            "CREATE CONSTRAINT vendor_name IF NOT EXISTS "
            "FOR (v:Vendor) REQUIRE v.name IS UNIQUE",
            "CREATE CONSTRAINT invoice_id IF NOT EXISTS "
            "FOR (i:Invoice) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT dispute_id IF NOT EXISTS "
            "FOR (d:Dispute) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT settlement_id IF NOT EXISTS "
            "FOR (s:Settlement) REQUIRE s.id IS UNIQUE",
            "CREATE INDEX po_id IF NOT EXISTS FOR (p:PO) ON (p.po_id)",
        ]
        try:
            with self._driver.session() as session:
                for cypher in statements:
                    session.run(cypher)
            write_audit_entry(
                step_name="knowledge_graph_schema",
                step_type="deterministic",
                input_summary="CREATE CONSTRAINT/INDEX for Vendor, Invoice, Dispute, Settlement",
                output_summary="Neo4j schema ready",
                details={"source": "neo4j", "statements": len(statements)},
            )
            # Seed only if the graph has no vendors yet.
            with self._driver.session() as session:
                count = session.run("MATCH (v:Vendor) RETURN count(v) AS c").single()
                if count and int(count["c"]) == 0:
                    seed_neo4j(self._driver, self._memory)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j schema init failed: %s — switching to memory", exc)
            self._driver = None
            self._source = "memory"
            self._memory.ensure_seed()
            write_audit_entry(
                step_name="knowledge_graph_schema",
                step_type="deterministic",
                input_summary="schema init failed; fallback",
                output_summary=f"{type(exc).__name__}: {exc}",
                details={"source": "memory", "error": str(exc)[:200]},
            )

    def record_transaction(
        self,
        invoice: ExtractedInvoice,
        po: PurchaseOrder | None,
        validation_result: ValidationResult | None,
        settlement: Settlement | None = None,
        decision: GateDecision | None = None,
        *,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist Vendor→Invoice→(PO)→(Dispute/Settlement) for every gate outcome.

        ``recorded_at`` (ISO-8601) backdates graph timestamps for historical seeding;
        when omitted, uses the context override or wall-clock now.
        """
        if not self._ready:
            self.connect()

        ts = recorded_at or get_recorded_at()
        inv_id = _invoice_key(invoice, po)
        matched = True if validation_result is None else bool(validation_result.matched)
        had_dispute = not matched or (
            decision is not None and decision.action in ("deny", "escalate")
        )
        wrote_settlement = settlement is not None

        try:
            if self._driver is not None:
                record_neo4j(
                    self._driver,
                    inv_id=inv_id,
                    invoice=invoice,
                    po=po,
                    validation_result=validation_result,
                    settlement=settlement,
                    decision=decision,
                    ts=ts,
                )
            else:
                logger.info(
                    "[NEO4J] Writing transaction node/relationships... "
                    "(in-memory fallback)"
                )
                record_memory(
                    self._memory,
                    inv_id=inv_id,
                    invoice=invoice,
                    po=po,
                    validation_result=validation_result,
                    settlement=settlement,
                    decision=decision,
                    ts=ts,
                )
                logger.info("[NEO4J] Write confirmed")
            summary = (
                f"Wrote Vendor={invoice.vendor_name} Invoice={inv_id} "
                f"po={po.po_id if po else None} dispute={had_dispute} "
                f"settlement={wrote_settlement} gate={decision.action if decision else None} "
                f"via {self._source}"
            )
            write_audit_entry(
                step_name="knowledge_graph_write",
                step_type="deterministic",
                input_summary=(
                    f"vendor={invoice.vendor_name} amount=${invoice.invoice_amount:.2f} "
                    f"po={po.po_id if po else None} matched={matched}"
                ),
                output_summary=summary,
                details={
                    "source": self._source,
                    "invoice_id": inv_id,
                    "had_dispute": had_dispute,
                    "wrote_settlement": wrote_settlement,
                    "vendor_name": invoice.vendor_name,
                    "po_id": po.po_id if po else None,
                    "gate_action": decision.action if decision else None,
                },
            )
            return {
                "ok": True,
                "source": self._source,
                "invoice_id": inv_id,
                "had_dispute": had_dispute,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge_graph write failed: %s", exc)
            write_audit_entry(
                step_name="knowledge_graph_write",
                step_type="deterministic",
                input_summary=(
                    f"vendor={invoice.vendor_name} "
                    f"po={po.po_id if po else None}"
                ),
                output_summary=f"FAILED {type(exc).__name__}: {exc}",
                details={"source": self._source, "error": str(exc)[:200]},
            )
            return {"ok": False, "error": str(exc), "source": self._source}

    def get_vendor_context(self, vendor_name: str) -> dict[str, Any]:
        """Query past disputes / discrepancies / settlements for a vendor."""
        if not self._ready:
            self.connect()

        try:
            if self._driver is not None:
                ctx = query_neo4j(self._driver, vendor_name)
            else:
                ctx = query_memory(self._memory, vendor_name)
            ctx["available"] = True
            ctx["source"] = self._source
            write_audit_entry(
                step_name="knowledge_graph_read",
                step_type="deterministic",
                input_summary=f"get_vendor_context({vendor_name})",
                output_summary=(
                    f"invoices={ctx['invoice_count']} disputes={ctx['dispute_count']} "
                    f"avg_disc=${ctx['avg_discrepancy']:.2f} via {self._source}"
                ),
                details={
                    "vendor_name": vendor_name,
                    "invoice_count": ctx["invoice_count"],
                    "dispute_count": ctx["dispute_count"],
                    "avg_discrepancy": ctx["avg_discrepancy"],
                    "source": self._source,
                },
            )
            return ctx
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge_graph read failed: %s", exc)
            ctx = empty_vendor_context(vendor_name, source=self._source)
            write_audit_entry(
                step_name="knowledge_graph_read",
                step_type="deterministic",
                input_summary=f"get_vendor_context({vendor_name})",
                output_summary=f"FAILED {type(exc).__name__}: {exc}",
                details={"vendor_name": vendor_name, "error": str(exc)[:200]},
            )
            return ctx

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:  # noqa: BLE001
                pass
            self._driver = None


_kg: KnowledgeGraph | None = None
_kg_lock = threading.Lock()


def reset_knowledge_graph() -> None:
    """Drop the process singleton so the next get reconnects (e.g. after .env change)."""
    global _kg
    with _kg_lock:
        if _kg is not None:
            try:
                _kg.close()
            except Exception:  # noqa: BLE001
                pass
            _kg = None


def get_knowledge_graph() -> KnowledgeGraph:
    global _kg
    with _kg_lock:
        if _kg is None:
            _kg = KnowledgeGraph()
            _kg.connect()
            _kg.init_schema()
        return _kg


def publish_vendor_context(ctx: dict[str, Any], *, session_id: str | None = None) -> None:
    """Push vendor context to the live UI before negotiation starts."""
    sid = session_id or get_session_id()
    payload = {"type": "vendor_context", **ctx}
    if sid:
        payload["session_id"] = sid
    audit_log.publish_live(payload, session_id=sid)


def vendor_graph_path_safe(vendor_name: str) -> str:
    """URL-encode a vendor name for the REST route."""
    return quote(vendor_name, safe="")
