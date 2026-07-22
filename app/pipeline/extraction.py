from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from app.config import get_settings
from app.core import ExtractedInvoice
from app.observability.console_logging import get_logger, truncate_for_log
from app.seed.demo_mode import demo_extract_invoice, demo_mode_enabled

logger = get_logger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-5"
EXTRACTION_TEMPERATURE = 0.1

_SYSTEM_PROMPT = """\
You are an accounts-payable extraction engine.
Extract invoice fields from LlamaParse markdown (or plain text) into the
ExtractedInvoice schema. Prefer structured markdown tables and headings when
present — they are more reliable than raw dumped PDF text.

Rules:
- vendor_name: the supplier / vendor legal or trade name.
- invoice_amount: the total amount due (numeric, no currency symbols).
- currency: ISO 4217 code (e.g. USD). Default to USD if clearly US dollars but code omitted.
- invoice_date: the invoice issue date (ISO date).
- line_items: each billed line with description and amount; omit tax/total rollups.
- confidence: your confidence in the extraction from 0.0 to 1.0.

If a field is ambiguous, choose the best-supported value and lower confidence.
Do not invent line items that are not present in the text.
"""

_CORRECTION_PROMPT = """\
Your previous extraction failed schema validation. Fix the output so it
strictly matches the ExtractedInvoice schema.

Validation error:
{error}

Re-extract from the same document. Return only valid structured fields.
"""


class InvoiceExtractionError(Exception):
    """Raised when Claude cannot produce a valid ExtractedInvoice."""


def get_anthropic_client() -> ChatAnthropic:
    """Return ChatAnthropic configured for low-temperature extraction."""
    s = get_settings()
    if not s.anthropic_api_key:
        raise InvoiceExtractionError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return ChatAnthropic(
        model=s.anthropic_model or DEFAULT_MODEL,
        temperature=EXTRACTION_TEMPERATURE,
        api_key=s.anthropic_api_key,
        max_retries=1,
    )


def _structured_extractor() -> Runnable:
    """Bind ExtractedInvoice as a tool/schema so bad output fails cleanly."""
    llm = get_anthropic_client()
    return llm.with_structured_output(
        ExtractedInvoice,
        method="function_calling",
    )


def _log_prompts(system: str, user: str) -> None:
    logger.info("[CLAUDE - EXTRACTION] Sending prompt...")
    logger.info(
        "[CLAUDE - EXTRACTION] system: %s",
        truncate_for_log(system, 300),
    )
    logger.info(
        "[CLAUDE - EXTRACTION] user: %s",
        truncate_for_log(user, 300),
    )


def extract_invoice(raw_text: str) -> ExtractedInvoice:
    """Extract an ExtractedInvoice from LlamaParse markdown via Claude Sonnet."""
    if not raw_text or not raw_text.strip():
        raise ValueError("raw_text is empty — nothing to extract")

    if demo_mode_enabled():
        logger.info(
            "[CLAUDE - EXTRACTION] DEMO_MODE — stub extraction (no API call)"
        )
        return demo_extract_invoice(raw_text)

    extractor = _structured_extractor()
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=raw_text),
    ]
    _log_prompts(_SYSTEM_PROMPT, raw_text)

    try:
        result = extractor.invoke(messages)
        invoice = _coerce_invoice(result)
        logger.info(
            "[CLAUDE - EXTRACTION] Response received, validated against schema"
        )
        return invoice
    except Exception as first_err:
        logger.info(
            "[CLAUDE - EXTRACTION] Validation FAILED, retrying..."
        )
        correction_user = _CORRECTION_PROMPT.format(error=str(first_err))
        correction = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=raw_text),
            HumanMessage(content=correction_user),
        ]
        _log_prompts(_SYSTEM_PROMPT, correction_user)
        try:
            result = extractor.invoke(correction)
            invoice = _coerce_invoice(result)
            logger.info(
                "[CLAUDE - EXTRACTION] Response received, validated against schema"
            )
            return invoice
        except Exception as second_err:
            raise InvoiceExtractionError(
                "Failed to extract a valid ExtractedInvoice after 1 retry. "
                f"First error: {first_err}. Retry error: {second_err}"
            ) from second_err


def _coerce_invoice(result: object) -> ExtractedInvoice:
    """Normalize structured-output result into ExtractedInvoice."""
    if isinstance(result, ExtractedInvoice):
        return result
    if isinstance(result, dict):
        return ExtractedInvoice.model_validate(result)
    raise InvoiceExtractionError(
        f"Structured output returned unexpected type: {type(result).__name__}"
    )
