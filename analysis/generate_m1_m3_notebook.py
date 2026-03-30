from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import sys

import nbformat as nbf
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "analysis" / "m1_m3_analysis.ipynb"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import analysis.m1_m3_analysis_lib as lib


def md(text: str):
    return nbf.v4.new_markdown_cell(dedent(text).strip())


def pct(value: float) -> str:
    return f"{value:.1%}"


def main() -> None:
    processed = lib.PROCESSED_DIR
    if not processed.exists():
        raise FileNotFoundError("Run analysis/materialize_m1_m3_outputs.py first.")

    row_counts = pd.read_parquet(processed / "row_counts.parquet")
    status_by_dataset = pd.read_parquet(processed / "status_by_dataset.parquet")
    engine_ok_rates = pd.read_parquet(processed / "engine_ok_rates.parquet")
    unique_sequences = pd.read_parquet(processed / "m1_unique_sequences.parquet")
    pair_summary = pd.read_parquet(processed / "m1_filter_order_pair_summary.parquet")
    diversity = pd.read_parquet(processed / "m1_sequence_diversity.parquet")
    fastest_engine = pd.read_parquet(processed / "fastest_engine.parquet")
    variance_ratio = pd.read_parquet(processed / "sequence_vs_engine_effect.parquet")
    kendall_pairs = pd.read_parquet(processed / "kendall_pairs.parquet")
    recommendations = pd.read_parquet(processed / "recommendations.parquet")
    universal_best = pd.read_parquet(processed / "universal_best.parquet")
    selection_penalty = pd.read_parquet(processed / "selection_penalty.parquet")
    speedup_by_size = pd.read_parquet(processed / "speedup_by_size.parquet")
    speedup_by_density = pd.read_parquet(processed / "speedup_by_density.parquet")
    position_overlap = pd.read_parquet(processed / "position_overlap.parquet")
    position_eta = pd.read_parquet(processed / "position_eta.parquet")

    row_counts_md = lib.markdown_table(row_counts)
    status_pivot = status_by_dataset.pivot(index="dataset", columns="status_group", values="count").fillna(0).reset_index()
    status_md = lib.markdown_table(status_pivot)
    engine_ok_md = lib.markdown_table(
        engine_ok_rates.assign(
            ok_rate=lambda df: df["ok_rate"].map(pct),
            timeout_rate=lambda df: df["timeout_rate"].map(pct),
            crash_rate=lambda df: df["crash_rate"].map(pct),
            failure_rate=lambda df: df["failure_rate"].map(pct),
        ),
        columns=["engine", "OK", "TIMEOUT", "CRASH", "ok_rate", "timeout_rate", "crash_rate", "failure_rate"],
    )
    unique_md = lib.markdown_table(
        unique_sequences.groupby("dataset", observed=True)["unique_sequences"]
        .agg(["median", "mean", "min", "max"])
        .reset_index()
    )
    pair_md = lib.markdown_table(pair_summary, head=15)
    diversity_md = lib.markdown_table(
        diversity.groupby("dataset", observed=True)[["unique_fraction", "duplicated_fraction", "max_method_overlap"]]
        .median()
        .reset_index()
    )
    fastest_md = lib.markdown_table(fastest_engine, head=24)
    variance_md = lib.markdown_table(
        variance_ratio.groupby("dataset", observed=True)[["sequence_variance_mean", "engine_variance_mean", "variance_ratio"]]
        .median()
        .reset_index()
    )
    kendall_md = lib.markdown_table(
        kendall_pairs.groupby(["engine_a", "engine_b"], observed=True)["kendall_tau"]
        .median()
        .reset_index()
        .sort_values("kendall_tau", ascending=False),
        head=15,
    )
    selection_md = lib.markdown_table(
        selection_penalty.groupby("dataset", observed=True)[["median_to_best_ratio", "worst_to_best_ratio", "sequence_count"]]
        .median()
        .reset_index()
    )
    size_md = lib.markdown_table(
        speedup_by_size.groupby("query_vertices", observed=True)[["worst_to_best_ratio", "median_to_best_ratio"]]
        .median()
        .reset_index()
    )
    density_md = lib.markdown_table(
        speedup_by_density.groupby("density_bucket", observed=True)[["worst_to_best_ratio", "median_to_best_ratio"]]
        .median()
        .reset_index()
    )
    overlap_md = lib.markdown_table(position_overlap.groupby("position", observed=True)["same_vertex"].mean().reset_index())
    eta_md = lib.markdown_table(
        position_eta.groupby("position", observed=True)["eta_squared"]
        .median()
        .reset_index()
        .sort_values("eta_squared", ascending=False)
        .head(15)
    )
    recommendations_md = lib.markdown_table(recommendations)

    median_tau = float(kendall_pairs["kendall_tau"].median()) if not kendall_pairs.empty else np.nan
    universal_rate = float(universal_best["universally_good"].mean()) if not universal_best.empty else np.nan
    median_var_ratio = float(variance_ratio["variance_ratio"].median()) if not variance_ratio.empty else np.nan
    median_unique = float(unique_sequences["unique_sequences"].median())
    median_best_vs_median = float(selection_penalty["median_to_best_ratio"].median())
    median_best_vs_worst = float(selection_penalty["worst_to_best_ratio"].median())

    nb = nbf.v4.new_notebook()
    nb["cells"] = [
        md(
            f"""
            # M1/M3 Analysis

            This notebook is a static, shareable rendering of the completed batch analysis for M1 and M3.
            All underlying tables were materialized to `analysis/processed/`, the figures were exported to `analysis/figures/`,
            and the markdown report was written to `analysis/m1_m3_report.md`.

            Key global summary:

            - Median unique candidate sequences per query: `{median_unique:.0f}`
            - Median sequence-vs-engine variance ratio: `{median_var_ratio:.2f}`
            - Median Kendall's tau across engine ranking pairs: `{median_tau:.3f}`
            - Universal-best-sequence rate: `{universal_rate:.1%}`
            - Median best-vs-median penalty: `{median_best_vs_median:.2f}x`
            - Median best-vs-worst speedup ceiling: `{median_best_vs_worst:.2f}x`
            """
        ),
        md("## Part 1: Data Overview and Quality Assessment"),
        md(f"### Row Counts\n\n{row_counts_md}"),
        md(f"### M3 Status Distribution by Dataset\n\n{status_md}"),
        md(f"### Engine Reliability\n\n{engine_ok_md}"),
        md("![](figures/part1_status_heatmap.png)"),
        md("![](figures/part1_enum_distribution.png)"),
        md("## Part 2: M1 Sequence Analysis"),
        md(f"### Unique Candidate Counts per Query\n\n{unique_md}"),
        md(f"### Filter/Order Pairs Producing the Most Unique Sequences\n\n{pair_md}"),
        md(f"### Sequence Diversity\n\n{diversity_md}"),
        md("![](figures/part2_unique_sequences.png)"),
        md("![](figures/part2_filter_order_pairs.png)"),
        md("## Part 3: Engine Performance and Sequence-Engine Interaction"),
        md(f"### Which Engine Is Fastest Most Often\n\n{fastest_md}"),
        md(f"### Sequence Effect vs Engine Effect\n\n{variance_md}"),
        md(f"### Cross-Engine Ranking Consistency\n\n{kendall_md}"),
        md("![](figures/part3_fastest_engine.png)"),
        md("![](figures/part3_variance_ratio.png)"),
        md("![](figures/part3_kendall_matrix.png)"),
        md("## Part 4: Sequence Quality and Selection Difficulty"),
        md(f"### Selection Penalty by Dataset\n\n{selection_md}"),
        md(f"### Difficulty by Query Size\n\n{size_md}"),
        md(f"### Difficulty by Query Density\n\n{density_md}"),
        md(f"### Best/Worst Vertex Agreement by Position\n\n{overlap_md}"),
        md(f"### Vertex-Choice Correlation Strength by Position\n\n{eta_md}"),
        md("![](figures/part4_speedup_trends.png)"),
        md("![](figures/part4_position_analysis.png)"),
        md("## Part 5: Implications for M2 Design"),
        md(recommendations_md),
        md(
            """
            ## Artifact Paths

            - Notebook: `analysis/m1_m3_analysis.ipynb`
            - Report: `analysis/m1_m3_report.md`
            - Processed tables: `analysis/processed/*.parquet`
            - Figures: `analysis/figures/part*.png`
            """
        ),
    ]

    nb["metadata"]["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    nb["metadata"]["language_info"] = {"name": "python", "version": "3.10"}

    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NOTEBOOK_PATH.open("w", encoding="utf-8") as f:
        nbf.write(nb, f)

    print(f"Wrote notebook to {NOTEBOOK_PATH}")


if __name__ == "__main__":
    main()
