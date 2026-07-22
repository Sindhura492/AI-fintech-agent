from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLE_DOCS = ROOT / "sample_docs"

# Anchor "today" so hist dates stay stable across runs.
TODAY = date(2026, 7, 22)

VENDORS = {
    "meridian": {
        "name": "Meridian Office Supply",
        "po_id": "PO-1001",
        "po_amount": 4850.00,
        "address": "448 Market Street, Suite 200\nPortland, OR 97201",
        "email": "billing@meridian-office.com",
        "terms": "Net 30",
        "lines_clean": [
            ("Ergonomic task chairs (qty 20)", 2400.00),
            ("Height-adjustable desks (qty 10)", 1850.00),
            ("Cable management kits (qty 30)", 600.00),
        ],
    },
    "cascade": {
        "name": "Cascade Industrial Parts",
        "po_id": "PO-1002",
        "po_amount": 3200.00,
        "address": "1200 River Road\nCleveland, OH 44113",
        "email": "ar@cascade-parts.com",
        "terms": "Net 30",
        "lines_clean": [
            ("Bearing assembly BA-440 (qty 40)", 1600.00),
            ("Hydraulic seal kit HS-12 (qty 80)", 960.00),
            ("Fastener assortment pack FA-9 (qty 20)", 640.00),
        ],
    },
    "northwind": {
        "name": "Northwind Components",
        "po_id": "PO-1003",
        "po_amount": 12500.00,
        "address": "8800 Innovation Drive\nAustin, TX 78758",
        "email": "invoices@northwind-components.com",
        "terms": "Net 45",
        "lines_clean": [
            ("Industrial sensor kits (qty 50)", 8750.00),
            ("PLC controller modules (qty 25)", 3750.00),
        ],
    },
}


@dataclass(frozen=True)
class InvoiceSpec:
    filename: str
    vendor_key: str
    inv_date: date
    kind: str  # clean | small | large
    inv_number: str


def _money(n: float) -> str:
    return f"${n:,.2f}"


def _month_day_year(d: date) -> str:
    months = (
        "January February March April May June July "
        "August September October November December"
    ).split()
    return f"{months[d.month - 1]} {d.day}, {d.year}"


def _scaled_lines(
    base_lines: list[tuple[str, float]],
    target_total: float,
) -> list[tuple[str, float]]:
    base_sum = sum(a for _, a in base_lines)
    if base_sum <= 0:
        return [("Invoice total", target_total)]
    scale = target_total / base_sum
    out: list[tuple[str, float]] = []
    running = 0.0
    for i, (desc, amt) in enumerate(base_lines):
        if i == len(base_lines) - 1:
            out.append((desc, round(target_total - running, 2)))
        else:
            scaled = round(amt * scale, 2)
            out.append((desc, scaled))
            running += scaled
    return out


def _amount_for(vendor_key: str, kind: str) -> float:
    po = float(VENDORS[vendor_key]["po_amount"])
    if kind == "clean":
        return round(po, 2)
    if kind == "small":
        return round(po * 1.02, 2)  # ~+2%
    if kind == "large":
        # Meridian/Cascade ~+15–20%; Northwind ~+18% (matches demo large)
        bump = 1.18 if vendor_key == "northwind" else 1.15
        return round(po * bump, 2)
    raise ValueError(kind)


def _write_pdf(path: Path, lines: list[str]) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 54
    c.setFont("Helvetica-Bold", 12)
    for i, line in enumerate(lines):
        if i == 0:
            c.setFont("Helvetica-Bold", 12)
        elif line.startswith("TOTAL") or line.startswith("AMOUNT DUE"):
            c.setFont("Helvetica-Bold", 10)
        else:
            c.setFont("Helvetica", 10)
        # ReportLab uses Latin-1 for standard fonts; keep ASCII-safe text.
        safe = line.encode("latin-1", errors="replace").decode("latin-1")
        c.drawString(50, y, safe[:110])
        y -= 14
        if y < 48:
            c.showPage()
            y = height - 54
            c.setFont("Helvetica", 10)
    c.save()


def render_invoice(spec: InvoiceSpec) -> Path:
    v = VENDORS[spec.vendor_key]
    amount = _amount_for(spec.vendor_key, spec.kind)
    line_items = _scaled_lines(list(v["lines_clean"]), amount)
    if spec.kind == "small" and spec.vendor_key == "cascade":
        # Keep freight-style surcharge visible like the demo sample.
        goods = float(v["po_amount"])
        freight = round(amount - goods, 2)
        line_items = list(v["lines_clean"]) + [("Freight / misc surcharge", freight)]

    body: list[str] = [
        f"INVOICE - {v['name']}",
        "",
        v["address"].split("\n")[0],
        v["address"].split("\n")[1] if "\n" in v["address"] else "",
        f"Email: {v['email']}",
        "",
        "Bill To: Contoso Procurement",
        "456 Enterprise Way, Redmond, WA 98052",
        "",
        f"Invoice Number:  {spec.inv_number}",
        f"Invoice Date:    {_month_day_year(spec.inv_date)}",
        f"PO Reference:    {v['po_id']}",
        f"Payment Terms:   {v['terms']}",
        "Currency:        USD",
        "",
        "Description                                         Amount",
        "-" * 58,
    ]
    for desc, amt in line_items:
        body.append(f"{desc:<48} {_money(amt):>9}")
    body.extend(
        [
            "-" * 58,
            f"{'Subtotal':<48} {_money(amount):>9}",
            f"{'Tax':<48} {'$0.00':>9}",
            f"{'TOTAL DUE':<48} {_money(amount):>9}",
            "",
            f"Kind: {spec.kind}  |  PO agreed {_money(float(v['po_amount']))}",
            f"Remit to: {v['email']}",
        ]
    )
    out = SAMPLE_DOCS / spec.filename
    _write_pdf(out, body)
    return out


