"""Vendor context helpers for knowledge-graph prompts."""

from __future__ import annotations

import contextvars
from datetime import datetime, timezone
from typing import Any

from app.core import ExtractedInvoice, PurchaseOrder

# Optional override for historical seeding (ISO-8601). None → wall clock.
_recorded_at_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "kg_recorded_at",
    default=None,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_recorded_at() -> str:
    """Timestamp used for graph writes (override or now)."""
    return _recorded_at_override.get() or _utc_now()


def set_recorded_at(iso_timestamp: str | None) -> contextvars.Token[str | None]:
    """Bind a backdated timestamp for subsequent ``record_transaction`` calls."""
    return _recorded_at_override.set(iso_timestamp)


def reset_recorded_at(token: contextvars.Token[str | None]) -> None:
    _recorded_at_override.reset(token)


def _invoice_key(
    invoice: ExtractedInvoice,
    po: PurchaseOrder | None = None,
) -> str:
    """Stable idempotent Invoice id — re-runs MERGE the same node (no session salt)."""
    po_part = po.po_id if po is not None else "nop"
    return (
        f"inv:{invoice.vendor_name}|{invoice.invoice_date.isoformat()}"
        f"|{invoice.invoice_amount:.2f}|{po_part}"
    )


def empty_vendor_context(vendor_name: str, *, source: str = "none") -> dict[str, Any]:
    return {
        "vendor_name": vendor_name,
        "invoice_count": 0,
        "dispute_count": 0,
        "avg_discrepancy": 0.0,
        "avg_invoice_amount": 0.0,
        "settlement_outcomes": {
            "agreed_count": 0,
            "not_agreed_count": 0,
            "avg_settlement_amount": None,
            "recent": [],
        },
        "last_updated": None,
        "source": source,
        "available": False,
    }


def format_vendor_context_for_prompt(ctx: dict[str, Any]) -> str:
    """Compact block injected into buyer/supplier agent system prompts."""
    outcomes = ctx.get("settlement_outcomes") or {}
    recent = outcomes.get("recent") or []
    recent_txt = "; ".join(
        (
            f"${r.get('final_amount', 0):,.2f}"
            f"({'agreed' if r.get('agreed_by_both') else 'no-deal'})"
        )
        for r in recent[:5]
    ) or "none"
    avg_settle = outcomes.get("avg_settlement_amount")
    avg_settle_txt = f"${avg_settle:,.2f}" if avg_settle is not None else "n/a"
    return (
        f"VENDOR KNOWLEDGE GRAPH ({ctx.get('source', 'graph')}):\n"
        f"- Past invoices on record: {ctx.get('invoice_count', 0)}\n"
        f"- Past disputes: {ctx.get('dispute_count', 0)}\n"
        f"- Avg discrepancy when disputed: ${float(ctx.get('avg_discrepancy') or 0):,.2f}\n"
        f"- Avg invoice amount: ${float(ctx.get('avg_invoice_amount') or 0):,.2f}\n"
        f"- Settlements agreed/not: "
        f"{outcomes.get('agreed_count', 0)}/{outcomes.get('not_agreed_count', 0)} "
        f"(avg settlement {avg_settle_txt})\n"
        f"- Recent settlements: {recent_txt}\n"
        "Use this history to ground your proposal — do not invent vendor facts."
    )
