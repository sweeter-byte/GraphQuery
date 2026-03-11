"""Session API routes including SSE streaming endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
import os
import subprocess
import re
import tempfile
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException, Request, Depends
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
session_log = logging.getLogger("gq.session")
daf_log = logging.getLogger("gq.daf")

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
        schedule_config=req.schedule_config,
        run_execution=req.run_execution,
        execution_config=req.execution_config,
    )
    storage.create_session(session)

    session_log.info(
        "SESSION_CREATED | sid=%s | dataset=%s | query_V=%d query_E=%d | beam_width=%s | schedule=%s | graph=%s",
        session.session_id, req.dataset_id,
        len(req.query_graph.vertices), len(req.query_graph.edges),
        req.beam_width,
        req.schedule_config.mode if req.schedule_config else "auto(default)",
        req.query_graph.model_dump_json() if hasattr(req.query_graph, 'model_dump_json') else req.query_graph.json(),
    )

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
        "execution_result": session.execution_result,
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
        "execution_result": session.execution_result,
    }


@router.post("/{session_id}/execute", status_code=202)
async def execute_query(session_id: str):
    """Trigger real query execution with all orders using DAF concurrently."""
    storage = _get_storage()
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Session must be completed before execution (status: {session.status.value})",
        )

    # 1. Find the best evaluated order instance for final return
    if session.best_order_id is None:
         raise HTTPException(status_code=400, detail="No best order found for execution")
         
    best_order = next((o for o in session.orders if o.order_id == session.best_order_id), None)
    if not best_order:
         raise HTTPException(status_code=500, detail="Best order instance not found")

    # 2. Convert frontend query graph to DAF format
    qg = session.query_graph
    if qg is None:
        raise HTTPException(status_code=500, detail="Session has no query graph")

    num_vertices = len(qg.vertices)
    num_edges = len(qg.edges)
    daf_graph_str = f"t {num_vertices} {num_edges}\n"
    
    vtx_id_map = {v.id: idx for idx, v in enumerate(qg.vertices)}
    
    for v in qg.vertices:
        idx = vtx_id_map[v.id]
        label = v.label
        daf_graph_str += f"v {idx} {label}\n"
        
    for e in qg.edges:
        src_idx = vtx_id_map[e.source]
        tgt_idx = vtx_id_map[e.target]
        daf_graph_str += f"e {src_idx} {tgt_idx}\n"

    # 3. Setup global DAF parameters
    data_graph_path = f"dataset/{session.dataset_id}/{session.dataset_id}.graph"
    daf_binary = "core/engines/daf/build/main/DAF"
    
    if not os.path.exists(daf_binary):
        raise HTTPException(status_code=500, detail="DAF binary not found. Please compile it first.")

    # Sort all generated orders by estimated score (best first)
    sorted_orders = sorted(session.orders, key=lambda o: o.score, reverse=True)

    # 4. Define concurrent executable task
    # Setup concurrency limit to physical CPU cores
    max_concurrent = os.cpu_count() or 4
    semaphore = asyncio.Semaphore(max_concurrent)
    loop = asyncio.get_running_loop()

    async def run_daf_parallel(order_rank: int, order_data: Any, tmp_query_filepath: str) -> dict:
        order_str = ",".join(str(vertex_id) for vertex_id in order_data.order)
        cmd = [
            daf_binary,
            "-d", data_graph_path,
            "-q", tmp_query_filepath,
            "-o", order_str
        ]

        async with semaphore:
            daf_log.debug(
                "DAF_SPAWN | sid=%s | rank=%d | order_id=%d | order=%s | est_score=%.2f",
                session.session_id, order_rank, order_data.order_id, order_str, order_data.score,
            )
            
            def _run_sync():
                # posix_spawn fast path, no memory dupes
                return subprocess.run(
                    cmd, capture_output=True, text=True, close_fds=False
                )
            
            try:
                # Enforce rigid 20s timeout on explosive permutations
                process = await asyncio.wait_for(
                    loop.run_in_executor(None, _run_sync),
                    timeout=20.0
                )
                
                if process.returncode != 0:
                    daf_log.error("DAF_FAIL | sid=%s | rank=%d | order_id=%d | rc=%d | err=%s", 
                                  session.session_id, order_rank, order_data.order_id, process.returncode, process.stderr.strip())
                    return {"rank": order_rank, "id": order_data.order_id, "status": "ERROR"}

                out_str = process.stdout
                matches_match = re.search(r'#Matches:\s*(\d+)', out_str)
                time_match = re.search(r'Total time:\s*([0-9.]+)', out_str)
                calls_match = re.search(r'#Recursive calls:\s*(\d+)', out_str)
                
                num_matches = int(matches_match.group(1)) if matches_match else 0
                execution_time_ms = float(time_match.group(1)) if time_match else 0.0
                num_calls = int(calls_match.group(1)) if calls_match else 0

                daf_log.info(
                    "DAF_EVAL_ALL | sid=%s | rank=%d | order_id=%d | order=%s | est_score=%.2f | matches=%d | time=%.2fms | recursive_calls=%d",
                    session.session_id, order_rank, order_data.order_id, order_str, order_data.score,
                    num_matches, execution_time_ms, num_calls,
                )
                
                return {
                    "rank": order_rank, "id": order_data.order_id, "status": "SUCCESS",
                    "matches": num_matches, "time_ms": execution_time_ms, "calls": num_calls
                }
                
            except asyncio.TimeoutError:
                daf_log.warning(
                    "DAF_EVAL_ALL | sid=%s | rank=%d | order_id=%d | order=%s | est_score=%.2f | status=TIMEOUT",
                    session.session_id, order_rank, order_data.order_id, order_str, order_data.score,
                )
                return {"rank": order_rank, "id": order_data.order_id, "status": "TIMEOUT"}
            except Exception as e:
                daf_log.error("DAF_SYS_FAIL | sid=%s | rank=%d | err=%s", session.session_id, order_rank, str(e))
                return {"rank": order_rank, "id": order_data.order_id, "status": "ERROR"}

    # 5. Execute map
    best_execution_result = None
    try:
        # Update session status to reflect we are executing downstream
        session.status = SessionStatus.RUNNING 
        storage.update_session(session)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.graph', delete=False) as f:
            f.write(daf_graph_str)
            tmp_query_path = f.name
            
        tasks = [
            run_daf_parallel(rank + 1, order, tmp_query_path) 
            for rank, order in enumerate(sorted_orders)
        ]
        
        # Fire off all candidate evaluations bounded by OS Core semaphore
        results = await asyncio.gather(*tasks)
        
        # Extract the metrics for the chosen best_order_id to return to frontend
        for r in results:
            if r["id"] == session.best_order_id:
                best_execution_result = r
                break
                
        # Store execution result in session
        if best_execution_result:
            session.execution_result = best_execution_result
        
        session.status = SessionStatus.COMPLETED
        storage.update_session(session)

    except Exception as e:
        daf_log.error("DAF_EXEC_POOL_FAIL | sid=%s | error=%s", session.session_id, str(e))
        session.status = SessionStatus.FAILED
        session.error = {"code": "DAF_EXEC_FAIL", "message": str(e)}
        storage.update_session(session)
        raise HTTPException(status_code=500, detail=f"DAF execution pool failed: {str(e)}")
    finally:
        if 'tmp_query_path' in locals() and os.path.exists(tmp_query_path):
            os.remove(tmp_query_path)

    # 6. Safety check fallback for frontend dict
    final_matches = 0
    final_time = 0.0
    final_calls = 0
    if best_execution_result and best_execution_result["status"] == "SUCCESS":
         final_matches = best_execution_result.get("matches", 0)
         final_time = best_execution_result.get("time_ms", 0.0)
         final_calls = best_execution_result.get("calls", 0)

    order_str = ",".join(str(vertex_id) for vertex_id in best_order.order)
    return {
        "session_id": session.session_id,
        "best_order_id": session.best_order_id,
        "used_order": order_str,
        "status": session.status.value,
        "results": {
            "num_matches": final_matches,
            "execution_time_ms": final_time,
            "recursive_calls": final_calls
        },
        "message": f"Execution succeeded. {len(sorted_orders)} permutations thoroughly evaluated in backend."
    }
