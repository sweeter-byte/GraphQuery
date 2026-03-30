from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "analysis" / "m3_eps_analysis.ipynb"


def md(text: str):
    return nbf.v4.new_markdown_cell(dedent(text).strip())


def code(text: str):
    return nbf.v4.new_code_cell(dedent(text).strip())


nb = nbf.v4.new_notebook()
nb["cells"] = [
    md(
        """
        # M3 EPS Analysis

        This notebook re-analyzes M3 using the paper's preferred throughput-style metric, `EPS` (embeddings per second),
        instead of only `enum_time`.

        The design follows the argument in `3639315.pdf`: rankings based on limited outputs or single time views may be biased,
        while `EPS` offers a more stable picture of algorithm throughput.
        """
    ),
    md(
        """
        ## Setup

        We recompute `eps_metric = embedding_count / total_time` for consistency with the paper's definition and
        compare it with the stored `eps` column before using it in downstream analyses.
        """
    ),
    code(
        """
        from pathlib import Path

        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        import seaborn as sns

        import analysis.m1_m3_analysis_lib as lib

        lib.setup_notebook_style()
        pd.set_option("display.max_columns", 100)
        pd.set_option("display.max_rows", 200)

        ROOT = Path.cwd()
        FIG_DIR = ROOT / "analysis" / "figures"
        PROCESSED_DIR = ROOT / "analysis" / "processed"
        """
    ),
    code(
        """
        m3 = pd.read_parquet(PROCESSED_DIR / "m3_all.parquet")
        m3["status_group"] = pd.Categorical(lib.normalize_status(m3["status"]), categories=["OK", "TIMEOUT", "CRASH"])
        m3_ok = pd.read_parquet(PROCESSED_DIR / "m3_ok.parquet")
        m3_eps_ok = lib.ok_eps_only(m3)

        print("M3 shape:", m3.shape)
        print("M3 OK shape:", m3_ok.shape)
        print("M3 EPS-OK shape:", m3_eps_ok.shape)
        """
    ),
    md(
        """
        ## EPS Sanity Check

        Before relying on EPS, we verify that the stored `eps` field is effectively the same as `embedding_count / total_time`.
        """
    ),
    code(
        """
        eps_check = pd.DataFrame(
            {
                "stored_eps_nonnull_rate": [m3_eps_ok["eps"].notna().mean()],
                "total_time_formula_match_rate": [
                    np.isclose(
                        m3_eps_ok["eps"],
                        m3_eps_ok["embedding_count"] / m3_eps_ok["total_time"],
                        rtol=1e-4,
                        atol=1e-6,
                    ).mean()
                ],
                "enum_time_formula_match_rate": [
                    np.isclose(
                        m3_eps_ok["eps"],
                        m3_eps_ok["embedding_count"] / m3_eps_ok["enum_time"].replace(0, np.nan),
                        rtol=1e-4,
                        atol=1e-6,
                    ).mean()
                ],
            }
        )
        eps_check
        """
    ),
    md(
        """
        ## Part 1: EPS Distribution and Reliability

        We first inspect EPS distributions by engine and combine throughput with failure rate to understand the practical frontier.
        """
    ),
    code(
        """
        eps_frontier = lib.eps_reliability_frontier(m3, m3_eps_ok)
        eps_frontier
        """
    ),
    code(
        """
        plt.figure(figsize=(12, 6))
        ax = lib.plot_eps_distribution(m3_eps_ok)
        plt.tight_layout()
        plt.savefig(FIG_DIR / "eps_part1_distribution.png", bbox_inches="tight")
        plt.show()
        """
    ),
    code(
        """
        plt.figure(figsize=(10, 6))
        ax = lib.plot_reliability_frontier(eps_frontier)
        plt.tight_layout()
        plt.savefig(FIG_DIR / "eps_part1_reliability_frontier.png", bbox_inches="tight")
        plt.show()
        """
    ),
    md(
        """
        ## Part 2: Which Engine Wins Under EPS?

        Here we repeat the per-sequence winner analysis, but use `EPS` as the score to maximize.
        """
    ),
    code(
        """
        eps_fastest = lib.fastest_engine_by_sequence_metric(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)
        eps_gap = lib.metric_gap(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)

        eps_fastest.head()
        """
    ),
    code(
        """
        plt.figure(figsize=(13, 6))
        ax = lib.plot_metric_winners(eps_fastest, title="Which Engine Wins Most Often Under EPS?", y_label="Share of sequence wins")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "eps_part2_winners.png", bbox_inches="tight")
        plt.show()
        """
    ),
    code(
        """
        plt.figure(figsize=(12, 6))
        ax = lib.plot_metric_gap_distribution(eps_gap, title="Engine Choice Effect Under EPS")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "eps_part2_gap.png", bbox_inches="tight")
        plt.show()
        """
    ),
    md(
        """
        ## Part 3: Cross-Engine Ranking Stability Under EPS

        We measure how similarly different engines rank the same sequence candidates under throughput.
        """
    ),
    code(
        """
        eps_rank_corr = lib.metric_rank_correlations(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)
        eps_universal = lib.metric_universal_best_sequences(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)

        eps_rank_corr.head()
        """
    ),
    code(
        """
        plt.figure(figsize=(12, 6))
        ax = lib.plot_rank_correlations(eps_rank_corr)
        ax.set_title("Cross-Engine Rank Correlation Under EPS")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "eps_part3_rank_correlations.png", bbox_inches="tight")
        plt.show()
        """
    ),
    code(
        """
        eps_universal_summary = (
            eps_universal.groupby("dataset", as_index=False)
            .agg(
                queries=("query_file", "nunique"),
                universal_best_rate=("universally_good", "mean"),
                median_distinct_best_sequences=("distinct_best_sequences", "median"),
            )
        )
        eps_universal_summary
        """
    ),
    md(
        """
        ## Part 4: Sequence Quality Under EPS

        Instead of asking how much slower a sequence is, we ask how much throughput is lost by not choosing the best one.
        """
    ),
    code(
        """
        eps_quality = lib.metric_sequence_quality(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)
        eps_quality_summary = (
            eps_quality.groupby("dataset", as_index=False)
            .agg(
                median_eps_penalty=("median_penalty_ratio", "median"),
                p90_eps_penalty=("median_penalty_ratio", lambda s: s.quantile(0.9)),
                median_worst_penalty=("worst_penalty_ratio", "median"),
            )
        )
        eps_quality_summary
        """
    ),
    md(
        """
        ## Part 5: Enum-Time Winners vs EPS Winners

        A key design question for M2 is whether optimizing for shortest runtime and highest throughput leads to the same sequence winner.
        """
    ),
    code(
        """
        agreement = lib.eps_vs_time_winner_agreement(m3_ok, m3_eps_ok)
        agreement_summary = (
            agreement.groupby(["dataset", "engine"], observed=True)["same_sequence"]
            .agg(
                winner_agreement_rate="mean",
                query_count="size",
            )
            .reset_index()
        )
        agreement_summary.sort_values(["dataset", "winner_agreement_rate"], ascending=[True, False])
        """
    ),
    code(
        """
        agreement_overall = (
            agreement.groupby("engine", as_index=False)
            .agg(
                winner_agreement_rate=("same_sequence", "mean"),
                query_count=("same_sequence", "size"),
            )
        )
        agreement_overall
        """
    ),
    md(
        """
        ## Part 6: Recommendations for M2 Labels

        We summarize what EPS changes, and when M2 should be optimized for throughput instead of only total runtime.
        """
    ),
    code(
        """
        eps_recommendations = pd.DataFrame(
            {
                "question": [
                    "Should M2 keep an EPS label?",
                    "Does EPS pick the same winner as enum_time?",
                    "Which engines look strongest under EPS?",
                    "What training target follows from this notebook?",
                ],
                "recommendation": [
                    "Yes. EPS should be retained alongside enum_time for paper-aligned evaluation.",
                    (
                        "Often similar but not identical"
                        if agreement["same_sequence"].mean() < 0.95
                        else "Nearly identical"
                    ),
                    ", ".join(
                        eps_fastest.groupby("engine", as_index=False)["win_count"].sum().sort_values("win_count", ascending=False).head(3)["engine"]
                    ),
                    "Use engine-aware ranking, with enum_time and EPS as parallel supervision views.",
                ],
            }
        )
        eps_recommendations
        """
    ),
    code(
        """
        eps_frames = {
            "eps_frontier": eps_frontier,
            "eps_fastest_engine_summary": eps_fastest,
            "eps_engine_gap": eps_gap,
            "eps_rank_correlations": eps_rank_corr,
            "eps_universal_best_sequences": eps_universal,
            "eps_sequence_quality": eps_quality,
            "eps_winner_agreement": agreement,
            "eps_winner_agreement_summary": agreement_summary,
            "eps_recommendations": eps_recommendations,
        }
        lib.save_processed_frames(eps_frames)
        sorted(p.name for p in PROCESSED_DIR.glob("eps_*.parquet"))
        """
    ),
]

nb["metadata"]["kernelspec"] = {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3",
}
nb["metadata"]["language_info"] = {
    "name": "python",
    "version": "3.10",
}

NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
with NOTEBOOK_PATH.open("w", encoding="utf-8") as f:
    nbf.write(nb, f)

print(f"Wrote notebook to {NOTEBOOK_PATH}")
