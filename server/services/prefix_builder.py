"""
Prefix Subgraph Builder.

Given a connected expansion order O = (v1, ..., vn) and query graph Q,
builds n prefix subgraphs Q_1, ..., Q_n where Q_k = Q[{v1, ..., vk}]
is the induced subgraph on the first k vertices.

All prefix subgraphs are represented as in-memory dictionaries — no disk I/O.
"""
from __future__ import annotations

from ..models import NormalizedGraph, PrefixPayload, Vertex, Edge


def build_prefix_subgraphs(
    graph: NormalizedGraph,
    order: list[int],
) -> list[PrefixPayload]:
    """
    Build all n prefix subgraphs for a given order.

    For k = 1..n:
      S_k = {v_1, ..., v_k}
      E_k = {(u,w) in E_Q | u in S_k and w in S_k}
      Q_k = (S_k, E_k, labels restricted to S_k and E_k)

    Returns list of PrefixPayload objects (index 0 = Q_1, index n-1 = Q_n).
    """
    n = len(order)

    # Build label lookup
    label_map = {v.id: v.label for v in graph.vertices}

    # Build edge lookup: all edges indexed by frozenset of endpoints
    edge_data: dict[frozenset[int], int] = {}
    for e in graph.edges:
        key = frozenset((e.source, e.target))
        edge_data[key] = e.label

    prefixes: list[PrefixPayload] = []
    current_set: set[int] = set()
    current_edges: list[tuple[int, int, int]] = []  # (src, tgt, label)

    for k in range(n):
        v_new = order[k]
        current_set.add(v_new)

        # Find new edges: between v_new and all existing vertices in current_set
        for v_existing in current_set:
            if v_existing == v_new:
                continue
            key = frozenset((v_new, v_existing))
            if key in edge_data:
                # Canonical edge direction: smaller id first
                src, tgt = min(v_new, v_existing), max(v_new, v_existing)
                current_edges.append((src, tgt, edge_data[key]))

        # Build renormalized prefix subgraph
        # The vertices in current_set need to be renormalized to 0..k
        sorted_vids = sorted(current_set)
        vid_remap = {old: new for new, old in enumerate(sorted_vids)}

        prefix_vertices = [
            Vertex(id=vid_remap[v], label=label_map[v])
            for v in sorted_vids
        ]

        prefix_edges = []
        for src, tgt, el in current_edges:
            prefix_edges.append(Edge(
                source=vid_remap[src],
                target=vid_remap[tgt],
                label=el,
            ))

        prefixes.append(PrefixPayload(
            num_vertices=len(sorted_vids),
            num_edges=len(prefix_edges),
            vertices=prefix_vertices,
            edges=prefix_edges,
        ))

    return prefixes


def build_single_prefix(
    graph: NormalizedGraph,
    order: list[int],
    k: int,
) -> PrefixPayload:
    """Build the k-th prefix subgraph (1-indexed)."""
    prefixes = build_prefix_subgraphs(graph, order[:k])
    return prefixes[-1]
