"""E1: Sequence quality comparison — M2 ranking vs M3 ground truth.

Compares the top-K orders selected by M2 (FaSTest estimation) against
actual M3 execution performance (EPS). Measures Spearman correlation
between estimated ranking and ground-truth ranking.

Usage:
    python experiments/run_e1.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES, DATASET_ROOT
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer
from experiments.common.stats import spearman_corr
from experiments.common.m2_runner import run_m2

from server.services.estimator_adapter import EstimatorAdapter
from server.services.order_strategies.pruned import generate_orders_pruned
from server.services.graph_format_converter import serialize_graph_to_file
from server.services.survey_engine_adapter import SurveyEngineAdapter


def main():
    p = base_argparser("E1: sequence quality — M2 ranking vs M3 ground truth")
    p.add_argument("--top-k", type=int, default=10, help="Top-K orders to execute via M3")
    p.add_argument("--max-embeddings", type=int, default=100000)
    p.add_argument("--time-limit", type=int, default=60)
    args = p.parse_args()

    adapter = EstimatorAdapter()
    engine = SurveyEngineAdapter()
    if not engine.is_available:
        print("ERROR: Survey binary not available. Build it first.")
        sys.exit(1)

    csv_out = ExperimentCSV(
        Path(args.output_dir) / "e1_sequence_quality.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "order_id", "m2_rank", "m2_score",
            "m3_eps", "m3_embeddings", "m3_time_s",
        ],
        metadata={"experiment": "E1", "top_k": str(args.top_k)},
    )

    csv_summary = ExperimentCSV(
        Path(args.output_dir) / "e1_summary.csv",
        columns=[
            "dataset", "size", "density", "query",
            "spearman_rho", "spearman_p", "top1_is_best",
        ],
        metadata={"experiment": "E1-summary"},
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

                # M2 ranking
                res_m2 = run_m2(graph, orders, adapter)
                topk = res_m2.aggregator.get_top_k()[:args.top_k]

                # M3 execution for each top-K order
                tmp_query = serialize_graph_to_file(graph)
                m2_scores = []
                m3_eps_list = []

                for entry in topk:
                    oid = entry["order_id"]
                    m2_rank = entry["rank"]
                    m2_score = entry["score"]

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

                    m2_scores.append(m2_score)
                    m3_eps_list.append(eps)

                    csv_out.write_row(
                        dataset=ds, size=q["size"], density=q["density"],
                        query=q["name"], n_orders=len(orders),
                        order_id=oid, m2_rank=m2_rank,
                        m2_score=f"{m2_score:.4f}",
                        m3_eps=f"{eps:.2f}", m3_embeddings=emb,
                        m3_time_s=f"{total_t:.4f}",
                    )

                # Clean up temp file
                import os
                if os.path.exists(tmp_query):
                    os.remove(tmp_query)

                # Summary: Spearman between M2 score (lower=better) and M3 EPS (higher=better)
                # Negate M2 scores so both are "higher=better" for correlation
                if len(m2_scores) >= 3:
                    neg_m2 = [-s for s in m2_scores]
                    rho, p_val = spearman_corr(neg_m2, m3_eps_list)
                else:
                    rho, p_val = float("nan"), float("nan")

                # Is M2's top-1 also the best by M3 EPS?
                best_m3_idx = max(range(len(m3_eps_list)), key=lambda i: m3_eps_list[i]) if m3_eps_list else -1
                top1_is_best = 1 if best_m3_idx == 0 else 0

                csv_summary.write_row(
                    dataset=ds, size=q["size"], density=q["density"],
                    query=q["name"],
                    spearman_rho=f"{rho:.4f}", spearman_p=f"{p_val:.4f}",
                    top1_is_best=top1_is_best,
                )

            print(f"  [{ds}] done")

    finally:
        csv_out.close()
        csv_summary.close()

    print(f"Results written to {args.output_dir}")


if __name__ == "__main__":
    main()
