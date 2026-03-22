"""
Session Pipeline Orchestrator.

Coordinates the full query evaluation flow:
  1. Load index (emit index_loading/index_loaded)
  2. Generate connected expansion orders
  3. Level-wise prefix evaluation with real-time SSE streaming
  4. Score aggregation, ranking, best order selection
  5. Optional downstream execution via SurveyEngineAdapter
  6. Terminal event (session_completed / session_failed)
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..models import (
    Session, SessionStatus, SSEEvent, OrderState,
)
from ..config import resolve_schedule_config
from ..logging_config import set_session_id, clear_session_id
from .estimator_adapter import EstimatorAdapter
from .execution_service import execute_downstream_query
from .order_strategies import generate_orders as strategic_generate_orders
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
    # Set session ID in contextvars so ALL log lines are auto-tagged
    token = set_session_id(session.session_id)
    pipeline_start = time.time()
    use_mock_estimator = getattr(adapter, "_estimator", None) is None

    try:
        # --- Step 1: Index loading ---
        session_log.info(
            "SESSION_START | dataset=%s | beam_width=%s | query_V=%d query_E=%d",
            session.dataset_id, session.beam_width,
            session.normalized_graph.num_vertices if session.normalized_graph else 0,
            session.normalized_graph.num_edges if session.normalized_graph else 0,
        )
        await aggregator.push_event(SSEEvent(
            event="index_loading",
            data={"dataset_id": session.dataset_id},
        ))

        # Load dataset (idempotent -- skips if already loaded)
        loop = asyncio.get_event_loop()
        if use_mock_estimator:
            adapter.load_dataset(session.dataset_id, dataset_root)
        else:
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

        orders = strategic_generate_orders(
            graph, beam_width=session.beam_width, strategy=session.order_strategy,
        )

        if not orders:
            raise RuntimeError("No valid connected expansion orders found")

        est_log.info(
            "ORDERS_GENERATED | count=%d | beam_width=%s",
            len(orders), session.beam_width,
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
        config = resolve_schedule_config(session.schedule_config)

        python_threads = config.python_threads
        omp_threads = config.omp_threads
        total_cores = os.cpu_count() or 1
        thread_log.info(
            "SCHEDULE_CONFIG | mode=%s | python_threads=%d | omp_threads=%d | "
            "total_system_cores=%d | oversubscription_ratio=%.2f",
            config.mode, python_threads, omp_threads,
            total_cores, (python_threads * omp_threads) / total_cores,
        )

        # --- Step 4: Level-wise prefix evaluation ---
        n = graph.num_vertices

        # Pre-build all prefix payloads
        all_prefixes: dict[int, list] = {}
        for i, order in enumerate(orders):
            all_prefixes[i] = build_prefix_subgraphs(graph, order)

        # --- O1 Optimization: Selective Prefix Evaluation ---
        # R1: Skip last prefix (level n-1) — Q_n is the full query graph,
        #     identical for all orders. Estimate once and broadcast.
        # R4: Prefix Memoization — cache by frozenset(vertex_ids) to reuse
        #     estimates across orders sharing the same prefix subgraph.
        optimized = getattr(session, "prefix_eval_mode", "optimized") == "optimized"

        # R1: determine which levels to evaluate via C++
        if optimized and n >= 2:
            eval_levels = list(range(n - 1))  # skip last level
        else:
            eval_levels = list(range(n))

        # R4: memoization cache — key: frozenset of prefix vertex IDs, value: c_hat
        prefix_cache: dict[frozenset[int], float] = {}
        cache_hits = 0
        cache_misses = 0
        r3_skips = 0  # R3: count of skipped evaluations

        # Track completed count for progress
        completed_count = 0
        total_evaluations = len(eval_levels) * len(orders)

        # Capture the session_id for use in worker threads (contextvars don't
        # propagate to ThreadPoolExecutor threads automatically)
        _sid = session.session_id

        for level in eval_levels:
            level_start = time.time()
            with ThreadPoolExecutor(max_workers=python_threads) as executor:
                async def _wait(fut, o_idx):
                    return o_idx, await fut

                wrapped = []
                # Orders resolved from R4 cache (no C++ call)
                cached_results: list[tuple[int, float]] = []
                # R4: within this level, group orders by prefix key to avoid
                # duplicate submissions. Only the first order per unique key
                # gets submitted; others wait for the result and reuse it.
                pending_by_key: dict[frozenset[int], list[int]] = {}
                # Map: order_idx -> prefix_key (for orders submitted to executor)
                submitted_keys: dict[int, frozenset[int]] = {}

                for order_idx in range(len(orders)):
                    prefix = all_prefixes[order_idx][level]

                    # R3: skip orders whose accumulated cost already exceeds threshold
                    if optimized and aggregator.should_skip_order(order_idx):
                        r3_skips += 1
                        completed_count += 1
                        continue

                    if optimized:
                        prefix_key = frozenset(orders[order_idx][:level + 1])

                        # Check cross-level cache first
                        cached_val = prefix_cache.get(prefix_key)
                        if cached_val is not None:
                            cache_hits += 1
                            cached_results.append((order_idx, cached_val))
                            continue

                        # Check if another order at this level already claimed this key
                        if prefix_key in pending_by_key:
                            cache_hits += 1
                            pending_by_key[prefix_key].append(order_idx)
                            continue

                        # First order with this prefix key — submit to executor
                        cache_misses += 1
                        pending_by_key[prefix_key] = []
                        submitted_keys[order_idx] = prefix_key

                    def run_estimation(p, threads, order_i, lvl):
                        _tok = set_session_id(_sid)
                        try:
                            t_name = threading.current_thread().name
                            t_id = threading.get_ident()
                            t0 = time.time()

                            payload_dict = p.to_dict()
                            payload_dict["omp_threads"] = threads

                            _fastest_core = getattr(adapter, "_estimator", None)
                            if _fastest_core is None:
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
                        finally:
                            clear_session_id(_tok)

                    if use_mock_estimator:
                        wrapped.append(
                            asyncio.sleep(
                                0,
                                result=(order_idx, run_estimation(prefix, omp_threads, order_idx, level)),
                            )
                        )
                    else:
                        future = loop.run_in_executor(
                            executor, run_estimation, prefix, omp_threads, order_idx, level
                        )
                        wrapped.append(_wait(future, order_idx))

                # Process cached results first (no C++ call needed)
                for order_idx, c_hat in cached_results:
                    completed_count += 1
                    pfx = all_prefixes[order_idx][level]
                    events = aggregator.record_estimate(
                        order_idx, level, c_hat,
                        n_edges=pfx.num_edges, n_vertices=pfx.num_vertices,
                    )
                    if order_idx < len(session.orders):
                        session.orders[order_idx].prefix_index = level + 1
                        session.orders[order_idx].score = aggregator.trackers[order_idx].score
                        session.orders[order_idx].prefix_estimates.append(c_hat)
                    await aggregator.push_events(events)
                    ranking_event = aggregator.build_ranking_event()
                    await aggregator.push_event(ranking_event)
                    await asyncio.sleep(0)

                # Process C++ estimation results as they complete
                for completed_coro in asyncio.as_completed(wrapped):
                    order_idx, result = await completed_coro
                    completed_count += 1

                    c_hat = result.get("estimated_cardinality", 0.0)

                    # R4: store in cache and broadcast to waiting orders
                    if optimized and order_idx in submitted_keys:
                        pkey = submitted_keys[order_idx]
                        prefix_cache[pkey] = c_hat
                        # Broadcast to orders that were waiting on this key
                        for waiting_idx in pending_by_key.get(pkey, []):
                            completed_count += 1
                            w_pfx = all_prefixes[waiting_idx][level]
                            w_events = aggregator.record_estimate(
                                waiting_idx, level, c_hat,
                                n_edges=w_pfx.num_edges, n_vertices=w_pfx.num_vertices,
                            )
                            if waiting_idx < len(session.orders):
                                session.orders[waiting_idx].prefix_index = level + 1
                                session.orders[waiting_idx].score = aggregator.trackers[waiting_idx].score
                                session.orders[waiting_idx].prefix_estimates.append(c_hat)
                            await aggregator.push_events(w_events)
                            ranking_event = aggregator.build_ranking_event()
                            await aggregator.push_event(ranking_event)
                            await asyncio.sleep(0)

                    # Record in aggregator and get events
                    pfx = all_prefixes[order_idx][level]
                    events = aggregator.record_estimate(
                        order_idx, level, c_hat,
                        n_edges=pfx.num_edges, n_vertices=pfx.num_vertices,
                    )

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
                "LEVEL_DONE | level=%d/%d | elapsed=%.1fms | top3_rank=[%s]",
                level + 1, n, level_elapsed, top_3_str,
            )

        # --- R1: Estimate the last prefix (full query graph) once, broadcast ---
        if optimized and n >= 2:
            last_level = n - 1
            level_start = time.time()

            # All orders share the same Q_n — estimate using the first order's prefix
            first_prefix = all_prefixes[0][last_level]

            def _estimate_last(p, threads):
                _tok = set_session_id(_sid)
                try:
                    payload_dict = p.to_dict()
                    payload_dict["omp_threads"] = threads
                    _fastest_core = getattr(adapter, "_estimator", None)
                    if _fastest_core is None:
                        import random
                        return {"estimated_cardinality": float(random.randint(10, 10000)), "QueryTime": 0.1}
                    return dict(_fastest_core.estimate_prefix(payload_dict))
                finally:
                    clear_session_id(_tok)

            if use_mock_estimator:
                result = _estimate_last(first_prefix, omp_threads)
            else:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    result = await loop.run_in_executor(executor, _estimate_last, first_prefix, omp_threads)
            shared_c_hat = result.get("estimated_cardinality", 0.0)

            est_log.info(
                "R1_BROADCAST | level=%d | shared_c_hat=%.4f | saved_calls=%d",
                last_level, shared_c_hat, len(orders) - 1,
            )

            # Broadcast to all orders — last prefix is the full query graph
            last_n_edges = graph.num_edges
            last_n_vertices = graph.num_vertices
            for order_idx in range(len(orders)):
                # R3: skip pruned orders in R1 broadcast too
                if order_idx in aggregator.skipped_orders:
                    completed_count += 1
                    continue
                completed_count += 1
                events = aggregator.record_estimate(
                    order_idx, last_level, shared_c_hat,
                    n_edges=last_n_edges, n_vertices=last_n_vertices,
                )
                if order_idx < len(session.orders):
                    session.orders[order_idx].prefix_index = last_level + 1
                    session.orders[order_idx].score = aggregator.trackers[order_idx].score
                    session.orders[order_idx].prefix_estimates.append(shared_c_hat)
                await aggregator.push_events(events)

            ranking_event = aggregator.build_ranking_event()
            await aggregator.push_event(ranking_event)
            await asyncio.sleep(0)

            level_elapsed = (time.time() - level_start) * 1000
            top_3 = aggregator.get_top_k()[:3]
            top_3_str = ", ".join([f"O{t['order_id']}:sc={t['score']:.2f}" for t in top_3])
            est_log.info(
                "LEVEL_DONE | level=%d/%d | elapsed=%.1fms | top3_rank=[%s] [R1-broadcast]",
                n, n, level_elapsed, top_3_str,
            )

        # Log R4 cache statistics
        if optimized:
            total_cache_ops = cache_hits + cache_misses
            est_log.info(
                "R4_CACHE_STATS | hits=%d | misses=%d | total=%d | hit_rate=%.1f%%",
                cache_hits, cache_misses, total_cache_ops,
                (cache_hits / total_cache_ops * 100) if total_cache_ops > 0 else 0.0,
            )
            if r3_skips > 0:
                est_log.info(
                    "R3_EARLY_STOP | skipped_evaluations=%d | skipped_orders=%d/%d",
                    r3_skips, len(aggregator.skipped_orders), len(orders),
                )

        # --- Step 5: Run downstream execution (optional) ---
        execution_result = None
        best_order_list = (
            aggregator.trackers[aggregator.best_order_id].order
            if aggregator.best_order_id is not None else None
        )
        if session.run_execution:
            try:
                await aggregator.push_event(SSEEvent(
                    event="execution_started",
                    data={"session_id": session.session_id},
                ))

                if use_mock_estimator:
                    execution_result = execute_downstream_query(
                        dataset_root=dataset_root,
                        dataset_id=session.dataset_id,
                        graph=graph,
                        execution_config=session.execution_config,
                        custom_order=best_order_list,
                    )
                else:
                    execution_result = await asyncio.to_thread(
                        execute_downstream_query,
                        dataset_root=dataset_root,
                        dataset_id=session.dataset_id,
                        graph=graph,
                        execution_config=session.execution_config,
                        custom_order=best_order_list,
                    )

                session.execution_result = execution_result

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
                    "EXECUTION_DONE | embeddings=%s | total_time=%.4fs | eps=%.2f",
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

        session_log.info(
            "SESSION_COMPLETED | best_order_id=%s | best_order=%s | "
            "best_score=%s | orders_evaluated=%d | total_time=%.3fs",
            aggregator.best_order_id, best_order_list,
            aggregator.best_score, len(orders), total_elapsed,
        )

        completion_data: dict = {
            "session_id": session.session_id,
            "best_order_id": aggregator.best_order_id,
            "best_order": best_order_list,
            "best_score": aggregator.best_score,
            "total_orders": len(orders),
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
        logger.exception("Session pipeline failed: %s", e)
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
        clear_session_id(token)
        await aggregator.close()
