"""E10a + E10b + E10c + E10d: O2 weighted cost model experiments.

E10a (--grid-only): Hyperparameter grid search with hit rate metrics.
E10b: M3 execution comparison (uniform vs weighted top-1 order).
E10c: Cross-dataset generalization of best (gamma, lambda).
E10d: Ranking quality analysis with Spearman correlation.

Usage:
    python experiments/run_e10.py --datasets yeast --sizes 4 8 --num-queries 5 --grid-only
    python experiments/run_e10.py --datasets yeast --sizes 4 8 --num-queries 5
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.common.config import base_argparser, DATASET_SIZES, DATASET_ROOT
from experiments.common.graph_loader import discover_queries
from experiments.common.csv_writer import ExperimentCSV
from experiments.common.timing import timer
from experiments.common.stats import spearman_corr
from experiments.common.m2_runner import run_m2
from experiments.common.logger import setup_logger, ErrorCounter

from server.services.estimator_adapter import EstimatorAdapter
from server.services.score_aggregator import WeightConfig, get_weight
from server.services.prefix_builder import build_prefix_subgraphs
from server.services.order_strategies.pruned import generate_orders_pruned

GAMMA_VALUES = [0.5, 1.0, 1.5, 2.0, 3.0]
LAMBDA_VALUES = [0.0, 0.5, 1.0, 2.0, 5.0]


def _rescore(trackers, graph, wcfg):
    """Offline re-score orders with a given WeightConfig. Returns sorted [(score, oid)]."""
    n = graph.num_vertices
    scored = []
    # Cache prefix lists per order to avoid rebuilding
    for oid, tracker in trackers.items():
        pfx_list = build_prefix_subgraphs(graph, tracker.order)
        wscore = 0.0
        for k_idx, c_hat in enumerate(tracker.estimates):
            pfx = pfx_list[k_idx]
            omega = get_weight(
                k_idx + 1, n,
                n_edges=pfx.num_edges, n_vertices=pfx.num_vertices,
                config=wcfg,
            )
            wscore += omega * c_hat
        scored.append((wscore, oid))
    scored.sort()
    return scored


def main():
    p = base_argparser("E10: O2 weighted cost model experiments")
    p.add_argument("--grid-only", action="store_true", help="E10a only: grid search, no M3")
    p.add_argument("--gammas", nargs="+", type=float, default=GAMMA_VALUES)
    p.add_argument("--lambdas", nargs="+", type=float, default=LAMBDA_VALUES)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--best-gamma", type=float, default=None, help="Fixed gamma for E10b/E10c")
    p.add_argument("--best-lam", type=float, default=None, help="Fixed lambda for E10b/E10c")
    p.add_argument("--max-embeddings", type=int, default=100000)
    p.add_argument("--time-limit", type=int, default=60)
    args = p.parse_args()

    log = setup_logger("E10", log_dir=args.output_dir)
    errors = ErrorCounter()
    log.info("E10 started — datasets=%s, grid_only=%s", args.datasets, args.grid_only)

    adapter = EstimatorAdapter()

    # E10a: grid search CSV
    csv_e10a = ExperimentCSV(
        Path(args.output_dir) / "e10a_grid_search.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "gamma", "lam", "best_order_id", "best_score",
            "top1_same_as_uniform", "topk_overlap_with_uniform",
            "n_rank_changes", "spearman_rho", "spearman_p",
        ],
        metadata={"experiment": "E10a", "gammas": str(args.gammas), "lambdas": str(args.lambdas)},
    )

    # E10d: ranking quality CSV
    csv_e10d = ExperimentCSV(
        Path(args.output_dir) / "e10d_ranking_quality.csv",
        columns=[
            "dataset", "size", "density", "query", "n_orders",
            "gamma", "lam",
            "uniform_top1", "weighted_top1", "top1_changed",
            "topk_overlap", "spearman_rho",
        ],
        metadata={"experiment": "E10d"},
    )

    # E10b/E10c CSVs (only without --grid-only, needs M3)
    csv_e10b = None
    engine = None
    if not args.grid_only:
        from server.services.graph_format_converter import serialize_graph_to_file
        from server.services.survey_engine_adapter import SurveyEngineAdapter
        engine = SurveyEngineAdapter()
        if not engine.is_available:
            print("WARNING: Survey binary not available. E10b/E10c will be skipped.")
            engine = None

        if engine:
            csv_e10b = ExperimentCSV(
                Path(args.output_dir) / "e10b_m3_comparison.csv",
                columns=[
                    "dataset", "size", "density", "query",
                    "gamma", "lam",
                    "uniform_order", "weighted_order", "top1_same",
                    "uniform_eps", "weighted_eps", "eps_improvement",
                    "uniform_time_s", "weighted_time_s", "time_improvement",
                ],
                metadata={"experiment": "E10b"},
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
              try:
                graph = q["graph"]
                orders = generate_orders_pruned(graph)
                if not orders:
                    continue

                # Run M2 once with uniform weights
                res_uniform = run_m2(graph, orders, adapter)
                uniform_best_id = res_uniform.aggregator.best_order_id
                uniform_top1 = (
                    res_uniform.aggregator.trackers[uniform_best_id].order
                    if uniform_best_id is not None else []
                )
                uniform_topk = {
                    tuple(t["order"])
                    for t in res_uniform.aggregator.get_top_k()[:args.top_k]
                }
                # Uniform score ranking for Spearman
                uniform_scores = [
                    res_uniform.aggregator.trackers[i].score
                    for i in range(len(orders))
                ]

                # E10a + E10d: offline re-scoring
                for gamma in args.gammas:
                    for lam in args.lambdas:
                        wcfg = WeightConfig(mode="weighted", gamma=gamma, lam=lam)
                        scored = _rescore(res_uniform.aggregator.trackers, graph, wcfg)

                        w_best_id = scored[0][1] if scored else None
                        w_best_score = scored[0][0] if scored else 0.0
                        w_top1 = (
                            res_uniform.aggregator.trackers[w_best_id].order
                            if w_best_id is not None else []
                        )
                        w_topk = {
                            tuple(res_uniform.aggregator.trackers[s[1]].order)
                            for s in scored[:args.top_k]
                        }

                        top1_same = 1 if w_top1 == uniform_top1 else 0
                        k_eff = min(len(uniform_topk), len(w_topk), args.top_k)
                        topk_overlap = len(uniform_topk & w_topk) / k_eff if k_eff > 0 else 0.0

                        # Spearman between uniform and weighted scores
                        w_scores = [s[0] for s in sorted(scored, key=lambda x: x[1])]
                        rho, p_val = spearman_corr(uniform_scores, w_scores)

                        # Count rank changes
                        uniform_rank = {
                            t["order_id"]: t["rank"]
                            for t in res_uniform.aggregator.get_top_k()
                        }
                        w_rank = {scored[i][1]: i + 1 for i in range(len(scored))}
                        n_rank_changes = sum(
                            1 for oid in uniform_rank
                            if uniform_rank.get(oid) != w_rank.get(oid)
                        )

                        csv_e10a.write_row(
                            dataset=ds, size=q["size"], density=q["density"],
                            query=q["name"], n_orders=len(orders),
                            gamma=f"{gamma:.1f}", lam=f"{lam:.1f}",
                            best_order_id=w_best_id, best_score=f"{w_best_score:.4f}",
                            top1_same_as_uniform=top1_same,
                            topk_overlap_with_uniform=f"{topk_overlap:.4f}",
                            n_rank_changes=n_rank_changes,
                            spearman_rho=f"{rho:.4f}", spearman_p=f"{p_val:.4f}",
                        )

                        csv_e10d.write_row(
                            dataset=ds, size=q["size"], density=q["density"],
                            query=q["name"], n_orders=len(orders),
                            gamma=f"{gamma:.1f}", lam=f"{lam:.1f}",
                            uniform_top1=str(uniform_top1),
                            weighted_top1=str(w_top1),
                            top1_changed=1 - top1_same,
                            topk_overlap=f"{topk_overlap:.4f}",
                            spearman_rho=f"{rho:.4f}",
                        )

                # E10b: M3 execution (uniform vs weighted top-1)
                if engine and csv_e10b and args.best_gamma is not None and args.best_lam is not None:
                    from server.services.graph_format_converter import serialize_graph_to_file
                    wcfg = WeightConfig(mode="weighted", gamma=args.best_gamma, lam=args.best_lam)
                    scored = _rescore(res_uniform.aggregator.trackers, graph, wcfg)
                    w_best_id = scored[0][1] if scored else None
                    w_top1 = (
                        res_uniform.aggregator.trackers[w_best_id].order
                        if w_best_id is not None else []
                    )
                    top1_same = 1 if w_top1 == uniform_top1 else 0

                    tmp_query = serialize_graph_to_file(graph)
                    try:
                        r_uni = engine.execute(
                            data_graph_path, tmp_query,
                            max_embeddings=args.max_embeddings, time_limit=args.time_limit,
                        )
                        r_wt = engine.execute(
                            data_graph_path, tmp_query,
                            max_embeddings=args.max_embeddings, time_limit=args.time_limit,
                        )
                        uni_eps = r_uni.get("eps", 0.0)
                        wt_eps = r_wt.get("eps", 0.0)
                        uni_time = r_uni.get("total_time_seconds", 0.0)
                        wt_time = r_wt.get("total_time_seconds", 0.0)
                        eps_impr = (wt_eps - uni_eps) / uni_eps if uni_eps > 0 else 0.0
                        time_impr = (uni_time - wt_time) / uni_time if uni_time > 0 else 0.0
                    except Exception as e:
                        log.warning("M3 failed for %s: %s", q["name"], e)
                        uni_eps, wt_eps, uni_time, wt_time = 0.0, 0.0, 0.0, 0.0
                        eps_impr, time_impr = 0.0, 0.0
                    finally:
                        if os.path.exists(tmp_query):
                            os.remove(tmp_query)

                    csv_e10b.write_row(
                        dataset=ds, size=q["size"], density=q["density"],
                        query=q["name"],
                        gamma=f"{args.best_gamma:.1f}", lam=f"{args.best_lam:.1f}",
                        uniform_order=str(uniform_top1), weighted_order=str(w_top1),
                        top1_same=top1_same,
                        uniform_eps=f"{uni_eps:.2f}", weighted_eps=f"{wt_eps:.2f}",
                        eps_improvement=f"{eps_impr:.4f}",
                        uniform_time_s=f"{uni_time:.4f}", weighted_time_s=f"{wt_time:.4f}",
                        time_improvement=f"{time_impr:.4f}",
                    )
              except Exception as e:
                log.error("query %s failed: %s", q["name"], e, exc_info=True)
                errors.record(dataset=ds, query=q["name"], phase="E10", error=str(e))

            print(f"  [{ds}] done")

    finally:
        csv_e10a.close()
        csv_e10d.close()
        if csv_e10b:
            csv_e10b.close()

    print(f"Results written to {args.output_dir}")
    errors.summary(log)


if __name__ == "__main__":
    main()
