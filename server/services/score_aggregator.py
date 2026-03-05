"""
Score Aggregator with real-time ranking and SSE event batching.

Responsibilities:
  - Accumulate prefix scores per order: score(O) = sum(omega_k * c_hat_k)
  - Maintain Top-K ranking across all orders
  - Buffer SSE events with 50-100ms debounce window
  - Emit batched events to avoid overwhelming the frontend
"""
from __future__ import annotations

import asyncio
import heapq
import logging
import time
from typing import Any

from ..models import SSEEvent

logger = logging.getLogger(__name__)

# Weight function — hardcoded to 1.0 per the technical supplement.
# Future: implement dynamic weighting here without touching C++ or frontend.
def get_weight(k: int, n: int) -> float:
    return 1.0


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

    def __init__(self, top_k: int = 10):
        self.top_k = top_k
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

    def record_estimate(self, order_id: int, prefix_index: int, c_hat: float) -> list[SSEEvent]:
        """
        Record an estimation result and return generated events.
        Called from the worker coroutine; events are also pushed to the internal queue.
        """
        tracker = self.trackers[order_id]
        k = prefix_index + 1  # 1-indexed for formula
        n = tracker.n_prefixes
        omega = get_weight(k, n)

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

        # Check for best order change
        if self.best_score is None or tracker.score < self.best_score:
            old_best = self.best_order_id
            self.best_order_id = order_id
            self.best_score = tracker.score
            if old_best != order_id:
                events.append(SSEEvent(
                    event="best_order_selected",
                    data={
                        "order_id": order_id,
                        "order": tracker.order,
                        "score": tracker.score,
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
        return SSEEvent(
            event="batch_update",
            data={
                "events": [{"event": e.event, "data": e.data} for e in events],
                "count": len(events),
            },
        )
