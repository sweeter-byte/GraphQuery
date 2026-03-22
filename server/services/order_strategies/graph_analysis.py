"""Shared graph analysis utilities for order generation strategies.

Provides k-core decomposition, equivalence class detection, and
neighbor safety scoring used by the pruned order generator.
"""
from __future__ import annotations

from collections import defaultdict

from ...models import NormalizedGraph


def build_adjacency(graph: NormalizedGraph) -> dict[int, set[int]]:
    """Build undirected adjacency map from a NormalizedGraph."""
    adj: dict[int, set[int]] = defaultdict(set)
    for e in graph.edges:
        adj[e.source].add(e.target)
        adj[e.target].add(e.source)
    return adj


def compute_k_core(graph: NormalizedGraph) -> dict[int, int]:
    """Compute core number for each vertex via iterative peeling.

    Returns mapping vertex_id -> core_number.
    """
    adj = build_adjacency(graph)
    degree = {v.id: len(adj[v.id]) for v in graph.vertices}
    core = dict(degree)
    remaining = set(degree.keys())

    while remaining:
        # Find vertex with minimum current degree among remaining
        v_min = min(remaining, key=lambda v: core[v])
        k = core[v_min]
        # Remove all vertices with core value == k in this round
        to_remove = [v for v in remaining if core[v] <= k]
        for v in to_remove:
            remaining.discard(v)
            for u in adj[v]:
                if u in remaining:
                    core[u] = max(core[u] - 1, k)
        for v in to_remove:
            core[v] = k

    return core


def compute_equivalence_classes(
    graph: NormalizedGraph,
) -> dict[tuple[int, tuple[int, ...]], list[int]]:
    """Group vertices by (label, sorted neighbor-label multiset).

    Vertices in the same equivalence class are structurally
    interchangeable at the same expansion level — only one
    representative needs to be explored.

    Returns mapping (label, neighbor_label_tuple) -> [vertex_ids].
    """
    adj = build_adjacency(graph)
    label_map = {v.id: v.label for v in graph.vertices}

    classes: dict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    for v in graph.vertices:
        neighbor_labels = tuple(sorted(label_map[u] for u in adj[v.id]))
        key = (v.label, neighbor_labels)
        classes[key].append(v.id)

    return dict(classes)
