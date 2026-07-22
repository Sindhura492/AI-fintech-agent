
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.observability.console_logging import setup_logging  # noqa: E402

setup_logging()

if "--demo" in sys.argv:
    from app.seed.demo_mode import enable_demo_mode

    enable_demo_mode()
    print("DEMO_MODE=1 — using stub extraction/negotiation (no Anthropic calls)")

from app.seed.demo_mode import demo_mode_enabled  # noqa: E402
from app.pipeline.orchestrator import run_pipeline  # noqa: E402

SAMPLE_DOCS = ROOT / "sample_docs"

SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "1. Clean match (PO-1001)",
        "file": SAMPLE_DOCS / "invoice_po1001_clean.txt",
        "po_id": "PO-1001",
        "expect": "Clean match → cash optimization (2% early pay) → APPROVE",
    },
    {
        "name": "2. Small discrepancy (PO-1002)",
        "file": SAMPLE_DOCS / "invoice_po1002_small_mismatch.txt",
        "po_id": "PO-1002",
        "expect": "Negotiate → settle within PO ±5% → APPROVE",
    },
    {
        "name": "3. Large discrepancy (PO-1003)",
        "file": SAMPLE_DOCS / "invoice_po1003_large_mismatch.txt",
        "po_id": "PO-1003",
        "expect": "Escalate (no convergence / over $5k) OR DENY (OOB) — never approve",
    },
]


def _trace_names(result: dict[str, Any]) -> list[str]:
    return [e.get("step_name", "") for e in result.get("trace") or []]


def _negotiated(result: dict[str, Any]) -> bool:
    names = _trace_names(result)
    return "negotiation_start" in names or "negotiation_complete" in names


def _fast_path(result: dict[str, Any]) -> bool:
    return "settlement_fast_path" in _trace_names(result)


def _cash_optimized(result: dict[str, Any]) -> bool:
    names = _trace_names(result)
    return "cash_optimization_start" in names or "cash_optimization_complete" in names


def check_clean(result: dict[str, Any]) -> tuple[bool, list[str]]:
    checks: list[str] = []
    ok = True
    val = result.get("validation") or {}
    dec = result.get("decision") or {}
    settlement = result.get("settlement") or {}
    cash = result.get("cash_optimization") or {}

    if val.get("matched") is True:
        checks.append("PASS  three_way_match.matched == True")
    else:
        checks.append(f"FAIL  expected matched=True, got {val.get('matched')}")
        ok = False

    if _cash_optimized(result) and not _negotiated(result):
        checks.append("PASS  cash optimization route (clean + discount-eligible)")
        if cash.get("accepted") is True:
            checks.append(
                f"PASS  early pay accepted "
                f"(net=${cash.get('net_payable')}, rate={cash.get('discount_rate')})"
            )
        else:
            checks.append(
                f"FAIL  expected early-pay accept, got accepted={cash.get('accepted')}"
            )
            ok = False
    elif _fast_path(result) and not _negotiated(result):
        checks.append("PASS  settlement_fast_path (not discount-eligible)")
    else:
        checks.append(
            f"FAIL  expected cash-opt or fast path "
            f"(cash={_cash_optimized(result)}, fast={_fast_path(result)}, "
            f"dispute={_negotiated(result)})"
        )
        ok = False

    if dec.get("action") == "approve":
        checks.append(
            f"PASS  gate APPROVE (rule_fired={dec.get('rule_fired')})"
        )
    else:
        checks.append(
            f"FAIL  expected approve, got {dec.get('action')} "
            f"({dec.get('rule_fired')}: {dec.get('reason')})"
        )
        ok = False

    if result.get("payment_executed") is True:
        checks.append("PASS  payment executed")
    else:
        checks.append("FAIL  payment was not executed")
        ok = False

    if settlement.get("agreed_by_both") is True:
        checks.append("PASS  settlement.agreed_by_both")
    else:
        checks.append("FAIL  settlement.agreed_by_both expected True")
        ok = False

    return ok, checks


def check_small(result: dict[str, Any]) -> tuple[bool, list[str]]:
    checks: list[str] = []
    ok = True
    val = result.get("validation") or {}
    dec = result.get("decision") or {}
    settlement = result.get("settlement") or {}

    if val.get("matched") is False:
        checks.append(
            f"PASS  discrepancy detected "
            f"(${val.get('discrepancy_amount')})"
        )
    else:
        checks.append("FAIL  expected matched=False for small mismatch")
        ok = False

    if _negotiated(result) and not _fast_path(result):
        checks.append("PASS  negotiation graph ran")
    else:
        checks.append("FAIL  expected negotiation (not fast path)")
        ok = False

    if settlement.get("within_bounds") is True:
        checks.append(
            f"PASS  settlement within bounds "
            f"(${settlement.get('final_amount')})"
        )
    else:
        checks.append(
            f"FAIL  expected within_bounds=True, "
            f"got {settlement.get('within_bounds')} "
            f"amount=${settlement.get('final_amount')}"
        )
        ok = False

    if settlement.get("agreed_by_both") is True:
        checks.append("PASS  agents converged (agreed_by_both)")
    else:
        checks.append(
            "FAIL  expected agents to converge within max_rounds"
        )
        ok = False

    if dec.get("action") == "approve":
        checks.append(
            f"PASS  gate APPROVE (rule_fired={dec.get('rule_fired')})"
        )
    else:
        checks.append(
            f"FAIL  expected approve after in-bounds settlement, "
            f"got {dec.get('action')} ({dec.get('rule_fired')})"
        )
        ok = False

    if result.get("payment_executed") is True:
        checks.append("PASS  payment executed")
    else:
        checks.append("FAIL  payment was not executed")
        ok = False

    return ok, checks


