"""
FastAPI application entry point for the Graph Query Planning System.

Run with:
  uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .storage import Storage
from .routes import datasets, sessions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

DATASET_ROOT = os.environ.get("DATASET_ROOT", "dataset")

app = FastAPI(
    title="Graph Query Planning System",
    description="Interactive graph query plan optimization via FaSTest cardinality estimation",
    version="0.1.0",
)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage and inject into routers
storage = Storage(dataset_root=DATASET_ROOT)
datasets.init_router(storage)
sessions.init_router(storage, dataset_root=DATASET_ROOT)

app.include_router(datasets.router)
app.include_router(sessions.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "datasets": len(storage.datasets)}
