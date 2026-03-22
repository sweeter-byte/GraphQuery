#!/usr/bin/env python3
"""
Random BFS query graph generator.

Generates query graphs by sampling connected subgraphs from a data graph
using the random BFS method described in the SubgraphMatchingSurvey
(SIGMOD 2020).

Two modes:
  - dense: induced subgraph (all edges between sampled vertices preserved)
  - sparse: BFS spanning tree + random extra edges to reach target density
            (default: |E| = 1.375 * |V|, matching the Survey convention)

Usage:
    python query_graph_generator.py \\
        --data_graph dataset/yeast/yeast.graph \\
        --output_dir dataset/yeast/query_graph \\
        --sizes 8 9 10 12 16 20 24 32 \\
        --modes dense sparse \\
        --count 200 \\
        --seed 42
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from collections import defaultdict, deque
from pathlib import Path


def load_data_graph(path: str) -> tuple[dict[int, int], dict[int, list[int]]]:
    """
    Load a data graph in .graph format.

    Returns
    -------
    labels : dict[int, int]
        vertex_id -> label
    adj : dict[int, list[int]]
        vertex_id -> list of neighbor vertex_ids
    """
    labels: dict[int, int] = {}
    adj: dict[int, list[int]] = defaultdict(list)

    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == "v":
                vid = int(parts[1])
                label = int(parts[2])
                labels[vid] = label
            elif parts[0] == "e":
                u, v = int(parts[1]), int(parts[2])
                adj[u].append(v)
                adj[v].append(u)

    return labels, adj


def random_bfs_sample(
    adj: dict[int, list[int]],
    target_size: int,
    rng: random.Random,
) -> list[int] | None:
    """
    Sample a connected subgraph of `target_size` vertices via random BFS.

    Returns None if the sampled region is too small.
    """
    all_vertices = list(adj.keys())
    start = rng.choice(all_vertices)

    visited: set[int] = {start}
    queue: deque[int] = deque([start])
    order: list[int] = [start]

    while queue and len(order) < target_size:
        v = queue.popleft()
        neighbors = adj[v]
        rng.shuffle(neighbors)
        for u in neighbors:
            if u not in visited:
                visited.add(u)
                order.append(u)
                queue.append(u)
                if len(order) >= target_size:
                    break

    if len(order) < target_size:
        return None
    return order[:target_size]


def extract_induced_subgraph(
    vertices: list[int],
    labels: dict[int, int],
    adj: dict[int, list[int]],
) -> tuple[list[tuple[int, int]], list[tuple[int, int, int]]]:
    """
    Extract the induced subgraph for the given vertex set.

    Returns
    -------
    v_list : list of (new_id, label)
    e_list : list of (new_src, new_dst, edge_label=0)
    """
    vset = set(vertices)
    old_to_new = {old: new for new, old in enumerate(vertices)}

    v_list = [(old_to_new[v], labels[v]) for v in vertices]

    edges: set[tuple[int, int]] = set()
    for v in vertices:
        nv = old_to_new[v]
        for u in adj[v]:
            if u in vset:
                nu = old_to_new[u]
                if nv < nu:
                    edges.add((nv, nu))

    e_list = [(u, v, 0) for u, v in sorted(edges)]
    return v_list, e_list


def sparsify(
    v_list: list[tuple[int, int]],
    e_list: list[tuple[int, int, int]],
    vertices: list[int],
    adj: dict[int, list[int]],
    target_edges: int,
    rng: random.Random,
) -> list[tuple[int, int, int]]:
    """
    Reduce the edge set to `target_edges` while keeping the graph connected.

    Strategy: start with BFS spanning tree edges, then randomly add induced
    edges until reaching target_edges.
    """
    n = len(v_list)
    vset = set(vertices)
    old_to_new = {old: new for new, old in enumerate(vertices)}

    # Build BFS tree in new IDs
    visited: set[int] = {0}
    queue: deque[int] = deque([0])
    tree_edges: set[tuple[int, int]] = set()

    new_adj: dict[int, list[int]] = defaultdict(list)
    for u, v, _ in e_list:
        new_adj[u].append(v)
        new_adj[v].append(u)

    while queue:
        v = queue.popleft()
        for u in new_adj[v]:
            if u not in visited:
                visited.add(u)
                queue.append(u)
                e = (min(v, u), max(v, u))
                tree_edges.add(e)

    # Non-tree edges
    all_edges = {(u, v) for u, v, _ in e_list}
    non_tree = list(all_edges - tree_edges)
    rng.shuffle(non_tree)

    # Start with tree, add random non-tree edges
    result = set(tree_edges)
    needed = target_edges - len(result)
    if needed > 0:
        result.update(non_tree[:needed])

    return [(u, v, 0) for u, v in sorted(result)]


def compute_degrees(
    n: int, e_list: list[tuple[int, int, int]]
) -> dict[int, int]:
    """Compute degree for each vertex."""
    deg: dict[int, int] = defaultdict(int)
    for u, v, _ in e_list:
        deg[u] += 1
        deg[v] += 1
    # Ensure all vertices present
    for i in range(n):
        if i not in deg:
            deg[i] = 0
    return deg


def write_graph_file(
    path: str,
    v_list: list[tuple[int, int]],
    e_list: list[tuple[int, int, int]],
) -> None:
    """Write a query graph in .graph format."""
    n = len(v_list)
    m = len(e_list)
    deg = compute_degrees(n, e_list)

    with open(path, "w") as f:
        f.write(f"t {n} {m}\n")
        for vid, label in v_list:
            f.write(f"v {vid} {label} {deg[vid]}\n")
        for u, v, el in e_list:
            f.write(f"e {u} {v} {el}\n")


def generate_queries(
    data_graph_path: str,
    output_dir: str,
    sizes: list[int],
    modes: list[str],
    count: int,
    seed: int,
    sparse_density: float = 1.375,
    max_retries: int = 1000,
) -> dict[str, int]:
    """
    Generate query graphs and write to output_dir.

    Parameters
    ----------
    sparse_density : float
        For sparse mode, target |E| = sparse_density * |V|.

    Returns
    -------
    stats : dict mapping "mode_size" -> number generated
    """
    rng = random.Random(seed)
    labels, adj = load_data_graph(data_graph_path)
    os.makedirs(output_dir, exist_ok=True)

    stats: dict[str, int] = {}

    for size in sizes:
        for mode in modes:
            key = f"{mode}_{size}"
            generated = 0
            attempts = 0

            while generated < count and attempts < count * max_retries:
                attempts += 1
                vertices = random_bfs_sample(adj, size, rng)
                if vertices is None:
                    continue

                v_list, e_list = extract_induced_subgraph(
                    vertices, labels, adj
                )

                if mode == "sparse":
                    target_edges = int(sparse_density * size)
                    # Need at least tree edges (size-1) and at most induced edges
                    if len(e_list) < size - 1:
                        continue  # not enough edges for a tree
                    if len(e_list) < target_edges:
                        # Use all induced edges if fewer than target
                        pass
                    else:
                        e_list = sparsify(
                            v_list, e_list, vertices, adj,
                            target_edges, rng,
                        )
                elif mode == "dense":
                    # Keep induced subgraph as-is
                    pass

                # Minimum connectivity check: need at least size-1 edges
                if len(e_list) < size - 1:
                    continue

                generated += 1
                fname = f"query_{mode}_{size}_{generated}.graph"
                write_graph_file(
                    os.path.join(output_dir, fname), v_list, e_list,
                )

            stats[key] = generated
            print(
                f"  {key}: generated {generated}/{count} "
                f"({attempts} attempts)"
            )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate query graphs via random BFS sampling"
    )
    parser.add_argument(
        "--data_graph", required=True,
        help="Path to the data graph (.graph format)",
    )
    parser.add_argument(
        "--output_dir", required=True,
        help="Directory to write generated query graphs",
    )
    parser.add_argument(
        "--sizes", nargs="+", type=int, default=[8, 16, 24, 32],
        help="Query graph sizes (number of vertices)",
    )
    parser.add_argument(
        "--modes", nargs="+", default=["dense", "sparse"],
        choices=["dense", "sparse"],
        help="Generation modes",
    )
    parser.add_argument(
        "--count", type=int, default=200,
        help="Number of query graphs per (size, mode) combination",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--sparse_density", type=float, default=1.375,
        help="For sparse mode, target |E| = density * |V|",
    )

    args = parser.parse_args()
    print(f"Loading data graph: {args.data_graph}")
    print(f"Output directory: {args.output_dir}")
    print(f"Sizes: {args.sizes}, Modes: {args.modes}, Count: {args.count}")

    stats = generate_queries(
        data_graph_path=args.data_graph,
        output_dir=args.output_dir,
        sizes=args.sizes,
        modes=args.modes,
        count=args.count,
        seed=args.seed,
        sparse_density=args.sparse_density,
    )

    print("\nGeneration complete:")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
