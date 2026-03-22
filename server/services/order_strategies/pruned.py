"""Pruned order generation strategy.

Combines four pruning techniques to reduce the search space of
connected expansion orders while preserving high-quality candidates:

  S1 — Symmetry Breaking: equivalent vertices at the same expansion
       level are collapsed to a single representative.
  S2 — Core-First Ordering: high k-core vertices expand first;
       degree-1 leaves are deferred.
  S3 — A* Heuristic Search: priority queue with f = g + h and a
       cost upper-bound cutoff (2× best complete solution).
  S4 — Neighbor Safety Priority: candidates whose *all* query-graph
       neighbors are already placed ("safe") expand before those
       with only partial connectivity ("dangling").
"""
from __future__ import annotations

import heapq
import logging
from collections import defaultdict

from ...models import NormalizedGraph
from .graph_analysis import build_adjacency, compute_k_core, compute_equivalence_classes

logger = logging.getLogger("gq.estimation")


def _vertex_degree_cost(degree: int) -> float:
    """Heuristic per-vertex expansion cost based on degree."""
    return float(degree)


def _heuristic_remaining(
    remaining: set[int],
    degree_map: dict[int, int],
) -> float:
    """Admissible lower-bound for remaining vertices: sum of 1/degree.

    Lower degree → less constrained → higher future cost estimate.
    """
    return sum(1.0 / max(degree_map[v], 1) for v in remaining)


def _candidate_sort_key(
    vid: int,
    in_path: set[int],
    adj: dict[int, set[int]],
    core: dict[int, int],
    degree_map: dict[int, int],
    *,
    enable_core_first: bool = True,
    enable_safety: bool = True,
) -> tuple[int, int, int, int]:
    """Sort key implementing S2 (core-first) and S4 (neighbor safety).

    Returns (safety_penalty, -core_number, -degree, vid) so that:
      - "safe" candidates (all query neighbors placed) come first
      - among equals, higher core number wins
      - then higher degree, then lower vid for determinism
    """
    if enable_safety:
        neighbors_in_graph = adj[vid]
        neighbors_placed = neighbors_in_graph & in_path
        all_placed = len(neighbors_placed) == len(neighbors_in_graph)
        safety_penalty = 0 if all_placed else 1
    else:
        safety_penalty = 0

    core_val = -core[vid] if enable_core_first else 0
    return (safety_penalty, core_val, -degree_map[vid], vid)