def check_large(result: dict[str, Any]) -> tuple[bool, list[str]]:
    checks: list[str] = []
    ok = True
    val = result.get("validation") or {}
    dec = result.get("decision") or {}
    action = dec.get("action")
    rule = dec.get("rule_fired")

    if val.get("matched") is False:
        checks.append(
            f"PASS  large discrepancy flagged "
            f"(${val.get('discrepancy_amount')})"
        )
    else:
        checks.append("FAIL  expected matched=False")
        ok = False

    if _negotiated(result):
        checks.append("PASS  negotiation attempted")
    else:
        checks.append("FAIL  expected negotiation for large discrepancy")
        ok = False


    if action == "approve":
        checks.append(
            f"FAIL  gate must not approve large dispute "
            f"(got approve / {rule})"
        )
        ok = False
    elif action == "escalate":
        checks.append(
            f"PASS  gate ESCALATE (rule_fired={rule}) — {dec.get('reason')}"
        )
    elif action == "deny":
        checks.append(
            f"PASS  gate DENY (rule_fired={rule}) — {dec.get('reason')}"
        )
    else:
        checks.append(f"FAIL  unexpected action={action!r}")
        ok = False

    if result.get("payment_executed") is False:
        checks.append("PASS  payment blocked (chokepoint held)")
    else:
        checks.append("FAIL  payment must not execute on escalate/deny")
        ok = False

    return ok, checks


CHECKS: list[Callable[[dict[str, Any]], tuple[bool, list[str]]]] = [
    check_clean,
    check_small,
    check_large,
]


def _banner(text: str, char: str = "=") -> None:
    print()
    print(char * 72)
    print(text)
    print(char * 72)


def main() -> int:
    mode = "DEMO (offline stubs)" if demo_mode_enabled() else "LIVE (Anthropic API)"
    _banner(f"DISPUTE RESOLVER — SCENARIO DEMO [{mode}]")
    print("Running 3 invoices through sandbox → extract → match → "
          "(negotiate) → enforce → pay")
    print(f"Sample docs: {SAMPLE_DOCS}")
    if not demo_mode_enabled():
        print("Tip: if Anthropic credits are empty, re-run with:  python run_scenarios.py --demo")

    results_summary: list[tuple[str, bool]] = []

    for scenario, checker in zip(SCENARIOS, CHECKS):
        name = scenario["name"]
        path: Path = scenario["file"]
        po_id: str = scenario["po_id"]

        _banner(name, "-")
        print(f"Expect : {scenario['expect']}")
        print(f"File   : {path.name}")
        print(f"PO     : {po_id}")
        print()

        if not path.exists():
            print(f"FAIL  missing file: {path}")
            results_summary.append((name, False))
            continue

        try:
            print("… running pipeline (LLM calls may take a bit) …")
            result = run_pipeline(str(path), po_id)
        except Exception as exc:
            print(f"FAIL  pipeline raised {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results_summary.append((name, False))
            continue

        decision = result.get("decision") or {}
        settlement = result.get("settlement") or {}
        print(
            f"Decision : {decision.get('action')} "
            f"| rule={decision.get('rule_fired')} "
            f"| {decision.get('reason')}"
        )
        print(
            f"Settlement: ${settlement.get('final_amount')} "
            f"agreed={settlement.get('agreed_by_both')} "
            f"within_bounds={settlement.get('within_bounds')}"
        )
        print(f"Payment  : executed={result.get('payment_executed')}")
        print(f"Session  : {result.get('session_id')}")
        print()

        passed, checks = checker(result)
        for line in checks:
            print(f"  {line}")

        results_summary.append((name, passed))
        print()
        print(">>> " + ("PASS" if passed else "FAIL") + f" — {name}")

    _banner("SUMMARY")
    all_ok = True
    for name, passed in results_summary:
        mark = "PASS" if passed else "FAIL"
        if not passed:
            all_ok = False
        print(f"  [{mark}]  {name}")

    print()
    if all_ok:
        print("All scenarios passed — enforcement gate behaved correctly.")
        return 0

    print("One or more scenarios failed — see details above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
