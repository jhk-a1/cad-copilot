"""CAD-Copilot AI server entry point.

  uvicorn ai_server.main:app --reload   ->  http://localhost:8000/docs

Stub services for now (Contract v2.0.0 exercised end to end). Real engines land per the
task-prompts schedule. WebSocket echoes a minimal progress contract for the UI to wire against.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import Environment, get_settings
from .middleware.logging import RequestLoggingMiddleware
from .middleware.security import (
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from .models import CONTRACT_VERSION
from .routers import codegen, health, object_plan, sketch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.getLogger("cad_copilot").info(
        "starting env=%s contract=%s", settings.environment.value, CONTRACT_VERSION
    )
    yield
    logging.getLogger("cad_copilot").info("shutting down")


app = FastAPI(
    title="CAD-Copilot AI Server",
    description="AI backend for the Autodesk Fusion CAD assistant",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Security guards (added last = run first). Rate limiting is off under tests.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    limit=settings.rate_limit_requests,
    window_s=settings.rate_limit_window_s,
    enabled=settings.environment != Environment.TEST,
)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_bytes=settings.max_request_size_mb * 1024 * 1024,
)

app.include_router(health.router)
app.include_router(object_plan.router)
app.include_router(sketch.router)
app.include_router(codegen.router)


@app.get("/", tags=["Meta"])
async def root() -> dict[str, str]:
    return {"name": "CAD-Copilot AI Server", "contract_version": CONTRACT_VERSION, "docs": "/docs"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Progress stream stub. Contract stages: PARSING_INTENT, GENERATING_SKETCH,
    SOLVING_SKETCH, BUILDING_IR, VALIDATING_IR, VERIFYING_CANDIDATES, RENDER_CHECK, COMPLETE.
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            await websocket.send_json(
                {"type": "PROGRESS", "stage": "COMPLETE", "progress": 100, "echo": data}
            )
    except WebSocketDisconnect:
        pass
