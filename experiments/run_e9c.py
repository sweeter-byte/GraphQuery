"""E9c: min_completed sensitivity analysis for R3 early stopping.

Sweeps min_completed values with a fixed multiplier, measuring skip ratio
and ranking quality impact.

Usage:
    python experiments/run_e9c.py --datasets yeast --sizes 4 8 --num-queries 5
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

DEFAULT_MIN_COMPLETED = [1, 2, 3, 5, 10, 20]


def main():
    p = base_argparser("E9c: min_completed sensitivity for R3")
    p.add_argument("--multiplier", type=float, default=2.0, help="Fixed R3 multiplier")
    p.add_argument(
        "--min-completed-values", nargs="+", type=int, default=DEFAULT_MIN_COMPLETED,
        help="min_completed values to sweep",
    )
    p.add_argument("--top-k", type=int, default=10)
    args = p.parse_args()

    log = setup_logger("E9c", log_dir=args.output_dir)
    errors = ErrorCounter()
    log.info("E9c started — datasets=%s", args.datasets)

    adapter = EstimatorAdapter()

    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e9c_min_completed.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "min_completed", "r3_skips", "skip_ratio",
            "cpp_calls", "m2_time_s",
            "top1_match", "topk_overlap",
        ],
        metadata={
            "experiment": "E9c",
            "multiplier": str(args.multiplier),
            "min_completed_values": str(args.min_completed_values),
        },
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
            print(f"  [{ds}] {len(queries)} queries x {len(args.min_completed_values)} min_completed values")

            for q in queries:
              try:
                with query_timeout(args.timeout):
                    graph = q["graph"]
                    orders = generate_orders(graph)
                    if not orders:
                        continue

                    # Baseline: no R3
                    res_base = run_m2(graph, orders, adapter)
                    base_top1 = (
                        res_base.aggregator.trackers[res_base.aggregator.best_order_id].order
                        if res_base.aggregator.best_order_id is not None else []
                    )
                    base_topk = {
                        tuple(t["order"])
                        for t in res_base.aggregator.get_top_k()[:args.top_k]
                    }

                    for mc in args.min_completed_values:
                        es_cfg = EarlyStopConfig(
                            enabled=True, multiplier=args.multiplier, min_completed=mc,
                        )
                        with timer() as t_r3:
                            res = run_m2(graph, orders, adapter, early_stop_config=es_cfg)

                        total_evals = len(orders) * graph.num_vertices
                        skip_ratio = res.r3_skips / total_evals if total_evals > 0 else 0.0

                        r3_top1 = (
                            res.aggregator.trackers[res.aggregator.best_order_id].order
                            if res.aggregator.best_order_id is not None else []
                        )
                        r3_topk = {
                            tuple(t["order"])
                            for t in res.aggregator.get_top_k()[:args.top_k]
                        }
                        k_eff = min(len(base_topk), len(r3_topk), args.top_k)
                        topk_overlap = len(base_topk & r3_topk) / k_eff if k_eff > 0 else 0.0

                        csv_out.write_row(
                            dataset=ds, size=q["size"], density=q["density"],
                            query=q["name"], n_orders=len(orders),
                            min_completed=mc,
                            r3_skips=res.r3_skips,
                            skip_ratio=f"{skip_ratio:.4f}",
                            cpp_calls=res.n_cpp_calls,
                            m2_time_s=f"{t_r3.elapsed_s:.6f}",
                            top1_match=1 if r3_top1 == base_top1 else 0,
                            topk_overlap=f"{topk_overlap:.4f}",
                        )
              except QueryTimeout:
                log.error("query %s timed out", q["name"])
                errors.record(dataset=ds, query=q["name"], phase="E9c", error="timeout")
              except Exception as e:
                log.error("query %s failed: %s", q["name"], e, exc_info=True)
                errors.record(dataset=ds, query=q["name"], phase="E9c", error=str(e))

            print(f"  [{ds}] done")

    finally:
        csv_out.close()

    print(f"Results written to {args.output_dir}")
    errors.summary(log)


if __name__ == "__main__":
    main()
