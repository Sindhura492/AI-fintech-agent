from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

from app.config import get_settings
from app.core import AuditEntry, StepType

DEFAULT_AUDIT_PATH = Path(get_settings().audit_log_path)

_current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_session_id",
    default=None,
)


def set_session_id(session_id: str | None) -> contextvars.Token[str | None]:
    """Bind the active pipeline session id for nested audit writes."""
    return _current_session_id.set(session_id)


def get_session_id() -> str | None:
    """Return the active pipeline session id, if any."""
    return _current_session_id.get()


def reset_session_id(token: contextvars.Token[str | None]) -> None:
    """Restore the previous session id binding."""
    _current_session_id.reset(token)


SubscriberCallback: TypeAlias = Callable[[AuditEntry], None]
LiveEvent: TypeAlias = dict[str, Any]
# Queues carry AuditEntry or live event dicts
_QueueSub: TypeAlias = tuple[str | None, asyncio.Queue[AuditEntry | LiveEvent]]


class AuditLog:
    """Append-only JSONL audit log with in-memory live fan-out."""

    def __init__(self, path: Path | str = DEFAULT_AUDIT_PATH) -> None:
        self.path = Path(path)
        self._file_lock = threading.Lock()
        self._sub_lock = threading.Lock()
        self._queues: list[_QueueSub] = []
        self._callbacks: list[SubscriberCallback] = []

    def append(
        self,
        step_name: str,
        step_type: StepType,
        input_summary: str,
        output_summary: str,
        *,
        session_id: str | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
        timestamp: datetime | None = None,
        duration_ms: float | None = None,
    ) -> AuditEntry:
        """Build an AuditEntry, append it to the JSONL file, and publish live."""
        payload: dict[str, str | int | float | bool | None] = dict(details or {})
        sid = session_id or _current_session_id.get()
        if sid is not None:
            payload["session_id"] = sid
            session_id = sid

        entry = AuditEntry(
            timestamp=timestamp or datetime.now(timezone.utc),
            step_name=step_name,
            step_type=step_type,
            input_summary=input_summary,
            output_summary=output_summary,
            details=payload,
            duration_ms=duration_ms,
        )
        self._write_line(entry)
        self._publish(entry)
        try:
            from app.observability.monitoring import metrics_store

            metrics_store.on_audit_entry(entry)
        except Exception:
            # Metrics must never break the pipeline.
            pass
        return entry

    def append_entry(self, entry: AuditEntry, *, session_id: str | None = None) -> AuditEntry:
        """Append a pre-built AuditEntry (optionally stamping session_id)."""
        if session_id is not None and entry.details.get("session_id") != session_id:
            stamped = entry.model_copy(
                update={"details": {**entry.details, "session_id": session_id}}
            )
            entry = stamped
        self._write_line(entry)
        self._publish(entry)
        try:
            from app.observability.monitoring import metrics_store

            metrics_store.on_audit_entry(entry)
        except Exception:
            pass
        return entry

    def publish_live(
        self,
        event: LiveEvent,
        *,
        session_id: str | None = None,
    ) -> LiveEvent:
        """Push an ephemeral UI event (not written to JSONL).

        Used for chat rendering: ``agent_thinking``, ``agent_message``,
        ``settlement_banner``.
        """
        sid = session_id or _current_session_id.get()
        payload = dict(event)
        if sid is not None:
            payload["session_id"] = sid
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._fanout(payload, sid)
        return payload

    def get_trace(self, session_id: str) -> list[AuditEntry]:
        """Return all audit entries for ``session_id`` in file order."""
        if not session_id:
            return []
        if not self.path.exists():
            return []

        entries: list[AuditEntry] = []
        with self._file_lock:
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = AuditEntry.model_validate_json(line)
                    except Exception:
                        continue
                    if entry.details.get("session_id") == session_id:
                        entries.append(entry)
        return entries

    def _write_line(self, entry: AuditEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(entry.model_dump_json() + "\n")

    def subscribe(
        self,
        session_id: str | None = None,
        *,
        maxsize: int = 0,
    ) -> asyncio.Queue[AuditEntry | LiveEvent]:
        """Register a queue for audit entries + live agent chat events."""
        queue: asyncio.Queue[AuditEntry | LiveEvent] = asyncio.Queue(maxsize=maxsize)
        with self._sub_lock:
            self._queues.append((session_id, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AuditEntry | LiveEvent]) -> None:
        with self._sub_lock:
            self._queues = [(sid, q) for sid, q in self._queues if q is not queue]

    def add_callback(self, callback: SubscriberCallback) -> None:
        with self._sub_lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: SubscriberCallback) -> None:
        with self._sub_lock:
            self._callbacks = [c for c in self._callbacks if c is not callback]

    def _publish(self, entry: AuditEntry) -> None:
        entry_session = entry.details.get("session_id")
        session_key = entry_session if isinstance(entry_session, str) else None

        with self._sub_lock:
            callbacks = list(self._callbacks)
            queues = list(self._queues)

        for callback in callbacks:
            try:
                callback(entry)
            except Exception:
                continue

        self._fanout(entry, session_key, queues=queues)

    def _fanout(
        self,
        item: AuditEntry | LiveEvent,
        session_key: str | None,
        *,
        queues: list[_QueueSub] | None = None,
    ) -> None:
        if queues is None:
            with self._sub_lock:
                queues = list(self._queues)
        for filter_sid, queue in queues:
            if filter_sid is not None and filter_sid != session_key:
                continue
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                continue


audit_log = AuditLog()


def write_audit_entry(
    step_name: str,
    step_type: StepType,
    input_summary: str,
    output_summary: str,
    details: dict[str, str | int | float | bool | None] | None = None,
    audit_path: Path | None = None,
    session_id: str | None = None,
    duration_ms: float | None = None,
) -> AuditEntry:
    """Append via the global AuditLog (or a one-off log at ``audit_path``)."""
    log = audit_log if audit_path is None else AuditLog(path=audit_path)
    sid = session_id
    if sid is None and details:
        raw = details.get("session_id")
        if isinstance(raw, str):
            sid = raw
    return log.append(
        step_name=step_name,
        step_type=step_type,
        input_summary=input_summary,
        output_summary=output_summary,
        session_id=sid,
        details=details,
        duration_ms=duration_ms,
    )


def read_audit_trail(
    audit_path: Path | None = None,
    dispute_id: str | None = None,
    session_id: str | None = None,
) -> list[AuditEntry]:
    """Read entries; prefer ``session_id`` via AuditLog.get_trace when set."""
    sid = session_id or dispute_id
    log = audit_log if audit_path is None else AuditLog(path=audit_path)
    if sid is not None:
        return log.get_trace(sid)

    if not log.path.exists():
        return []
    entries: list[AuditEntry] = []
    with log.path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(AuditEntry.model_validate_json(line))
            except Exception:
                continue
    return entries
