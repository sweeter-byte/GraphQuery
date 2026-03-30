from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import analysis.m1_m3_analysis_lib as lib


def main() -> None:
    lib.setup_notebook_style()
    fig_dir = ROOT / "analysis" / "figures"
    processed_dir = ROOT / "analysis" / "processed"

    m3 = pd.read_parquet(processed_dir / "m3_all.parquet")
    m3["status_group"] = pd.Categorical(lib.normalize_status(m3["status"]), categories=["OK", "TIMEOUT", "CRASH"])
    m3_ok = pd.read_parquet(processed_dir / "m3_ok.parquet")
    m3_eps_ok = lib.ok_eps_only(m3)

    eps_frontier = lib.eps_reliability_frontier(m3, m3_eps_ok)
    plt.figure(figsize=(12, 6))
    lib.plot_eps_distribution(m3_eps_ok)
    plt.tight_layout()
    plt.savefig(fig_dir / "eps_part1_distribution.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(10, 6))
    lib.plot_reliability_frontier(eps_frontier)
    plt.tight_layout()
    plt.savefig(fig_dir / "eps_part1_reliability_frontier.png", bbox_inches="tight")
    plt.close()

    eps_fastest = lib.fastest_engine_by_sequence_metric(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)
    eps_gap = lib.metric_gap(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)
    plt.figure(figsize=(13, 6))
    lib.plot_metric_winners(eps_fastest, title="Which Engine Wins Most Often Under EPS?", y_label="Share of sequence wins")
    plt.tight_layout()
    plt.savefig(fig_dir / "eps_part2_winners.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(12, 6))
    lib.plot_metric_gap_distribution(eps_gap, title="Engine Choice Effect Under EPS")
    plt.tight_layout()
    plt.savefig(fig_dir / "eps_part2_gap.png", bbox_inches="tight")
    plt.close()

    eps_rank_corr = lib.metric_rank_correlations(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)
    eps_universal = lib.metric_universal_best_sequences(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)
    plt.figure(figsize=(12, 6))
    ax = lib.plot_rank_correlations(eps_rank_corr)
    ax.set_title("Cross-Engine Rank Correlation Under EPS")
    plt.tight_layout()
    plt.savefig(fig_dir / "eps_part3_rank_correlations.png", bbox_inches="tight")
    plt.close()

    eps_quality = lib.metric_sequence_quality(m3_eps_ok, metric_col="eps_metric", higher_is_better=True)
    agreement = lib.eps_vs_time_winner_agreement(m3_ok, m3_eps_ok)
    agreement_summary = (
        agreement.groupby(["dataset", "engine"], observed=True)["same_sequence"]
        .agg(winner_agreement_rate="mean", query_count="size")
        .reset_index()
    )
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
                "Often similar but not identical" if agreement["same_sequence"].mean() < 0.95 else "Nearly identical",
                ", ".join(
                    eps_fastest.groupby("engine", as_index=False)["win_count"]
                    .sum()
                    .sort_values("win_count", ascending=False)
                    .head(3)["engine"]
                ),
                "Use engine-aware ranking, with enum_time and EPS as parallel supervision views.",
            ],
        }
    )

    lib.save_processed_frames(
        {
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
    )

    print("EPS figures:", len(list(fig_dir.glob("eps_*.png"))))
    print("EPS parquet:", len(list(processed_dir.glob("eps_*.parquet"))))


if __name__ == "__main__":
    main()
