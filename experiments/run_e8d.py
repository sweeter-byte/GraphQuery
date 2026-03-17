"""E8d: Prefix sharing degree analysis.

For each query, measures how many unique prefix subgraphs exist per level
vs total prefixes, quantifying the sharing opportunity exploited by R4.

Usage:
    python experiments/run_e8d.py --datasets yeast --sizes 4 8 --num-queries 10
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV

from server.services.order_strategies.pruned import generate_orders_pruned
from server.services.prefix_builder import build_prefix_subgraphs


def main():
    p = base_argparser("E8d: prefix sharing degree analysis")
    args = p.parse_args()

    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e8d_sharing.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders", "level",
            "total_prefixes", "unique_prefixes", "sharing_ratio",
        ],
        metadata={"experiment": "E8d"},
    )

    try:
        for ds in args.datasets:
            sizes = args.sizes or DATASET_SIZES.get(ds, [])
            queries = discover_queries(
                ds, sizes=sizes, density=args.density,
                max_per_size=args.num_queries, seed=args.seed,
            )
            if not queries:
                print(f"  [{ds}] no queries found, skipping")
                continue

            print(f"  [{ds}] {len(queries)} queries")

            for q in queries:
                graph = q["graph"]
                orders = generate_orders_pruned(graph)
                if not orders:
                    continue

                n = graph.num_vertices
                # Pre-build all prefix payloads
                all_prefixes = {
                    i: build_prefix_subgraphs(graph, order)
                    for i, order in enumerate(orders)
                }

                for level in range(n):
                    # Compute unique prefix keys at this level
                    prefix_keys = set()
                    for i, order in enumerate(orders):
                        prefix_keys.add(frozenset(order[: level + 1]))

                    total = len(orders)
                    unique = len(prefix_keys)
                    sharing = 1.0 - (unique / total) if total > 0 else 0.0

                    csv_out.write_row(
                        dataset=ds, size=q["size"], density=q["density"],
                        query=q["name"], n_orders=len(orders), level=level,
                        total_prefixes=total, unique_prefixes=unique,
                        sharing_ratio=f"{sharing:.4f}",
                    )

            print(f"  [{ds}] done")

    finally:
        csv_out.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
