from __future__ import annotations

import re
from datetime import date

from app.core import ExtractedInvoice, InvoiceLineItem


def demo_mode_enabled() -> bool:
    from app.config import get_settings

    return bool(get_settings().demo_mode)


def enable_demo_mode() -> None:
    import os

    from app.config import clear_settings_cache

    os.environ["DEMO_MODE"] = "1"
    clear_settings_cache()


def demo_extract_invoice(raw_text: str) -> ExtractedInvoice:
    """Heuristic extraction for the three sample invoices (and similar text)."""
    text = raw_text
    lower = text.lower()

    vendor = "Unknown Vendor"
    for name in (
        "Meridian Office Supply",
        "Cascade Industrial Parts",
        "Northwind Components",
    ):
        if name.lower() in lower:
            vendor = name
            break

    amount = _find_total(text)
    inv_date = _find_date(text) or date(2026, 7, 7)

    # Line items: pull ".... $1,234.56" style tails when present
    line_items: list[InvoiceLineItem] = []
    for match in re.finditer(
        r"^.*?\$\s*([\d,]+(?:\.\d{2})?)\s*$",
        text,
        flags=re.MULTILINE,
    ):
        desc = match.group(0)
        if re.search(r"subtotal|tax|total|amount due|freight", desc, re.I):
            continue
        amt = float(match.group(1).replace(",", ""))
        if amt <= 0 or amt >= amount:
            continue
        label = re.sub(r"\$\s*[\d,]+\.\d{2}\s*$", "", desc).strip(" .-")
        if len(label) > 3:
            line_items.append(InvoiceLineItem(description=label[:120], amount=amt))

    if not line_items:
        line_items = [InvoiceLineItem(description="Invoice total", amount=amount)]

    return ExtractedInvoice(
        vendor_name=vendor,
        invoice_amount=amount,
        currency="USD",
        invoice_date=inv_date,
        line_items=line_items[:8],
        confidence=0.85,
    )


def _find_total(text: str) -> float:
    patterns = [
        r"(?:TOTAL DUE|AMOUNT DUE|TOTAL)\s*[:.]?\s*\$?\s*([\d,]+(?:\.\d{2})?)",
        r"TOTAL:\s*\$?\s*([\d,]+(?:\.\d{2})?)",
    ]
    for pat in patterns:
        matches = re.findall(pat, text, flags=re.IGNORECASE)
        if matches:
            return float(matches[-1].replace(",", ""))
    # Fallback: largest money-looking number
    nums = [float(n.replace(",", "")) for n in re.findall(r"\$\s*([\d,]+\.\d{2})", text)]
    if not nums:
        raise ValueError("demo_extract_invoice: could not find an invoice total")
    return max(nums)


def _find_date(text: str) -> date | None:
    # e.g. July 7, 2026
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})",
        text,
        re.I,
    )
    if m:
        months = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        return date(int(m.group(3)), months[m.group(1).lower()], int(m.group(2)))
    # ISO / US numeric: 2026-03-15 or 03/15/2026
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    return None
