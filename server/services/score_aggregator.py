"""
Score Aggregator with real-time ranking and SSE event batching.

Responsibilities:
  - Accumulate prefix scores per order: score(O) = sum(omega_k * c_hat_k)
  - Maintain Top-K ranking across all orders
  - Buffer SSE events with 50-100ms debounce window
  - Emit batched events to avoid overwhelming the frontend

Weight modes:
  - "uniform": omega_k = 1.0 (original baseline)
  - "weighted": omega(k, Q_k) = alpha(k) * beta(Q_k)
      alpha(k) = ((n - k + 1) / n) ^ gamma       — position decay
      beta(Q_k) = 1 + lambda * (E_k - V_k + 1) / V_k  — topology factor
"""
from __future__ import annotations

import asyncio
import heapq
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

from ..models import SSEEvent

logger = logging.getLogger(__name__)
sse_log = logging.getLogger("gq.session")


@dataclass
class WeightConfig:
    """Configuration for the cost model weight function.

    Attributes:
        mode: "uniform" (omega=1.0) or "weighted" (position-topology aware).
        gamma: Position decay exponent (>0). Higher = more weight on early prefixes.
        lam: Topology sensitivity coefficient (>=0). Higher = more weight on cyclic prefixes.
    """
    mode: str = "uniform"
    gamma: float = 1.0
    lam: float = 0.0


# ---------------------------------------------------------------------------
# Weight functions
# ---------------------------------------------------------------------------

def get_weight(
    k: int,
    n: int,
    *,
    n_edges: int = 0,
    n_vertices: int = 0,
    config: WeightConfig | None = None,
) -> float:
    """Compute weight omega for the k-th prefix (1-indexed) of an n-vertex query.

    When config is None or config.mode == "uniform", returns 1.0 (original behavior).
    When config.mode == "weighted", returns alpha(k) * beta(Q_k).
    """
    if config is None or config.mode == "uniform":
        return 1.0

    # --- Position factor: alpha(k) = ((n - k + 1) / n) ^ gamma ---
    gamma = config.gamma
    alpha = ((n - k + 1) / n) ** gamma if n > 0 else 1.0

    # --- Topology factor: beta(Q_k) = 1 + lam * (E_k - V_k + 1) / V_k ---
    # When Q_k is a tree: E_k = V_k - 1, so beta = 1.
    # More cycles → higher beta → more informative prefix gets higher weight.
    lam = config.lam
    if n_vertices > 0 and lam > 0:
        excess_edges = n_edges - (n_vertices - 1)  # 0 for tree, >0 for cyclic
        beta = 1.0 + lam * max(excess_edges, 0) / n_vertices
    else:
        beta = 1.0

    return alpha * beta


class OrderTracker:
    """Tracks the estimation state for a single order."""

    def __init__(self, order_id: int, order: list[int], n_prefixes: int):
        self.order_id = order_id
        self.order = order
        self.n_prefixes = n_prefixes
        self.prefix_index = 0  # next prefix to evaluate (0-indexed)
        self.estimates: list[float] = []
        self.score = 0.0
        self.done = False


