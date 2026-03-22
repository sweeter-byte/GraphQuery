"""
FastAPI application entry point for the Graph Query Planning System.

Run with:
  uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_config
from .logging_config import setup_logging, get_logger
from .storage import Storage
from .routes import datasets, sessions

# Initialize structured logging BEFORE anything else
setup_logging()

http_log = get_logger("api")
logger = logging.getLogger(__name__)

config = get_config()

app = FastAPI(
    title="Graph Query Planning System",
    description="Interactive graph query plan optimization via FaSTest cardinality estimation",
    version="0.1.0",
)


# ── Request / Response logging middleware ──
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed_ms = (time.time() - start) * 1000
        http_log.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response


app.add_middleware(RequestLoggingMiddleware)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage and inject into routers
storage = Storage(dataset_root=config.dataset_root)
datasets.init_router(storage)
sessions.init_router(storage)

app.include_router(datasets.router)
app.include_router(sessions.router)

logger.info("GraphQuery server initialized -- dataset_root=%s", config.dataset_root)


@app.get("/api/health")
async def health():
    return {"status": "ok", "datasets": len(storage.datasets)}
