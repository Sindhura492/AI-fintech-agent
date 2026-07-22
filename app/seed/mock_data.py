from __future__ import annotations

from datetime import date

from app.core import GoodsReceipt, PurchaseOrder


PURCHASE_ORDERS: list[PurchaseOrder] = [
    # Clean match: invoice, PO, and GR all land on $4,850.00
    PurchaseOrder(
        po_id="PO-1001",
        vendor_name="Meridian Office Supply",
        agreed_amount=4850.00,
        agreed_date=date(2026, 5, 12),
    ),
    # Small discrepancy: PO/GR = $3,200; invoice will bill $3,264 (+2%)
    PurchaseOrder(
        po_id="PO-1002",
        vendor_name="Cascade Industrial Parts",
        agreed_amount=3200.00,
        agreed_date=date(2026, 6, 3),
    ),
    # Large discrepancy: PO/GR = $12,500; invoice will bill $14,750 (+18%)
    PurchaseOrder(
        po_id="PO-1003",
        vendor_name="Northwind Components",
        agreed_amount=12500.00,
        agreed_date=date(2026, 6, 20),
    ),
]


GOODS_RECEIPTS: list[GoodsReceipt] = [
    GoodsReceipt(
        po_id="PO-1001",
        received_amount=4850.00,
        received_date=date(2026, 6, 2),
    ),
    GoodsReceipt(
        po_id="PO-1002",
        received_amount=3200.00,
        received_date=date(2026, 6, 28),
    ),
    GoodsReceipt(
        po_id="PO-1003",
        received_amount=12500.00,
        received_date=date(2026, 7, 8),
    ),
]


VENDOR_HISTORY: dict[str, list[float]] = {
    "Meridian Office Supply": [
        3900.00,
        4100.00,
        4250.00,
        4520.00,
        4380.00,
        4850.00,
        3980.00,
        4700.00,
        4550.00,
        4850.00,
        4400.00,
        5100.00,
        4620.00,
        4780.00,
    ],
    "Cascade Industrial Parts": [
        2650.00,
        2800.00,
        2950.00,
        3150.00,
        3050.00,
        3200.00,
        2900.00,
        3300.00,
        3100.00,
        3250.00,
        3180.00,
        3020.00,
        3280.00,
    ],
    "Northwind Components": [
        11500.00,
        11800.00,
        12050.00,
        12200.00,
        12500.00,
        11950.00,
        12400.00,
        12100.00,
        12600.00,
        12350.00,
        12280.00,
        12480.00,
        12000.00,
        12550.00,
    ],
}


VENDOR_BILLING_CADENCE: dict[str, dict[str, int]] = {
    "Meridian Office Supply": {"typical_gap_days": 22, "days_since_last": 18},
    "Cascade Industrial Parts": {"typical_gap_days": 28, "days_since_last": 25},
    "Northwind Components": {"typical_gap_days": 20, "days_since_last": 45},
}


VENDOR_EMAILS: dict[str, str] = {
    "Meridian Office Supply": "billing@meridian-office.com",
    "Cascade Industrial Parts": "ar@cascade-parts.com",
    "Northwind Components": "invoices@northwind-components.com",
}


VENDOR_PAYMENT_TERMS: dict[str, dict[str, float | int]] = {
    "Meridian Office Supply": {
        "standard_payment_terms_days": 30,
        "early_payment_discount_rate": 0.02,  # 2/10 net 30 style
    },
    "Cascade Industrial Parts": {
        "standard_payment_terms_days": 30,
        "early_payment_discount_rate": 0.0,  # not eligible
    },
    "Northwind Components": {
        "standard_payment_terms_days": 45,
        "early_payment_discount_rate": 0.015,
    },
}


BUYER_PROFILE: dict[str, float | str] = {
    "name": "Contoso Procurement",
    "available_cash": 10000.00,  # enough for Meridian early pay; demo declines if raised
}



def get_purchase_orders() -> list[PurchaseOrder]:
    """Return all seed purchase orders."""
    return list(PURCHASE_ORDERS)


def get_goods_receipts() -> list[GoodsReceipt]:
    """Return all seed goods receipts."""
    return list(GOODS_RECEIPTS)


