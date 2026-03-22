"""E9a + E9b + E9d: R3 early stopping experiments.

E9a: Evaluation skip ratio under various R3 configurations.
E9b: Top-K quality preservation (R3 on vs off).
E9d: R3 + R4 synergy — combined vs individual optimization.

Usage:
    python experiments/run_e9.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES
from experiments.common.graph_loader import discover_queries, generate_orders
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer, query_timeout, QueryTimeout
from experiments.common.m2_runner import run_m2
from experiments.common.logger import setup_logger, ErrorCounter

from server.services.estimator_adapter import EstimatorAdapter
from server.services.score_aggregator import EarlyStopConfig

# R3 multiplier values to test
R3_MULTIPLIERS = [1.5, 2.0, 3.0, 5.0]


def main():
    p = base_argparser("E9: R3 early stopping experiments")
    p.add_argument("--multipliers", nargs="+", type=float, default=R3_MULTIPLIERS)
    p.add_argument("--top-k", type=int, default=10)
    args = p.parse_args()

    log = setup_logger("E9", log_dir=args.output_dir)
    errors = ErrorCounter()
    log.info("E9 started — datasets=%s", args.datasets)

    adapter = EstimatorAdapter()

    # E9a+E9b: skip ratio and quality
    csv_e9ab = ExperimentCSV(
        Path(args.output_dir) / "e9ab_early_stop.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "multiplier", "r3_skips", "skip_ratio",
            "cpp_calls", "m2_time_s",
            "top1_match", "topk_overlap",
        ],
        metadata={"experiment": "E9a+E9b", "multipliers": str(args.multipliers)},
    )

    # E9d: R3+R4 synergy
    csv_e9d = ExperimentCSV(
        Path(args.output_dir) / "e9d_synergy.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "config", "cpp_calls", "cache_hits", "r3_skips", "m2_time_s",
            "top1_match",
        ],
        metadata={"experiment": "E9d"},
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
                with query_timeout(args.timeout):
                    graph = q["graph"]
                    orders = generate_orders(graph)
                    if not orders:
                        continue

                    # Baseline: no R3 (optimized R1+R4 only)
                    with timer() as t_base:
                        res_base = run_m2(graph, orders, adapter)

                    base_top1 = (
                        res_base.aggregator.trackers[res_base.aggregator.best_order_id].order
                        if res_base.aggregator.best_order_id is not None else []
                    )
                    base_topk = {
                        tuple(t["order"])
                        for t in res_base.aggregator.get_top_k()[:args.top_k]
                    }

                    # E9a+E9b: sweep multipliers
                    for mult in args.multipliers:
                        es_cfg = EarlyStopConfig(enabled=True, multiplier=mult, min_completed=1)
                        with timer() as t_r3:
                            res_r3 = run_m2(
                                graph, orders, adapter,
                                early_stop_config=es_cfg,
                            )

                        total_evals = len(orders) * graph.num_vertices
                        skip_ratio = res_r3.r3_skips / total_evals if total_evals > 0 else 0.0

                        r3_top1 = (
                            res_r3.aggregator.trackers[res_r3.aggregator.best_order_id].order
                            if res_r3.aggregator.best_order_id is not None else []
                        )
                        r3_topk = {
                            tuple(t["order"])
                            for t in res_r3.aggregator.get_top_k()[:args.top_k]
                        }
                        k_eff = min(len(base_topk), len(r3_topk), args.top_k)
                        topk_overlap = len(base_topk & r3_topk) / k_eff if k_eff > 0 else 0.0

                        csv_e9ab.write_row(
                            dataset=ds, size=q["size"], density=q["density"],
                            query=q["name"], n_orders=len(orders),
                            multiplier=f"{mult:.1f}",
                            r3_skips=res_r3.r3_skips,
                            skip_ratio=f"{skip_ratio:.4f}",
                            cpp_calls=res_r3.n_cpp_calls,
                            m2_time_s=f"{t_r3.elapsed_s:.6f}",
                            top1_match=1 if r3_top1 == base_top1 else 0,
                            topk_overlap=f"{topk_overlap:.4f}",
                        )

                    # E9d: synergy comparison (4 configs)
                    configs = {
                        "none": {"enable_r1": False, "enable_r4": False,
                                 "early_stop_config": None},
                        "R4_only": {"enable_r1": False, "enable_r4": True,
                                    "early_stop_config": None},
                        "R3_only": {"enable_r1": False, "enable_r4": False,
                                    "early_stop_config": EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)},
                        "R3+R4": {"enable_r1": True, "enable_r4": True,
                                  "early_stop_config": EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)},
                    }

                    for cfg_name, cfg_kwargs in configs.items():
                        with timer() as t_cfg:
                            res_cfg = run_m2(graph, orders, adapter, **cfg_kwargs)

                        cfg_top1 = (
                            res_cfg.aggregator.trackers[res_cfg.aggregator.best_order_id].order
                            if res_cfg.aggregator.best_order_id is not None else []
                        )

                        csv_e9d.write_row(
                            dataset=ds, size=q["size"], density=q["density"],
                            query=q["name"], n_orders=len(orders),
                            config=cfg_name,
                            cpp_calls=res_cfg.n_cpp_calls,
                            cache_hits=res_cfg.cache_hits,
                            r3_skips=res_cfg.r3_skips,
                            m2_time_s=f"{t_cfg.elapsed_s:.6f}",
                            top1_match=1 if cfg_top1 == base_top1 else 0,
                        )
              except QueryTimeout:
                log.error("query %s timed out", q["name"])
                errors.record(dataset=ds, query=q["name"], phase="E9", error="timeout")
              except Exception as e:
                log.error("query %s failed: %s", q["name"], e, exc_info=True)
                errors.record(dataset=ds, query=q["name"], phase="E9", error=str(e))

            print(f"  [{ds}] done")

    finally:
        csv_e9ab.close()
        csv_e9d.close()

    print(f"Results written to {args.output_dir}")
    errors.summary(log)


if __name__ == "__main__":
    main()