def generate_orders_pruned(
    graph: NormalizedGraph,
    beam_width: int | None = None,
    exact_threshold: int = 7,
    cost_factor: float = 2.0,
    max_orders: int = 500,
    max_heap_pops: int = 200_000,
    enable_symmetry: bool = True,
    enable_core_first: bool = True,
    enable_astar_prune: bool = True,
    enable_safety: bool = True,
) -> list[list[int]]:
    """Generate connected expansion orders with S1-S4 pruning.

    Parameters
    ----------
    graph : NormalizedGraph
    beam_width : unused (kept for interface compatibility)
    exact_threshold : unused (kept for interface compatibility)
    cost_factor : prune partial orders whose f > cost_factor * best_complete
    max_orders : hard cap on number of complete orders returned
    max_heap_pops : search budget — stop after this many heap pops (default 200k)
    enable_symmetry : S1 — collapse equivalent vertices (default True)
    enable_core_first : S2 — prioritize high k-core vertices (default True)
    enable_astar_prune : S3 — A* cost cutoff (False = cost_factor=inf)
    enable_safety : S4 — neighbor safety priority (default True)
    """
    n = graph.num_vertices
    adj = build_adjacency(graph)
    core = compute_k_core(graph)
    equiv_classes = compute_equivalence_classes(graph)
    label_map = {v.id: v.label for v in graph.vertices}
    degree_map = {v.id: len(adj[v.id]) for v in graph.vertices}

    effective_cost_factor = cost_factor if enable_astar_prune else float("inf")

    # Build reverse lookup: vertex -> equivalence class key
    vertex_to_class: dict[int, tuple] = {}
    for key, members in equiv_classes.items():
        for vid in members:
            vertex_to_class[vid] = key

    # --- A* search (S3) with S1/S2/S4 integrated ---
    counter = 0
    pops = 0
    best_cost = float("inf")
    results: list[list[int]] = []

    all_vids = sorted(
        range(n),
        key=lambda v: (-core[v] if enable_core_first else 0, -degree_map[v], v),
    )

    # Initialize: one entry per equivalence-class representative (S1)
    seen_classes_root: set[tuple] = set()
    heap: list[tuple[float, int, tuple[int, ...], frozenset[int], float]] = []

    for v in all_vids:
        if enable_symmetry:
            cls = vertex_to_class[v]
            if cls in seen_classes_root:
                continue
            seen_classes_root.add(cls)
        g = _vertex_degree_cost(degree_map[v])
        remaining = set(range(n)) - {v}
        h = _heuristic_remaining(remaining, degree_map)
        f = g + h
        heapq.heappush(heap, (f, counter, (v,), frozenset({v}), g))
        counter += 1

    max_depth_seen = 1  # track deepest path reached

    while heap and len(results) < max_orders:
        pops += 1
        if pops > max_heap_pops:
            logger.warning(
                "PRUNED_SEARCH budget exhausted | V=%d | pops=%d | found=%d | max_depth=%d",
                n, pops, len(results), max_depth_seen,
            )
            break
        # Early futility checks (only when no results found yet):
        if not results:
            # (a) 20% budget used but depth < V/2 → search too shallow
            if pops > max_heap_pops // 5 and max_depth_seen < n // 2:
                logger.warning(
                    "PRUNED_SEARCH early abort (shallow) | V=%d | pops=%d | max_depth=%d",
                    n, pops, max_depth_seen,
                )
                break
            # (b) 50% budget used but depth < V*2/3 → unlikely to complete
            if pops > max_heap_pops // 2 and max_depth_seen < (n * 2) // 3:
                logger.warning(
                    "PRUNED_SEARCH early abort (stalled) | V=%d | pops=%d | max_depth=%d",
                    n, pops, max_depth_seen,
                )
                break
        f_score, _, path, in_path, g_score = heapq.heappop(heap)
        if len(path) > max_depth_seen:
            max_depth_seen = len(path)

        # S3 pruning
        if f_score > effective_cost_factor * best_cost:
            continue

        if len(path) == n:
            results.append(list(path))
            if g_score < best_cost:
                best_cost = g_score
            continue

        # Gather candidates: adjacent to current path, not yet placed
        candidates_set: set[int] = set()
        for v in path:
            for u in adj[v]:
                if u not in in_path:
                    candidates_set.add(u)

        # S2 + S4: sort candidates
        candidates = sorted(
            candidates_set,
            key=lambda v: _candidate_sort_key(
                v, in_path, adj, core, degree_map,
                enable_core_first=enable_core_first,
                enable_safety=enable_safety,
            ),
        )

        # S1: within this expansion level, only keep one representative
        seen_classes: set[tuple] = set()
        for v in candidates:
            if enable_symmetry:
                cls = vertex_to_class[v]
                if cls in seen_classes:
                    continue
                seen_classes.add(cls)

            new_g = g_score + _vertex_degree_cost(degree_map[v])
            remaining = set(range(n)) - (in_path | {v})
            new_h = _heuristic_remaining(remaining, degree_map)
            new_f = new_g + new_h

            if new_f > effective_cost_factor * best_cost:
                continue

            heapq.heappush(
                heap,
                (new_f, counter, path + (v,), in_path | {v}, new_g),
            )
            counter += 1

    logger.info(
        "PRUNED_SEARCH | V=%d | orders_generated=%d | heap_pops=%d | best_cost=%.2f",
        n, len(results), counter, best_cost if best_cost < float("inf") else -1,
    )
    return results
