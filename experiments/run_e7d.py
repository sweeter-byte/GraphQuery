"""E7d: cost_factor sensitivity analysis for M1 A* pruning (S3).

Sweeps cost_factor values and measures order count and generation time.

Usage:
    python experiments/run_e7d.py --datasets yeast --sizes 4 8 --num-queries 10
    python experiments/run_e7d.py --cost-factors 1.2 1.5 2.0 3.0 5.0 10.0
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES, ALL_DATASETS
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer, query_timeout, QueryTimeout
from experiments.common.logger import setup_logger, ErrorCounter

from server.services.order_strategies.pruned import generate_orders_pruned

DEFAULT_COST_FACTORS = [1.1, 1.2, 1.5, 2.0, 3.0, 5.0, 10.0, 50.0]


def main():
    p = base_argparser("E7d: cost_factor sensitivity analysis", default_datasets=ALL_DATASETS)
    p.add_argument(
        "--cost-factors", nargs="+", type=float, default=DEFAULT_COST_FACTORS,
        help="cost_factor values to sweep",
    )
    p.add_argument("--max-orders", type=int, default=500)
    args = p.parse_args()

    log = setup_logger("E7d", log_dir=args.output_dir)
    errors = ErrorCounter()
    log.info("E7d started — datasets=%s, cost_factors=%s", args.datasets, args.cost_factors)

    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e7d_cost_factor.csv",
        columns=[
            "dataset", "size", "density", "query", "cost_factor",
            "n_orders", "time_s",
        ],
        metadata={
            "experiment": "E7d",
            "cost_factors": ",".join(f"{cf:.1f}" for cf in args.cost_factors),
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

            print(f"  [{ds}] {len(queries)} queries x {len(args.cost_factors)} cost_factors")

            for q in queries:
              try:
                with query_timeout(args.timeout):
                  graph = q["graph"]
                  # Quick feasibility check: try the most permissive cost_factor.
                  # If even that returns 0, skip all cost_factors for this query.
                  max_cf = max(args.cost_factors)
                  probe = generate_orders_pruned(
                      graph, cost_factor=max_cf, max_orders=1,
                  )
                  skip_all = len(probe) == 0
                  for cf in args.cost_factors:
                      if skip_all:
                          csv_out.write_row(
                              dataset=ds, size=q["size"], density=q["density"],
                              query=q["name"], cost_factor=f"{cf:.2f}",
                              n_orders=0, time_s="0.000000",
                          )
                          continue
                      with timer() as t:
                          orders = generate_orders_pruned(
                              graph, cost_factor=cf, max_orders=args.max_orders,
                          )
                      csv_out.write_row(
                          dataset=ds, size=q["size"], density=q["density"],
                          query=q["name"], cost_factor=f"{cf:.2f}",
                          n_orders=len(orders), time_s=f"{t.elapsed_s:.6f}",
                      )
              except QueryTimeout:
                log.warning("query %s timed out (%ds)", q["name"], args.timeout)
                errors.record(dataset=ds, query=q["name"], phase="E7d", error=f"timeout ({args.timeout}s)")
              except Exception as e:
                log.error("query %s failed: %s", q["name"], e, exc_info=True)
                errors.record(dataset=ds, query=q["name"], phase="E7d", error=str(e))

            print(f"  [{ds}] done")

    finally:
        csv_out.close()

    print(f"Results written to {args.output_dir}")
    errors.summary(log)


if __name__ == "__main__":
    main()
