"""
Connected Expansion Order Generation Engine (Dual Mode).

Supports:
  - Exact BFS/DFS: Enumerates all valid connected expansion orders Omega(Q).
  - Beam Search: Level-wise evolution with Top-b truncation per layer.

DFS tie-breaking: vertex label ascending, then vertex ID ascending.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Generator

from ..models import NormalizedGraph


def _build_adjacency(graph: NormalizedGraph) -> dict[int, set[int]]:
    adj: dict[int, set[int]] = defaultdict(set)
    for e in graph.edges:
        adj[e.source].add(e.target)
        adj[e.target].add(e.source)
    return adj


def _vertex_sort_key(vid: int, label_map: dict[int, int]) -> tuple[int, int]:
    """Tie-breaking: label ascending, then vertex ID ascending."""
    return (label_map.get(vid, 0), vid)


def enumerate_connected_orders_exact(
    graph: NormalizedGraph,
) -> list[list[int]]:
    """
    Enumerate ALL valid connected expansion orders via DFS.

    A connected expansion order O = (v1, ..., vn) satisfies:
    for each k >= 2, v_k is adjacent to at least one vertex in {v1, ..., v_{k-1}}.

    Returns list of all valid orders.
    WARNING: O(n!) worst case — only use for small graphs (|V| <= ~8).
    """
    n = graph.num_vertices
    adj = _build_adjacency(graph)
    label_map = {v.id: v.label for v in graph.vertices}
    all_vids = sorted(range(n), key=lambda v: _vertex_sort_key(v, label_map))

    results: list[list[int]] = []

    def dfs(path: list[int], in_path: set[int]) -> None:
        if len(path) == n:
            results.append(list(path))
            return

        # Candidate vertices: not in path, adjacent to at least one vertex in path
        if not path:
            candidates = all_vids
        else:
            candidates_set: set[int] = set()
            for v in path:
                for u in adj[v]:
                    if u not in in_path:
                        candidates_set.add(u)
            candidates = sorted(candidates_set, key=lambda v: _vertex_sort_key(v, label_map))

        for v in candidates:
            path.append(v)
            in_path.add(v)
            dfs(path, in_path)
            path.pop()
            in_path.discard(v)

    dfs([], set())
    return results


def enumerate_connected_orders_beam(
    graph: NormalizedGraph,
    beam_width: int = 50,
) -> list[list[int]]:
    """
    Level-wise Beam Search for connected expansion orders.

    At each level k, expand all surviving partial orders by one vertex,
    then truncate to Top-b by accumulated placeholder score (order index
    used as proxy until real scores are available).

    Returns up to beam_width candidate orders.
    """
    n = graph.num_vertices
    adj = _build_adjacency(graph)
    label_map = {v.id: v.label for v in graph.vertices}
    all_vids = sorted(range(n), key=lambda v: _vertex_sort_key(v, label_map))

    # State: (partial_order, vertex_set)
    active: list[tuple[list[int], set[int]]] = []

    # Initialize with each vertex as a root
    for v in all_vids:
        active.append(([v], {v}))

    # Truncate initial roots if more than beam_width
    if len(active) > beam_width:
        active = active[:beam_width]

    for _level in range(1, n):
        next_level: list[tuple[list[int], set[int]]] = []

        for path, in_path in active:
            # Find candidate expansions
            candidates_set: set[int] = set()
            for v in path:
                for u in adj[v]:
                    if u not in in_path:
                        candidates_set.add(u)
            candidates = sorted(candidates_set, key=lambda v: _vertex_sort_key(v, label_map))

            for v in candidates:
                new_path = path + [v]
                new_set = in_path | {v}
                next_level.append((new_path, new_set))

        # Beam truncation: keep top-b by deterministic ordering
        # (Without real scores yet, just keep first beam_width)
        if len(next_level) > beam_width:
            next_level = next_level[:beam_width]

        active = next_level

    return [path for path, _ in active]


def generate_orders(
    graph: NormalizedGraph,
    beam_width: int | None = None,
    exact_threshold: int = 7,
) -> list[list[int]]:
    """
    Dual-engine order generation.

    - If beam_width is None and |V| <= exact_threshold: exact enumeration.
    - Otherwise: beam search with given beam_width (default 50).
    """
    n = graph.num_vertices
    if beam_width is None and n <= exact_threshold:
        return enumerate_connected_orders_exact(graph)
    else:
        bw = beam_width if beam_width is not None else 50
        return enumerate_connected_orders_beam(graph, beam_width=bw)
