"""
Comprehensive pytest suite for the Graph Query Planning System backend.

Tests cover:
  - Unit tests for query validation, order generation, prefix building
  - API endpoint tests (datasets, sessions)
  - SSE streaming integration test
  - End-to-end test with real C++ estimator (if available)
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
import httpx
from fastapi.testclient import TestClient

from server.main import app
from server.models import (
    QueryGraph, Vertex, Edge, NormalizedGraph, PrefixPayload,
)
from server.services.query_validator import validate_and_normalize, ValidationError
from server.services.order_generator import (
    enumerate_connected_orders_exact,
    enumerate_connected_orders_beam,
    generate_orders,
)
from server.services.prefix_builder import build_prefix_subgraphs
from server.services.score_aggregator import ScoreAggregator, get_weight

client = TestClient(app)


# =============================================================================
# Fixtures
# =============================================================================

def _make_triangle_query() -> QueryGraph:
    """A simple triangle: 3 vertices, 3 edges."""
    return QueryGraph(
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


def _make_path4_query() -> QueryGraph:
    """A 4-vertex path."""
    return QueryGraph(
        vertices=[
            Vertex(id=10, label=0),
            Vertex(id=20, label=0),
            Vertex(id=30, label=1),
            Vertex(id=40, label=0),
        ],
        edges=[
            Edge(source=10, target=20, label=0),
            Edge(source=20, target=30, label=0),
            Edge(source=30, target=40, label=0),
        ],
    )


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


# =============================================================================
# Unit Tests: Query Validation
# =============================================================================

class TestQueryValidation:
    def test_valid_triangle(self):
        q = _make_triangle_query()
        result = validate_and_normalize(q)
        assert result.num_vertices == 3
        assert result.num_edges == 3
        assert all(v.id in [0, 1, 2] for v in result.vertices)

    def test_valid_path_with_normalization(self):
        q = _make_path4_query()
        result = validate_and_normalize(q)
        assert result.num_vertices == 4
        # Original IDs 10,20,30,40 -> normalized 0,1,2,3
        assert result.vertex_id_mapping == {10: 0, 20: 1, 30: 2, 40: 3}
        # Check edges reference normalized IDs
        for e in result.edges:
            assert 0 <= e.source < 4
            assert 0 <= e.target < 4

    def test_disconnected_graph_rejected(self):
        q = QueryGraph(
            vertices=[
                Vertex(id=0, label=0),
                Vertex(id=1, label=0),
                Vertex(id=2, label=0),
            ],
            edges=[Edge(source=0, target=1, label=0)],
        )
        with pytest.raises(ValidationError) as exc_info:
            validate_and_normalize(q)
        assert exc_info.value.code == "DISCONNECTED_GRAPH"

    def test_self_loop_rejected(self):
        q = QueryGraph(
            vertices=[Vertex(id=0, label=0), Vertex(id=1, label=0)],
            edges=[
                Edge(source=0, target=1, label=0),
                Edge(source=0, target=0, label=0),
            ],
        )
        with pytest.raises(ValidationError) as exc_info:
            validate_and_normalize(q)
        assert exc_info.value.code == "SELF_LOOP"

    def test_invalid_edge_endpoint(self):
        q = QueryGraph(
            vertices=[Vertex(id=0, label=0), Vertex(id=1, label=0)],
            edges=[Edge(source=0, target=99, label=0)],
        )
        with pytest.raises(ValidationError) as exc_info:
            validate_and_normalize(q)
        assert exc_info.value.code == "INVALID_EDGE_ENDPOINT"

    def test_duplicate_vertex_id(self):
        q = QueryGraph(
            vertices=[Vertex(id=0, label=0), Vertex(id=0, label=1)],
            edges=[Edge(source=0, target=0, label=0)],
        )
        with pytest.raises(ValidationError) as exc_info:
            validate_and_normalize(q)
        assert exc_info.value.code == "DUPLICATE_VERTEX_ID"


# =============================================================================
# Unit Tests: Order Generation
# =============================================================================

class TestOrderGeneration:
    def test_triangle_exact_orders(self):
        graph = _make_normalized_triangle()
        orders = enumerate_connected_orders_exact(graph)
        # Triangle: every permutation is valid since all vertices connected
        # 3! = 6 orders
        assert len(orders) == 6
        # Each order should be a permutation of [0,1,2]
        for order in orders:
            assert sorted(order) == [0, 1, 2]

    def test_path_exact_orders(self):
        graph = _make_normalized_path4()
        orders = enumerate_connected_orders_exact(graph)
        # 4-path: must start from an endpoint or grow connected
        assert len(orders) > 0
        for order in orders:
            assert sorted(order) == [0, 1, 2, 3]
            # Verify connected expansion constraint
            visited = {order[0]}
            for i in range(1, len(order)):
                v = order[i]
                assert any(
                    frozenset((v, u)) in {frozenset((e.source, e.target)) for e in graph.edges}
                    for u in visited
                ), f"Vertex {v} at position {i} not adjacent to visited set"
                visited.add(v)

    def test_beam_search_returns_valid_orders(self):
        graph = _make_normalized_path4()
        orders = enumerate_connected_orders_beam(graph, beam_width=10)
        assert len(orders) > 0
        for order in orders:
            assert sorted(order) == [0, 1, 2, 3]

    def test_beam_search_truncation(self):
        graph = _make_normalized_triangle()
        orders = enumerate_connected_orders_beam(graph, beam_width=2)
        # Should have at most 2 orders
        assert 0 < len(orders) <= 2

    def test_generate_orders_dual_mode(self):
        # Small graph -> exact mode
        graph = _make_normalized_triangle()
        orders_exact = generate_orders(graph, beam_width=None, exact_threshold=7)
        assert len(orders_exact) == 6

        # Forced beam mode
        orders_beam = generate_orders(graph, beam_width=3, exact_threshold=7)
        assert 0 < len(orders_beam) <= 3

    def test_deterministic_ordering(self):
        """Same input should always produce same output (DFS tie-breaking)."""
        graph = _make_normalized_triangle()
        orders1 = enumerate_connected_orders_exact(graph)
        orders2 = enumerate_connected_orders_exact(graph)
        assert orders1 == orders2


# =============================================================================
# Unit Tests: Prefix Builder
# =============================================================================

class TestPrefixBuilder:
    def test_triangle_prefixes(self):
        graph = _make_normalized_triangle()
        order = [0, 1, 2]
        prefixes = build_prefix_subgraphs(graph, order)

        assert len(prefixes) == 3

        # k=1: single vertex
        p1 = prefixes[0]
        assert p1.num_vertices == 1
        assert p1.num_edges == 0

        # k=2: edge (0,1)
        p2 = prefixes[1]
        assert p2.num_vertices == 2
        assert p2.num_edges == 1

        # k=3: full triangle
        p3 = prefixes[2]
        assert p3.num_vertices == 3
        assert p3.num_edges == 3

    def test_prefix_payload_dict(self):
        graph = _make_normalized_triangle()
        order = [0, 1, 2]
        prefixes = build_prefix_subgraphs(graph, order)
        d = prefixes[2].to_dict()
        assert d["num_vertices"] == 3
        assert d["num_edges"] == 3
        assert len(d["vertices"]) == 3
        assert len(d["edges"]) == 3

    def test_path_prefixes_edge_count(self):
        graph = _make_normalized_path4()
        order = [0, 1, 2, 3]
        prefixes = build_prefix_subgraphs(graph, order)
        # Path: each step adds exactly one edge
        for i, p in enumerate(prefixes):
            assert p.num_vertices == i + 1
            assert p.num_edges == i  # 0, 1, 2, 3 edges

    def test_prefix_labels_preserved(self):
        graph = _make_normalized_path4()
        order = [0, 1, 2, 3]
        prefixes = build_prefix_subgraphs(graph, order)
        # In the full graph, vertex 2 has label=1
        # After renormalization in prefix k=4, vertex 2 keeps label=1
        full = prefixes[3]
        labels = {v.id: v.label for v in full.vertices}
        assert labels[2] == 1  # vertex 2 in the 0-indexed renormalized graph


# =============================================================================
# Unit Tests: Score Aggregator
# =============================================================================

class TestScoreAggregator:
    def test_weight_function(self):
        assert get_weight(1, 5) == 1.0
        assert get_weight(3, 5) == 1.0

    def test_record_estimate(self):
        agg = ScoreAggregator()
        agg.register_order(0, [0, 1, 2], 3)

        events = agg.record_estimate(0, 0, 100.0)
        assert any(e.event == "prefix_progress" for e in events)
        assert agg.trackers[0].score == 100.0

        events = agg.record_estimate(0, 1, 200.0)
        assert agg.trackers[0].score == 300.0

    def test_ranking_update(self):
        agg = ScoreAggregator()
        agg.register_order(0, [0, 1, 2], 3)
        agg.register_order(1, [2, 1, 0], 3)

        agg.record_estimate(0, 0, 500.0)
        agg.record_estimate(1, 0, 100.0)

        top = agg.get_top_k()
        assert top[0]["order_id"] == 1  # lower score first
        assert top[0]["score"] == 100.0
        assert agg.best_order_id == 1

    def test_best_order_selection(self):
        agg = ScoreAggregator()
        agg.register_order(0, [0, 1], 2)
        agg.register_order(1, [1, 0], 2)

        events0 = agg.record_estimate(0, 0, 1000.0)
        assert agg.best_order_id == 0

        events1 = agg.record_estimate(1, 0, 500.0)
        assert agg.best_order_id == 1
        assert any(e.event == "best_order_selected" for e in events1)


# =============================================================================
# API Tests: Dataset Endpoints
# =============================================================================

class TestDatasetAPI:
    def test_list_datasets(self):
        resp = client.get("/api/datasets")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Should contain yeast if dataset exists
        ids = [d["id"] for d in data]
        assert "yeast" in ids

    def test_get_dataset(self):
        resp = client.get("/api/datasets/yeast")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "yeast"
        assert data["num_vertices"] > 0
        assert data["num_edges"] > 0

    def test_get_dataset_not_found(self):
        resp = client.get("/api/datasets/nonexistent")
        assert resp.status_code == 404

    def test_health(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# =============================================================================
# API Tests: Session Endpoints
# =============================================================================

class TestSessionAPI:
    def test_create_session_invalid_dataset(self):
        resp = client.post("/api/sessions", json={
            "dataset_id": "nonexistent",
            "query_graph": {
                "vertices": [{"id": 0, "label": 0}],
                "edges": [{"source": 0, "target": 0}],
            },
        })
        assert resp.status_code == 404

    def test_create_session_disconnected_graph(self):
        resp = client.post("/api/sessions", json={
            "dataset_id": "yeast",
            "query_graph": {
                "vertices": [
                    {"id": 0, "label": 0},
                    {"id": 1, "label": 0},
                    {"id": 2, "label": 0},
                ],
                "edges": [{"source": 0, "target": 1}],
            },
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "DISCONNECTED_GRAPH"

    def test_create_session_valid(self):
        """Create a session with a valid triangle query, verify it returns 202."""
        resp = client.post("/api/sessions", json={
            "dataset_id": "yeast",
            "query_graph": {
                "vertices": [
                    {"id": 0, "label": 0},
                    {"id": 1, "label": 0},
                    {"id": 2, "label": 1},
                ],
                "edges": [
                    {"source": 0, "target": 1, "label": 0},
                    {"source": 1, "target": 2, "label": 0},
                    {"source": 0, "target": 2, "label": 0},
                ],
            },
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "session_id" in data
        assert data["status"] == "queued"
        assert "stream" in data["stream_url"]

        # Verify we can fetch session state
        session_id = data["session_id"]
        resp2 = client.get(f"/api/sessions/{session_id}")
        assert resp2.status_code == 200

    def test_session_not_found(self):
        resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404

    def test_execute_before_completion(self):
        """Execute should fail with 409 if session not completed."""
        resp = client.post("/api/sessions", json={
            "dataset_id": "yeast",
            "query_graph": {
                "vertices": [
                    {"id": 0, "label": 0},
                    {"id": 1, "label": 0},
                ],
                "edges": [{"source": 0, "target": 1}],
            },
        })
        session_id = resp.json()["session_id"]
        # Immediately try to execute (session likely still queued/running)
        resp = client.post(f"/api/sessions/{session_id}/execute")
        # Could be 409 or 202 depending on timing; just ensure no 500
        assert resp.status_code in (202, 409)


# =============================================================================
# Async Integration Tests (SSE + Full Pipeline)
# =============================================================================

@pytest.mark.asyncio
async def test_full_session_with_sse():
    """
    End-to-end async integration test:
    Create a session, read SSE stream, verify all event types.
    Uses httpx.AsyncClient for proper async task execution.
    """
    from httpx import AsyncClient, ASGITransport

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create session
        resp = await ac.post("/api/sessions", json={
            "dataset_id": "yeast",
            "query_graph": {
                "vertices": [
                    {"id": 0, "label": 0},
                    {"id": 1, "label": 0},
                ],
                "edges": [{"source": 0, "target": 1}],
            },
        })
        assert resp.status_code == 202
        session_id = resp.json()["session_id"]

        # Read SSE stream
        events_seen: list[str] = []
        async with ac.stream("GET", f"/api/sessions/{session_id}/stream") as response:
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                    events_seen.append(event_type)
                if any(t in events_seen for t in ("session_completed", "session_failed")):
                    break
                if len(events_seen) > 500:
                    break

        # Verify event flow
        assert "index_loading" in events_seen, f"Missing index_loading. Saw: {events_seen}"
        assert "index_loaded" in events_seen, f"Missing index_loaded. Saw: {events_seen}"
        assert "session_started" in events_seen, f"Missing session_started. Saw: {events_seen}"
        assert any(
            e in events_seen for e in ("session_completed", "session_failed")
        ), f"Missing terminal event. Saw: {events_seen}"

        has_progress = any(
            e in ("prefix_progress", "batch_update", "ranking_updated") for e in events_seen
        )
        assert has_progress, f"No progress events found. Saw: {events_seen}"

        # Verify session completed
        resp = await ac.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("completed", "failed")

        if data["status"] == "completed":
            # Verify result endpoint
            resp = await ac.get(f"/api/sessions/{session_id}/result")
            assert resp.status_code == 200
            result = resp.json()
            assert result["best_order_id"] is not None
            assert result["best_score"] > 0
            assert len(result["orders"]) > 0

            # Verify execute endpoint
            resp = await ac.post(f"/api/sessions/{session_id}/execute")
            assert resp.status_code == 202


@pytest.mark.asyncio
async def test_full_session_triangle():
    """
    End-to-end test with a triangle query (more complex than edge).
    Verifies multiple orders and ranking.
    """
    from httpx import AsyncClient, ASGITransport

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/sessions", json={
            "dataset_id": "yeast",
            "query_graph": {
                "vertices": [
                    {"id": 0, "label": 0},
                    {"id": 1, "label": 0},
                    {"id": 2, "label": 1},
                ],
                "edges": [
                    {"source": 0, "target": 1, "label": 0},
                    {"source": 1, "target": 2, "label": 0},
                    {"source": 0, "target": 2, "label": 0},
                ],
            },
        })
        assert resp.status_code == 202
        session_id = resp.json()["session_id"]

        # Read SSE stream to completion
        events_seen: list[str] = []
        event_data: list[dict] = []
        async with ac.stream("GET", f"/api/sessions/{session_id}/stream") as response:
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                    events_seen.append(event_type)
                elif line.startswith("data:"):
                    try:
                        data = json.loads(line.split(":", 1)[1].strip())
                        event_data.append(data)
                    except json.JSONDecodeError:
                        pass
                if any(t in events_seen for t in ("session_completed", "session_failed")):
                    break
                if len(events_seen) > 500:
                    break

        # Triangle has 6 exact orders — verify we got order_generated events
        assert "order_generated" in events_seen
        assert "session_completed" in events_seen

        # Verify progress events (may be batched)
        has_progress = any(
            e in ("prefix_progress", "batch_update", "ranking_updated") for e in events_seen
        )
        assert has_progress, f"No progress events. Saw: {events_seen}"

        # Fetch final result
        resp = await ac.get(f"/api/sessions/{session_id}/result")
        assert resp.status_code == 200
        result = resp.json()
        assert len(result["orders"]) == 6  # all 6 triangle permutations
        assert result["best_score"] > 0
