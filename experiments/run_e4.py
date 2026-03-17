"""E4: Overhead reduction — planning time breakdown with parameter sweeps.

E4a: Beam width sweep — M1+M2 time vs OPT quality at different beam widths.
E4b: R3 early stopping configs comparison.
E4c: Parallelism sweep — python_threads impact on M2 throughput.
Also: baseline vs optimized pipeline comparison.

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
from experiments.common.logger import setup_logger, ErrorCounter

from server.services.estimator_adapter import EstimatorAdapter
from server.services.score_aggregator import EarlyStopConfig
from server.services.order_strategies.baseline import generate_orders_baseline
from server.services.order_strategies.pruned import generate_orders_pruned

BEAM_WIDTHS = [10, 25, 50, 100, 200, None]  # None = exact/pruned
R3_CONFIGS = [
    ("no_r3", None),
    ("r3_conservative", EarlyStopConfig(enabled=True, multiplier=3.0, min_completed=1)),
    ("r3_default", EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)),
    ("r3_moderate", EarlyStopConfig(enabled=True, multiplier=1.5, min_completed=1)),
]


def main():
    p = base_argparser("E4: overhead reduction — planning time breakdown")
    p.add_argument("--beam-widths", nargs="+", type=int, default=[10, 25, 50, 100, 200])
    args = p.parse_args()

    log = setup_logger("E4", log_dir=args.output_dir)
    errors = ErrorCounter()
    log.info("E4 started — datasets=%s", args.datasets)

    adapter = EstimatorAdapter()

    # E4 main: baseline vs optimized comparison
    csv_main = ExperimentCSV(
        Path(args.output_dir) / "e4_overhead.csv",
        columns=[
            "dataset", "size", "density", "query",
            "bl_n_orders", "bl_m1_s", "bl_m2_s", "bl_total_s", "bl_cpp_calls",
            "opt_n_orders", "opt_m1_s", "opt_m2_s", "opt_total_s",
            "opt_cpp_calls", "opt_cache_hits", "opt_r3_skips",
            "m1_speedup", "m2_speedup", "total_speedup", "cpp_call_reduction",
        ],
        metadata={"experiment": "E4"},
    )

    # E4a: beam width sweep
    csv_e4a = ExperimentCSV(
        Path(args.output_dir) / "e4a_beam_width.csv",
        columns=[
            "dataset", "size", "density", "query",
            "beam_width", "n_orders", "m1_time_s", "m2_time_s",
            "total_plan_s", "cpp_calls", "best_score",
        ],
        metadata={"experiment": "E4a", "beam_widths": str(args.beam_widths)},
    )

    # E4b: R3 configs comparison
    csv_e4b = ExperimentCSV(
        Path(args.output_dir) / "e4b_r3_configs.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "config", "cpp_calls", "r3_skips", "m2_time_s", "best_score",
        ],
        metadata={"experiment": "E4b"},
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
              try:
                graph = q["graph"]

                # --- E4 main: baseline vs optimized ---
                with timer() as t_bl_m1:
                    orders_bl = generate_orders_baseline(graph)
                if not orders_bl:
                    continue
                with timer() as t_bl_m2:
                    res_bl = run_m2_full(graph, orders_bl, adapter)
                bl_total = t_bl_m1.elapsed_s + t_bl_m2.elapsed_s

                with timer() as t_opt_m1:
                    orders_opt = generate_orders_pruned(graph)
                if not orders_opt:
                    continue
                es_cfg = EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)
                with timer() as t_opt_m2:
                    res_opt = run_m2(graph, orders_opt, adapter, early_stop_config=es_cfg)
                opt_total = t_opt_m1.elapsed_s + t_opt_m2.elapsed_s

                m1_sp = t_bl_m1.elapsed_s / t_opt_m1.elapsed_s if t_opt_m1.elapsed_s > 0 else float("inf")
                m2_sp = t_bl_m2.elapsed_s / t_opt_m2.elapsed_s if t_opt_m2.elapsed_s > 0 else float("inf")
                total_sp = bl_total / opt_total if opt_total > 0 else float("inf")
                call_red = 1.0 - (res_opt.n_cpp_calls / res_bl.n_cpp_calls) if res_bl.n_cpp_calls > 0 else 0.0

                csv_main.write_row(
                    dataset=ds, size=q["size"], density=q["density"], query=q["name"],
                    bl_n_orders=len(orders_bl), bl_m1_s=f"{t_bl_m1.elapsed_s:.6f}",
                    bl_m2_s=f"{t_bl_m2.elapsed_s:.6f}", bl_total_s=f"{bl_total:.6f}",
                    bl_cpp_calls=res_bl.n_cpp_calls,
                    opt_n_orders=len(orders_opt), opt_m1_s=f"{t_opt_m1.elapsed_s:.6f}",
                    opt_m2_s=f"{t_opt_m2.elapsed_s:.6f}", opt_total_s=f"{opt_total:.6f}",
                    opt_cpp_calls=res_opt.n_cpp_calls, opt_cache_hits=res_opt.cache_hits,
                    opt_r3_skips=res_opt.r3_skips,
                    m1_speedup=f"{m1_sp:.2f}", m2_speedup=f"{m2_sp:.2f}",
                    total_speedup=f"{total_sp:.2f}", cpp_call_reduction=f"{call_red:.4f}",
                )

                # --- E4a: beam width sweep ---
                for bw in args.beam_widths:
                    with timer() as t_m1_bw:
                        orders_bw = generate_orders_baseline(graph, beam_width=bw)
                    if not orders_bw:
                        continue
                    with timer() as t_m2_bw:
                        res_bw = run_m2(graph, orders_bw, adapter)
                    best_sc = res_bw.aggregator.best_score or 0.0
                    csv_e4a.write_row(
                        dataset=ds, size=q["size"], density=q["density"], query=q["name"],
                        beam_width=bw, n_orders=len(orders_bw),
                        m1_time_s=f"{t_m1_bw.elapsed_s:.6f}",
                        m2_time_s=f"{t_m2_bw.elapsed_s:.6f}",
                        total_plan_s=f"{t_m1_bw.elapsed_s + t_m2_bw.elapsed_s:.6f}",
                        cpp_calls=res_bw.n_cpp_calls,
                        best_score=f"{best_sc:.4f}",
                    )
                # Also add pruned as a row
                best_sc_opt = res_opt.aggregator.best_score or 0.0
                csv_e4a.write_row(
                    dataset=ds, size=q["size"], density=q["density"], query=q["name"],
                    beam_width="pruned", n_orders=len(orders_opt),
                    m1_time_s=f"{t_opt_m1.elapsed_s:.6f}",
                    m2_time_s=f"{t_opt_m2.elapsed_s:.6f}",
                    total_plan_s=f"{opt_total:.6f}",
                    cpp_calls=res_opt.n_cpp_calls,
                    best_score=f"{best_sc_opt:.4f}",
                )

                # --- E4b: R3 configs ---
                for cfg_name, es in R3_CONFIGS:
                    with timer() as t_r3:
                        res_r3 = run_m2(graph, orders_opt, adapter, early_stop_config=es)
                    best_sc_r3 = res_r3.aggregator.best_score or 0.0
                    csv_e4b.write_row(
                        dataset=ds, size=q["size"], density=q["density"], query=q["name"],
                        n_orders=len(orders_opt), config=cfg_name,
                        cpp_calls=res_r3.n_cpp_calls, r3_skips=res_r3.r3_skips,
                        m2_time_s=f"{t_r3.elapsed_s:.6f}",
                        best_score=f"{best_sc_r3:.4f}",
                    )
              except Exception as e:
                log.error("query %s failed: %s", q["name"], e, exc_info=True)
                errors.record(dataset=ds, query=q["name"], phase="E4", error=str(e))

            print(f"  [{ds}] done")

    finally:
        csv_main.close()
        csv_e4a.close()
        csv_e4b.close()

    print(f"Results written to {args.output_dir}")
    errors.summary(log)


if __name__ == "__main__":
    main()
