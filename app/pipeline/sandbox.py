

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.config import get_settings
from app.observability.console_logging import get_logger

logger = get_logger(__name__)

_SANDBOX_TIMEOUT_SECONDS = 120
_MAX_OUTPUT_BYTES = 512_000

# Child: LlamaParse via llamaparse_client, else local pypdf/UTF-8.
_SANDBOX_READER = r"""
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
max_bytes = int(sys.argv[2])

raw = path.read_bytes()
if len(raw) > max_bytes:
    print(f"sandbox: file exceeds {max_bytes} byte limit", file=sys.stderr)
    sys.exit(2)

api_key = (os.environ.get("LLAMA_CLOUD_API_KEY") or "").strip()
text = ""
method = "local"

if api_key:
    try:
        from app.pipeline.llamaparse_client import parse_with_llamaparse

        text = parse_with_llamaparse(path, api_key=api_key)
        method = "llamaparse" if text.strip() else "local_fallback"
        if not text.strip():
            text = ""
    except Exception as exc:
        print(
            f"sandbox: LlamaParse failed ({type(exc).__name__}: {exc}); falling back",
            file=sys.stderr,
        )
        text = ""
        method = "local_fallback"

if not text:
    if raw[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(raw))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            text = "\n".join(parts)
        except Exception as exc:
            print(f"sandbox: PDF extract failed: {exc}", file=sys.stderr)
            sys.exit(3)
    else:
        text = raw.decode("utf-8", errors="replace")
    if method == "llamaparse":
        method = "local_fallback"
    elif method != "local_fallback":
        method = "local"

text = text.replace("\x00", "")
if not text.strip():
    print("sandbox: empty text after extract", file=sys.stderr)
    sys.exit(4)

sys.stderr.write(f"sandbox_method={method}\n")
sys.stdout.write(text)
"""


def parse_document(file_path: str) -> str:
    """Parse a document to clean markdown via LlamaParse in a sandbox subprocess."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Document not found: {file_path}")

    logger.info(
        "[SANDBOX] Parsing %s in isolated subprocess...",
        path.name,
    )

    api_key = (get_settings().llama_cloud_api_key or "").strip()
    if api_key:
        logger.info(
            "[LLAMAPARSE] Sending %s to LlamaParse API...",
            path.name,
        )

    clean_env = {
        "PATH": "/usr/bin:/bin:" + str(Path(sys.executable).parent),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": ":".join(sys.path),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LOG_LEVEL": get_settings().log_level,
        # Child should not emit Rich logs onto captured stderr (parent logs tags).
        "DISPUTE_RESOLVER_SANDBOX_CHILD": "1",
    }
    if api_key:
        clean_env["LLAMA_CLOUD_API_KEY"] = api_key

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                _SANDBOX_READER,
                str(path),
                str(_MAX_OUTPUT_BYTES),
            ],
            capture_output=True,
            text=True,
            timeout=_SANDBOX_TIMEOUT_SECONDS,
            env=clean_env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"Sandbox timed out after {_SANDBOX_TIMEOUT_SECONDS}s parsing {path}"
        ) from exc

    if completed.stderr:
        for line in completed.stderr.splitlines():
            if line.startswith("sandbox_method="):
                continue
            if line.startswith("sandbox:"):
                logger.warning("[SANDBOX] %s", line)

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise RuntimeError(
            f"Sandbox failed parsing {path} (exit {completed.returncode}): {detail}"
        )

    text = completed.stdout
    if not text or not text.strip():
        raise RuntimeError(f"Sandbox returned empty text for {path}")

    method = last_parse_method_from_stderr(completed.stderr or "")
    if method == "llamaparse":
        logger.info(
            "[LLAMAPARSE] Received %s chars of parsed markdown",
            len(text.strip()),
        )
    else:
        if api_key:
            logger.info(
                "[LLAMAPARSE] API empty/failed — fell back to local parse (%s chars)",
                len(text.strip()),
            )
        logger.info(
            "[SANDBOX] Local parse complete (%s) — %s chars",
            method,
            len(text.strip()),
        )

    return text


def parse_in_sandbox(file_path: str) -> str:
    """Backward-compatible alias for ``parse_document``."""
    return parse_document(file_path)


def read_document(path: str | Path) -> str:
    """Read document text via the sandboxed LlamaParse pipeline."""
    return parse_document(str(path))


def last_parse_method_from_stderr(stderr: str) -> str:
    """Helper for tests — extract sandbox_method= from child stderr."""
    for line in (stderr or "").splitlines():
        if line.startswith("sandbox_method="):
            return line.split("=", 1)[1].strip()
    return "unknown"
