"""Shared LLM and audit helpers for negotiation agents."""

from __future__ import annotations

from typing import Literal

from langchain_anthropic import ChatAnthropic

from app.observability.audit import write_audit_entry
from app.config import get_settings
from app.core.schemas_audit import AuditEntry
from app.core.schemas_negotiation import DisputeProposal

NEGOTIATION_TEMPERATURE = 0.2


def _llm() -> ChatAnthropic:
    s = get_settings()
    if not s.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return ChatAnthropic(
        model=s.anthropic_model,
        temperature=NEGOTIATION_TEMPERATURE,
        api_key=s.anthropic_api_key,
        max_retries=1,
    )


def _emit(
    step_name: str,
    step_type: Literal["llm", "deterministic", "ml"],
    input_summary: str,
    output_summary: str,
    details: dict[str, str | int | float | bool | None] | None = None,
) -> list[AuditEntry]:
    """Write + return a one-item audit list for the state reducer."""
    entry = write_audit_entry(
        step_name=step_name,
        step_type=step_type,
        input_summary=input_summary,
        output_summary=output_summary,
        details=details,
    )
    return [entry]


def _amounts_equal(a: float, b: float) -> bool:
    from app.agents.bounds import AMOUNT_EQ_TOLERANCE

    return abs(a - b) <= AMOUNT_EQ_TOLERANCE


def _last_proposal(
    proposals: list[DisputeProposal], side: Literal["buyer", "supplier"]
) -> DisputeProposal | None:
    for prop in reversed(proposals):
        if prop.proposing_side == side:
            return prop
    return None
