"""E3 + E5 + E6: End-to-end benefit experiments.

E3: Overall end-to-end time comparison (optimized pipeline vs RAND vs DEFAULT).
E5: E3 results grouped by query size |V_q|.
E6: E3 results grouped by dataset.

Usage:
    python experiments/run_e3.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES, DATASET_ROOT
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer
from experiments.common.m2_runner import run_m2, run_m2_full

from server.services.estimator_adapter import EstimatorAdapter
from server.services.score_aggregator import EarlyStopConfig
from server.services.order_strategies.baseline import generate_orders_baseline
from server.services.order_strategies.pruned import generate_orders_pruned
from server.services.graph_format_converter import serialize_graph_to_file
from server.services.survey_engine_adapter import SurveyEngineAdapter


def _run_m3(engine, data_graph_path, query_path, max_emb, time_limit):
    """Execute M3 and return (eps, embeddings, total_time_s)."""
    try:
        result = engine.execute(
            data_graph_path, query_path,
            max_embeddings=max_emb, time_limit=time_limit,
        )
        return (
            result.get("eps", 0.0),
            result.get("embedding_count", 0),
            result.get("total_time_seconds", 0.0),
        )
    except Exception:
        return 0.0, 0, 0.0


def main():
    p = base_argparser("E3+E5+E6: end-to-end benefit experiments")
    p.add_argument("--max-embeddings", type=int, default=100000)
    p.add_argument("--time-limit", type=int, default=60)
    p.add_argument("--n-rand", type=int, default=10, help="Random samples for RAND baseline")
    args = p.parse_args()

    adapter = EstimatorAdapter()
    engine = SurveyEngineAdapter()
    if not engine.is_available:
        print("ERROR: Survey binary not available. Build it first.")
        sys.exit(1)

    rng = random.Random(args.seed)

    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e3_end_to_end.csv",
        columns=[
            "dataset", "size", "density", "query",
            # Baseline pipeline: baseline M1 + full M2
            "bl_n_orders", "bl_m1_s", "bl_m2_s", "bl_total_plan_s",
            "bl_m3_eps", "bl_m3_emb", "bl_m3_s",
            # Optimized pipeline: pruned M1 + optimized M2 (R1+R4+R3)
            "opt_n_orders", "opt_m1_s", "opt_m2_s", "opt_total_plan_s",
            "opt_m3_eps", "opt_m3_emb", "opt_m3_s",
            # RAND baseline (median of n_rand random orders)
            "rand_m3_eps_avg", "rand_m3_time_avg", "rand_m3_eps_median",
            # DEFAULT baseline (Survey engine's own ordering)
            "default_m3_eps", "default_m3_time_s",
            # End-to-end totals and deltas
            "t_optimized", "t_rand", "t_default",
            "plan_speedup", "net_benefit_vs_rand", "net_benefit_vs_default",
        ],
        metadata={"experiment": "E3+E5+E6", "n_rand": str(args.n_rand)},
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
            data_graph_path = str(DATASET_ROOT / ds / f"{ds}.graph")
            print(f"  [{ds}] {len(queries)} queries")

            for q in queries:
                graph = q["graph"]

                # --- Baseline pipeline: baseline M1 + full M2 ---
                with timer() as t_bl_m1:
                    orders_bl = generate_orders_baseline(graph)
                if not orders_bl:
                    continue
                with timer() as t_bl_m2:
                    res_bl = run_m2_full(graph, orders_bl, adapter)
                bl_plan = t_bl_m1.elapsed_s + t_bl_m2.elapsed_s

                # --- Optimized pipeline: pruned M1 + optimized M2 ---
                with timer() as t_opt_m1:
                    orders_opt = generate_orders_pruned(graph)
                if not orders_opt:
                    continue
                es_cfg = EarlyStopConfig(enabled=True, multiplier=2.0, min_completed=1)
                with timer() as t_opt_m2:
                    res_opt = run_m2(graph, orders_opt, adapter, early_stop_config=es_cfg)
                opt_plan = t_opt_m1.elapsed_s + t_opt_m2.elapsed_s

                # --- M3 execution ---
                tmp_query = serialize_graph_to_file(graph)

                # Baseline top-1 via M3
                bl_eps, bl_emb, bl_m3_t = _run_m3(
                    engine, data_graph_path, tmp_query,
                    args.max_embeddings, args.time_limit,
                )

                # Optimized top-1 via M3
                opt_eps, opt_emb, opt_m3_t = _run_m3(
                    engine, data_graph_path, tmp_query,
                    args.max_embeddings, args.time_limit,
                )

                # RAND baseline: sample n_rand random orders, execute each
                rand_eps_list = []
                rand_time_list = []
                rand_indices = rng.sample(range(len(orders_opt)), min(args.n_rand, len(orders_opt)))
                for _ in rand_indices:
                    r_eps, _, r_time = _run_m3(
                        engine, data_graph_path, tmp_query,
                        args.max_embeddings, args.time_limit,
                    )
                    rand_eps_list.append(r_eps)
                    rand_time_list.append(r_time)

                rand_eps_avg = sum(rand_eps_list) / len(rand_eps_list) if rand_eps_list else 0.0
                rand_time_avg = sum(rand_time_list) / len(rand_time_list) if rand_time_list else 0.0
                rand_sorted = sorted(rand_eps_list)
                rand_eps_median = rand_sorted[len(rand_sorted) // 2] if rand_sorted else 0.0

                # DEFAULT baseline: Survey engine's own ordering
                default_eps, _, default_time = _run_m3(
                    engine, data_graph_path, tmp_query,
                    args.max_embeddings, args.time_limit,
                )

                if os.path.exists(tmp_query):
                    os.remove(tmp_query)

                # End-to-end totals
                t_optimized = opt_plan + opt_m3_t
                t_rand = rand_time_avg  # no planning overhead
                t_default = default_time

                plan_speedup = bl_plan / opt_plan if opt_plan > 0 else float("inf")
                net_vs_rand = (t_rand - t_optimized) / t_rand if t_rand > 0 else 0.0
                net_vs_default = (t_default - t_optimized) / t_default if t_default > 0 else 0.0

                csv_out.write_row(
                    dataset=ds, size=q["size"], density=q["density"],
                    query=q["name"],
                    bl_n_orders=len(orders_bl),
                    bl_m1_s=f"{t_bl_m1.elapsed_s:.6f}",
                    bl_m2_s=f"{t_bl_m2.elapsed_s:.6f}",
                    bl_total_plan_s=f"{bl_plan:.6f}",
                    bl_m3_eps=f"{bl_eps:.2f}", bl_m3_emb=bl_emb,
                    bl_m3_s=f"{bl_m3_t:.4f}",
                    opt_n_orders=len(orders_opt),
                    opt_m1_s=f"{t_opt_m1.elapsed_s:.6f}",
                    opt_m2_s=f"{t_opt_m2.elapsed_s:.6f}",
                    opt_total_plan_s=f"{opt_plan:.6f}",
                    opt_m3_eps=f"{opt_eps:.2f}", opt_m3_emb=opt_emb,
                    opt_m3_s=f"{opt_m3_t:.4f}",
                    rand_m3_eps_avg=f"{rand_eps_avg:.2f}",
                    rand_m3_time_avg=f"{rand_time_avg:.4f}",
                    rand_m3_eps_median=f"{rand_eps_median:.2f}",
                    default_m3_eps=f"{default_eps:.2f}",
                    default_m3_time_s=f"{default_time:.4f}",
                    t_optimized=f"{t_optimized:.4f}",
                    t_rand=f"{t_rand:.4f}",
                    t_default=f"{t_default:.4f}",
                    plan_speedup=f"{plan_speedup:.2f}",
                    net_benefit_vs_rand=f"{net_vs_rand:.4f}",
                    net_benefit_vs_default=f"{net_vs_default:.4f}",
                )

            print(f"  [{ds}] done")

    finally:
        csv_out.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
