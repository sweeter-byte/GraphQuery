"""E8a + E8b + E8c + E8e: M2 prefix deduplication experiments.

E8a: C++ call reduction ratio — full vs R1-only vs R4-only vs R1+R4.
E8b: M2 wall-clock speedup.
E8c: Ranking consistency (lossless verification) with Spearman correlation.
E8e: End-to-end 4-pipeline comparison (baseline/pruned × full/optimized).

Usage:
    python experiments/run_e8.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer
from experiments.common.stats import spearman_corr
from experiments.common.m2_runner import run_m2

from server.services.estimator_adapter import EstimatorAdapter
from server.services.order_strategies.baseline import generate_orders_baseline
from server.services.order_strategies.pruned import generate_orders_pruned

# R1/R4 ablation configs: name -> (enable_r1, enable_r4)
DEDUP_CONFIGS = {
    "full":    (False, False),
    "R1_only": (True,  False),
    "R4_only": (False, True),
    "R1+R4":   (True,  True),
}


def main():
    p = base_argparser("E8: M2 prefix deduplication (R1+R4)")
    p.add_argument("--top-k", type=int, default=10)
    args = p.parse_args()

    adapter = EstimatorAdapter()

    # E8a+E8b: per-config ablation results
    csv_e8a = ExperimentCSV(
        Path(args.output_dir) / "e8a_dedup_ablation.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "config", "cpp_calls", "cache_hits", "cache_misses",
            "cache_hit_rate", "m2_time_s",
        ],
        metadata={"experiment": "E8a+E8b", "configs": ",".join(DEDUP_CONFIGS.keys())},
    )

    # E8c: ranking consistency (full vs R1+R4)
    csv_e8c = ExperimentCSV(
        Path(args.output_dir) / "e8c_consistency.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "top1_match", "scores_identical", "spearman_rho", "spearman_p",
            "top5_overlap", "max_score_diff",
        ],
        metadata={"experiment": "E8c"},
    )

    # E8e: 4-pipeline comparison (baseline/pruned × full/optimized)
    csv_e8e = ExperimentCSV(
        Path(args.output_dir) / "e8e_pipeline.csv",
        columns=[
            "dataset", "size", "density", "query",
            "pipeline", "m1_strategy", "m2_mode",
            "n_orders", "m1_time_s", "m2_time_s", "total_plan_s",
            "cpp_calls", "cache_hits", "r3_skips",
        ],
        metadata={"experiment": "E8e"},
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

                # Generate orders with both strategies for E8e
                with timer() as t_m1_bl:
                    orders_bl = generate_orders_baseline(graph)
                with timer() as t_m1_pr:
                    orders_pr = generate_orders_pruned(graph)

                if not orders_pr:
                    continue

                # --- E8a+E8b: R1/R4 ablation (using pruned orders) ---
                ablation_results = {}
                for cfg_name, (r1, r4) in DEDUP_CONFIGS.items():
                    with timer() as t_cfg:
                        res = run_m2(
                            graph, orders_pr, adapter,
                            prefix_eval_mode="full",
                            enable_r1=r1, enable_r4=r4,
                        )
                    ablation_results[cfg_name] = (res, t_cfg.elapsed_s)
                    hit_total = res.cache_hits + res.cache_misses
                    csv_e8a.write_row(
                        dataset=ds, size=q["size"], density=q["density"],
                        query=q["name"], n_orders=len(orders_pr),
                        config=cfg_name, cpp_calls=res.n_cpp_calls,
                        cache_hits=res.cache_hits, cache_misses=res.cache_misses,
                        cache_hit_rate=f"{res.cache_hits / hit_total:.4f}" if hit_total > 0 else "0.0000",
                        m2_time_s=f"{t_cfg.elapsed_s:.6f}",
                    )

                # --- E8c: ranking consistency (full vs R1+R4) ---
                res_full = ablation_results["full"][0]
                res_opt = ablation_results["R1+R4"][0]

                full_best_id = res_full.aggregator.best_order_id
                opt_best_id = res_opt.aggregator.best_order_id
                full_top1 = res_full.aggregator.trackers[full_best_id].order if full_best_id is not None else []
                opt_top1 = res_opt.aggregator.trackers[opt_best_id].order if opt_best_id is not None else []
                top1_match = 1 if full_top1 == opt_top1 else 0

                # Spearman correlation on all order scores
                full_scores = [res_full.aggregator.trackers[i].score for i in range(len(orders_pr))]
                opt_scores = [res_opt.aggregator.trackers[i].score for i in range(len(orders_pr))]
                rho, p_val = spearman_corr(full_scores, opt_scores)

                # Max score diff and scores_identical
                max_diff = 0.0
                scores_identical = 1
                for i in range(len(orders_pr)):
                    diff = abs(full_scores[i] - opt_scores[i])
                    max_diff = max(max_diff, diff)
                    if diff > 1e-6:
                        scores_identical = 0

                # Top-5 overlap
                full_topk = [t["order_id"] for t in res_full.aggregator.get_top_k()[:5]]
                opt_topk = [t["order_id"] for t in res_opt.aggregator.get_top_k()[:5]]
                top5_overlap = len(set(full_topk) & set(opt_topk))

                csv_e8c.write_row(
                    dataset=ds, size=q["size"], density=q["density"],
                    query=q["name"], n_orders=len(orders_pr),
                    top1_match=top1_match, scores_identical=scores_identical,
                    spearman_rho=f"{rho:.6f}", spearman_p=f"{p_val:.6f}",
                    top5_overlap=top5_overlap, max_score_diff=f"{max_diff:.8f}",
                )

                # --- E8e: 4-pipeline comparison ---
                pipelines = [
                    ("A_bl_full", "baseline", "full", orders_bl, t_m1_bl, False, False),
                    ("B_bl_opt",  "baseline", "R1+R4", orders_bl, t_m1_bl, True, True),
                    ("C_pr_full", "pruned",   "full", orders_pr, t_m1_pr, False, False),
                    ("D_pr_opt",  "pruned",   "R1+R4", orders_pr, t_m1_pr, True, True),
                ]
                for pname, m1_strat, m2_mode, orders, t_m1, r1, r4 in pipelines:
                    if not orders:
                        continue
                    with timer() as t_m2:
                        res = run_m2(
                            graph, orders, adapter,
                            prefix_eval_mode="full",
                            enable_r1=r1, enable_r4=r4,
                        )
                    csv_e8e.write_row(
                        dataset=ds, size=q["size"], density=q["density"],
                        query=q["name"], pipeline=pname,
                        m1_strategy=m1_strat, m2_mode=m2_mode,
                        n_orders=len(orders),
                        m1_time_s=f"{t_m1.elapsed_s:.6f}",
                        m2_time_s=f"{t_m2.elapsed_s:.6f}",
                        total_plan_s=f"{t_m1.elapsed_s + t_m2.elapsed_s:.6f}",
                        cpp_calls=res.n_cpp_calls,
                        cache_hits=res.cache_hits,
                        r3_skips=res.r3_skips,
                    )

            print(f"  [{ds}] done")

    finally:
        csv_e8a.close()
        csv_e8c.close()
        csv_e8e.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
