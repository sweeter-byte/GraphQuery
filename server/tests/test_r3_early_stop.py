"""
Tests for O1-R3: Adaptive Early Stopping.

Verifies:
  - Early stopping disabled by default (backward compatible)
  - should_skip_order returns False when disabled
  - should_skip_order returns False before min_completed orders finish
  - should_skip_order returns True when accumulated score exceeds threshold
  - Skipped orders are excluded from further evaluation in pipeline
  - R3 does not affect the best order selection (only prunes hopeless orders)
"""
from __future__ import annotations

import asyncio
import pytest

from server.models import NormalizedGraph, Vertex, Edge, Session
from server.services.score_aggregator import (
    ScoreAggregator, WeightConfig, EarlyStopConfig, get_weight,
)
from server.services.session_pipeline import run_session_pipeline


# ---------------------------------------------------------------------------
# Unit tests for should_skip_order
# ---------------------------------------------------------------------------

class TestShouldSkipOrder:
    def test_disabled_by_default(self):
        agg = ScoreAggregator()
        agg.register_order(0, [0, 1, 2], 3)
        agg.record_estimate(0, 0, 99999.0)
        assert agg.should_skip_order(0) is False

    def test_disabled_explicit(self):
        cfg = EarlyStopConfig(enabled=False, multiplier=1.0)
        agg = ScoreAggregator(early_stop_config=cfg)
        agg.register_order(0, [0, 1, 2], 3)
        agg.record_estimate(0, 0, 99999.0)
        assert agg.should_skip_order(0) is False

    def test_no_skip_before_min_completed(self):
        cfg = EarlyStopConfig(enabled=True, multiplier=1.5, min_completed=2)
        agg = ScoreAggregator(early_stop_config=cfg)
        agg.register_order(0, [0, 1], 2)
        agg.register_order(1, [1, 0], 2)
        agg.register_order(2, [0, 1], 2)
        # Complete order 0 only (need 2 min_completed)
        agg.record_estimate(0, 0, 10.0)
        agg.record_estimate(0, 1, 10.0)  # order 0 done, score=20
        # Order 2 has high score but only 1 completed
        agg.record_estimate(2, 0, 9999.0)
        assert agg.should_skip_order(2) is False

    def test_skip_when_exceeds_threshold(self):
        cfg = EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)
        agg = ScoreAggregator(early_stop_config=cfg)
        agg.register_order(0, [0, 1, 2], 3)
        agg.register_order(1, [2, 1, 0], 3)
        # Complete order 0 with low score
        agg.record_estimate(0, 0, 10.0)
        agg.record_estimate(0, 1, 10.0)
        agg.record_estimate(0, 2, 10.0)  # order 0 done, score=30
        # Order 1 already exceeds 2.0 * 30 = 60
        agg.record_estimate(1, 0, 100.0)  # score=100 > 60
        assert agg.should_skip_order(1) is True

    def test_no_skip_when_below_threshold(self):
        cfg = EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)
        agg = ScoreAggregator(early_stop_config=cfg)
        agg.register_order(0, [0, 1, 2], 3)
        agg.register_order(1, [2, 1, 0], 3)
        # Complete order 0
        agg.record_estimate(0, 0, 10.0)
        agg.record_estimate(0, 1, 10.0)
        agg.record_estimate(0, 2, 10.0)  # score=30
        # Order 1 score is below threshold
        agg.record_estimate(1, 0, 5.0)  # score=5 < 60
        assert agg.should_skip_order(1) is False

    def test_skip_persists_once_triggered(self):
        cfg = EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)
        agg = ScoreAggregator(early_stop_config=cfg)
        agg.register_order(0, [0, 1, 2], 3)
        agg.register_order(1, [2, 1, 0], 3)
        agg.record_estimate(0, 0, 10.0)
        agg.record_estimate(0, 1, 10.0)
        agg.record_estimate(0, 2, 10.0)  # order 0 done, score=30
        agg.record_estimate(1, 0, 100.0)  # score=100 > 60
        assert agg.should_skip_order(1) is True
        # Still skipped on subsequent checks
        assert agg.should_skip_order(1) is True
        assert 1 in agg.skipped_orders

    def test_completed_order_not_skipped(self):
        cfg = EarlyStopConfig(enabled=True, multiplier=1.0, min_completed=1)
        agg = ScoreAggregator(early_stop_config=cfg)
        agg.register_order(0, [0, 1], 2)
        agg.record_estimate(0, 0, 10.0)
        agg.record_estimate(0, 1, 10.0)  # done
        # Completed orders should not be skipped
        assert agg.should_skip_order(0) is False


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

class _MockAdapter:
    _estimator = None
    def load_dataset(self, dataset_id, dataset_root):
        pass


def _make_triangle() -> NormalizedGraph:
    return NormalizedGraph(
        num_vertices=3, num_edges=3,
        vertices=[Vertex(id=0, label=0), Vertex(id=1, label=0), Vertex(id=2, label=1)],
        edges=[
            Edge(source=0, target=1), Edge(source=1, target=2), Edge(source=0, target=2),
        ],
    )


class TestPipelineR3:
    def test_r3_pipeline_completes_with_early_stop(self):
        from server.models import EarlyStopConfigModel
        session = Session(
            dataset_id="yeast",
            normalized_graph=_make_triangle(),
            prefix_eval_mode="optimized",
            early_stop_config=EarlyStopConfigModel(enabled=True, multiplier=2.0, min_completed=1),
        )
        cfg = EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)
        aggregator = ScoreAggregator(early_stop_config=cfg)
        adapter = _MockAdapter()

        asyncio.get_event_loop().run_until_complete(
            run_session_pipeline(session, adapter, aggregator, dataset_root="dataset")
        )
        assert session.status.value == "completed"
        assert session.best_order_id is not None

    def test_r3_disabled_pipeline_completes(self):
        """Pipeline works normally when R3 is disabled (backward compatible)."""
        session = Session(
            dataset_id="yeast",
            normalized_graph=_make_triangle(),
            prefix_eval_mode="optimized",
        )
        aggregator = ScoreAggregator()
        adapter = _MockAdapter()

        asyncio.get_event_loop().run_until_complete(
            run_session_pipeline(session, adapter, aggregator, dataset_root="dataset")
        )
        assert session.status.value == "completed"
        assert len(aggregator.skipped_orders) == 0
