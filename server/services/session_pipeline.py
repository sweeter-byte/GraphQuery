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
import time
from typing import Any

from ..models import (
    Session, SessionStatus, SSEEvent, OrderState,
)
from .estimator_adapter import EstimatorAdapter
from .order_generator import generate_orders
from .prefix_builder import build_prefix_subgraphs
from .score_aggregator import ScoreAggregator

logger = logging.getLogger(__name__)


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
    try:
        # --- Step 1: Index loading ---
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

        # --- Step 4: Level-wise prefix evaluation ---
        # Evaluate all orders level by level (level-wise evolution)
        # This ensures smooth, synchronized SSE updates across branches
        n = graph.num_vertices

        # Pre-build all prefix payloads
        all_prefixes: dict[int, list] = {}
        for i, order in enumerate(orders):
            all_prefixes[i] = build_prefix_subgraphs(graph, order)

        for level in range(n):
            for order_idx in range(len(orders)):
                prefix = all_prefixes[order_idx][level]

                # Run C++ estimation in thread pool (CPU-bound)
                result = await loop.run_in_executor(
                    None, adapter.estimate_prefix, prefix
                )

                c_hat = result.get("estimated_cardinality", 0.0)

                # Record in aggregator and get events
                events = aggregator.record_estimate(order_idx, level, c_hat)

                # Update session state
                if order_idx < len(session.orders):
                    session.orders[order_idx].prefix_index = level + 1
                    session.orders[order_idx].score = aggregator.trackers[order_idx].score
                    session.orders[order_idx].prefix_estimates.append(c_hat)

                # Push events
                await aggregator.push_events(events)

            # After each level, emit a ranking update
            ranking_event = aggregator.build_ranking_event()
            await aggregator.push_event(ranking_event)

            # Yield control to allow SSE batching to flush
            await asyncio.sleep(0)

        # --- Step 5: Session completed ---
        session.status = SessionStatus.COMPLETED
        session.best_order_id = aggregator.best_order_id
        session.best_score = aggregator.best_score
        session.completed_at = time.time()

        await aggregator.push_event(SSEEvent(
            event="session_completed",
            data={
                "session_id": session.session_id,
                "best_order_id": aggregator.best_order_id,
                "best_order": aggregator.trackers[aggregator.best_order_id].order
                    if aggregator.best_order_id is not None else None,
                "best_score": aggregator.best_score,
                "total_orders_evaluated": len(orders),
            },
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
