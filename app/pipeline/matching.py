from __future__ import annotations

import re

from app.observability.audit import audit_log, get_session_id
from app.seed.mock_data import (
    open_pos_for_vendor,
    resolve_seed_vendor,
    vendor_name_for_email,
)
from app.core import AuditEntry, ExtractedInvoice, PurchaseOrder

# Auto-match if invoice is within 25% of PO amount.
_AMOUNT_PROXIMITY = 0.25


def extract_email_address(sender: str) -> str:
    """Pull a bare email from a From header like ``Name <user@host>``."""
    if not sender:
        return ""
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", sender)
    return match.group(0).lower() if match else sender.strip().lower()


def _relative_delta(invoice_amount: float, po_amount: float) -> float:
    if po_amount == 0:
        return 0.0 if invoice_amount == 0 else float("inf")
    return abs(invoice_amount - po_amount) / abs(po_amount)


def _best_po_by_amount(
    candidates: list[PurchaseOrder],
    invoice_amount: float,
) -> tuple[PurchaseOrder | None, float]:
    """Return (closest PO, relative delta), or (None, inf) if empty."""
    if not candidates:
        return None, float("inf")
    best = min(candidates, key=lambda po: abs(po.agreed_amount - invoice_amount))
    return best, _relative_delta(invoice_amount, best.agreed_amount)


def _emit_match_audit(
    *,
    strategy: str,
    input_summary: str,
    output_summary: str,
    details: dict[str, str | int | float | bool | None],
) -> AuditEntry:
    return audit_log.append(
        step_name="match_to_po",
        step_type="deterministic",
        input_summary=input_summary,
        output_summary=output_summary,
        session_id=get_session_id(),
        details={"strategy": strategy, **details},
    )


def match_to_po(
    extracted_invoice: ExtractedInvoice,
    sender_email: str,
) -> PurchaseOrder | None:
    """Match an extracted invoice to an open PO without guessing.

    Strategy (deterministic, in order):
      1. Resolve vendor via ``sender_email`` against ``VENDOR_EMAILS``.
      2. Fall back to ``extracted_invoice.vendor_name`` if email is unknown.
      3. Among that vendor's open POs, pick by amount proximity - only if the
         closest PO is within ``_AMOUNT_PROXIMITY`` (25%) of the invoice total.

    If any step fails to produce a confident match, returns ``None`` and
    audits a fallthrough to manual PO matching (no silent guess).

    Args:
        extracted_invoice: Structured invoice from the extraction stage.
        sender_email: Raw From header or bare address from the inbound email.

    Returns:
        The matched PurchaseOrder, or None when manual review is required.
    """
    bare_email = extract_email_address(sender_email)
    amount = extracted_invoice.invoice_amount
    invoice_vendor = extracted_invoice.vendor_name.strip()

    input_summary = (
        f"sender={bare_email or '(none)'} vendor={invoice_vendor!r} "
        f"amount=${amount:.2f}"
    )

    # --- 1. Sender email → known vendor ---
    email_vendor = vendor_name_for_email(bare_email) if bare_email else None
    strategy_used = "sender_email"
    vendor_name = email_vendor

    if vendor_name is None:
        # --- 2. Fall back to extracted vendor_name ---
        strategy_used = "vendor_name"
        vendor_name = invoice_vendor or None

    if vendor_name:
        # Normalize "Northwind Components LLC" → seed "Northwind Components"
        resolved = resolve_seed_vendor(vendor_name)
        if resolved:
            vendor_name = resolved

    if not vendor_name:
        _emit_match_audit(
            strategy="manual_review",
            input_summary=input_summary,
            output_summary=(
                "No confident match - unknown sender and empty vendor_name; "
                "needs manual PO matching"
            ),
            details={
                "matched": False,
                "sender_email": bare_email or None,
                "invoice_amount": amount,
            },
        )
        return None

    # Prefer email-authenticated vendor over invoice text.
    open_pos = open_pos_for_vendor(vendor_name)
    if not open_pos:
        _emit_match_audit(
            strategy="manual_review",
            input_summary=input_summary,
            output_summary=(
                f"No open POs for vendor={vendor_name!r} "
                f"(resolved via {strategy_used}); needs manual PO matching"
            ),
            details={
                "matched": False,
                "vendor_name": vendor_name,
                "sender_email": bare_email or None,
                "invoice_amount": amount,
                "vendor_source": strategy_used,
            },
        )
        return None

    best, rel_delta = _best_po_by_amount(open_pos, amount)
    if best is None or rel_delta > _AMOUNT_PROXIMITY:
        _emit_match_audit(
            strategy="manual_review",
            input_summary=input_summary,
            output_summary=(
                f"Vendor={vendor_name!r} resolved via {strategy_used}, but no PO "
                f"within {_AMOUNT_PROXIMITY:.0%} of ${amount:.2f}"
                + (
                    f" (closest {best.po_id} delta={rel_delta:.1%})"
                    if best is not None
                    else ""
                )
                + "; needs manual PO matching"
            ),
            details={
                "matched": False,
                "vendor_name": vendor_name,
                "sender_email": bare_email or None,
                "invoice_amount": amount,
                "closest_po_id": best.po_id if best else None,
                "relative_delta": round(rel_delta, 4) if best else None,
                "vendor_source": strategy_used,
            },
        )
        return None

    # Ambiguity guard: if two open POs are similarly close, do not guess.
    if len(open_pos) > 1:
        ranked = sorted(
            open_pos,
            key=lambda po: abs(po.agreed_amount - amount),
        )
        second_delta = _relative_delta(amount, ranked[1].agreed_amount)
        if second_delta <= _AMOUNT_PROXIMITY and abs(rel_delta - second_delta) < 0.05:
            _emit_match_audit(
                strategy="manual_review",
                input_summary=input_summary,
                output_summary=(
                    f"Ambiguous amount match for {vendor_name!r}: "
                    f"{ranked[0].po_id} ({rel_delta:.1%}) vs "
                    f"{ranked[1].po_id} ({second_delta:.1%}); "
                    "needs manual PO matching"
                ),
                details={
                    "matched": False,
                    "vendor_name": vendor_name,
                    "sender_email": bare_email or None,
                    "invoice_amount": amount,
                    "vendor_source": strategy_used,
                },
            )
            return None

    final_strategy = (
        "sender_email+amount_proximity"
        if strategy_used == "sender_email"
        else "vendor_name+amount_proximity"
    )
    _emit_match_audit(
        strategy=final_strategy,
        input_summary=input_summary,
        output_summary=(
            f"Matched {best.po_id} via {final_strategy} "
            f"(vendor={vendor_name}, delta={rel_delta:.1%}, "
            f"PO ${best.agreed_amount:.2f})"
        ),
        details={
            "matched": True,
            "po_id": best.po_id,
            "vendor_name": vendor_name,
            "sender_email": bare_email or None,
            "invoice_amount": amount,
            "po_amount": best.agreed_amount,
            "relative_delta": round(rel_delta, 4),
            "vendor_source": strategy_used,
        },
    )
    return best
