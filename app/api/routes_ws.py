"""WebSocket live audit / agent-chat stream."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core import AuditEntry
from app.observability.audit import audit_log

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def audit_websocket(websocket: WebSocket) -> None:
    """Stream audit + live agent-chat events for a subscribed session."""
    await websocket.accept()
    queue = None
    try:
        while True:
            if queue is None:
                message = await websocket.receive_json()
                if message.get("action") != "subscribe" or not message.get("session_id"):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": 'Send {"action":"subscribe","session_id":"..."} first',
                        }
                    )
                    continue
                queue = audit_log.subscribe(session_id=str(message["session_id"]))
                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "session_id": message["session_id"],
                    }
                )
                continue

            get_task = asyncio.create_task(queue.get())
            recv_task = asyncio.create_task(websocket.receive_json())
            done, pending = await asyncio.wait(
                {get_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            if get_task in done and not get_task.cancelled():
                item = get_task.result()
                if isinstance(item, AuditEntry):
                    payload = item.model_dump(mode="json")
                    payload["type"] = "audit"
                elif isinstance(item, dict):
                    payload = item
                else:
                    payload = {"type": "raw", "message": str(item)}
                await websocket.send_json(payload)

            if recv_task in done and not recv_task.cancelled():
                message = recv_task.result()
                if message.get("action") == "subscribe" and message.get("session_id"):
                    audit_log.unsubscribe(queue)
                    queue = audit_log.subscribe(session_id=str(message["session_id"]))
                    await websocket.send_json(
                        {
                            "type": "subscribed",
                            "session_id": message["session_id"],
                        }
                    )
    except WebSocketDisconnect:
        pass
    finally:
        if queue is not None:
            audit_log.unsubscribe(queue)
