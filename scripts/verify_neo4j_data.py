from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import get_settings  # noqa: E402
from app.observability.console_logging import setup_logging  # noqa: E402


def _connect_driver():
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
        return None

    from neo4j import GraphDatabase

    connect_uri = uri
    if s.neo4j_trust_all:
        connect_uri = uri.replace("neo4j+s://", "neo4j+ssc://").replace(
            "bolt+s://", "bolt+ssc://"
        )
    driver = GraphDatabase.driver(connect_uri, auth=(user, password))
    driver.verify_connectivity()
    return driver


def _print_report(
    *,
    vendors: int,
    invoices: int,
    disputes: int,
    settlements: int,
    recent: list[dict],
    backend: str,
) -> None:
    print("=" * 64)
    print(f"NEO4J GRAPH VERIFICATION ({backend})")
    print("=" * 64)
    print(f"  Vendor nodes     : {vendors}")
    print(f"  Invoice nodes    : {invoices}")
    print(f"  Dispute nodes    : {disputes}")
    print(f"  Settlement nodes : {settlements}")
    print("-" * 64)
    print("  5 most recent Invoice transactions:")
    if not recent:
        print("    (none)")
    for row in recent:
        print(
            f"    • {row.get('updated_at')} | {row.get('vendor_name')} | "
            f"${row.get('amount')} | gate={row.get('gate_action')} | "
            f"matched={row.get('matched')} | id={row.get('id')}"
        )
    print("=" * 64)


def verify_aura() -> int:
    driver = _connect_driver()
    if driver is None:
        print("ERROR: Neo4j is not configured.")
        print("Set a real NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in .env")
        print("(placeholder YOUR_INSTANCE_ID URIs are treated as unset).")
        print("Or run: python scripts/verify_neo4j_data.py --demo-memory")
        return 1

    from app.intelligence.knowledge_graph.store_neo4j import (
        count_graph_nodes,
        recent_transactions,
    )

    try:
        counts = count_graph_nodes(driver)
        recent = recent_transactions(driver, limit=5)
    finally:
        driver.close()

    _print_report(
        vendors=counts["vendors"],
        invoices=counts["invoices"],
        disputes=counts["disputes"],
        settlements=counts["settlements"],
        recent=recent,
        backend="neo4j",
    )
    return 0


def verify_demo_memory() -> int:
    """Run two sample pipelines and dump in-memory graph counts."""
    from app.intelligence.knowledge_graph import get_knowledge_graph
    from app.pipeline.orchestrator import run_pipeline
    from app.seed.demo_mode import enable_demo_mode

    enable_demo_mode()
    kg = get_knowledge_graph()

    def snapshot() -> tuple[int, int, int, int]:
        m = kg._memory
        return (
            len(m.vendors),
            len(m.invoices),
            len(m.disputes),
            len(m.settlements),
        )

    before = snapshot()
    print(f"Before pipeline runs: invoices={before[1]} disputes={before[2]}")

    run_pipeline(str(ROOT / "sample_docs/invoice_po1001_clean.txt"), "PO-1001")
    mid = snapshot()
    print(f"After PO-1001 (approve): invoices={mid[1]} disputes={mid[2]}")

    run_pipeline(
        str(ROOT / "sample_docs/invoice_po1003_large_mismatch.txt"), "PO-1003"
    )
    after = snapshot()
    print(f"After PO-1003 (escalate): invoices={after[1]} disputes={after[2]}")

    # Idempotent re-run — invoice count must not grow
    run_pipeline(str(ROOT / "sample_docs/invoice_po1001_clean.txt"), "PO-1001")
    rerun = snapshot()
    print(f"After PO-1001 re-run (idempotent): invoices={rerun[1]}")
    if rerun[1] != after[1]:
        print("FAIL: re-run created a duplicate Invoice node")
        return 2

    m = kg._memory
    recent = sorted(
        m.invoices.values(),
        key=lambda i: i.get("updated_at") or "",
        reverse=True,
    )[:5]
    _print_report(
        vendors=rerun[0],
        invoices=rerun[1],
        disputes=rerun[2],
        settlements=rerun[3],
        recent=recent,
        backend=f"memory (source={kg.source})",
    )
    ctx = kg.get_vendor_context("Meridian Office Supply")
    print(f"GET /vendor-graph sample last_updated={ctx.get('last_updated')!r}")
    if after[1] <= before[1]:
        print("FAIL: invoice count did not increase after pipeline runs")
        return 2
    print("OK — counts increased;")
    return 0


def main() -> int:
    setup_logging()
    if "--demo-memory" in sys.argv:
        return verify_demo_memory()
    return verify_aura()


if __name__ == "__main__":
    raise SystemExit(main())
