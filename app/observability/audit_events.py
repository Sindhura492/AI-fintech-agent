from __future__ import annotations

from app.observability.audit import audit_log, get_session_id


def emit_agent_thinking(
    speaker: str,
    round_number: int,
    *,
    session_id: str | None = None,
) -> None:
    """Notify the UI that an agent is about to call the LLM (typing indicator)."""
    audit_log.publish_live(
        {
            "type": "agent_thinking",
            "speaker": speaker,
            "round_number": round_number,
        },
        session_id=session_id,
    )


def emit_agent_message(
    *,
    speaker: str,
    text: str,
    round_number: int,
    amount: float | None,
    verified: bool = False,
    session_id: str | None = None,
) -> None:
    """Push a chat bubble event for the negotiation UI."""
    audit_log.publish_live(
        {
            "type": "agent_message",
            "speaker": speaker,
            "text": text,
            "round_number": round_number,
            "amount": amount,
            "verified": verified,
        },
        session_id=session_id,
    )


def emit_settlement_banner(
    *,
    converged: bool,
    amount: float | None = None,
    session_id: str | None = None,
) -> None:
    """Show settlement / escalation banner under the chat."""
    audit_log.publish_live(
        {
            "type": "settlement_banner",
            "converged": converged,
            "amount": amount,
        },
        session_id=session_id,
    )

