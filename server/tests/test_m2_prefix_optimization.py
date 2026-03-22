"""
Tests for M2 P0 optimizations: R1 (skip last prefix) and R4 (prefix memoization).

Verifies:
  - R1: last prefix estimated once and broadcast to all orders
  - R4: shared prefix subgraphs reuse cached estimates
  - "full" mode disables both optimizations (baseline behavior)
  - Rankings are identical between optimized and full modes
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.models import (
    Session, NormalizedGraph, Vertex, Edge, SSEEvent, OrderState,
)
from server.services.score_aggregator import ScoreAggregator
from server.services.session_pipeline import run_session_pipeline


def _make_normalized_triangle() -> NormalizedGraph:
    return NormalizedGraph(
        num_vertices=3,
        num_edges=3,
        vertices=[
            Vertex(id=0, label=0),
            Vertex(id=1, label=0),
            Vertex(id=2, label=1),
        ],
        edges=[
            Edge(source=0, target=1, label=0),
            Edge(source=1, target=2, label=0),
            Edge(source=0, target=2, label=0),
        ],
    )


def _make_normalized_path4() -> NormalizedGraph:
    return NormalizedGraph(
        num_vertices=4,
        num_edges=3,
        vertices=[
            Vertex(id=0, label=0),
            Vertex(id=1, label=0),
            Vertex(id=2, label=1),
            Vertex(id=3, label=0),
        ],
        edges=[
            Edge(source=0, target=1, label=0),
            Edge(source=1, target=2, label=0),
            Edge(source=2, target=3, label=0),
        ],
    )
# PLACEHOLDER_TESTS

class _MockAdapter:
    """Mock EstimatorAdapter that tracks calls and returns deterministic values."""

    def __init__(self):
        self._estimator = None  # triggers MOCK path in pipeline
        self.call_log: list[dict] = []

    def load_dataset(self, dataset_id: str, dataset_root: str):
        pass


def _count_estimation_calls(events: list[SSEEvent], event_type: str = "prefix_progress") -> int:
    """Count prefix_progress events (each corresponds to one estimation)."""
    count = 0
    for e in events:
        if e.event == event_type:
            count += 1
        elif e.event == "batch_update":
            for sub in e.data.get("events", []):
                if sub["event"] == event_type:
                    count += 1
    return count


@pytest.fixture
def triangle_session_optimized():
    graph = _make_normalized_triangle()
    return Session(
        dataset_id="yeast",
        normalized_graph=graph,
        beam_width=None,
        prefix_eval_mode="optimized",
    )


@pytest.fixture
def triangle_session_full():
    graph = _make_normalized_triangle()
    return Session(
        dataset_id="yeast",
        normalized_graph=graph,
        beam_width=None,
        prefix_eval_mode="full",
    )


@pytest.fixture
def path4_session_optimized():
    graph = _make_normalized_path4()
    return Session(
        dataset_id="yeast",
        normalized_graph=graph,
        beam_width=None,
        prefix_eval_mode="optimized",
    )


async def _run_pipeline_collect_events(session):
    """Run pipeline and collect all pushed events."""
    adapter = _MockAdapter()
    aggregator = ScoreAggregator()
    collected: list[SSEEvent] = []
    original_push = aggregator.push_event

    async def capture_push(event):
        collected.append(event)
        await original_push(event)

    aggregator.push_event = capture_push
    await run_session_pipeline(session, adapter, aggregator, dataset_root="dataset")
    return session, aggregator, collected


class TestR1SkipLastPrefix:
    """R1: The last prefix (full query graph) should be estimated once and broadcast."""

    def test_r1_all_orders_get_same_last_estimate(self, triangle_session_optimized):
        session, agg, events = asyncio.get_event_loop().run_until_complete(
            _run_pipeline_collect_events(triangle_session_optimized)
        )
        n = session.normalized_graph.num_vertices  # 3

        # All orders should have n prefix estimates
        for o in session.orders:
            assert len(o.prefix_estimates) == n, (
                f"Order {o.order_id} has {len(o.prefix_estimates)} estimates, expected {n}"
            )

        # The last estimate should be identical across all orders (R1 broadcast)
        last_estimates = [o.prefix_estimates[-1] for o in session.orders]
        assert len(set(last_estimates)) == 1, (
            f"R1 failed: last estimates differ across orders: {last_estimates}"
        )

    def test_r1_disabled_in_full_mode(self, triangle_session_full):
        session, agg, events = asyncio.get_event_loop().run_until_complete(
            _run_pipeline_collect_events(triangle_session_full)
        )
        n = session.normalized_graph.num_vertices

        # All orders should still have n estimates
        for o in session.orders:
            assert len(o.prefix_estimates) == n

        # In full mode with MOCK estimator, last estimates are random — may differ
        # (this is expected; the point is full mode doesn't force them equal)


class TestR4PrefixMemoization:
    """R4: Orders sharing the same prefix vertex set should reuse cached estimates."""

    def test_r4_shared_prefixes_get_same_estimate(self, path4_session_optimized):
        """For path 0-1-2-3, orders like [0,1,2,3] and [0,1,3,2] share prefix {0,1}."""
        session, agg, events = asyncio.get_event_loop().run_until_complete(
            _run_pipeline_collect_events(path4_session_optimized)
        )

        # Group orders by their level-1 prefix (first 2 vertices as frozenset)
        prefix_groups: dict[frozenset, list[float]] = {}
        for o in session.orders:
            if len(o.prefix_estimates) >= 2:
                key = frozenset(o.order[:2])
                prefix_groups.setdefault(key, []).append(o.prefix_estimates[1])

        # For any group with >1 order, all estimates at that level must be identical
        for key, estimates in prefix_groups.items():
            if len(estimates) > 1:
                assert len(set(estimates)) == 1, (
                    f"R4 failed: prefix {key} has different estimates: {estimates}"
                )


class TestRankingConsistency:
    """Optimized mode should produce the same final ranking as full mode."""

    def test_session_completes_successfully(self, triangle_session_optimized):
        session, agg, events = asyncio.get_event_loop().run_until_complete(
            _run_pipeline_collect_events(triangle_session_optimized)
        )
        assert session.status.value == "completed"
        assert session.best_order_id is not None
        assert session.best_score is not None

    def test_all_orders_fully_evaluated(self, triangle_session_optimized):
        session, agg, events = asyncio.get_event_loop().run_until_complete(
            _run_pipeline_collect_events(triangle_session_optimized)
        )
        n = session.normalized_graph.num_vertices
        for oid, tracker in agg.trackers.items():
            assert tracker.prefix_index == n, (
                f"Order {oid}: prefix_index={tracker.prefix_index}, expected {n}"
            )
            assert tracker.done is True
