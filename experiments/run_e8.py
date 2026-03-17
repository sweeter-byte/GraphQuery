"""E8a + E8b + E8c + E8e: M2 prefix deduplication experiments.

E8a: C++ call reduction ratio (full vs optimized R1+R4).
E8b: M2 wall-clock speedup.
E8c: Ranking consistency (lossless verification).
E8e: End-to-end M1+M2 time with optimized prefix evaluation.

Usage:
    python experiments/run_e8.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES, DATASETS_WITH_INDEX
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer
from experiments.common.m2_runner import run_m2, run_m2_full

from server.services.estimator_adapter import EstimatorAdapter
from server.services.order_strategies.pruned import generate_orders_pruned


def main():
    p = base_argparser("E8: M2 prefix deduplication (R1+R4)")
    p.add_argument("--strategy", default="pruned", choices=["baseline", "pruned"])
    args = p.parse_args()

    adapter = EstimatorAdapter()

    csv_e8 = ExperimentCSV(
        Path(args.output_dir) / "e8_dedup.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            # E8a: call reduction
            "cpp_calls_full", "cpp_calls_opt", "call_reduction",
            "cache_hits", "cache_misses", "cache_hit_rate",
            # E8b: M2 speedup
            "m2_time_full_s", "m2_time_opt_s", "m2_speedup",
            # E8c: ranking consistency
            "top1_match", "scores_identical",
            # E8e: end-to-end
            "m1_time_s", "total_full_s", "total_opt_s", "total_speedup",
        ],
        metadata={"experiment": "E8a+E8b+E8c+E8e", "strategy": args.strategy},
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

                # M1: generate orders once
                with timer() as t_m1:
                    if args.strategy == "pruned":
                        orders = generate_orders_pruned(graph)
                    else:
                        from server.services.order_strategies.baseline import generate_orders_baseline
                        orders = generate_orders_baseline(graph)

                if not orders:
                    continue

                # M2 full mode (no R1/R4)
                with timer() as t_full:
                    res_full = run_m2_full(graph, orders, adapter)

                # M2 optimized mode (R1+R4)
                with timer() as t_opt:
                    res_opt = run_m2(graph, orders, adapter)

                # E8a: call reduction
                calls_full = res_full.n_cpp_calls
                calls_opt = res_opt.n_cpp_calls
                call_reduction = 1.0 - (calls_opt / calls_full) if calls_full > 0 else 0.0
                hit_rate = res_opt.cache_hits / (res_opt.cache_hits + res_opt.cache_misses) if (res_opt.cache_hits + res_opt.cache_misses) > 0 else 0.0

                # E8c: ranking consistency
                full_best_id = res_full.aggregator.best_order_id
                opt_best_id = res_opt.aggregator.best_order_id
                full_top1 = res_full.aggregator.trackers[full_best_id].order if full_best_id is not None else []
                opt_top1 = res_opt.aggregator.trackers[opt_best_id].order if opt_best_id is not None else []
                top1_match = 1 if full_top1 == opt_top1 else 0

                # Check if all order scores are identical
                scores_identical = 1
                for oid in res_full.aggregator.trackers:
                    sf = res_full.aggregator.trackers[oid].score
                    so = res_opt.aggregator.trackers[oid].score
                    if abs(sf - so) > 1e-6:
                        scores_identical = 0
                        break

                # E8e: end-to-end
                total_full = t_m1.elapsed_s + t_full.elapsed_s
                total_opt = t_m1.elapsed_s + t_opt.elapsed_s
                total_speedup = total_full / total_opt if total_opt > 0 else float("inf")

                csv_e8.write_row(
                    dataset=ds, size=q["size"], density=q["density"],
                    query=q["name"], n_orders=len(orders),
                    cpp_calls_full=calls_full, cpp_calls_opt=calls_opt,
                    call_reduction=f"{call_reduction:.4f}",
                    cache_hits=res_opt.cache_hits, cache_misses=res_opt.cache_misses,
                    cache_hit_rate=f"{hit_rate:.4f}",
                    m2_time_full_s=f"{t_full.elapsed_s:.6f}",
                    m2_time_opt_s=f"{t_opt.elapsed_s:.6f}",
                    m2_speedup=f"{t_full.elapsed_s / t_opt.elapsed_s:.2f}" if t_opt.elapsed_s > 0 else "inf",
                    top1_match=top1_match, scores_identical=scores_identical,
                    m1_time_s=f"{t_m1.elapsed_s:.6f}",
                    total_full_s=f"{total_full:.6f}",
                    total_opt_s=f"{total_opt:.6f}",
                    total_speedup=f"{total_speedup:.2f}",
                )

            print(f"  [{ds}] done")

    finally:
        csv_e8.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
