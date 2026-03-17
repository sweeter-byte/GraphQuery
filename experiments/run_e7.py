"""E7a + E7b + E7e: M1 pruned search space reduction, quality, and end-to-end.

E7a (--no-m2): Search space reduction ratio — baseline vs pruned order counts.
E7b (needs M2): Top-K quality preservation — Spearman correlation of rankings.
E7e (needs M2): End-to-end M1+M2 time comparison.

Usage:
    python experiments/run_e7.py --datasets yeast --sizes 4 8 --num-queries 5 --no-m2
    python experiments/run_e7.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES, RESULTS_DIR
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer
from experiments.common.stats import spearman_corr, mean_std

from server.services.order_strategies.baseline import generate_orders_baseline
from server.services.order_strategies.pruned import generate_orders_pruned


def main():
    p = base_argparser("E7: M1 pruned order generation experiments")
    p.add_argument("--no-m2", action="store_true", help="Skip M2 evaluation (E7a only)")
    p.add_argument("--top-k", type=int, default=10, help="Top-K for quality comparison")
    args = p.parse_args()

    # --- E7a CSV: search space reduction ---
    csv_e7a = ExperimentCSV(
        Path(args.output_dir) / "e7a_space_reduction.csv",
        columns=[
            "dataset", "size", "density", "query",
            "n_baseline", "n_pruned", "reduction_ratio",
            "time_baseline_s", "time_pruned_s", "speedup",
        ],
        metadata={"experiment": "E7a", "num_queries": str(args.num_queries)},
    )

    # --- E7b/E7e CSVs (only if M2 enabled) ---
    csv_e7b = None
    csv_e7e = None
    adapter = None

    if not args.no_m2:
        from experiments.common.m2_runner import run_m2
        from server.services.estimator_adapter import EstimatorAdapter
        adapter = EstimatorAdapter()

        csv_e7b = ExperimentCSV(
            Path(args.output_dir) / "e7b_quality.csv",
            columns=[
                "dataset", "size", "density", "query",
                "spearman_rho", "spearman_p",
                "top1_match", "topk_overlap",
            ],
            metadata={"experiment": "E7b", "top_k": str(args.top_k)},
        )
        csv_e7e = ExperimentCSV(
            Path(args.output_dir) / "e7e_end_to_end.csv",
            columns=[
                "dataset", "size", "density", "query",
                "m1_baseline_s", "m2_baseline_s", "total_baseline_s",
                "m1_pruned_s", "m2_pruned_s", "total_pruned_s",
                "total_speedup", "n_baseline", "n_pruned",
            ],
            metadata={"experiment": "E7e"},
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

            # Load dataset index for M2
            if adapter is not None:
                print(f"  [{ds}] loading C++ index...")
                adapter.load_dataset(ds)

            print(f"  [{ds}] {len(queries)} queries")

            for q in queries:
                graph = q["graph"]

                # --- Baseline M1 ---
                with timer() as t_bl:
                    orders_bl = generate_orders_baseline(graph)
                # --- Pruned M1 ---
                with timer() as t_pr:
                    orders_pr = generate_orders_pruned(graph)

                n_bl = len(orders_bl)
                n_pr = len(orders_pr)
                reduction = 1.0 - (n_pr / n_bl) if n_bl > 0 else 0.0
                speedup = t_bl.elapsed_s / t_pr.elapsed_s if t_pr.elapsed_s > 0 else float("inf")

                csv_e7a.write_row(
                    dataset=ds, size=q["size"], density=q["density"], query=q["name"],
                    n_baseline=n_bl, n_pruned=n_pr,
                    reduction_ratio=f"{reduction:.4f}",
                    time_baseline_s=f"{t_bl.elapsed_s:.6f}",
                    time_pruned_s=f"{t_pr.elapsed_s:.6f}",
                    speedup=f"{speedup:.2f}",
                )

                # --- M2 evaluation (E7b + E7e) ---
                if adapter is not None and csv_e7b and csv_e7e:
                    with timer() as t_m2_bl:
                        res_bl = run_m2(graph, orders_bl, adapter)
                    with timer() as t_m2_pr:
                        res_pr = run_m2(graph, orders_pr, adapter)

                    # E7b: ranking quality
                    # Build score map for baseline orders
                    bl_scores = {
                        tuple(res_bl.aggregator.trackers[i].order): res_bl.aggregator.trackers[i].score
                        for i in res_bl.aggregator.trackers
                    }
                    pr_scores = {
                        tuple(res_pr.aggregator.trackers[i].order): res_pr.aggregator.trackers[i].score
                        for i in res_pr.aggregator.trackers
                    }

                    # Find common orders for Spearman
                    common = set(bl_scores.keys()) & set(pr_scores.keys())
                    if len(common) >= 3:
                        common_list = sorted(common)
                        a_vals = [bl_scores[o] for o in common_list]
                        b_vals = [pr_scores[o] for o in common_list]
                        rho, p_val = spearman_corr(a_vals, b_vals)
                    else:
                        rho, p_val = float("nan"), float("nan")

                    # Top-1 match
                    bl_top1 = res_bl.aggregator.trackers[res_bl.aggregator.best_order_id].order if res_bl.aggregator.best_order_id is not None else []
                    pr_top1 = res_pr.aggregator.trackers[res_pr.aggregator.best_order_id].order if res_pr.aggregator.best_order_id is not None else []
                    top1_match = 1 if bl_top1 == pr_top1 else 0

                    # Top-K overlap
                    bl_topk = {tuple(t["order"]) for t in res_bl.aggregator.get_top_k()[:args.top_k]}
                    pr_topk = {tuple(t["order"]) for t in res_pr.aggregator.get_top_k()[:args.top_k]}
                    k_eff = min(len(bl_topk), len(pr_topk), args.top_k)
                    topk_overlap = len(bl_topk & pr_topk) / k_eff if k_eff > 0 else 0.0

                    csv_e7b.write_row(
                        dataset=ds, size=q["size"], density=q["density"], query=q["name"],
                        spearman_rho=f"{rho:.4f}", spearman_p=f"{p_val:.4f}",
                        top1_match=top1_match, topk_overlap=f"{topk_overlap:.4f}",
                    )

                    # E7e: end-to-end timing
                    total_bl = t_bl.elapsed_s + t_m2_bl.elapsed_s
                    total_pr = t_pr.elapsed_s + t_m2_pr.elapsed_s
                    total_speedup = total_bl / total_pr if total_pr > 0 else float("inf")

                    csv_e7e.write_row(
                        dataset=ds, size=q["size"], density=q["density"], query=q["name"],
                        m1_baseline_s=f"{t_bl.elapsed_s:.6f}",
                        m2_baseline_s=f"{t_m2_bl.elapsed_s:.6f}",
                        total_baseline_s=f"{total_bl:.6f}",
                        m1_pruned_s=f"{t_pr.elapsed_s:.6f}",
                        m2_pruned_s=f"{t_m2_pr.elapsed_s:.6f}",
                        total_pruned_s=f"{total_pr:.6f}",
                        total_speedup=f"{total_speedup:.2f}",
                        n_baseline=n_bl, n_pruned=n_pr,
                    )

            print(f"  [{ds}] done")

    finally:
        csv_e7a.close()
        if csv_e7b:
            csv_e7b.close()
        if csv_e7e:
            csv_e7e.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
