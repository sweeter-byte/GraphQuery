"""E4: Overhead reduction — planning time breakdown.

Measures the time breakdown of each pipeline stage (M1, M2, total planning)
for both baseline and optimized pipelines, quantifying the overhead reduction
from all optimizations combined.

Usage:
    python experiments/run_e4.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer
from experiments.common.m2_runner import run_m2, run_m2_full

from server.services.estimator_adapter import EstimatorAdapter
from server.services.score_aggregator import EarlyStopConfig
from server.services.order_strategies.baseline import generate_orders_baseline
from server.services.order_strategies.pruned import generate_orders_pruned


def main():
    p = base_argparser("E4: overhead reduction — planning time breakdown")
    args = p.parse_args()

    adapter = EstimatorAdapter()

    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e4_overhead.csv",
        columns=[
            "dataset", "size", "density", "query",
            # Baseline
            "bl_n_orders", "bl_m1_s", "bl_m2_s", "bl_total_s",
            "bl_cpp_calls",
            # Optimized
            "opt_n_orders", "opt_m1_s", "opt_m2_s", "opt_total_s",
            "opt_cpp_calls", "opt_cache_hits", "opt_r3_skips",
            # Speedups
            "m1_speedup", "m2_speedup", "total_speedup",
            "cpp_call_reduction",
        ],
        metadata={"experiment": "E4"},
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

                # --- Baseline: original M1 + full M2 ---
                with timer() as t_bl_m1:
                    orders_bl = generate_orders_baseline(graph)
                if not orders_bl:
                    continue
                with timer() as t_bl_m2:
                    res_bl = run_m2_full(graph, orders_bl, adapter)
                bl_total = t_bl_m1.elapsed_s + t_bl_m2.elapsed_s

                # --- Optimized: pruned M1 + optimized M2 (R1+R4+R3) ---
                with timer() as t_opt_m1:
                    orders_opt = generate_orders_pruned(graph)
                if not orders_opt:
                    continue
                es_cfg = EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)
                with timer() as t_opt_m2:
                    res_opt = run_m2(graph, orders_opt, adapter, early_stop_config=es_cfg)
                opt_total = t_opt_m1.elapsed_s + t_opt_m2.elapsed_s

                # Speedups
                m1_sp = t_bl_m1.elapsed_s / t_opt_m1.elapsed_s if t_opt_m1.elapsed_s > 0 else float("inf")
                m2_sp = t_bl_m2.elapsed_s / t_opt_m2.elapsed_s if t_opt_m2.elapsed_s > 0 else float("inf")
                total_sp = bl_total / opt_total if opt_total > 0 else float("inf")
                call_red = 1.0 - (res_opt.n_cpp_calls / res_bl.n_cpp_calls) if res_bl.n_cpp_calls > 0 else 0.0

                csv_out.write_row(
                    dataset=ds, size=q["size"], density=q["density"],
                    query=q["name"],
                    bl_n_orders=len(orders_bl),
                    bl_m1_s=f"{t_bl_m1.elapsed_s:.6f}",
                    bl_m2_s=f"{t_bl_m2.elapsed_s:.6f}",
                    bl_total_s=f"{bl_total:.6f}",
                    bl_cpp_calls=res_bl.n_cpp_calls,
                    opt_n_orders=len(orders_opt),
                    opt_m1_s=f"{t_opt_m1.elapsed_s:.6f}",
                    opt_m2_s=f"{t_opt_m2.elapsed_s:.6f}",
                    opt_total_s=f"{opt_total:.6f}",
                    opt_cpp_calls=res_opt.n_cpp_calls,
                    opt_cache_hits=res_opt.cache_hits,
                    opt_r3_skips=res_opt.r3_skips,
                    m1_speedup=f"{m1_sp:.2f}",
                    m2_speedup=f"{m2_sp:.2f}",
                    total_speedup=f"{total_sp:.2f}",
                    cpp_call_reduction=f"{call_red:.4f}",
                )

            print(f"  [{ds}] done")

    finally:
        csv_out.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
