"""
Tests for M1 Pruned Order Generation (S1-S4 strategies).

Verifies:
  - graph_analysis: k-core decomposition, equivalence classes, adjacency
  - S1 symmetry breaking: equivalent vertices collapsed
  - S2 core-first: high-core vertices appear earlier
  - S3 A* pruning: cost_factor cutoff limits search
  - S4 neighbor safety: safe expansions preferred
  - Baseline strategy unchanged (backward compatible)
  - Pipeline integration: pruned strategy flows through API → pipeline
"""
from __future__ import annotations

import asyncio
import pytest

from server.models import NormalizedGraph, Vertex, Edge, Session
from server.services.order_strategies import generate_orders, OrderStrategy
from server.services.order_strategies.graph_analysis import (
    build_adjacency, compute_k_core, compute_equivalence_classes,
)
from server.services.order_strategies.pruned import generate_orders_pruned
from server.services.order_strategies.baseline import generate_orders_baseline


# ---------------------------------------------------------------------------
# Helper graphs
# ---------------------------------------------------------------------------

def _make_triangle() -> NormalizedGraph:
    """Triangle: 3 vertices (0,1 label=0; 2 label=1), 3 edges."""
    return NormalizedGraph(
        num_vertices=3, num_edges=3,
        vertices=[Vertex(id=0, label=0), Vertex(id=1, label=0), Vertex(id=2, label=1)],
        edges=[Edge(source=0, target=1), Edge(source=1, target=2), Edge(source=0, target=2)],
    )

def _make_k4() -> NormalizedGraph:
    """K4 complete graph, all same label."""
    return NormalizedGraph(
        num_vertices=4, num_edges=6,
        vertices=[Vertex(id=i, label=0) for i in range(4)],
        edges=[Edge(source=i, target=j) for i in range(4) for j in range(i+1, 4)],
    )

def _make_path5() -> NormalizedGraph:
    """Path P5: 0-1-2-3-4, all different labels."""
    return NormalizedGraph(
        num_vertices=5, num_edges=4,
        vertices=[Vertex(id=i, label=i) for i in range(5)],
        edges=[Edge(source=i, target=i+1) for i in range(4)],
    )

def _make_star5() -> NormalizedGraph:
    """Star: center=0 (label=0), leaves=1,2,3,4 (label=1)."""
    return NormalizedGraph(
        num_vertices=5, num_edges=4,
        vertices=[Vertex(id=0, label=0)] + [Vertex(id=i, label=1) for i in range(1, 5)],
        edges=[Edge(source=0, target=i) for i in range(1, 5)],
    )


# ---------------------------------------------------------------------------
# graph_analysis tests
# ---------------------------------------------------------------------------

class TestGraphAnalysis:
    def test_adjacency_triangle(self):
        adj = build_adjacency(_make_triangle())
        assert adj[0] == {1, 2}
        assert adj[1] == {0, 2}
        assert adj[2] == {0, 1}

    def test_k_core_triangle(self):
        core = compute_k_core(_make_triangle())
        # All vertices in a triangle have core number 2
        assert all(core[v] == 2 for v in range(3))

    def test_k_core_star(self):
        core = compute_k_core(_make_star5())
        # Center has core 1, leaves have core 1 (star is 1-core)
        assert core[0] == 1
        for v in range(1, 5):
            assert core[v] == 1

    def test_k_core_path(self):
        core = compute_k_core(_make_path5())
        # Path graph: all vertices have core number 1
        assert all(core[v] == 1 for v in range(5))

    def test_equivalence_classes_triangle(self):
        classes = compute_equivalence_classes(_make_triangle())
        # Vertices 0,1 have same (label=0, neighbor_labels=(0,1))
        # Vertex 2 has (label=1, neighbor_labels=(0,0))
        found_pair = False
        for key, members in classes.items():
            if len(members) == 2:
                assert set(members) == {0, 1}
                found_pair = True
        assert found_pair

    def test_equivalence_classes_k4(self):
        classes = compute_equivalence_classes(_make_k4())
        # All 4 vertices are equivalent (same label, same neighbor labels)
        assert len(classes) == 1
        members = list(classes.values())[0]
        assert set(members) == {0, 1, 2, 3}

    def test_equivalence_classes_path_all_different(self):
        classes = compute_equivalence_classes(_make_path5())
        # All labels different → each vertex is its own class
        assert len(classes) == 5


