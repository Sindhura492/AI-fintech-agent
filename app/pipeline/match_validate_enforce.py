from __future__ import annotations

from app.agents import (
    compute_bounds,
    run_cash_optimization,
    run_negotiation,
    within_bounds,
)
from app.agents.bounds import outside_historical_range
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
            f"- {validation.reason}"
        ),
        duration_ms=t["ms"],
        matched=validation.matched,
        discrepancy_amount=validation.discrepancy_amount,
    )

    history = get_vendor_amounts(invoice.vendor_name)
    anomaly = run_anomaly_checks(invoice, po, history)

    # ML anomaly blocks negotiation/payment until human clears it.
    from app.human_loop.review_queue import anomaly_review_queue
    from app.observability.audit import audit_log

    sid = get_session_id()
    pending_anom = anomaly_review_queue.get(sid) if sid else None
    if pending_anom is not None and pending_anom.status == "pending_review":
        _audit(
            "anomaly_hold",
            "deterministic",
            f"vendor={invoice.vendor_name} amount=${invoice.invoice_amount:.2f}",
            "pipeline paused - waiting for human approve/deny on ML anomaly",
            anomaly_score=pending_anom.anomaly_score,
        )
        audit_log.publish_live(
            {
                "type": "anomaly_hold",
                "kind": "anomaly",
                "session_id": sid,
                "vendor_name": pending_anom.vendor_name,
                "amount": pending_anom.amount,
                "anomaly_score": pending_anom.anomaly_score,
                "explanation": pending_anom.explanation,
                "status": "pending_review",
            },
            session_id=sid,
        )
        while True:
            item = anomaly_review_queue.wait_until_resolved(sid, timeout=5.0)
            if item is not None and item.status != "pending_review":
                break

        if item is not None and item.status == "denied":
            min_a, max_a = compute_bounds(po)
            settlement = Settlement(
                final_amount=invoice.invoice_amount,
                agreed_by_both=False,
                within_bounds=within_bounds(invoice.invoice_amount, min_a, max_a),
            )
            decision = GateDecision(
                action="deny",
                reason="human confirmed ML anomaly - payment blocked",
                rule_fired="ANOMALY_HUMAN_DENIED",
            )
            _audit(
                "anomaly_blocked_pipeline",
                "deterministic",
                f"session_id={sid}",
                "human denied anomaly - skipping negotiation and payment",
                action=decision.action,
                rule_fired=decision.rule_fired,
            )
            _audit(
                "pipeline_complete",
                "deterministic",
                f"session_id={sid}",
                f"final action={decision.action} payment_executed=False",
                action=decision.action,
                payment_executed=False,
            )
            persist_pipeline_outcomes(
                invoice=invoice,
                po=po,
                validation=validation,
                settlement=settlement,
                decision=decision,
            )
            return validation, anomaly, settlement, decision, False, None

        _audit(
            "anomaly_cleared",
            "deterministic",
            f"session_id={sid}",
            "human cleared anomaly - resuming negotiation / enforcement",
        )

    # Publish vendor history for UI.
    vendor_context: dict = {}
    try:
        from app.intelligence.knowledge_graph import get_knowledge_graph, publish_vendor_context

        vendor_context = get_knowledge_graph().get_vendor_context(invoice.vendor_name)
        publish_vendor_context(vendor_context)
    except Exception:  # noqa: BLE001
        vendor_context = {}

    cash_opt: CashOptimizationProposal | None = None
    eligible = is_early_payment_eligible(invoice.vendor_name)

    out_hist, hist_band = outside_historical_range(
        invoice.invoice_amount,
        vendor_context,
        po_amount=po.agreed_amount,
        receipt_amount=receipt.received_amount,
    )
    from app.agents.bounds import has_favorable_precedent

    favorable = has_favorable_precedent(
        vendor_context,
        invoice.invoice_amount,
        po_amount=po.agreed_amount,
    )
    # Negotiate on discrepancy, or on true outliers with no favorable precedent.
    needs_negotiation = (not validation.matched) or (out_hist and not favorable)
    if hist_band is not None:
        _audit(
            "historical_settlement_check",
            "deterministic",
            (
                f"invoice=${invoice.invoice_amount:.2f} "
                f"vendor_history_n={int(hist_band['n'])}"
            ),
            (
                f"outside_history={out_hist} "
                f"band=${float(hist_band['min']):.2f}-${float(hist_band['max']):.2f} "
                f"(past agreed raw "
                f"${float(hist_band['raw_min']):.2f}-${float(hist_band['raw_max']):.2f})"
            ),
            outside_history=out_hist,
            hist_min=float(hist_band["min"]),
            hist_max=float(hist_band["max"]),
            hist_n=int(hist_band["n"]),
        )

    # Negotiate when three-way fails OR amount is unlike past accepted settlements.
    needs_negotiation = (not validation.matched) or out_hist

    if needs_negotiation:
        route = (
            "dispute_negotiation"
            if not validation.matched
            else "history_outlier_negotiation"
        )
        _audit(
            "route_decision",
            "deterministic",
            (
                "three_way_match matched=False"
                if not validation.matched
                else "invoice outside vendor historical settlement range"
            ),
            (
                "Route → dispute negotiation (amount discrepancy)"
                if not validation.matched
                else "Route → negotiation (unlike past accepted settlements)"
            ),
            route=route,
            matched=validation.matched,
            outside_history=out_hist,
            discount_eligible=eligible,
        )

        from app.intelligence.knowledge_graph import get_knowledge_graph, publish_vendor_context
        from app.intelligence.rag_index import query_similar_disputes

        kg = get_knowledge_graph()
        with _timer() as t:
            if not vendor_context:
                vendor_context = kg.get_vendor_context(invoice.vendor_name)
                publish_vendor_context(vendor_context)
        with _timer() as t_rag:
            similar = query_similar_disputes(invoice)
        _ = t_rag

        _audit(
            "negotiation_start",
            "deterministic",
            f"discrepancy=${validation.discrepancy_amount:.2f} outside_history={out_hist}",
            "invoking buyer/supplier dispute LangGraph",
            discrepancy_amount=validation.discrepancy_amount,
            outside_history=out_hist,
        )
        with _timer() as t:
            settlement, _neg_audit = run_negotiation(
                invoice=invoice,
                po=po,
                receipt=receipt,
                validation=validation,
                max_rounds=5,
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
                f"${settlement.final_amount:.2f} - {cash_opt.reasoning[:160]}"
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
        decision = enforce(
            settlement,
            validation,
            vendor_context=vendor_context,
            po_amount=po.agreed_amount,
            receipt_amount=receipt.received_amount,
            invoice_amount=invoice.invoice_amount,
            vendor_name=invoice.vendor_name,
            cash_opt=cash_opt,
        )
    _audit(
        "enforce",
        "deterministic",
        (
            f"settlement=${settlement.final_amount:.2f} "
            f"agreed={settlement.agreed_by_both} bounds={settlement.within_bounds}"
        ),
        f"action={decision.action} rule_fired={decision.rule_fired} - {decision.reason}",
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
        try:
            from app.human_loop.notifications import notify_auto_approved

            notify_auto_approved(
                vendor_name=invoice.vendor_name,
                amount=settlement.final_amount,
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        _audit(
            "execute_payment_skipped",
            "deterministic",
            f"GateDecision.action={decision.action}",
            "payment not executed - gate did not approve",
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
                invoice=invoice,
                po=po,
                validation=validation,
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
