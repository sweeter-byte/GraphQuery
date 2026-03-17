"""E2: Estimation precision verification — M2 estimates vs M3 ground truth.

For each prefix level, compares FaSTest cardinality estimates against
actual embedding counts from M3 execution.

Usage:
    python experiments/run_e2.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES, DATASET_ROOT
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.m2_runner import run_m2

from server.services.estimator_adapter import EstimatorAdapter
from server.services.order_strategies.pruned import generate_orders_pruned
from server.services.graph_format_converter import serialize_graph_to_file
from server.services.survey_engine_adapter import SurveyEngineAdapter


def main():
    p = base_argparser("E2: estimation precision — M2 vs M3 ground truth")
    p.add_argument("--top-k", type=int, default=5, help="Orders to verify")
    p.add_argument("--max-embeddings", type=int, default=100000)
    p.add_argument("--time-limit", type=int, default=60)
    args = p.parse_args()

    adapter = EstimatorAdapter()
    engine = SurveyEngineAdapter()
    if not engine.is_available:
        print("ERROR: Survey binary not available. Build it first.")
        sys.exit(1)

    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e2_precision.csv",
        columns=[
            "dataset", "size", "density", "query",
            "order_id", "m2_score", "m3_eps", "m3_embeddings", "m3_time_s",
            "m2_rank", "m3_rank",
        ],
        metadata={"experiment": "E2", "top_k": str(args.top_k)},
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
                orders = generate_orders_pruned(graph)
                if not orders:
                    continue

                res_m2 = run_m2(graph, orders, adapter)
                topk = res_m2.aggregator.get_top_k()[:args.top_k]

                tmp_query = serialize_graph_to_file(graph)

                # Execute M3 for each top-K order and collect EPS
                m3_results = []
                for entry in topk:
                    oid = entry["order_id"]
                    try:
                        result = engine.execute(
                            data_graph_path, tmp_query,
                            max_embeddings=args.max_embeddings,
                            time_limit=args.time_limit,
                        )
                        eps = result.get("eps", 0.0)
                        emb = result.get("embedding_count", 0)
                        total_t = result.get("total_time_seconds", 0.0)
                    except Exception as e:
                        print(f"    M3 failed for order {oid}: {e}")
                        eps, emb, total_t = 0.0, 0, 0.0
                    m3_results.append({
                        "order_id": oid, "m2_score": entry["score"],
                        "m2_rank": entry["rank"],
                        "eps": eps, "emb": emb, "time_s": total_t,
                    })

                if os.path.exists(tmp_query):
                    os.remove(tmp_query)

                # Compute M3 ranking by EPS (higher = better → rank 1)
                m3_sorted = sorted(m3_results, key=lambda x: -x["eps"])
                m3_rank_map = {r["order_id"]: i + 1 for i, r in enumerate(m3_sorted)}

                for r in m3_results:
                    csv_out.write_row(
                        dataset=ds, size=q["size"], density=q["density"],
                        query=q["name"],
                        order_id=r["order_id"],
                        m2_score=f"{r['m2_score']:.4f}",
                        m3_eps=f"{r['eps']:.2f}",
                        m3_embeddings=r["emb"],
                        m3_time_s=f"{r['time_s']:.4f}",
                        m2_rank=r["m2_rank"],
                        m3_rank=m3_rank_map[r["order_id"]],
                    )

            print(f"  [{ds}] done")

    finally:
        csv_out.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
