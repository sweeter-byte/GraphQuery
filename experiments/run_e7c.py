"""E7c: Ablation study for M1 pruning strategies (S1-S4).

Runs pruned order generation with each strategy disabled individually
and all combinations, measuring order count and generation time.

Usage:
    python experiments/run_e7c.py --datasets yeast --sizes 4 8 --num-queries 10
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

# Ablation configurations: name -> kwargs overrides
ABLATION_CONFIGS = {
    "full":       {},
    "no_S1":      {"enable_symmetry": False},
    "no_S2":      {"enable_core_first": False},
    "no_S3":      {"enable_astar_prune": False},
    "no_S4":      {"enable_safety": False},
    "no_S1S2":    {"enable_symmetry": False, "enable_core_first": False},
    "no_S1S3":    {"enable_symmetry": False, "enable_astar_prune": False},
    "no_S3S4":    {"enable_astar_prune": False, "enable_safety": False},
    "none":       {"enable_symmetry": False, "enable_core_first": False,
                   "enable_astar_prune": False, "enable_safety": False},
}


def main():
    p = base_argparser("E7c: M1 pruning ablation study", default_datasets=ALL_DATASETS)
    p.add_argument(
        "--configs", nargs="+", default=list(ABLATION_CONFIGS.keys()),
        help="Ablation configs to run (default: all)",
    )
    p.add_argument("--max-orders", type=int, default=500)
    args = p.parse_args()

    log = setup_logger("E7c", log_dir=args.output_dir)
    errors = ErrorCounter()
    log.info("E7c started — datasets=%s, configs=%s", args.datasets, args.configs)

    configs = {k: ABLATION_CONFIGS[k] for k in args.configs if k in ABLATION_CONFIGS}

    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e7c_ablation.csv",
        columns=[
            "dataset", "size", "density", "query", "config",
            "n_orders", "time_s",
        ],
        metadata={"experiment": "E7c", "configs": ",".join(configs.keys())},
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

            print(f"  [{ds}] {len(queries)} queries x {len(configs)} configs")

            for q in queries:
              try:
                with query_timeout(args.timeout):
                  graph = q["graph"]
                  skip_rest = False
                  for cfg_name, cfg_kwargs in configs.items():
                      if skip_rest:
                          csv_out.write_row(
                              dataset=ds, size=q["size"], density=q["density"],
                              query=q["name"], config=cfg_name,
                              n_orders=0, time_s="0.000000",
                          )
                          continue
                      with timer() as t:
                          orders = generate_orders_pruned(
                              graph, max_orders=args.max_orders, **cfg_kwargs,
                          )
                      csv_out.write_row(
                          dataset=ds, size=q["size"], density=q["density"],
                          query=q["name"], config=cfg_name,
                          n_orders=len(orders), time_s=f"{t.elapsed_s:.6f}",
                      )
                      # If "full" (best) config found 0 orders, skip remaining
                      # configs — they won't do better with fewer strategies.
                      if cfg_name == "full" and len(orders) == 0:
                          skip_rest = True
              except QueryTimeout:
                log.warning("query %s timed out (%ds)", q["name"], args.timeout)
                errors.record(dataset=ds, query=q["name"], phase="E7c", error=f"timeout ({args.timeout}s)")
              except Exception as e:
                log.error("query %s failed: %s", q["name"], e, exc_info=True)
                errors.record(dataset=ds, query=q["name"], phase="E7c", error=str(e))

            print(f"  [{ds}] done")

    finally:
        csv_out.close()

    print(f"Results written to {args.output_dir}")
    errors.summary(log)


if __name__ == "__main__":
    main()