class ScoreAggregator:
    """
    Manages scoring, ranking, and SSE event buffering for a session.

    The aggregator maintains an async queue of SSE events. High-frequency
    events are buffered in a 50-100ms window and emitted as batched arrays.
    """

    BATCH_INTERVAL_MS = 75  # 50-100ms debounce window

    def __init__(self, top_k: int = 10, weight_config: WeightConfig | None = None):
        self.top_k = top_k
        self.weight_config = weight_config or WeightConfig()
        self.trackers: dict[int, OrderTracker] = {}
        self.ranking: list[tuple[float, int]] = []  # min-heap of (score, order_id)
        self.best_order_id: int | None = None
        self.best_score: float | None = None

        # SSE event queue
        self._event_queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue()
        # Batch buffer
        self._batch_buffer: list[SSEEvent] = []
        self._last_flush_time: float = 0.0
        self._closed = False

    def register_order(self, order_id: int, order: list[int], n_prefixes: int) -> None:
        self.trackers[order_id] = OrderTracker(order_id, order, n_prefixes)

    def record_estimate(
        self,
        order_id: int,
        prefix_index: int,
        c_hat: float,
        *,
        n_edges: int = 0,
        n_vertices: int = 0,
    ) -> list[SSEEvent]:
        """
        Record an estimation result and return generated events.
        Called from the worker coroutine; events are also pushed to the internal queue.

        Parameters
        ----------
        n_edges, n_vertices : prefix subgraph topology, used by weighted mode.
            Ignored when weight_config.mode == "uniform".
        """
        tracker = self.trackers[order_id]
        k = prefix_index + 1  # 1-indexed for formula
        n = tracker.n_prefixes
        omega = get_weight(
            k, n,
            n_edges=n_edges, n_vertices=n_vertices,
            config=self.weight_config,
        )

        tracker.estimates.append(c_hat)
        tracker.score += omega * c_hat
        tracker.prefix_index = prefix_index + 1

        events: list[SSEEvent] = []

        # prefix_progress event
        events.append(SSEEvent(
            event="prefix_progress",
            data={
                "order_id": order_id,
                "order": tracker.order,
                "prefix_index": prefix_index,
                "total_prefixes": n,
                "estimated_cardinality": c_hat,
                "weight": omega,
                "accumulated_score": tracker.score,
            },
        ))

        # score_updated event
        events.append(SSEEvent(
            event="score_updated",
            data={
                "order_id": order_id,
                "score": tracker.score,
                "prefix_index": prefix_index,
            },
        ))

        # Check if order is complete
        if tracker.prefix_index >= n:
            tracker.done = True

        # Update ranking
        self._update_ranking(order_id, tracker.score)

        # Update best order to the current rank 1
        if self.ranking:
            current_best_score, current_best_order_id = self.ranking[0]
            if current_best_order_id != self.best_order_id or current_best_score != self.best_score:
                logger.debug(
                    "RANK_SHIFT | previous_best_id=%s -> new_best_id=%s | new_score=%.2f",
                    self.best_order_id, current_best_order_id, current_best_score
                )
                self.best_order_id = current_best_order_id
                self.best_score = current_best_score
                events.append(SSEEvent(
                    event="best_order_selected",
                    data={
                        "order_id": current_best_order_id,
                        "order": self.trackers[current_best_order_id].order,
                        "score": current_best_score,
                    },
                ))

        return events

    def _update_ranking(self, order_id: int, score: float) -> None:
        # Rebuild ranking (simple approach for correctness)
        self.ranking = [
            (t.score, t.order_id)
            for t in self.trackers.values()
        ]
        self.ranking.sort()

    def get_top_k(self) -> list[dict[str, Any]]:
        return [
            {
                "rank": i + 1,
                "order_id": oid,
                "order": self.trackers[oid].order,
                "score": sc,
                "prefix_index": self.trackers[oid].prefix_index,
                "total_prefixes": self.trackers[oid].n_prefixes,
            }
            for i, (sc, oid) in enumerate(self.ranking[:self.top_k])
        ]

    def build_ranking_event(self) -> SSEEvent:
        return SSEEvent(
            event="ranking_updated",
            data={
                "top_k": self.get_top_k(),
                "total_orders": len(self.trackers),
            },
        )

    async def push_event(self, event: SSEEvent) -> None:
        """Push an event into the batching buffer."""
        if self._closed:
            return
        await self._event_queue.put(event)

    async def push_events(self, events: list[SSEEvent]) -> None:
        """Push multiple events."""
        for e in events:
            await self.push_event(e)

    async def close(self) -> None:
        """Signal end of stream."""
        self._closed = True
        await self._event_queue.put(None)

    async def stream_events(self):
        """
        Async generator yielding SSE events with debounce batching.

        High-frequency events (prefix_progress, score_updated) are buffered
        for BATCH_INTERVAL_MS and emitted as a batch. Low-frequency events
        (session_started, session_completed, etc.) are emitted immediately.
        """
        IMMEDIATE_EVENTS = {
            "index_loading", "index_loaded", "session_started",
            "session_completed", "session_failed",
            "best_order_selected", "order_generated",
            "execution_started", "execution_completed",
        }
        BATCHABLE_EVENTS = {"prefix_progress", "score_updated", "ranking_updated"}

        batch: list[SSEEvent] = []
        batch_deadline: float | None = None

        while True:
            # Calculate timeout for batch flush
            timeout: float | None = None
            if batch and batch_deadline is not None:
                timeout = max(0.0, batch_deadline - time.monotonic())

            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Batch deadline reached — flush
                if batch:
                    yield self._make_batch_event(batch)
                    batch = []
                    batch_deadline = None
                continue

            if event is None:
                # Stream closed — flush remaining batch
                if batch:
                    yield self._make_batch_event(batch)
                break

            if event.event in IMMEDIATE_EVENTS:
                # Flush any pending batch first
                if batch:
                    yield self._make_batch_event(batch)
                    batch = []
                    batch_deadline = None
                yield event
                # Terminal events end the stream
                if event.event in ("session_completed", "session_failed"):
                    break
            elif event.event in BATCHABLE_EVENTS:
                batch.append(event)
                if batch_deadline is None:
                    batch_deadline = time.monotonic() + self.BATCH_INTERVAL_MS / 1000.0
            else:
                # Unknown event type — emit immediately
                if batch:
                    yield self._make_batch_event(batch)
                    batch = []
                    batch_deadline = None
                yield event

    def _make_batch_event(self, events: list[SSEEvent]) -> SSEEvent:
        """Combine multiple events into a single batch_update event."""
        if len(events) == 1:
            return events[0]
        sse_log.debug(
            "SSE_BATCH_FLUSH | events=%d | types=%s",
            len(events),
            ", ".join(e.event for e in events),
        )
        return SSEEvent(
            event="batch_update",
            data={
                "events": [{"event": e.event, "data": e.data} for e in events],
                "count": len(events),
            },
        )
