"""Session API routes including SSE streaming endpoint."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..models import (
    Session, SessionStatus, SessionCreateRequest, SessionCreateResponse,
    ErrorResponse, ErrorDetail, IndexStatus,
)
from ..storage import Storage
from ..services.query_validator import validate_and_normalize, ValidationError
from ..services.estimator_adapter import get_estimator_adapter
from ..services.score_aggregator import ScoreAggregator
from ..services.session_pipeline import run_session_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_storage: Storage | None = None
_dataset_root: str = "dataset"

# Active aggregators keyed by session_id
_aggregators: dict[str, ScoreAggregator] = {}
# Active background tasks
_tasks: dict[str, asyncio.Task] = {}


def init_router(storage: Storage, dataset_root: str = "dataset") -> None:
    global _storage, _dataset_root
    _storage = storage
    _dataset_root = dataset_root


def _get_storage() -> Storage:
    if _storage is None:
        raise HTTPException(status_code=500, detail="Storage not initialized")
    return _storage


@router.post("", status_code=202, response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest):
    """Create a new query evaluation session."""
    storage = _get_storage()

    # Validate dataset exists and index is ready
    dataset = storage.get_dataset(req.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{req.dataset_id}' not found")
    if dataset.index_status != IndexStatus.READY:
        raise HTTPException(
            status_code=409,
            detail=f"Dataset index not ready (status: {dataset.index_status.value})",
        )

    # Validate and normalize query graph
    try:
        normalized = validate_and_normalize(req.query_graph)
    except ValidationError as e:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error=ErrorDetail(code=e.code, message=e.message, details=e.details),
            ).model_dump(),
        )

    # Create session
    session = Session(
        dataset_id=req.dataset_id,
        query_graph=req.query_graph,
        normalized_graph=normalized,
        beam_width=req.beam_width,
    )
    storage.create_session(session)

    # Create aggregator
    aggregator = ScoreAggregator()
    _aggregators[session.session_id] = aggregator

    # Launch pipeline as background task
    adapter = get_estimator_adapter()
    task = asyncio.create_task(
        run_session_pipeline(session, adapter, aggregator, _dataset_root)
    )
    _tasks[session.session_id] = task

    return SessionCreateResponse(
        session_id=session.session_id,
        status=session.status,
        stream_url=f"/api/sessions/{session.session_id}/stream",
    )


@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get current session state (snapshot for reconnection)."""
    storage = _get_storage()
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    result: dict = {
        "session_id": session.session_id,
        "dataset_id": session.dataset_id,
        "status": session.status.value,
        "beam_width": session.beam_width,
        "best_order_id": session.best_order_id,
        "best_score": session.best_score,
        "created_at": session.created_at,
        "completed_at": session.completed_at,
        "error": session.error,
    }

    # Include order summaries
    if session.orders:
        result["orders"] = [
            {
                "order_id": o.order_id,
                "order": o.order,
                "prefix_index": o.prefix_index,
                "score": o.score,
            }
            for o in session.orders
        ]

    # Include aggregator ranking if available
    agg = _aggregators.get(session_id)
    if agg and agg.trackers:
        result["ranking"] = agg.get_top_k()

    return result


@router.get("/{session_id}/stream")
async def stream_session(session_id: str, request: Request):
    """SSE streaming endpoint for real-time session progress."""
    storage = _get_storage()
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    aggregator = _aggregators.get(session_id)
    if aggregator is None:
        raise HTTPException(status_code=404, detail="No active stream for this session")

    async def event_generator():
        async for event in aggregator.stream_events():
            if await request.is_disconnected():
                break
            yield {
                "event": event.event,
                "data": json.dumps(event.data),
            }

    return EventSourceResponse(event_generator())


@router.get("/{session_id}/result")
async def get_result(session_id: str):
    """Get final session result after completion."""
    storage = _get_storage()
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if session.status == SessionStatus.FAILED:
        return JSONResponse(
            status_code=500,
            content={"error": session.error},
        )

    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Session not completed (status: {session.status.value})",
        )

    return {
        "session_id": session.session_id,
        "status": session.status.value,
        "best_order_id": session.best_order_id,
        "best_score": session.best_score,
        "orders": [
            {
                "order_id": o.order_id,
                "order": o.order,
                "score": o.score,
                "prefix_estimates": o.prefix_estimates,
            }
            for o in session.orders
        ],
    }


@router.post("/{session_id}/execute", status_code=202)
async def execute_query(session_id: str):
    """Trigger real query execution with the best order (placeholder)."""
    storage = _get_storage()
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Session must be completed before execution (status: {session.status.value})",
        )

    # Placeholder: downstream execution adapter not yet implemented
    return {
        "session_id": session.session_id,
        "best_order_id": session.best_order_id,
        "message": "Execution triggered (downstream adapter not yet integrated)",
    }
