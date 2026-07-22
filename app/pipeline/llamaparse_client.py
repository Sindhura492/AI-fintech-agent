from __future__ import annotations

from pathlib import Path

from app.observability.console_logging import get_logger

logger = get_logger(__name__)


def parse_with_llamaparse(file_path: str | Path, *, api_key: str) -> str:
    """Send a file to LlamaParse and return markdown text.

    Raises on API/library failure so the sandbox can fall back locally.
    """
    import os

    path = Path(file_path)
    filename = path.name
    # Parent process owns Rich [LLAMAPARSE] lines when running in the sandbox child.
    in_child = os.environ.get("DISPUTE_RESOLVER_SANDBOX_CHILD") == "1"
    if not in_child:
        logger.info("[LLAMAPARSE] Sending %s to LlamaParse API...", filename)

    from llama_parse import LlamaParse

    parser = LlamaParse(
        api_key=api_key,
        result_type="markdown",
        verbose=False,
        language="en",
    )
    documents = parser.load_data(str(path))
    parts: list[str] = []
    for doc in documents:
        chunk = getattr(doc, "text", None) or getattr(doc, "get_content", lambda: "")()
        if callable(chunk):
            chunk = chunk()
        if chunk:
            parts.append(str(chunk))
    text = "\n\n".join(parts).strip()
    if not in_child:
        logger.info(
            "[LLAMAPARSE] Received %s chars of parsed markdown",
            len(text),
        )
    return text
