"""
Query graph validation and vertex ID normalization.
"""
from __future__ import annotations

from collections import defaultdict

from ..models import QueryGraph, NormalizedGraph, Vertex, Edge


class ValidationError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def validate_and_normalize(query: QueryGraph) -> NormalizedGraph:
    """
    Validate query graph and normalize vertex IDs to 0..n-1.

    Checks:
      1. Format: vertices and edges non-empty, fields present
      2. Connectivity: graph must be connected (undirected)
      3. Edge endpoints must reference existing vertices

    Returns NormalizedGraph with consecutive vertex IDs.
    """
    # 1. Collect vertex IDs
    vertex_ids = {v.id for v in query.vertices}
    if len(vertex_ids) != len(query.vertices):
        raise ValidationError(
            "DUPLICATE_VERTEX_ID",
            "Duplicate vertex IDs found in query graph",
        )

    # 2. Validate edge endpoints
    for e in query.edges:
        if e.source not in vertex_ids:
            raise ValidationError(
                "INVALID_EDGE_ENDPOINT",
                f"Edge source {e.source} not in vertex set",
                {"source": e.source},
            )
        if e.target not in vertex_ids:
            raise ValidationError(
                "INVALID_EDGE_ENDPOINT",
                f"Edge target {e.target} not in vertex set",
                {"target": e.target},
            )
        if e.source == e.target:
            raise ValidationError(
                "SELF_LOOP",
                f"Self-loop detected at vertex {e.source}",
                {"vertex": e.source},
            )

    # 3. Check connectivity (BFS on undirected graph)
    adj: dict[int, set[int]] = defaultdict(set)
    for e in query.edges:
        adj[e.source].add(e.target)
        adj[e.target].add(e.source)

    start = next(iter(vertex_ids))
    visited: set[int] = set()
    queue = [start]
    visited.add(start)
    while queue:
        v = queue.pop()
        for u in adj[v]:
            if u not in visited:
                visited.add(u)
                queue.append(u)

    if visited != vertex_ids:
        unreachable = vertex_ids - visited
        raise ValidationError(
            "DISCONNECTED_GRAPH",
            "Query graph is not connected",
            {"unreachable_vertices": sorted(unreachable)},
        )

    # 4. Normalize vertex IDs to 0..n-1
    sorted_ids = sorted(vertex_ids)
    id_mapping = {old: new for new, old in enumerate(sorted_ids)}
    label_map = {v.id: v.label for v in query.vertices}

    normalized_vertices = [
        Vertex(id=id_mapping[vid], label=label_map[vid])
        for vid in sorted_ids
    ]

    normalized_edges = [
        Edge(
            source=id_mapping[e.source],
            target=id_mapping[e.target],
            label=e.label,
        )
        for e in query.edges
    ]

    return NormalizedGraph(
        num_vertices=len(normalized_vertices),
        num_edges=len(normalized_edges),
        vertices=normalized_vertices,
        edges=normalized_edges,
        vertex_id_mapping=id_mapping,
    )
