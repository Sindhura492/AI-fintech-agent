from __future__ import annotations

from app.agents import (
    compute_bounds,
    run_cash_optimization,
    run_negotiation,
    within_bounds,
)
from app.core import (
    CashOptimizationProposal,
    ExtractedInvoice,
    GateDecision,
    GoodsReceipt,
    PurchaseOrder,
    Settlement,
    ValidationResult,
)
from app.observability.audit import get_session_id
from app.pipeline.anomaly_checks import run_anomaly_checks
from app.pipeline.enforcement import enforce, execute_payment
from app.pipeline.persist_outcomes import persist_pipeline_outcomes
from app.pipeline.pipeline_helpers import _audit, _timer
from app.pipeline.validation import three_way_match
from app.seed.mock_data import get_vendor_amounts, is_early_payment_eligible


def _run_match_validate_enforce(
    *,
    invoice: ExtractedInvoice,
    po: PurchaseOrder,
    receipt: GoodsReceipt,
) -> tuple[
    ValidationResult,
    dict[str, bool | float],
    Settlement,
    GateDecision,
    bool,
    CashOptimizationProposal | None,
]:
    """Shared path: three-way match → route → enforce → optional pay.

    Routing after validation:
      - discrepancy           → dispute negotiation
      - clean + discount-eligible → cash optimization negotiation
      - clean + not eligible  → straight to enforcement
    """
    with _timer() as t:
        validation = three_way_match(invoice, po, receipt)
    _audit(
        "three_way_match",
        "deterministic",
        (
            f"invoice=${invoice.invoice_amount:.2f} po=${po.agreed_amount:.2f} "
            f"gr=${receipt.received_amount:.2f}"
        ),
        (
            f"matched={validation.matched} discrepancy=${validation.discrepancy_amount:.2f} "
            f"— {validation.reason}"
        ),
        duration_ms=t["ms"],
        matched=validation.matched,
        discrepancy_amount=validation.discrepancy_amount,
    )

    history = get_vendor_amounts(invoice.vendor_name)
    anomaly = run_anomaly_checks(invoice, po, history)

    cash_opt: CashOptimizationProposal | None = None
    eligible = is_early_payment_eligible(invoice.vendor_name)

    if not validation.matched:
        route = "dispute_negotiation"
        _audit(
            "route_decision",
            "deterministic",
            "three_way_match matched=False",
            "Route → dispute negotiation (amount discrepancy)",
            route=route,
            matched=False,
            discount_eligible=eligible,
        )

        from app.intelligence.knowledge_graph import get_knowledge_graph, publish_vendor_context
        from app.intelligence.rag_index import query_similar_disputes

        kg = get_knowledge_graph()
        with _timer() as t:
            vendor_context = kg.get_vendor_context(invoice.vendor_name)
        # knowledge_graph_read already audited inside get_vendor_context
        publish_vendor_context(vendor_context)
        with _timer() as t_rag:
            similar = query_similar_disputes(invoice)
        # rag_similar_disputes already audited inside query_similar_disputes
        _ = t_rag

        _audit(
            "negotiation_start",
            "deterministic",
            f"discrepancy=${validation.discrepancy_amount:.2f}",
            "invoking buyer/supplier dispute LangGraph",
            discrepancy_amount=validation.discrepancy_amount,
        )
        with _timer() as t:
            settlement, _neg_audit = run_negotiation(
                invoice=invoice,
                po=po,
                receipt=receipt,
                validation=validation,
                max_rounds=3,
                vendor_context=vendor_context,
                similar_disputes=similar,
            )
        _audit(
            "negotiation_complete",
            "deterministic",
            "LangGraph finished",
            (
                f"final_amount=${settlement.final_amount:.2f} "
                f"agreed_by_both={settlement.agreed_by_both} "
                f"within_bounds={settlement.within_bounds}"
            ),
            duration_ms=t["ms"],
            final_amount=settlement.final_amount,
            agreed_by_both=settlement.agreed_by_both,
            within_bounds=settlement.within_bounds,
            negotiated=True,
        )
    elif eligible:
        route = "cash_optimization"
        _audit(
            "route_decision",
            "deterministic",
            "three_way_match matched=True + early-payment eligible",
            "Route → cash optimization negotiation",
            route=route,
            matched=True,
            discount_eligible=True,
        )
        with _timer() as t:
            cash_opt, _cash_audit = run_cash_optimization(invoice)
            if cash_opt.accepted:
                settlement = Settlement(
                    final_amount=cash_opt.net_payable,
                    agreed_by_both=True,
                    within_bounds=True,
                )
            else:
                settlement = Settlement(
                    final_amount=invoice.invoice_amount,
                    agreed_by_both=True,
                    within_bounds=True,
                )
        _audit(
            "cash_optimization_complete",
            "deterministic",
            (
                f"rate={cash_opt.discount_rate} "
                f"discount=${cash_opt.discount_amount:.2f} "
                f"net=${cash_opt.net_payable:.2f}"
            ),
            (
                f"accepted={cash_opt.accepted} → settlement "
                f"${settlement.final_amount:.2f} — {cash_opt.reasoning[:160]}"
            ),
            duration_ms=t["ms"],
            accepted=cash_opt.accepted,
            final_amount=settlement.final_amount,
            discount_amount=cash_opt.discount_amount,
            net_payable=cash_opt.net_payable,
        )
    else:
        route = "straight_to_enforcement"
        _audit(
            "route_decision",
            "deterministic",
            "three_way_match matched=True + not discount-eligible",
            "Route → straight to enforcement gate (no negotiation)",
            route=route,
            matched=True,
            discount_eligible=False,
        )
        with _timer() as t:
            min_a, max_a = compute_bounds(po)
            in_bounds = within_bounds(invoice.invoice_amount, min_a, max_a)
            settlement = Settlement(
                final_amount=invoice.invoice_amount,
                agreed_by_both=True,
                within_bounds=in_bounds,
            )
        _audit(
            "settlement_fast_path",
            "deterministic",
            "clean match, no early-payment discount on file",
            (
                f"Settlement ${settlement.final_amount:.2f} "
                f"agreed_by_both=True within_bounds={in_bounds}"
            ),
            duration_ms=t["ms"],
            final_amount=settlement.final_amount,
            within_bounds=in_bounds,
            negotiated=False,
        )

    with _timer() as t:
        decision = enforce(settlement, validation)
    _audit(
        "enforce",
        "deterministic",
        (
            f"settlement=${settlement.final_amount:.2f} "
            f"agreed={settlement.agreed_by_both} bounds={settlement.within_bounds}"
        ),
        f"action={decision.action} rule_fired={decision.rule_fired} — {decision.reason}",
        duration_ms=t["ms"],
        action=decision.action,
        rule_fired=decision.rule_fired,
        final_amount=settlement.final_amount,
    )

    payment_executed = False
    if decision.action == "approve":
        execute_payment(settlement, decision)
        payment_executed = True
        _audit(
            "execute_payment",
            "deterministic",
            f"GateDecision.action=approve amount=${settlement.final_amount:.2f}",
            f"PAYMENT EXECUTED: {settlement.final_amount}",
            payment_executed=True,
            amount=settlement.final_amount,
        )
    else:
        _audit(
            "execute_payment_skipped",
            "deterministic",
            f"GateDecision.action={decision.action}",
            "payment not executed — gate did not approve",
            payment_executed=False,
            action=decision.action,
        )
        if decision.action == "escalate":
            from app.human_loop.escalations import escalation_store

            escalation_store.register(
                vendor_name=invoice.vendor_name,
                amount=settlement.final_amount,
                decision=decision,
                settlement=settlement,
                po_id=po.po_id,
            )

    _audit(
        "pipeline_complete",
        "deterministic",
        f"session_id={get_session_id()}",
        f"final action={decision.action} payment_executed={payment_executed}",
        action=decision.action,
        payment_executed=payment_executed,
    )

    persist_pipeline_outcomes(
        invoice=invoice,
        po=po,
        validation=validation,
        settlement=settlement,
        decision=decision,
    )

    return validation, anomaly, settlement, decision, payment_executed, cash_opt
