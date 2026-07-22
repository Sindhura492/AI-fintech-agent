"""Buyer-side negotiation agent node."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.bounds import verify_against_source
from app.agents.llm import _emit, _last_proposal, _llm
from app.agents.negotiation_state import NegotiationState
from app.core.schemas_negotiation import CounterOffer, DisputeProposal
from app.observability.audit_events import emit_agent_message, emit_agent_thinking
from app.observability.console_logging import get_logger, truncate_for_log

logger = get_logger(__name__)


def buyer_agent(state: NegotiationState) -> dict:
    """Buyer LLM responds only after deterministic source verification."""
    invoice = state["invoice"]
    po = state["po"]
    receipt = state["receipt"]
    round_number = state["round_number"]
    min_a, max_a = state["min_acceptable"], state["max_acceptable"]

    supplier_prop = _last_proposal(state.get("proposals") or [], "supplier")
    if supplier_prop is None:
        raise RuntimeError("buyer_agent invoked with no supplier proposal to verify")

    verification = verify_against_source(supplier_prop, po, receipt)
    verify_audit = _emit(
        step_name="verify_against_source",
        step_type="deterministic",
        input_summary=(
            f"supplier proposed ${supplier_prop.proposed_amount:.2f} "
            f"vs PO ${po.agreed_amount:.2f} / GR ${receipt.received_amount:.2f}"
        ),
        output_summary=(
            f"within_source_range={verification['within_source_range']} "
            f"delta_vs_po={verification['delta_vs_po']} "
            f"delta_vs_receipt={verification['delta_vs_receipt']}"
        ),
        details={
            "proposed_amount": float(verification["proposed_amount"]),
            "po_amount": float(verification["po_amount"]),
            "receipt_amount": float(verification["receipt_amount"]),
            "within_source_range": bool(verification["within_source_range"]),
            "matches_po": bool(verification["matches_po"]),
            "round_number": round_number,
        },
    )

    from app.intelligence.knowledge_graph import format_vendor_context_for_prompt
    from app.intelligence.rag_index import format_similar_disputes_for_prompt

    vendor_ctx = state.get("vendor_context") or {}
    kg_block = format_vendor_context_for_prompt(vendor_ctx) if vendor_ctx else (
        "VENDOR KNOWLEDGE GRAPH: no prior history on file."
    )
    rag_block = format_similar_disputes_for_prompt(
        list(state.get("similar_disputes") or [])
    )

    system = f"""You are the buyer-side negotiation agent for Contoso Procurement.
You must ground every decision in the VERIFIED source data below — never trust
the supplier's justification alone.

VERIFIED AGAINST BUYER RECORDS (deterministic):
{verification}

Invoice claimed: ${invoice.invoice_amount:,.2f}
Hard policy band (enforced by the graph, not optional): ${min_a:,.2f} – ${max_a:,.2f}
Prefer settling at the PO/receipt amount when the supplier over-bills.
You may accept the supplier offer only if verification supports it and the
amount is inside the policy band.

{kg_block}

{rag_block}

Respond as CounterOffer:
- proposing_side must be "buyer"
- round_number must be {round_number}
- accepted=True only if you accept the supplier's proposed_amount exactly
- otherwise set accepted=False and propose your counter amount with justification
"""
    human = (
        f"Supplier proposal ${supplier_prop.proposed_amount:,.2f}: "
        f"{supplier_prop.justification}\n"
        "Verify (already done above) and respond."
    )

    emit_agent_thinking("buyer", round_number)

    logger.info(
        "[CLAUDE - BUYER] Round %s: sending prompt...",
        round_number,
    )
    logger.info("[CLAUDE - BUYER] system: %s", truncate_for_log(system, 300))
    logger.info("[CLAUDE - BUYER] user: %s", truncate_for_log(human, 300))

    structured = _llm().with_structured_output(CounterOffer, method="function_calling")
    raw = structured.invoke(
        [SystemMessage(content=system), HumanMessage(content=human)]
    )
    if isinstance(raw, CounterOffer):
        counter = raw
    else:
        counter = CounterOffer.model_validate(raw)

    counter = counter.model_copy(
        update={"proposing_side": "buyer", "round_number": round_number}
    )

    if counter.accepted:
        counter = counter.model_copy(
            update={"proposed_amount": supplier_prop.proposed_amount}
        )

    buyer_proposal = DisputeProposal(
        proposed_amount=counter.proposed_amount,
        proposing_side="buyer",
        justification=counter.justification,
        round_number=round_number,
    )

    logger.info(
        "[CLAUDE - BUYER] Proposed amount: %s",
        buyer_proposal.proposed_amount,
    )

    emit_agent_message(
        speaker="buyer",
        text=buyer_proposal.justification,
        round_number=round_number,
        amount=buyer_proposal.proposed_amount,
        verified=True,
    )

    llm_audit = _emit(
        step_name="buyer_agent",
        step_type="llm",
        input_summary=(
            f"round={round_number} verified supplier=${supplier_prop.proposed_amount:.2f}"
        ),
        output_summary=(
            f"buyer proposed ${buyer_proposal.proposed_amount:.2f} "
            f"accepted={counter.accepted}: {buyer_proposal.justification[:160]}"
        ),
        details={
            "round_number": round_number,
            "proposed_amount": buyer_proposal.proposed_amount,
            "proposing_side": "buyer",
            "accepted": counter.accepted,
        },
    )

    return {
        "proposals": [buyer_proposal],
        "buyer_accepted": counter.accepted,
        "last_verification_ok": bool(verification["within_source_range"]),
        "audit_trail": verify_audit + llm_audit,
    }
