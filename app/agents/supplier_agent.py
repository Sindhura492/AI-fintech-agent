"""Supplier-side negotiation agent node."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import _emit, _last_proposal, _llm
from app.agents.negotiation_state import NegotiationState
from app.core.schemas_negotiation import DisputeProposal
from app.observability.audit_events import emit_agent_message, emit_agent_thinking
from app.observability.console_logging import get_logger, truncate_for_log

logger = get_logger(__name__)


def supplier_agent(state: NegotiationState) -> dict:
    """Supplier LLM proposes a DisputeProposal for the disputed amount."""
    invoice = state["invoice"]
    po = state["po"]
    validation = state["validation_result"]
    round_number = state["round_number"]
    min_a, max_a = state["min_acceptable"], state["max_acceptable"]
    prior_buyer = _last_proposal(state.get("proposals") or [], "buyer")

    from app.intelligence.knowledge_graph import format_vendor_context_for_prompt
    from app.intelligence.rag_index import format_similar_disputes_for_prompt

    vendor_ctx = state.get("vendor_context") or {}
    kg_block = format_vendor_context_for_prompt(vendor_ctx) if vendor_ctx else (
        "VENDOR KNOWLEDGE GRAPH: no prior history on file."
    )
    rag_block = format_similar_disputes_for_prompt(
        list(state.get("similar_disputes") or [])
    )

    system = f"""You are the supplier-side negotiation agent for {invoice.vendor_name}.
You are negotiating a disputed invoice against the buyer's purchase order.

Invoice amount: ${invoice.invoice_amount:,.2f}
PO agreed amount ({po.po_id}): ${po.agreed_amount:,.2f}
Discrepancy: ${validation.discrepancy_amount:,.2f}
Validation reason: {validation.reason}
Policy band the buyer will enforce (you should stay inside it): ${min_a:,.2f} – ${max_a:,.2f}

{kg_block}

{rag_block}

Propose a settlement amount as DisputeProposal.
proposing_side must be "supplier".
round_number must be {round_number}.
Justify briefly why this amount is fair. Prefer converging toward the PO when possible,
but you may defend a portion of the invoice variance. Reference vendor graph history
and similar past disputes when they strengthen your position.
"""
    human = "Open the negotiation with your preferred settlement amount."
    if prior_buyer is not None:
        human = (
            f"The buyer last proposed ${prior_buyer.proposed_amount:,.2f}: "
            f"{prior_buyer.justification}\n"
            "Respond with your next supplier proposal (concede, hold, or meet them)."
        )

    emit_agent_thinking("supplier", round_number)

    logger.info(
        "[CLAUDE - SUPPLIER] Round %s: sending prompt...",
        round_number,
    )
    logger.info("[CLAUDE - SUPPLIER] system: %s", truncate_for_log(system, 300))
    logger.info("[CLAUDE - SUPPLIER] user: %s", truncate_for_log(human, 300))

    structured = _llm().with_structured_output(DisputeProposal, method="function_calling")
    raw = structured.invoke(
        [SystemMessage(content=system), HumanMessage(content=human)]
    )
    if isinstance(raw, DisputeProposal):
        proposal = raw
    else:
        proposal = DisputeProposal.model_validate(raw)

    proposal = proposal.model_copy(
        update={"proposing_side": "supplier", "round_number": round_number}
    )

    logger.info(
        "[CLAUDE - SUPPLIER] Proposed amount: %s",
        proposal.proposed_amount,
    )

    emit_agent_message(
        speaker="supplier",
        text=proposal.justification,
        round_number=round_number,
        amount=proposal.proposed_amount,
        verified=False,
    )

    audit = _emit(
        step_name="supplier_agent",
        step_type="llm",
        input_summary=(
            f"round={round_number} invoice=${invoice.invoice_amount:.2f} "
            f"po=${po.agreed_amount:.2f}"
        ),
        output_summary=(
            f"supplier proposed ${proposal.proposed_amount:.2f}: "
            f"{proposal.justification[:160]}"
        ),
        details={
            "round_number": round_number,
            "proposed_amount": proposal.proposed_amount,
            "proposing_side": "supplier",
        },
    )
    return {"proposals": [proposal], "audit_trail": audit}
