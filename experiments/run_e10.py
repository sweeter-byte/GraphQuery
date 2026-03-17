"""E10a + E10b + E10c + E10d: O2 weighted cost model experiments.

E10a (--grid-only): Hyperparameter grid search for gamma and lambda.
E10b: M3 execution comparison (uniform vs weighted top-1 order).
E10c: Cross-dataset generalization of best (gamma, lambda).
E10d: Weighted model ranking quality vs uniform baseline.

Usage:
    python experiments/run_e10.py --datasets yeast --sizes 4 8 --num-queries 5 --grid-only
    python experiments/run_e10.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer
from experiments.common.m2_runner import run_m2

from server.services.estimator_adapter import EstimatorAdapter
from server.services.score_aggregator import WeightConfig, get_weight
from server.services.order_strategies.pruned import generate_orders_pruned

GAMMA_VALUES = [0.5, 1.0, 1.5, 2.0, 3.0]
LAMBDA_VALUES = [0.0, 0.5, 1.0, 2.0, 5.0]


def main():
    p = base_argparser("E10: O2 weighted cost model experiments")
    p.add_argument("--grid-only", action="store_true", help="E10a only: grid search, no M3")
    p.add_argument("--gammas", nargs="+", type=float, default=GAMMA_VALUES)
    p.add_argument("--lambdas", nargs="+", type=float, default=LAMBDA_VALUES)
    p.add_argument("--top-k", type=int, default=10)
    args = p.parse_args()

    adapter = EstimatorAdapter()

    # E10a: grid search CSV
    csv_e10a = ExperimentCSV(
        Path(args.output_dir) / "e10a_grid_search.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "gamma", "lam", "best_order_id", "best_score",
            "top1_same_as_uniform", "topk_overlap_with_uniform",
        ],
        metadata={
            "experiment": "E10a",
            "gammas": str(args.gammas),
            "lambdas": str(args.lambdas),
        },
    )

    # E10d: ranking quality CSV
    csv_e10d = ExperimentCSV(
        Path(args.output_dir) / "e10d_ranking_quality.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "gamma", "lam",
            "uniform_top1", "weighted_top1", "top1_changed",
            "topk_overlap",
        ],
        metadata={"experiment": "E10d"},
    )

    # E10b/E10c CSVs (only without --grid-only, needs M3)
    csv_e10b = None
    csv_e10c = None
    if not args.grid_only:
        csv_e10b = ExperimentCSV(
            Path(args.output_dir) / "e10b_m3_comparison.csv",
            columns=[
                "dataset", "size", "density", "query",
                "gamma", "lam",
                "uniform_order", "weighted_order",
                "uniform_eps", "weighted_eps", "eps_improvement",
            ],
            metadata={"experiment": "E10b"},
        )
        csv_e10c = ExperimentCSV(
            Path(args.output_dir) / "e10c_generalization.csv",
            columns=[
                "dataset", "size", "density", "query",
                "train_dataset", "gamma", "lam",
                "uniform_eps", "weighted_eps", "eps_improvement",
            ],
            metadata={"experiment": "E10c"},
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

            print(f"  [{ds}] loading C++ index...")
            adapter.load_dataset(ds)
            print(f"  [{ds}] {len(queries)} queries")

            for q in queries:
                graph = q["graph"]
                orders = generate_orders_pruned(graph)
                if not orders:
                    continue

                # Run M2 once with uniform weights to get per-prefix estimates
                res_uniform = run_m2(graph, orders, adapter)
                uniform_best_id = res_uniform.aggregator.best_order_id
                uniform_top1 = (
                    res_uniform.aggregator.trackers[uniform_best_id].order
                    if uniform_best_id is not None else []
                )
                uniform_topk = {
                    tuple(t["order"])
                    for t in res_uniform.aggregator.get_top_k()[:args.top_k]
                }

                # E10a + E10d: offline re-scoring with different weight configs
                for gamma in args.gammas:
                    for lam in args.lambdas:
                        # Re-score using stored per-prefix estimates
                        n = graph.num_vertices
                        wcfg = WeightConfig(mode="weighted", gamma=gamma, lam=lam)

                        # Rebuild scores from raw estimates
                        scored: list[tuple[float, int]] = []
                        for oid, tracker in res_uniform.aggregator.trackers.items():
                            prefixes_data = res_uniform.aggregator.trackers[oid]
                            # Recompute weighted score from stored estimates
                            # We need prefix topology info — get from prefix builder
                            from server.services.prefix_builder import build_prefix_subgraphs
                            pfx_list = build_prefix_subgraphs(graph, tracker.order)
                            wscore = 0.0
                            for k_idx, c_hat in enumerate(tracker.estimates):
                                pfx = pfx_list[k_idx]
                                omega = get_weight(
                                    k_idx + 1, n,
                                    n_edges=pfx.num_edges,
                                    n_vertices=pfx.num_vertices,
                                    config=wcfg,
                                )
                                wscore += omega * c_hat
                            scored.append((wscore, oid))

                        scored.sort()
                        w_best_id = scored[0][1] if scored else None
                        w_best_score = scored[0][0] if scored else 0.0
                        w_top1 = (
                            res_uniform.aggregator.trackers[w_best_id].order
                            if w_best_id is not None else []
                        )
                        w_topk = {
                            tuple(res_uniform.aggregator.trackers[s[1]].order)
                            for s in scored[:args.top_k]
                        }

                        top1_same = 1 if w_top1 == uniform_top1 else 0
                        k_eff = min(len(uniform_topk), len(w_topk), args.top_k)
                        topk_overlap = len(uniform_topk & w_topk) / k_eff if k_eff > 0 else 0.0

                        csv_e10a.write_row(
                            dataset=ds, size=q["size"], density=q["density"],
                            query=q["name"], n_orders=len(orders),
                            gamma=f"{gamma:.1f}", lam=f"{lam:.1f}",
                            best_order_id=w_best_id,
                            best_score=f"{w_best_score:.4f}",
                            top1_same_as_uniform=top1_same,
                            topk_overlap_with_uniform=f"{topk_overlap:.4f}",
                        )

                        csv_e10d.write_row(
                            dataset=ds, size=q["size"], density=q["density"],
                            query=q["name"], n_orders=len(orders),
                            gamma=f"{gamma:.1f}", lam=f"{lam:.1f}",
                            uniform_top1=str(uniform_top1),
                            weighted_top1=str(w_top1),
                            top1_changed=1 - top1_same,
                            topk_overlap=f"{topk_overlap:.4f}",
                        )

            print(f"  [{ds}] done")

    finally:
        csv_e10a.close()
        csv_e10d.close()
        if csv_e10b:
            csv_e10b.close()
        if csv_e10c:
            csv_e10c.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
