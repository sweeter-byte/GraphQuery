"""E1: Sequence quality comparison — OPT vs RAND vs DEFAULT vs WORST.

Compares M2's top-1 order against random, default, and worst baselines
via M3 ground-truth execution.

Usage:
    python experiments/run_e1.py --datasets yeast --sizes 4 8 --num-queries 5
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
from experiments.common.stats import spearman_corr, mean_std, wilcoxon_test
from experiments.common.m2_runner import run_m2

from server.services.estimator_adapter import EstimatorAdapter
from server.services.order_strategies.pruned import generate_orders_pruned
from server.services.graph_format_converter import serialize_graph_to_file
from server.services.survey_engine_adapter import SurveyEngineAdapter


def _run_m3(engine, data_graph_path, query_path, max_emb, time_limit):
    """Execute M3 and return result dict."""
    try:
        result = engine.execute(
            data_graph_path, query_path,
            max_embeddings=max_emb, time_limit=time_limit,
        )
        return {
            "eps": result.get("eps", 0.0),
            "embeddings": result.get("embedding_count", 0),
            "total_time_s": result.get("total_time_seconds", 0.0),
            "enum_time_s": result.get("enumeration_time_seconds", 0.0),
            "call_count": result.get("call_count", 0),
            "timed_out": result.get("timed_out", False),
        }
    except Exception as e:
        return {"eps": 0.0, "embeddings": 0, "total_time_s": 0.0,
                "enum_time_s": 0.0, "call_count": 0, "timed_out": False, "error": str(e)}


def main():
    p = base_argparser("E1: sequence quality — OPT vs RAND vs DEFAULT vs WORST")
    p.add_argument("--n-rand", type=int, default=10, help="Number of random samples")
    p.add_argument("--top-k", type=int, default=5, help="Top-K orders for TOP5-AVG")
    p.add_argument("--max-embeddings", type=int, default=100000)
    p.add_argument("--time-limit", type=int, default=60)
    args = p.parse_args()

    adapter = EstimatorAdapter()
    engine = SurveyEngineAdapter()
    if not engine.is_available:
        print("ERROR: Survey binary not available. Build it first.")
        sys.exit(1)

    # Per-sequence-source results
    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e1_sequence_quality.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "source", "order_id", "m2_score",
            "m3_eps", "m3_embeddings", "m3_total_time_s",
            "m3_enum_time_s", "m3_call_count", "m3_timed_out",
        ],
        metadata={"experiment": "E1", "n_rand": str(args.n_rand), "top_k": str(args.top_k)},
    )

    # Per-query summary
    csv_summary = ExperimentCSV(
        Path(args.output_dir) / "e1_summary.csv",
        columns=[
            "dataset", "size", "density", "query",
            "opt_eps", "top5_avg_eps", "rand_avg_eps", "rand_median_eps",
            "default_eps", "worst_eps",
            "speedup_vs_rand", "speedup_vs_default",
        ],
        metadata={"experiment": "E1-summary"},
    )

    rng = random.Random(args.seed)

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
                orders = generate_orders_pruned(graph)
                if not orders:
                    continue

                # M2 ranking
                res_m2 = run_m2(graph, orders, adapter)
                ranking = res_m2.aggregator.get_top_k()

                tmp_query = serialize_graph_to_file(graph)

                def _exec(source, oid, score):
                    r = _run_m3(engine, data_graph_path, tmp_query,
                                args.max_embeddings, args.time_limit)
                    csv_out.write_row(
                        dataset=ds, size=q["size"], density=q["density"],
                        query=q["name"], n_orders=len(orders),
                        source=source, order_id=oid, m2_score=f"{score:.4f}",
                        m3_eps=f"{r['eps']:.2f}", m3_embeddings=r["embeddings"],
                        m3_total_time_s=f"{r['total_time_s']:.4f}",
                        m3_enum_time_s=f"{r['enum_time_s']:.4f}",
                        m3_call_count=r["call_count"],
                        m3_timed_out=1 if r["timed_out"] else 0,
                    )
                    return r

                # OPT: M2 top-1
                opt_entry = ranking[0] if ranking else None
                opt_r = _exec("OPT", opt_entry["order_id"], opt_entry["score"]) if opt_entry else None

                # TOP5-AVG: M2 top-5
                top5_eps = []
                for entry in ranking[:args.top_k]:
                    r = _exec("TOP5", entry["order_id"], entry["score"])
                    top5_eps.append(r["eps"])

                # WORST: M2 last-ranked
                worst_entry = ranking[-1] if ranking else None
                worst_r = _exec("WORST", worst_entry["order_id"], worst_entry["score"]) if worst_entry else None

                # RAND-k: random sample from candidate space
                rand_indices = rng.sample(range(len(orders)), min(args.n_rand, len(orders)))
                rand_eps = []
                for idx in rand_indices:
                    score = res_m2.aggregator.trackers[idx].score
                    r = _exec("RAND", idx, score)
                    rand_eps.append(r["eps"])

                # DEFAULT: use Survey engine's own ordering (no custom order)
                default_r = _exec("DEFAULT", -1, 0.0)

                if os.path.exists(tmp_query):
                    os.remove(tmp_query)

                # Summary
                opt_eps = opt_r["eps"] if opt_r else 0.0
                top5_avg = sum(top5_eps) / len(top5_eps) if top5_eps else 0.0
                rand_avg = sum(rand_eps) / len(rand_eps) if rand_eps else 0.0
                rand_sorted = sorted(rand_eps)
                rand_median = rand_sorted[len(rand_sorted) // 2] if rand_sorted else 0.0
                default_eps = default_r["eps"] if default_r else 0.0
                worst_eps = worst_r["eps"] if worst_r else 0.0

                opt_time = opt_r["total_time_s"] if opt_r else 0.0
                rand_avg_time = sum(r["total_time_s"] for r in [_run_m3(engine, data_graph_path, "/dev/null", 1, 1)] * 0) or 0.0
                # Use rand times already collected
                rand_times = []
                # We already have rand_eps but not rand times stored separately
                # Speedup based on EPS (higher = better)
                speedup_rand = opt_eps / rand_avg if rand_avg > 0 else float("inf")
                speedup_default = opt_eps / default_eps if default_eps > 0 else float("inf")

                csv_summary.write_row(
                    dataset=ds, size=q["size"], density=q["density"],
                    query=q["name"],
                    opt_eps=f"{opt_eps:.2f}",
                    top5_avg_eps=f"{top5_avg:.2f}",
                    rand_avg_eps=f"{rand_avg:.2f}",
                    rand_median_eps=f"{rand_median:.2f}",
                    default_eps=f"{default_eps:.2f}",
                    worst_eps=f"{worst_eps:.2f}",
                    speedup_vs_rand=f"{speedup_rand:.2f}",
                    speedup_vs_default=f"{speedup_default:.2f}",
                )

            print(f"  [{ds}] done")

    finally:
        csv_out.close()
        csv_summary.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
