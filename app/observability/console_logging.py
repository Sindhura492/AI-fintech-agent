from __future__ import annotations

import logging
import re
from typing import Final

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

_CONFIGURED = False
_TAG_RE = re.compile(r"^\[([^\]]+)\]")
_REDACTED = "***REDACTED***"

# Component tag → Rich style for live terminal scanning
_TAG_STYLES: Final[dict[str, str]] = {
    "SANDBOX": "cyan",
    "LLAMAPARSE": "magenta",
    "CLAUDE - EXTRACTION": "bright_blue",
    "CLAUDE - BUYER": "yellow",
    "CLAUDE - SUPPLIER": "bright_yellow",
    "LLAMAINDEX": "green",
    "ML - ISOLATION FOREST": "bright_red",
    "ENFORCEMENT GATE": "bold white",
    "NEO4J": "bright_cyan",
    "PIPELINE": "dim white",
}


class SecretRedactionFilter(logging.Filter):
    """Replace known secret values with ``***REDACTED***`` in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = _secret_values()
        if not secrets:
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = _redact_text(msg, secrets)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        if record.exc_text:
            record.exc_text = _redact_text(record.exc_text, secrets)
        return True


def _secret_values() -> list[str]:
    """Collect non-empty credential strings from Settings (longest first)."""
    try:
        from app.config import get_settings

        s = get_settings()
    except Exception:
        return []

    values = [
        s.anthropic_api_key,
        s.email_app_password,
        s.neo4j_password,
        s.llama_cloud_api_key,
    ]
    cleaned = [v.strip() for v in values if isinstance(v, str) and v.strip()]
    # Longest first so partial overlaps redact fully
    return sorted(set(cleaned), key=len, reverse=True)


def _redact_text(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret and secret in out:
            out = out.replace(secret, _REDACTED)
    return out


class ComponentFormatter(logging.Formatter):
    """Keep message body; RichHandler supplies time/level columns."""

    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


class ComponentRichHandler(RichHandler):
    """Color the ``[COMPONENT]`` prefix when present."""

    def render_message(self, record: logging.LogRecord, message: str) -> Text:  # type: ignore[override]
        text = Text()
        match = _TAG_RE.match(message)
        if match:
            tag = match.group(1)
            style = _TAG_STYLES.get(tag, "bold")
            bracketed = f"[{tag}]"
            text.append(bracketed, style=style)
            text.append(message[len(bracketed) :])
        else:
            text.append(message)
        return text


def truncate_for_log(text: str, limit: int = 300) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def setup_logging(*, force: bool = False) -> None:
    """Configure root logging once (Rich console). Safe to call from workers."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    from app.config import get_settings

    level_name = (get_settings().log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    console = Console(stderr=True, highlight=False, soft_wrap=True)
    handler = ComponentRichHandler(
        console=console,
        show_time=True,
        show_path=False,
        show_level=True,
        markup=False,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        omit_repeated_times=False,
    )
    handler.setFormatter(ComponentFormatter())
    handler.addFilter(SecretRedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.filters.clear()
    root.addFilter(SecretRedactionFilter())
    root.addHandler(handler)
    root.setLevel(level)

    for name in (
        "httpx",
        "httpcore",
        "openai",
        "neo4j",
        "uvicorn.access",
        "llama_index",
        "llama_parse",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
