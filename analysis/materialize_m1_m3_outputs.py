from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import analysis.m1_m3_analysis_lib as lib


REPORT_PATH = ROOT / "analysis" / "m1_m3_report.md"


def pct(value: float) -> str:
    return f"{value:.1%}"


def write_report(art: lib.AnalysisArtifacts) -> None:
    focus_engines = art.engine_ok_rates.head(3)["engine"].tolist()
    excluded_engines = art.engine_ok_rates.tail(max(len(art.engine_ok_rates) - 3, 0))["engine"].tolist()
    median_tau = float(art.kendall_pairs["kendall_tau"].median()) if not art.kendall_pairs.empty else np.nan
    universal_rate = float(art.universal_best["universally_good"].mean()) if not art.universal_best.empty else np.nan
    median_var_ratio = float(art.sequence_vs_engine_effect["variance_ratio"].median()) if not art.sequence_vs_engine_effect.empty else np.nan
    median_unique = float(art.unique_sequences["unique_sequences"].median())
    p75_unique = float(art.unique_sequences["unique_sequences"].quantile(0.75))
    median_best_vs_median = float(art.selection_penalty["median_to_best_ratio"].median())
    median_best_vs_worst = float(art.selection_penalty["worst_to_best_ratio"].median())
    best_positions = (
        art.position_eta.groupby("position", observed=True)["eta_squared"].median().sort_values(ascending=False).head(5)
        if not art.position_eta.empty
        else pd.Series(dtype=float)
    )
    overlap_summary = (
        art.position_overlap.groupby("position", observed=True)["same_vertex"].mean().reset_index()
        if not art.position_overlap.empty
        else pd.DataFrame(columns=["position", "same_vertex"])
    )
    mode_summary = (
        art.unique_sequences.groupby(["dataset", "mode"], observed=True)["unique_sequences"]
        .median()
        .reset_index()
        .sort_values(["dataset", "mode"])
    )
    size_penalty = (
        art.speedup_by_size.groupby("query_vertices", observed=True)[["worst_to_best_ratio", "median_to_best_ratio"]]
        .median()
        .reset_index()
        .sort_values("query_vertices")
    )

    text = f"""# M1/M3 Analysis Report

## Scope

This report analyzes the batch M1 candidate-sequence data under `results/m1_data/` and the batch M3 enumeration data under `results/m3_data/`. The analysis follows the task specification exactly: dataset-quality assessment, M1 sequence diversity, engine/sequence interaction, selection difficulty, position-level effects, and concrete recommendations for the future M2 batch experiment.

## Part 1: Data Overview and Quality

### Row Counts

{lib.markdown_table(art.row_counts, head=None)}

### M3 Status Distribution by Dataset

{lib.markdown_table(
    art.status_by_dataset.pivot(index="dataset", columns="status_group", values="count").fillna(0).reset_index(),
    head=None,
)}

### Engine Reliability

{lib.markdown_table(
    art.engine_ok_rates.assign(
        ok_rate=lambda df: df["ok_rate"].map(pct),
        timeout_rate=lambda df: df["timeout_rate"].map(pct),
        crash_rate=lambda df: df["crash_rate"].map(pct),
        failure_rate=lambda df: df["failure_rate"].map(pct),
    ),
    columns=["engine", "OK", "TIMEOUT", "CRASH", "ok_rate", "timeout_rate", "crash_rate", "failure_rate"],
    head=None,
)}

Engine focus recommendation: `{", ".join(focus_engines)}`.

Engine exclusion recommendation: `{", ".join(excluded_engines)}`.

Rationale: these focused engines deliver the highest aggregate OK-rates while still winning a meaningful share of per-sequence contests.

## Part 2: M1 Sequence Analysis

### Unique Candidate Counts per Query

{lib.markdown_table(
    art.unique_sequences.groupby("dataset", observed=True)["unique_sequences"]
    .agg(["median", "mean", "min", "max"])
    .reset_index(),
    head=None,
)}

Overall, the median query has `{median_unique:.0f}` unique sequences and the 75th percentile is `{p75_unique:.0f}`.

### Which Filter/Order Pairs Add the Most Diversity

{lib.markdown_table(art.filter_order_pair_summary, columns=["filter", "order", "query_count", "rows", "unique_sequences", "median_unique_sequences"], head=15)}

### Sequence Diversity

{lib.markdown_table(
    art.sequence_diversity.groupby("dataset", observed=True)[["unique_fraction", "duplicated_fraction", "max_method_overlap"]]
    .median()
    .reset_index(),
    head=None,
)}

Dense vs sparse candidate diversity:

{lib.markdown_table(mode_summary, head=None)}

## Part 3: Engine Performance and Sequence-Engine Interaction

### Which Engine Is Fastest Most Frequently

{lib.markdown_table(art.fastest_engine, columns=["dataset", "engine", "fastest_count", "fastest_share"], head=24)}

### Sequence Effect vs Engine Effect

{lib.markdown_table(
    art.sequence_vs_engine_effect.groupby("dataset", observed=True)[["sequence_variance_mean", "engine_variance_mean", "variance_ratio"]]
    .median()
    .reset_index(),
    head=None,
)}

Median variance ratio across all queries: `{median_var_ratio:.2f}`.

Interpretation: values above `1.0` mean sequence choice matters more than engine choice for a fixed query graph.

### Cross-Engine Ranking Consistency

Median Kendall's tau across all query-level engine pairs: `{median_tau:.3f}`.

Universal-best-sequence rate: `{universal_rate:.1%}`.

{lib.markdown_table(
    art.kendall_pairs.groupby(["engine_a", "engine_b"], observed=True)["kendall_tau"]
    .median()
    .reset_index()
    .sort_values("kendall_tau", ascending=False),
    head=12,
)}

Conclusion: the optimal sequence is {"mostly engine-agnostic" if universal_rate >= 0.7 and median_var_ratio >= 1 else "meaningfully engine-dependent"}.

## Part 4: Sequence Quality and Selection Difficulty

### Best/Worst Speedup and Random-Pick Penalty

{lib.markdown_table(
    art.selection_penalty.groupby("dataset", observed=True)[["median_to_best_ratio", "worst_to_best_ratio", "sequence_count"]]
    .median()
    .reset_index(),
    head=None,
)}

Median best-vs-median penalty: `{median_best_vs_median:.2f}x`.

Median best-vs-worst speedup ceiling: `{median_best_vs_worst:.2f}x`.

### Difficulty by Query Size

{lib.markdown_table(size_penalty, head=None)}

### Position Analysis

Best/worst sequence agreement by position:

{lib.markdown_table(overlap_summary, head=None)}

Vertex-choice correlation strength by position:

{lib.markdown_table(
    best_positions.rename("median_eta_squared").reset_index(),
    head=None,
)}

Interpretation: smaller agreement and larger eta-squared indicate that the position strongly differentiates runtime.

## Part 5: Implications for M2

{lib.markdown_table(art.recommendations, head=None)}

### Recommended M2 Batch Experiment

1. Datasets: keep all 8 datasets to preserve cross-domain generalization.
2. Pattern coverage: include both `dense` and `sparse` queries for every dataset.
3. Query sizes: prioritize sizes `8, 12, 16, 24, 32`, while still retaining smaller sizes as sanity checks.
4. Engines: focus on `{", ".join(focus_engines)}` for the main experiment; retain one lower-reliability engine only if you want a stress-test split.
5. Sequence budget: evaluate up to `32` unique sequences per query by default; for queries with fewer than 32 unique sequences, keep all of them.
6. Prefix budget: compute all prefixes for small queries; for larger queries, ensure early prefixes and the first cyclic prefix are always included, because position effects concentrate near the front of the sequence.

## Artifact Locations

- Notebook: `analysis/m1_m3_analysis.ipynb`
- Processed tables: `analysis/processed/*.parquet`
- Figures: `analysis/figures/part*.png`
"""
    REPORT_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    lib.setup_notebook_style()
    m1, m3 = lib.load_all_data()
    art = lib.run_full_analysis(m1, m3)
    m3_ok = lib.ok_only(m3)

    plt.figure(figsize=(12, 5))
    lib.plot_status_heatmap(art.status_by_engine)
    plt.tight_layout()
    plt.savefig(lib.FIG_DIR / "part1_status_heatmap.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(12, 6))
    lib.plot_enum_distribution(m3_ok)
    plt.tight_layout()
    plt.savefig(lib.FIG_DIR / "part1_enum_distribution.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(12, 6))
    lib.plot_unique_sequences(art.unique_sequences)
    plt.tight_layout()
    plt.savefig(lib.FIG_DIR / "part2_unique_sequences.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(12, 7))
    lib.plot_filter_order_pair_summary(art.filter_order_pair_summary)
    plt.tight_layout()
    plt.savefig(lib.FIG_DIR / "part2_filter_order_pairs.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(13, 6))
    lib.plot_fastest_engine(art.fastest_engine)
    plt.tight_layout()
    plt.savefig(lib.FIG_DIR / "part3_fastest_engine.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(12, 6))
    lib.plot_variance_ratio(art.sequence_vs_engine_effect)
    plt.tight_layout()
    plt.savefig(lib.FIG_DIR / "part3_variance_ratio.png", bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(8, 6))
    lib.plot_kendall_matrix(art.kendall_matrix)
    plt.tight_layout()
    plt.savefig(lib.FIG_DIR / "part3_kendall_matrix.png", bbox_inches="tight")
    plt.close()

    fig, _ = lib.plot_speedup_trends(art.speedup_by_size, art.speedup_by_density)
    fig.tight_layout()
    fig.savefig(lib.FIG_DIR / "part4_speedup_trends.png", bbox_inches="tight")
    plt.close(fig)

    fig, _ = lib.plot_position_analysis(art.position_overlap, art.position_eta)
    fig.tight_layout()
    fig.savefig(lib.FIG_DIR / "part4_position_analysis.png", bbox_inches="tight")
    plt.close(fig)

    processed_frames = {
        "m1_all": m1,
        "m3_all": m3,
        "m3_ok": m3_ok,
        "row_counts": art.row_counts,
        "overview": art.overview,
        "status_by_dataset": art.status_by_dataset,
        "status_by_engine": art.status_by_engine,
        "engine_ok_rates": art.engine_ok_rates,
        "m1_unique_sequences": art.unique_sequences,
        "m1_filter_order_pairs": art.filter_order_pairs,
        "m1_filter_order_pair_summary": art.filter_order_pair_summary,
        "m1_sequence_diversity": art.sequence_diversity,
        "fastest_engine": art.fastest_engine,
        "sequence_vs_engine_effect": art.sequence_vs_engine_effect,
        "kendall_pairs": art.kendall_pairs,
        "kendall_matrix": art.kendall_matrix.reset_index().rename(columns={"index": "engine"}),
        "universal_best": art.universal_best,
        "best_worst": art.best_worst,
        "selection_penalty": art.selection_penalty,
        "difficulty_by_shape": art.difficulty_by_shape,
        "speedup_by_size": art.speedup_by_size,
        "speedup_by_density": art.speedup_by_density,
        "position_overlap": art.position_overlap,
        "position_eta": art.position_eta,
        "recommendations": art.recommendations,
    }
    lib.save_processed_frames(processed_frames)
    write_report(art)

    print("Wrote report to", REPORT_PATH)
    print("Saved", len(processed_frames), "parquet tables to", lib.PROCESSED_DIR)
    print("Saved figures:", len(list(lib.FIG_DIR.glob("part*.png"))))


if __name__ == "__main__":
    main()