def demo_specs() -> list[InvoiceSpec]:
    """Original three demo scenarios as PDFs (alongside existing .txt samples)."""
    return [
        InvoiceSpec(
            "invoice_po1001_clean.pdf",
            "meridian",
            date(2026, 7, 7),
            "clean",
            "INV-8841",
        ),
        InvoiceSpec(
            "invoice_po1002_small_mismatch.pdf",
            "cascade",
            date(2026, 7, 9),
            "small",
            "INV-2290",
        ),
        InvoiceSpec(
            "invoice_po1003_large_mismatch.pdf",
            "northwind",
            date(2026, 7, 17),
            "large",
            "INV-NWC-4417",
        ),
    ]


def hist_specs() -> list[InvoiceSpec]:
    """15 historical invoices: 5 per vendor, mixed kinds, ~6 months of dates."""
    # Days-ago offsets spanning ~Jan–Jul 2026 (relative to TODAY).
    schedule: list[tuple[str, str, int]] = [
        # Meridian
        ("meridian", "clean", 180),
        ("meridian", "clean", 150),
        ("meridian", "small", 120),
        ("meridian", "small", 75),
        ("meridian", "large", 40),
        # Cascade
        ("cascade", "clean", 170),
        ("cascade", "clean", 135),
        ("cascade", "small", 100),
        ("cascade", "small", 55),
        ("cascade", "large", 25),
        # Northwind
        ("northwind", "clean", 160),
        ("northwind", "small", 110),
        ("northwind", "clean", 85),
        ("northwind", "large", 60),
        ("northwind", "large", 15),
    ]
    specs: list[InvoiceSpec] = []
    for i, (vendor_key, kind, days_ago) in enumerate(schedule, start=1):
        inv_date = TODAY - timedelta(days=days_ago)
        specs.append(
            InvoiceSpec(
                filename=f"invoice_hist_{i:02d}.pdf",
                vendor_key=vendor_key,
                inv_date=inv_date,
                kind=kind,
                inv_number=f"INV-HIST-{i:04d}",
            )
        )
    return specs


def main() -> int:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("reportlab is required: pip install reportlab", file=sys.stderr)
        return 1

    SAMPLE_DOCS.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    print("Generating demo scenario PDFs…")
    for spec in demo_specs():
        path = render_invoice(spec)
        written.append(path)
        print(f"  {path.name}  {spec.kind:5s}  {VENDORS[spec.vendor_key]['name']}")

    print("Generating historical invoices (invoice_hist_01..15)…")
    for spec in hist_specs():
        path = render_invoice(spec)
        amount = _amount_for(spec.vendor_key, spec.kind)
        written.append(path)
        print(
            f"  {path.name}  {spec.inv_date.isoformat()}  "
            f"{spec.kind:5s}  {_money(amount):>10s}  "
            f"{VENDORS[spec.vendor_key]['name']}"
        )

    print("Generating edge-case unknown vendor…")
    path = write_unknown_vendor_pdf()
    written.append(path)
    print(f"  {path.name}  unknown vendor → expect NO_MATCHING_PO escalate")

    print(f"Done — wrote {len(written)} PDFs under {SAMPLE_DOCS}/")
    return 0


def write_unknown_vendor_pdf() -> Path:
    """Edge-case PDF: vendor not in seed POs → email path escalates NO_MATCHING_PO."""
    lines = [
        "INVOICE - Atlas Freight GmbH",
        "",
        "Hafenstrasse 12, 80331 Muenchen, Germany",
        "Email: ar@atlas-freight.example",
        "",
        "Bill To: Contoso Procurement",
        "456 Enterprise Way, Redmond, WA 98052",
        "",
        "Invoice Number:  INV-ATLAS-7734",
        "Invoice Date:    July 15, 2026",
        "PO Reference:    (none on file)",
        "Payment Terms:   Net 30",
        "Currency:        USD",
        "",
        "Description                                         Amount",
        "-" * 58,
        f"{'Freight Service (Berlin to Munich)':<48} {'$8,200.00':>9}",
        f"{'Fuel surcharge':<48} {'$1,100.00':>9}",
        "-" * 58,
        f"{'Subtotal':<48} {'$9,300.00':>9}",
        f"{'Tax':<48} {'$0.00':>9}",
        f"{'TOTAL DUE':<48} {'$9,300.00':>9}",
        "",
        "Kind: unknown_vendor  |  not in Contoso open PO list",
        "Remit to: ar@atlas-freight.example",
    ]
    out = SAMPLE_DOCS / "invoice_unknown_vendor.pdf"
    _write_pdf(out, lines)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