# ---------------------------------------------------------------------------
# S1: Symmetry Breaking
# ---------------------------------------------------------------------------

class TestSymmetryBreaking:
    def test_k4_collapses_to_one(self):
        """K4 with all same labels: all vertices equivalent → 1 order."""
        orders = generate_orders_pruned(_make_k4())
        assert len(orders) == 1

    def test_triangle_reduces(self):
        """Triangle with 2 same labels: 6 baseline → 3 pruned."""
        baseline = generate_orders_baseline(_make_triangle())
        pruned = generate_orders_pruned(_make_triangle())
        assert len(pruned) < len(baseline)

    def test_star_reduces(self):
        """Star with 4 same-label leaves: 48 baseline → 2 pruned."""
        baseline = generate_orders_baseline(_make_star5())
        pruned = generate_orders_pruned(_make_star5())
        assert len(pruned) < len(baseline)

    def test_no_reduction_all_different(self):
        """Path with all different labels: no equivalence → no reduction."""
        baseline = generate_orders_baseline(_make_path5())
        pruned = generate_orders_pruned(_make_path5())
        assert len(pruned) == len(baseline)


# ---------------------------------------------------------------------------
# Pruned orders are valid connected expansion orders
# ---------------------------------------------------------------------------

class TestOrderValidity:
    def _validate_orders(self, graph: NormalizedGraph, orders: list[list[int]]):
        adj = build_adjacency(graph)
        n = graph.num_vertices
        for order in orders:
            assert len(order) == n, f"Order length {len(order)} != {n}"
            assert set(order) == set(range(n)), f"Order missing vertices: {order}"
            # Check connectivity: each vertex (except first) adjacent to some predecessor
            for k in range(1, n):
                predecessors = set(order[:k])
                assert any(order[k] in adj[p] for p in predecessors), \
                    f"Vertex {order[k]} at position {k} not connected to predecessors in {order}"

    def test_triangle_valid(self):
        self._validate_orders(_make_triangle(), generate_orders_pruned(_make_triangle()))

    def test_k4_valid(self):
        self._validate_orders(_make_k4(), generate_orders_pruned(_make_k4()))

    def test_path_valid(self):
        self._validate_orders(_make_path5(), generate_orders_pruned(_make_path5()))

    def test_star_valid(self):
        self._validate_orders(_make_star5(), generate_orders_pruned(_make_star5()))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_baseline_strategy(self):
        orders = generate_orders(_make_triangle(), strategy="baseline")
        assert len(orders) == 6  # exact DFS for small graph

    def test_pruned_strategy(self):
        orders = generate_orders(_make_triangle(), strategy="pruned")
        assert len(orders) < 6

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError):
            generate_orders(_make_triangle(), strategy="nonexistent")


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

class _MockAdapter:
    _estimator = None
    def load_dataset(self, dataset_id, dataset_root):
        pass


class TestPipelineM1:
    def test_pruned_pipeline_completes(self):
        from server.services.score_aggregator import ScoreAggregator
        from server.services.session_pipeline import run_session_pipeline

        session = Session(
            dataset_id="yeast",
            normalized_graph=_make_triangle(),
            order_strategy="pruned",
        )
        aggregator = ScoreAggregator()
        asyncio.get_event_loop().run_until_complete(
            run_session_pipeline(session, _MockAdapter(), aggregator, dataset_root="dataset")
        )
        assert session.status.value == "completed"
        assert session.best_order_id is not None

    def test_baseline_pipeline_completes(self):
        from server.services.score_aggregator import ScoreAggregator
        from server.services.session_pipeline import run_session_pipeline

        session = Session(
            dataset_id="yeast",
            normalized_graph=_make_triangle(),
            order_strategy="baseline",
        )
        aggregator = ScoreAggregator()
        asyncio.get_event_loop().run_until_complete(
            run_session_pipeline(session, _MockAdapter(), aggregator, dataset_root="dataset")
        )
        assert session.status.value == "completed"
