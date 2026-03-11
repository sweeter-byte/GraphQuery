"""
Session Pipeline Orchestrator.

Coordinates the full query evaluation flow:
  1. Load index (emit index_loading/index_loaded)
  2. Generate connected expansion orders
  3. Level-wise prefix evaluation with real-time SSE streaming
  4. Score aggregation, ranking, best order selection
  5. Terminal event (session_completed / session_failed)
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..models import (
    Session, SessionStatus, SSEEvent, OrderState,
)
from .estimator_adapter import EstimatorAdapter
from .order_generator import generate_orders
from .prefix_builder import build_prefix_subgraphs
from .score_aggregator import ScoreAggregator

logger = logging.getLogger(__name__)
session_log = logging.getLogger("gq.session")
est_log = logging.getLogger("gq.estimation")
thread_log = logging.getLogger("gq.threading")


async def run_session_pipeline(
    session: Session,
    adapter: EstimatorAdapter,
    aggregator: ScoreAggregator,
    dataset_root: str = "dataset",
) -> None:
    """
    Main async pipeline for evaluating a query session.

    Pushes SSE events to the aggregator's event queue as work progresses.
    The SSE streaming endpoint reads from the same aggregator.
    """
    pipeline_start = time.time()
    try:
        # --- Step 1: Index loading ---
        session_log.info(
            "SESSION_START | sid=%s | dataset=%s | beam_width=%s | query_V=%d query_E=%d | graph=%s",
            session.session_id, session.dataset_id, session.beam_width,
            session.normalized_graph.num_vertices if session.normalized_graph else 0,
            session.normalized_graph.num_edges if session.normalized_graph else 0,
            session.query_graph.model_dump_json() if session.query_graph and hasattr(session.query_graph, 'model_dump_json') else (session.query_graph.json() if session.query_graph else "None"),
        )
        await aggregator.push_event(SSEEvent(
            event="index_loading",
            data={"dataset_id": session.dataset_id},
        ))

        # Load dataset (idempotent — skips if already loaded)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, adapter.load_dataset, session.dataset_id, dataset_root
        )

        await aggregator.push_event(SSEEvent(
            event="index_loaded",
            data={"dataset_id": session.dataset_id},
        ))

        # --- Step 2: Session started ---
        session.status = SessionStatus.RUNNING
        await aggregator.push_event(SSEEvent(
            event="session_started",
            data={"session_id": session.session_id},
        ))

        # --- Step 3: Generate orders ---
        graph = session.normalized_graph
        if graph is None:
            raise RuntimeError("Normalized graph not set on session")

        orders = generate_orders(graph, beam_width=session.beam_width)

        if not orders:
            raise RuntimeError("No valid connected expansion orders found")

        est_log.info(
            "ORDERS_GENERATED | sid=%s | count=%d | beam_width=%s",
            session.session_id, len(orders), session.beam_width,
        )
        for i, order in enumerate(orders):
            est_log.debug("  ORDER[%d] = %s", i, order)

        # Register orders with aggregator
        session.orders = []
        for i, order in enumerate(orders):
            aggregator.register_order(i, order, graph.num_vertices)
            session.orders.append(OrderState(
                order_id=i,
                order=order,
                prefix_index=0,
                score=0.0,
            ))
            await aggregator.push_event(SSEEvent(
                event="order_generated",
                data={"order_id": i, "order": order, "total_orders": len(orders)},
            ))

        # --- Step 3.5: Resolve Schedule Configuration ---
        config = session.schedule_config
        if not config or config.mode == "auto":
            # Load default if explicitly auto or not provided
            config_path = Path("server/default_config/schedule_config.json")
            if config_path.exists():
                try:
                    with open(config_path, "r") as f:
                        data = json.load(f)
                        # Reconstruct config properly
                        from ..models import ScheduleConfig
                        config = ScheduleConfig(**data)
                except Exception as e:
                    logger.warning(f"Failed to read default config: {e}. Using fallback.")
            
            # Fallback if file missing or parse failed
            if not config or config.mode == "auto":
                config = type(session).mock_config if hasattr(type(session), "mock_config") else None
                if not config:
                    from ..models import ScheduleConfig
                    cores = os.cpu_count() or 4
                    config = ScheduleConfig(mode="auto", python_threads=cores, omp_threads=1)
        
        python_threads = config.python_threads
        omp_threads = config.omp_threads
        total_cores = os.cpu_count() or 1
        thread_log.info(
            "SCHEDULE_CONFIG | sid=%s | mode=%s | python_threads=%d | omp_threads=%d | "
            "total_system_cores=%d | oversubscription_ratio=%.2f",
            session.session_id, config.mode, python_threads, omp_threads,
            total_cores, (python_threads * omp_threads) / total_cores,
        )
        session_log.info(
            "Session %s using threads: Python=%d, OMP=%d (total_cores=%d, mode=%s)",
            session.session_id, python_threads, omp_threads, total_cores, config.mode,
        )

        # --- Step 4: Level-wise prefix evaluation ---
        # Evaluate all orders level by level (level-wise evolution)
        # Events are emitted incrementally as each order estimation completes
        n = graph.num_vertices

        # Pre-build all prefix payloads
        all_prefixes: dict[int, list] = {}
        for i, order in enumerate(orders):
            all_prefixes[i] = build_prefix_subgraphs(graph, order)

        # Track completed count for progress
        completed_count = 0
        total_evaluations = n * len(orders)

        for level in range(n):
            level_start = time.time()
            # Dispatch all prefix estimations concurrently using explicit thread pool
            with ThreadPoolExecutor(max_workers=python_threads) as executor:
                # Async wrapper: pairs each future result with its order_idx
                # so we don't need a dict lookup (asyncio.as_completed wraps
                # futures in new coroutine objects that can't be used as keys).
                async def _wait(fut, o_idx):
                    return o_idx, await fut

                wrapped = []
                for order_idx in range(len(orders)):
                    prefix = all_prefixes[order_idx][level]

                    def run_estimation(p, threads, order_i, lvl):
                        t_name = threading.current_thread().name
                        t_id = threading.get_ident()
                        t0 = time.time()

                        payload_dict = p.to_dict()
                        payload_dict["omp_threads"] = threads

                        _fastest_core = getattr(adapter, "_estimator", None)
                        if _fastest_core is None:
                             # mock estimation
                             import random
                             c_hat = float(random.randint(10, 10000))
                             elapsed = (time.time() - t0) * 1000
                             thread_log.info(
                                 "THREAD_EXEC | thread=%s(id=%d) | order=%d | level=%d | "
                                 "omp_threads=%d | c_hat=%.2f | wall=%.1fms [MOCK]",
                                 t_name, t_id, order_i, lvl, threads, c_hat, elapsed,
                             )
                             return {
                                 "estimated_cardinality": c_hat,
                                 "QueryTime": 0.1,
                             }
                        result = dict(_fastest_core.estimate_prefix(payload_dict))
                        elapsed = (time.time() - t0) * 1000
                        c_hat = result.get("estimated_cardinality", 0.0)
                        thread_log.info(
                            "THREAD_EXEC | thread=%s(id=%d) | order=%d | level=%d | "
                            "omp_threads=%d | V=%d E=%d | c_hat=%.4f | wall=%.1fms | "
                            "CSBuild=%.2f TreeCount=%.2f TreeSample=%.2f GraphSample=%.2f QueryTime=%.2f",
                            t_name, t_id, order_i, lvl, threads,
                            payload_dict.get("num_vertices", 0), payload_dict.get("num_edges", 0),
                            c_hat, elapsed,
                            result.get("CSBuildTime", 0.0), result.get("TreeCountTime", 0.0),
                            result.get("TreeSampleTime", 0.0), result.get("GraphSampleTime", 0.0),
                            result.get("QueryTime", 0.0),
                        )
                        return result

                    future = loop.run_in_executor(
                        executor, run_estimation, prefix, omp_threads, order_idx, level
                    )
                    wrapped.append(_wait(future, order_idx))

                # Process results incrementally as each order completes
                for completed_coro in asyncio.as_completed(wrapped):
                    order_idx, result = await completed_coro
                    completed_count += 1

                    c_hat = result.get("estimated_cardinality", 0.0)

                    # Record in aggregator and get events
                    events = aggregator.record_estimate(order_idx, level, c_hat)

                    # Update session state
                    if order_idx < len(session.orders):
                        session.orders[order_idx].prefix_index = level + 1
                        session.orders[order_idx].score = aggregator.trackers[order_idx].score
                        session.orders[order_idx].prefix_estimates.append(c_hat)

                    # Push prefix_progress events immediately
                    await aggregator.push_events(events)

                    # Emit ranking update after each individual estimation
                    ranking_event = aggregator.build_ranking_event()
                    await aggregator.push_event(ranking_event)

                    # Yield control to allow SSE to flush each event individually
                    await asyncio.sleep(0)

            level_elapsed = (time.time() - level_start) * 1000

            # Log level summary
            top_3 = aggregator.get_top_k()[:3]
            top_3_str = ", ".join([f"O{t['order_id']}:sc={t['score']:.2f}" for t in top_3])

            est_log.info(
                "LEVEL_DONE | sid=%s | level=%d/%d | elapsed=%.1fms | top3_rank=[%s]",
                session.session_id, level + 1, n, level_elapsed, top_3_str,
            )

        # --- Step 5: Run downstream execution (optional) ---
        execution_result = None
        if session.run_execution:
            try:
                from .graph_format_converter import serialize_graph_to_file
                from .survey_engine_adapter import get_survey_engine

                await aggregator.push_event(SSEEvent(
                    event="execution_started",
                    data={"session_id": session.session_id},
                ))

                # Serialize query graph to temp .graph file
                tmp_query_path = serialize_graph_to_file(graph)

                # Resolve data graph path
                data_graph_path = str(
                    Path(dataset_root) / session.dataset_id / f"{session.dataset_id}.graph"
                )

                # Build execution kwargs from config
                exec_kwargs: dict = {}
                cfg = session.execution_config or {}
                if "filter_type" in cfg:
                    exec_kwargs["filter_type"] = cfg["filter_type"]
                if "order_type" in cfg:
                    exec_kwargs["order_type"] = cfg["order_type"]
                if "engine_type" in cfg:
                    exec_kwargs["engine_type"] = cfg["engine_type"]
                if "max_embeddings" in cfg:
                    exec_kwargs["max_embeddings"] = int(cfg["max_embeddings"])
                if "time_limit" in cfg:
                    exec_kwargs["time_limit"] = int(cfg["time_limit"])

                engine = get_survey_engine()
                execution_result = await loop.run_in_executor(
                    None,
                    lambda: engine.execute(
                        data_graph_path, tmp_query_path, **exec_kwargs,
                    ),
                )

                # Remove stdout from stored result (too large)
                execution_result.pop("stdout", None)
                session.execution_result = execution_result

                # Clean up temp file
                import os as _os
                if _os.path.exists(tmp_query_path):
                    _os.remove(tmp_query_path)

                await aggregator.push_event(SSEEvent(
                    event="execution_completed",
                    data={
                        "session_id": session.session_id,
                        "embedding_count": execution_result.get("embedding_count", 0),
                        "total_time_seconds": execution_result.get("total_time_seconds", 0.0),
                        "eps": execution_result.get("eps", 0.0),
                    },
                ))

                est_log.info(
                    "EXECUTION_DONE | sid=%s | embeddings=%s | total_time=%.4fs | eps=%.2f",
                    session.session_id,
                    execution_result.get("embedding_count"),
                    execution_result.get("total_time_seconds", 0.0),
                    execution_result.get("eps", 0.0),
                )

            except Exception as exec_err:
                logger.warning("Execution phase failed: %s", exec_err)
                await aggregator.push_event(SSEEvent(
                    event="execution_completed",
                    data={
                        "session_id": session.session_id,
                        "error": str(exec_err),
                    },
                ))

        # --- Step 6: Session completed ---
        session.status = SessionStatus.COMPLETED
        session.best_order_id = aggregator.best_order_id
        session.best_score = aggregator.best_score
        session.completed_at = time.time()
        total_elapsed = time.time() - pipeline_start

        best_order_list = (
            aggregator.trackers[aggregator.best_order_id].order
            if aggregator.best_order_id is not None else None
        )

        est_log.info(
            "SESSION_COMPLETED | sid=%s | best_order_id=%s | best_order=%s | "
            "best_score=%s | orders_evaluated=%d | total_time=%.3fs",
            session.session_id, aggregator.best_order_id, best_order_list,
            aggregator.best_score, len(orders), total_elapsed,
        )

        completion_data: dict = {
            "session_id": session.session_id,
            "best_order_id": aggregator.best_order_id,
            "best_order": best_order_list,
            "best_score": aggregator.best_score,
            "total_orders_evaluated": len(orders),
        }
        if execution_result:
            completion_data["execution_result"] = {
                "embedding_count": execution_result.get("embedding_count", 0),
                "total_time_seconds": execution_result.get("total_time_seconds", 0.0),
                "eps": execution_result.get("eps", 0.0),
            }

        await aggregator.push_event(SSEEvent(
            event="session_completed",
            data=completion_data,
        ))

    except Exception as e:
        logger.exception(f"Session {session.session_id} failed: {e}")
        session.status = SessionStatus.FAILED
        session.error = {"code": "PIPELINE_ERROR", "message": str(e)}
        session.completed_at = time.time()

        await aggregator.push_event(SSEEvent(
            event="session_failed",
            data={
                "session_id": session.session_id,
                "error": {"code": "PIPELINE_ERROR", "message": str(e)},
            },
        ))

    finally:
        await aggregator.close()