def get_vendor_history() -> dict[str, list[float]]:
    """Return vendor_name → recent invoice amounts (anomaly baseline)."""
    return {k: list(v) for k, v in VENDOR_HISTORY.items()}


def get_vendor_billing_cadence(vendor_name: str) -> dict[str, int]:
    """Typical gap + days since last invoice (for anomaly explanation prose)."""
    return dict(
        VENDOR_BILLING_CADENCE.get(
            vendor_name,
            {"typical_gap_days": 30, "days_since_last": 30},
        )
    )

def get_po_by_id(po_id: str) -> PurchaseOrder | None:
    """Look up a purchase order by PO id."""
    for po in PURCHASE_ORDERS:
        if po.po_id == po_id:
            return po
    return None


def get_receipts_for_po(po_id: str) -> list[GoodsReceipt]:
    """Return all goods receipts linked to a given PO."""
    return [gr for gr in GOODS_RECEIPTS if gr.po_id == po_id]


def get_vendor_amounts(vendor_name: str) -> list[float]:
    """Return past invoice amounts for a vendor, or [] if unknown."""
    return list(VENDOR_HISTORY.get(vendor_name, []))


def get_vendor_emails() -> dict[str, str]:
    """Return vendor_name → expected inbound sender email."""
    return dict(VENDOR_EMAILS)


def vendor_name_for_email(sender_email: str) -> str | None:
    """Resolve a sender address to a vendor_name via VENDOR_EMAILS."""
    needle = sender_email.strip().lower()
    if not needle:
        return None
    for vendor_name, expected in VENDOR_EMAILS.items():
        if expected.lower() == needle:
            return vendor_name
    return None


def normalize_vendor_name(name: str) -> str:
    """Lowercase + strip common legal suffixes for fuzzy vendor matching."""
    n = (name or "").strip().lower()
    for suffix in (
        " llc",
        " l.l.c.",
        " inc.",
        " inc",
        " ltd.",
        " ltd",
        " gmbh",
        " co.",
        " co",
        " corp.",
        " corp",
        " limited",
        " plc",
    ):
        if n.endswith(suffix):
            n = n[: -len(suffix)].rstrip(" ,.")
            break
    return " ".join(n.split())


def resolve_seed_vendor(vendor_name: str) -> str | None:
    """Map an extracted vendor string to a canonical seed vendor, if any."""
    needle = normalize_vendor_name(vendor_name)
    if not needle:
        return None
    # Exact normalized match against known seed vendors
    known = {po.vendor_name for po in PURCHASE_ORDERS} | set(VENDOR_HISTORY) | set(
        VENDOR_EMAILS
    )
    for name in known:
        if normalize_vendor_name(name) == needle:
            return name
    # Substring match either way.
    for name in known:
        canon = normalize_vendor_name(name)
        if needle in canon or canon in needle:
            return name
    return None


def open_pos_for_vendor(vendor_name: str) -> list[PurchaseOrder]:
    """Return open POs for a vendor (all seed POs are treated as open)."""
    resolved = resolve_seed_vendor(vendor_name) or vendor_name
    vendor_n = normalize_vendor_name(resolved)
    return [
        po
        for po in PURCHASE_ORDERS
        if normalize_vendor_name(po.vendor_name) == vendor_n
    ]


def get_vendor_payment_terms(vendor_name: str) -> dict[str, float | int] | None:
    """Return standard_payment_terms_days + early_payment_discount_rate for a vendor."""
    # Exact match first, then case-insensitive.
    if vendor_name in VENDOR_PAYMENT_TERMS:
        return dict(VENDOR_PAYMENT_TERMS[vendor_name])
    vendor_l = vendor_name.strip().lower()
    for name, terms in VENDOR_PAYMENT_TERMS.items():
        if name.lower() == vendor_l:
            return dict(terms)
    return None


def is_early_payment_eligible(vendor_name: str) -> bool:
    """True when vendor publishes a positive early-payment discount rate."""
    terms = get_vendor_payment_terms(vendor_name)
    if not terms:
        return False
    return float(terms.get("early_payment_discount_rate", 0)) > 0


def get_buyer_profile() -> dict[str, float | str]:
    """Return the buyer cash-position profile used by cash optimization."""
    return dict(BUYER_PROFILE)
