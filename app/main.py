from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_anomaly import router as anomaly_router
from app.api.routes_escalations import router as escalations_router
from app.api.routes_health import router as health_router
from app.api.routes_inbox import router as inbox_router
from app.api.routes_metrics import router as metrics_router
from app.api.routes_pipeline import router as pipeline_router
from app.api.routes_vendor import router as vendor_router
from app.api.routes_ws import router as ws_router
from app.observability.console_logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Init metrics DB + knowledge graph, then start the Gmail inbox poller."""
    from app.ingest.email_ingest import poll_inbox_loop
    from app.intelligence.knowledge_graph import get_knowledge_graph
    from app.observability.monitoring import metrics_store

    try:
        metrics_store.log_startup_check()
    except Exception:
        logger.exception("Metrics DB startup check failed")

    try:
        get_knowledge_graph()
        logger.info("[PIPELINE] Knowledge graph ready")
    except Exception:
        logger.exception("Knowledge graph init failed — continuing without Neo4j")

    inbox_task = asyncio.create_task(poll_inbox_loop(), name="poll_inbox_loop")
    logger.info("[PIPELINE] Started poll_inbox_loop background task")
    try:
        yield
    finally:
        inbox_task.cancel()
        try:
            await inbox_task
        except asyncio.CancelledError:
            pass
        try:
            get_knowledge_graph().close()
        except Exception:
            pass
        logger.info("[PIPELINE] Stopped poll_inbox_loop background task")


app = FastAPI(
    title="Agent Finance",
    description="Automated three-way match and dispute resolution pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(inbox_router)
app.include_router(vendor_router)
app.include_router(pipeline_router)
app.include_router(escalations_router)
app.include_router(anomaly_router)
app.include_router(ws_router)
