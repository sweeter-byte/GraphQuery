from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
import re
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import kendalltau


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
ANALYSIS_DIR = ROOT / "analysis"
FIG_DIR = ANALYSIS_DIR / "figures"
PROCESSED_DIR = ANALYSIS_DIR / "processed"

DATASETS = ["dblp", "eu2005", "hprd", "human", "patents", "wordnet", "yeast", "youtube"]
ENGINES = ["EXPLORE", "LFTJ", "GQL", "QSI", "VF3", "RM", "KSS"]
QUERY_RE = re.compile(r"^query_(dense|sparse)_(\d+)_(\d+)\.graph$")

M1_DTYPES = {
    "dataset": "category",
    "query_file": "string",
    "query_vertices": "int16",
    "query_edges": "int16",
    "filter": "category",
    "order": "category",
    "sequence": "string",
    "filter_time": "float32",
    "plan_time": "float32",
    "preprocessing_time": "float32",
    "status": "category",
}

M3_DTYPES = {
    "dataset": "category",
    "query_file": "string",
    "query_vertices": "int16",
    "query_edges": "int16",
    "filter": "category",
    "order": "category",
    "engine": "category",
    "sequence": "string",
    "embedding_count": "float64",
    "total_time": "float32",
    "enum_time": "float32",
    "filter_time": "float32",
    "build_table_time": "float32",
    "plan_time": "float32",
    "preprocessing_time": "float32",
    "memory_mb": "float32",
    "call_count": "float64",
    "eps": "float32",
    "status": "category",
}

PLOT_COLORS = {
    "EXPLORE": "#0f766e",
    "LFTJ": "#ea580c",
    "GQL": "#2563eb",
    "QSI": "#7c3aed",
    "VF3": "#dc2626",
    "RM": "#ca8a04",
    "KSS": "#4f46e5",
}


@dataclass
class AnalysisArtifacts:
    row_counts: pd.DataFrame
    overview: pd.DataFrame
    status_by_dataset: pd.DataFrame
    status_by_engine: pd.DataFrame
    engine_ok_rates: pd.DataFrame
    unique_sequences: pd.DataFrame
    filter_order_pairs: pd.DataFrame
    filter_order_pair_summary: pd.DataFrame
    sequence_diversity: pd.DataFrame
    fastest_engine: pd.DataFrame
    sequence_vs_engine_effect: pd.DataFrame
    kendall_pairs: pd.DataFrame
    kendall_matrix: pd.DataFrame
    universal_best: pd.DataFrame
    best_worst: pd.DataFrame
    selection_penalty: pd.DataFrame
    difficulty_by_shape: pd.DataFrame
    speedup_by_size: pd.DataFrame
    speedup_by_density: pd.DataFrame
    position_overlap: pd.DataFrame
    position_eta: pd.DataFrame
    recommendations: pd.DataFrame


def setup_notebook_style() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams.update(
        {
            "figure.figsize": (12, 6),
            "axes.titlesize": 16,
            "axes.labelsize": 13,
            "legend.fontsize": 10,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "figure.dpi": 130,
            "savefig.dpi": 180,
        }
    )


def parse_query_file(series: pd.Series) -> pd.DataFrame:
    extracted = series.astype("string").str.extract(QUERY_RE)
    out = pd.DataFrame(index=series.index)
    out["mode"] = pd.Categorical(extracted[0], categories=["dense", "sparse"])
    out["size"] = pd.to_numeric(extracted[1], errors="coerce").astype("Int16")
    out["query_id"] = pd.to_numeric(extracted[2], errors="coerce").astype("Int16")
    return out


def normalize_status(series: pd.Series) -> pd.Series:
    status = series.astype("string")
    return pd.Categorical(
        np.where(status.eq("OK"), "OK", np.where(status.eq("TIMEOUT"), "TIMEOUT", "CRASH")),
        categories=["OK", "TIMEOUT", "CRASH"],
    )


def add_common_columns(df: pd.DataFrame) -> pd.DataFrame:
    extra = parse_query_file(df["query_file"])
    out = df.copy()
    out["mode"] = extra["mode"]
    out["size"] = extra["size"]
    out["query_id"] = extra["query_id"]
    denom = out["query_vertices"] * (out["query_vertices"] - 1) / 2
    out["query_density"] = np.where(denom > 0, out["query_edges"] / denom, np.nan)
    out["query_file"] = out["query_file"].astype("category")
    return out


def read_csv(kind: str, dataset: str) -> pd.DataFrame:
    path = RESULTS_DIR / f"{kind}_data" / f"{dataset}.csv"
    frame = pd.read_csv(path, dtype=M1_DTYPES if kind == "m1" else M3_DTYPES, low_memory=False)
    frame = add_common_columns(frame)
    frame["dataset"] = frame["dataset"].astype("category")
    if kind == "m3":
        frame["status_group"] = normalize_status(frame["status"])
    return frame


def load_all_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    m1 = pd.concat([read_csv("m1", dataset) for dataset in DATASETS], ignore_index=True)
    m3 = pd.concat([read_csv("m3", dataset) for dataset in DATASETS], ignore_index=True)
    return m1, m3


def row_counts(m1: pd.DataFrame, m3: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in DATASETS:
        rows.append(
            {
                "dataset": dataset,
                "m1_rows": int((m1["dataset"] == dataset).sum()),
                "m3_rows": int((m3["dataset"] == dataset).sum()),
                "m1_queries": int(m1.loc[m1["dataset"] == dataset, "query_file"].nunique()),
                "m3_queries": int(m3.loc[m3["dataset"] == dataset, "query_file"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def dataset_overview(m1: pd.DataFrame, m3: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for table_name, frame in [("m1", m1), ("m3", m3)]:
        for dataset, part in frame.groupby("dataset", observed=True):
            for column in part.columns:
                missing = int(part[column].isna().sum())
                rows.append(
                    {
                        "table": table_name,
                        "dataset": str(dataset),
                        "column": column,
                        "dtype": str(part[column].dtype),
                        "rows": int(len(part)),
                        "missing": missing,
                        "missing_rate": float(missing / len(part)),
                    }
                )
    return pd.DataFrame(rows)


def status_distribution(m3: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_dataset = (
        m3.groupby(["dataset", "status_group"], observed=True)
        .size()
        .rename("count")
        .reset_index()
    )
    by_engine = (
        m3.groupby(["dataset", "engine", "status_group"], observed=True)
        .size()
        .rename("count")
        .reset_index()
    )
    totals = by_engine.groupby(["dataset", "engine"], observed=True)["count"].transform("sum")
    by_engine["rate"] = by_engine["count"] / totals
    return by_dataset, by_engine


def engine_ok_rates(m3: pd.DataFrame) -> pd.DataFrame:
    summary = (
        m3.groupby(["engine", "status_group"], observed=True)
        .size()
        .rename("count")
        .reset_index()
        .pivot(index="engine", columns="status_group", values="count")
        .fillna(0)
        .reset_index()
    )
    for col in ["OK", "TIMEOUT", "CRASH"]:
        if col not in summary.columns:
            summary[col] = 0
    summary["total"] = summary["OK"] + summary["TIMEOUT"] + summary["CRASH"]
    summary["ok_rate"] = summary["OK"] / summary["total"]
    summary["timeout_rate"] = summary["TIMEOUT"] / summary["total"]
    summary["crash_rate"] = summary["CRASH"] / summary["total"]
    summary["failure_rate"] = 1 - summary["ok_rate"]
    return summary.sort_values(["ok_rate", "crash_rate"], ascending=[False, True]).reset_index(drop=True)


def ok_only(m3: pd.DataFrame) -> pd.DataFrame:
    ok = m3.loc[m3["status_group"].eq("OK")].copy()
    ok["enum_time"] = pd.to_numeric(ok["enum_time"], errors="coerce")
    ok = ok.loc[ok["enum_time"].notna() & np.isfinite(ok["enum_time"]) & (ok["enum_time"] > 0)].copy()
    return ok


def ok_eps_only(m3: pd.DataFrame) -> pd.DataFrame:
    ok = m3.loc[m3["status_group"].eq("OK")].copy()
    ok["total_time"] = pd.to_numeric(ok["total_time"], errors="coerce")
    ok["embedding_count"] = pd.to_numeric(ok["embedding_count"], errors="coerce")
    ok["eps_metric"] = ok["embedding_count"] / ok["total_time"]
    ok = ok.loc[
        ok["total_time"].notna()
        & ok["embedding_count"].notna()
        & np.isfinite(ok["eps_metric"])
        & (ok["total_time"] > 0)
        & (ok["embedding_count"] > 0)
    ].copy()
    return ok


def aggregated_perf(m3_ok: pd.DataFrame) -> pd.DataFrame:
    return (
        m3_ok.groupby(["dataset", "query_file", "mode", "size", "query_vertices", "query_edges", "query_density", "engine", "sequence"], observed=True)["enum_time"]
        .min()
        .reset_index()
    )


def m1_unique_sequences(m1: pd.DataFrame) -> pd.DataFrame:
    return (
        m1.groupby(["dataset", "query_file", "mode", "size", "query_vertices", "query_edges"], observed=True)
        .agg(candidate_rows=("sequence", "size"), unique_sequences=("sequence", "nunique"))
        .reset_index()
        .assign(unique_fraction=lambda df: df["unique_sequences"] / df["candidate_rows"])
    )


def m1_filter_order_pairs(m1: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pair_level = (
        m1.groupby(["dataset", "query_file", "filter", "order"], observed=True)
        .agg(rows=("sequence", "size"), unique_sequences=("sequence", "nunique"))
        .reset_index()
        .assign(duplicate_fraction=lambda df: 1 - df["unique_sequences"] / df["rows"])
    )
    pair_summary = (
        pair_level.groupby(["filter", "order"], observed=True)
        .agg(
            query_count=("query_file", "nunique"),
            rows=("rows", "sum"),
            unique_sequences=("unique_sequences", "sum"),
            median_unique_sequences=("unique_sequences", "median"),
        )
        .reset_index()
        .sort_values(["unique_sequences", "query_count"], ascending=[False, False])
    )
    return pair_level, pair_summary


def m1_sequence_diversity(m1: pd.DataFrame) -> pd.DataFrame:
    dup = (
        m1.groupby(["dataset", "query_file", "sequence"], observed=True)
        .size()
        .rename("method_count")
        .reset_index()
    )
    totals = (
        m1.groupby(["dataset", "query_file"], observed=True)
        .size()
        .rename("candidate_rows")
        .reset_index()
    )
    out = (
        dup.groupby(["dataset", "query_file"], observed=True)
        .agg(
            unique_sequences=("sequence", "size"),
            duplicated_sequences=("method_count", lambda s: int((s > 1).sum())),
            max_method_overlap=("method_count", "max"),
            mean_method_overlap=("method_count", "mean"),
        )
        .reset_index()
    )
    out = out.merge(totals, on=["dataset", "query_file"], how="left")
    out["unique_fraction"] = out["unique_sequences"] / out["candidate_rows"]
    out["duplicated_fraction"] = out["duplicated_sequences"] / out["unique_sequences"]
    return out


def fastest_engine_by_sequence(m3_ok: pd.DataFrame) -> pd.DataFrame:
    perf = aggregated_perf(m3_ok)
    winners = perf.loc[perf.groupby(["dataset", "query_file", "sequence"], observed=True)["enum_time"].idxmin()]
    summary = (
        winners.groupby(["dataset", "engine"], observed=True)
        .size()
        .rename("fastest_count")
        .reset_index()
    )
    totals = summary.groupby("dataset", observed=True)["fastest_count"].transform("sum")
    summary["fastest_share"] = summary["fastest_count"] / totals
    return summary.sort_values(["dataset", "fastest_share"], ascending=[True, False])


def sequence_vs_engine_effect(m3_ok: pd.DataFrame) -> pd.DataFrame:
    perf = aggregated_perf(m3_ok)
    rows: list[dict[str, object]] = []
    for (dataset, query_file), part in perf.groupby(["dataset", "query_file"], observed=True):
        seq_var = (
            part.groupby("engine", observed=True)["enum_time"]
            .var(ddof=0)
            .dropna()
        )
        eng_var = (
            part.groupby("sequence", observed=True)["enum_time"]
            .var(ddof=0)
            .dropna()
        )
        if seq_var.empty or eng_var.empty:
            continue
        seq_mean = float(seq_var.mean())
        eng_mean = float(eng_var.mean())
        rows.append(
            {
                "dataset": str(dataset),
                "query_file": str(query_file),
                "sequence_variance_mean": seq_mean,
                "engine_variance_mean": eng_mean,
                "variance_ratio": seq_mean / eng_mean if eng_mean > 0 else np.nan,
                "sequence_count": int(part["sequence"].nunique()),
                "engine_count": int(part["engine"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def kendall_rank_correlations(m3_ok: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    perf = aggregated_perf(m3_ok)
    rows: list[dict[str, object]] = []
    for (dataset, query_file), part in perf.groupby(["dataset", "query_file"], observed=True):
        pivot = part.pivot(index="sequence", columns="engine", values="enum_time")
        for engine_a, engine_b in combinations([c for c in pivot.columns if c in ENGINES], 2):
            pair = pivot[[engine_a, engine_b]].dropna()
            if len(pair) < 3:
                continue
            tau, p_value = kendalltau(pair[engine_a], pair[engine_b])
            rows.append(
                {
                    "dataset": str(dataset),
                    "query_file": str(query_file),
                    "engine_a": str(engine_a),
                    "engine_b": str(engine_b),
                    "sequence_overlap": int(len(pair)),
                    "kendall_tau": float(tau) if tau == tau else np.nan,
                    "p_value": float(p_value) if p_value == p_value else np.nan,
                }
            )
    pair_df = pd.DataFrame(rows)
    matrix = pd.DataFrame(np.eye(len(ENGINES)), index=ENGINES, columns=ENGINES)
    if not pair_df.empty:
        medians = pair_df.groupby(["engine_a", "engine_b"], observed=True)["kendall_tau"].median()
        for (engine_a, engine_b), value in medians.items():
            matrix.loc[engine_a, engine_b] = value
            matrix.loc[engine_b, engine_a] = value
    return pair_df, matrix


def universal_best_sequences(m3_ok: pd.DataFrame) -> pd.DataFrame:
    perf = aggregated_perf(m3_ok)
    best = perf.loc[perf.groupby(["dataset", "query_file", "engine"], observed=True)["enum_time"].idxmin()]
    out = (
        best.groupby(["dataset", "query_file"], observed=True)
        .agg(engine_count=("engine", "nunique"), distinct_best_sequences=("sequence", "nunique"))
        .reset_index()
    )
    out["universally_good"] = out["distinct_best_sequences"].eq(1)
    return out


def selection_quality(m3_ok: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    perf = aggregated_perf(m3_ok)
    summary = (
        perf.groupby(["dataset", "query_file", "mode", "size", "query_vertices", "query_edges", "query_density", "engine"], observed=True)["enum_time"]
        .agg(best="min", median="median", worst="max", sequence_count="size")
        .reset_index()
    )
    summary["median_to_best_ratio"] = summary["median"] / summary["best"]
    summary["worst_to_best_ratio"] = summary["worst"] / summary["best"]

    best_idx = perf.groupby(["dataset", "query_file", "engine"], observed=True)["enum_time"].idxmin()
    worst_idx = perf.groupby(["dataset", "query_file", "engine"], observed=True)["enum_time"].idxmax()
    best_worst = pd.concat(
        [perf.loc[best_idx].assign(which="best"), perf.loc[worst_idx].assign(which="worst")],
        ignore_index=True,
    )
    return summary, best_worst


def difficulty_by_query_shape(selection_penalty: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    difficulty = selection_penalty.copy()
    difficulty["density_bucket"] = pd.cut(
        difficulty["query_density"],
        bins=[0, 0.2, 0.35, 0.5, 0.7, 1.0],
        labels=["<=0.20", "0.20-0.35", "0.35-0.50", "0.50-0.70", "0.70-1.00"],
        include_lowest=True,
    )
    speedup_by_size = (
        difficulty.groupby(["dataset", "query_vertices"], observed=True)[["worst_to_best_ratio", "median_to_best_ratio"]]
        .median()
        .reset_index()
    )
    speedup_by_density = (
        difficulty.groupby(["dataset", "density_bucket"], observed=True)[["worst_to_best_ratio", "median_to_best_ratio"]]
        .median()
        .reset_index()
    )
    return difficulty, speedup_by_size, speedup_by_density


def parse_sequence(sequence: str) -> list[int]:
    seq = str(sequence).strip()
    if not seq:
        return []
    return [int(token) for token in seq.replace("-", " ").replace(",", " ").split()]


def correlation_ratio(categories: pd.Series, values: pd.Series) -> tuple[float, float]:
    frame = pd.DataFrame({"cat": categories, "value": values}).dropna()
    if frame.empty or frame["cat"].nunique() < 2 or frame["value"].nunique() < 2:
        return np.nan, np.nan
    grouped = frame.groupby("cat", observed=True)["value"]
    counts = grouped.size().to_numpy(dtype=float)
    means = grouped.mean().to_numpy(dtype=float)
    total_mean = frame["value"].mean()
    numerator = np.sum(counts * (means - total_mean) ** 2)
    denominator = np.sum((frame["value"] - total_mean) ** 2)
    if denominator <= 0:
        return np.nan, np.nan
    eta_sq = numerator / denominator
    return float(np.sqrt(eta_sq)), float(eta_sq)


def eta_squared_from_codes(categories: np.ndarray, values: np.ndarray) -> tuple[float, float]:
    if categories.size == 0 or values.size == 0:
        return np.nan, np.nan
    valid = categories >= 0
    categories = categories[valid]
    values = values[valid]
    if categories.size == 0:
        return np.nan, np.nan
    uniq, inv, counts = np.unique(categories, return_inverse=True, return_counts=True)
    if uniq.size < 2 or np.unique(values).size < 2:
        return np.nan, np.nan
    sums = np.bincount(inv, weights=values)
    means = sums / counts
    total_mean = values.mean()
    numerator = np.sum(counts * (means - total_mean) ** 2)
    denominator = np.sum((values - total_mean) ** 2)
    if denominator <= 0:
        return np.nan, np.nan
    eta_sq = numerator / denominator
    return float(np.sqrt(eta_sq)), float(eta_sq)


def position_analysis(m3_ok: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    perf = aggregated_perf(m3_ok)
    overlap_rows: list[dict[str, object]] = []
    eta_rows: list[dict[str, object]] = []

    for (dataset, query_file, engine), part in perf.groupby(["dataset", "query_file", "engine"], observed=True):
        if part["sequence"].nunique() < 3:
            continue
        sequences = [parse_sequence(seq) for seq in part["sequence"].tolist()]
        if not sequences:
            continue
        max_len = max(len(seq) for seq in sequences)
        matrix = np.full((len(sequences), max_len), -1, dtype=np.int16)
        for idx, seq in enumerate(sequences):
            if seq:
                matrix[idx, : len(seq)] = seq

        enum_time = part["enum_time"].to_numpy(dtype=float)
        values = np.log10(enum_time)

        best_idx = int(np.argmin(enum_time))
        worst_idx = int(np.argmax(enum_time))
        best_seq = matrix[best_idx]
        worst_seq = matrix[worst_idx]

        for position in range(max_len):
            cats = matrix[:, position]
            best_vertex = best_seq[position]
            worst_vertex = worst_seq[position]
            eta, eta_sq = eta_squared_from_codes(cats, values)
            overlap_rows.append(
                {
                    "dataset": str(dataset),
                    "query_file": str(query_file),
                    "engine": str(engine),
                    "position": position + 1,
                    "same_vertex": bool(best_vertex >= 0 and best_vertex == worst_vertex),
                }
            )
            eta_rows.append(
                {
                    "dataset": str(dataset),
                    "query_file": str(query_file),
                    "engine": str(engine),
                    "position": position + 1,
                    "eta": eta,
                    "eta_squared": eta_sq,
                }
            )

    overlap_df = pd.DataFrame(overlap_rows)
    eta_df = pd.DataFrame(eta_rows)
    if not overlap_df.empty:
        overlap_df["same_vertex"] = overlap_df["same_vertex"].astype(bool)
    return overlap_df, eta_df


def build_recommendations(
    engine_ok: pd.DataFrame,
    universal_best: pd.DataFrame,
    variance_df: pd.DataFrame,
    unique_sequences: pd.DataFrame,
    selection_penalty: pd.DataFrame,
    position_eta: pd.DataFrame,
) -> pd.DataFrame:
    focus_engines = engine_ok.head(3)["engine"].tolist()
    ranking_stability = float(universal_best["universally_good"].mean()) if not universal_best.empty else np.nan
    variance_ratio = float(variance_df["variance_ratio"].median()) if not variance_df.empty else np.nan
    median_candidates = float(unique_sequences["unique_sequences"].median())
    p75_candidates = float(unique_sequences["unique_sequences"].quantile(0.75))
    median_best_vs_worst = float(selection_penalty["worst_to_best_ratio"].median())
    median_best_vs_median = float(selection_penalty["median_to_best_ratio"].median())
    critical_positions = (
        position_eta.groupby("position", observed=True)["eta_squared"].median().sort_values(ascending=False).head(3).index.tolist()
        if not position_eta.empty
        else []
    )

    if pd.isna(ranking_stability):
        ranking_text = "Insufficient overlap to judge cross-engine stability."
    elif ranking_stability >= 0.7 and (pd.isna(variance_ratio) or variance_ratio >= 1.0):
        ranking_text = (
            f"Mostly engine-agnostic: {ranking_stability:.1%} of queries have a universal best sequence, "
            f"and the median sequence-vs-engine variance ratio is {variance_ratio:.2f}."
        )
    else:
        ranking_text = (
            f"Engine-dependent enough to keep a multi-engine check: only {ranking_stability:.1%} of queries have "
            f"a universal best sequence and the median variance ratio is {variance_ratio:.2f}."
        )

    candidate_text = (
        f"Typical queries expose about {median_candidates:.0f} unique sequences (75th percentile {p75_candidates:.0f}). "
        f"An HPC batch can cap evaluation at top-{min(int(round(p75_candidates)), 64)} unique sequences per query "
        "without discarding the typical search space."
    )
    position_text = (
        f"The most informative positions are {', '.join(str(p) for p in critical_positions)}; "
        "estimate every prefix for small queries, but for larger queries prioritize early layers and the first cyclic prefix."
        if critical_positions
        else "Position-effect analysis was inconclusive."
    )
    hpc_text = (
        f"Recommended engine set: {', '.join(focus_engines)}. Include all 8 datasets, both dense and sparse patterns, "
        "and emphasize sizes 8, 12, 16, 24, and 32. Per query, evaluate up to 32 unique sequences when available, "
        "or all unique sequences if fewer."
    )

    rows = [
        ("Engine recommendation", f"Focus on {', '.join(focus_engines)} because they combine the highest OK-rates with competitive speed."),
        ("Sequence ranking stability", ranking_text),
        ("Candidate reduction", candidate_text),
        ("Critical positions", position_text),
        ("Performance ceiling", f"Median best-vs-median penalty is {median_best_vs_median:.2f}x and median best-vs-worst speedup is {median_best_vs_worst:.2f}x."),
        ("M2 batch experiment", hpc_text),
    ]
    return pd.DataFrame(rows, columns=["question", "recommendation"])


def run_full_analysis(m1: pd.DataFrame, m3: pd.DataFrame) -> AnalysisArtifacts:
    m3_ok = ok_only(m3)
    rows = row_counts(m1, m3)
    overview = dataset_overview(m1, m3)
    status_by_dataset, status_by_engine = status_distribution(m3)
    engine_ok = engine_ok_rates(m3)
    unique_sequences = m1_unique_sequences(m1)
    filter_order_pairs, filter_order_pair_summary = m1_filter_order_pairs(m1)
    sequence_diversity = m1_sequence_diversity(m1)
    fastest_engine = fastest_engine_by_sequence(m3_ok)
    variance_df = sequence_vs_engine_effect(m3_ok)
    kendall_pairs, kendall_matrix = kendall_rank_correlations(m3_ok)
    universal_best = universal_best_sequences(m3_ok)
    selection_penalty, best_worst = selection_quality(m3_ok)
    difficulty, speedup_by_size, speedup_by_density = difficulty_by_query_shape(selection_penalty)
    position_overlap, position_eta = position_analysis(m3_ok)
    recommendations = build_recommendations(
        engine_ok=engine_ok,
        universal_best=universal_best,
        variance_df=variance_df,
        unique_sequences=unique_sequences,
        selection_penalty=selection_penalty,
        position_eta=position_eta,
    )
    return AnalysisArtifacts(
        row_counts=rows,
        overview=overview,
        status_by_dataset=status_by_dataset,
        status_by_engine=status_by_engine,
        engine_ok_rates=engine_ok,
        unique_sequences=unique_sequences,
        filter_order_pairs=filter_order_pairs,
        filter_order_pair_summary=filter_order_pair_summary,
        sequence_diversity=sequence_diversity,
        fastest_engine=fastest_engine,
        sequence_vs_engine_effect=variance_df,
        kendall_pairs=kendall_pairs,
        kendall_matrix=kendall_matrix,
        universal_best=universal_best,
        best_worst=best_worst,
        selection_penalty=selection_penalty,
        difficulty_by_shape=difficulty,
        speedup_by_size=speedup_by_size,
        speedup_by_density=speedup_by_density,
        position_overlap=position_overlap,
        position_eta=position_eta,
        recommendations=recommendations,
    )


def save_processed_frames(frames: dict[str, pd.DataFrame]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_parquet(PROCESSED_DIR / f"{name}.parquet", index=False)


def plot_status_heatmap(status_by_engine: pd.DataFrame) -> plt.Axes:
    non_ok = status_by_engine.loc[status_by_engine["status_group"].isin(["TIMEOUT", "CRASH"])].copy()
    heat = (
        non_ok.groupby(["engine", "dataset"], observed=True)["rate"]
        .sum()
        .reset_index()
        .pivot(index="engine", columns="dataset", values="rate")
        .reindex(index=ENGINES)
    )
    ax = sns.heatmap(heat, annot=True, fmt=".0%", cmap="magma_r", cbar_kws={"label": "Non-OK rate"})
    ax.set_title("M3 Failure Rate by Dataset and Engine")
    ax.set_xlabel("Dataset")
    ax.set_ylabel("Engine")
    return ax


def plot_enum_distribution(m3_ok: pd.DataFrame) -> plt.Axes:
    sample = m3_ok.copy()
    sample["log_enum_time"] = np.log10(sample["enum_time"])
    ax = sns.violinplot(data=sample, x="engine", y="log_enum_time", order=ENGINES, palette=PLOT_COLORS, cut=0)
    ax.set_title("M3 OK Enum-Time Distribution")
    ax.set_xlabel("Engine")
    ax.set_ylabel("log10(enum_time seconds)")
    return ax


def plot_unique_sequences(unique_sequences: pd.DataFrame) -> plt.Axes:
    ax = sns.boxplot(data=unique_sequences, x="dataset", y="unique_sequences", color="#60a5fa")
    ax.set_title("Unique M1 Sequences per Query")
    ax.set_xlabel("Dataset")
    ax.set_ylabel("Unique sequences")
    ax.tick_params(axis="x", rotation=30)
    return ax


def plot_filter_order_pair_summary(pair_summary: pd.DataFrame, top_n: int = 15) -> plt.Axes:
    top = pair_summary.head(top_n).copy()
    top["pair"] = top["filter"].astype(str) + "+" + top["order"].astype(str)
    ax = sns.barplot(data=top, x="unique_sequences", y="pair", color="#34d399")
    ax.set_title("Filter/Order Pairs Producing the Most Unique Sequences")
    ax.set_xlabel("Total unique sequences across all queries")
    ax.set_ylabel("Filter + Order")
    return ax


def plot_fastest_engine(fastest_engine: pd.DataFrame) -> plt.Axes:
    pivot = fastest_engine.pivot(index="dataset", columns="engine", values="fastest_share").fillna(0)
    ax = pivot.plot(kind="bar", stacked=True, color=[PLOT_COLORS.get(c, "#94a3b8") for c in pivot.columns])
    ax.set_title("Which Engine Wins Most Often for a Fixed Sequence?")
    ax.set_xlabel("Dataset")
    ax.set_ylabel("Share of sequences won")
    ax.legend(title="Engine", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.xticks(rotation=30)
    return ax


def plot_variance_ratio(variance_df: pd.DataFrame) -> plt.Axes:
    ax = sns.boxplot(data=variance_df, x="dataset", y="variance_ratio", color="#f59e0b")
    ax.axhline(1.0, color="#111827", linestyle="--", linewidth=1)
    ax.set_yscale("log")
    ax.set_title("Sequence-Effect vs Engine-Effect Variance Ratio")
    ax.set_xlabel("Dataset")
    ax.set_ylabel("Mean variance across sequences / across engines")
    ax.tick_params(axis="x", rotation=30)
    return ax


def plot_kendall_matrix(kendall_matrix: pd.DataFrame) -> plt.Axes:
    ax = sns.heatmap(kendall_matrix.astype(float), annot=True, fmt=".2f", cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_title("Cross-Engine Kendall Tau of Sequence Rankings")
    ax.set_xlabel("Engine")
    ax.set_ylabel("Engine")
    return ax


def plot_speedup_trends(speedup_by_size: pd.DataFrame, speedup_by_density: pd.DataFrame) -> tuple[plt.Figure, list[plt.Axes]]:
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    size_summary = (
        speedup_by_size.groupby("query_vertices", observed=True)[["worst_to_best_ratio", "median_to_best_ratio"]]
        .median()
        .reset_index()
    )
    sns.lineplot(data=size_summary, x="query_vertices", y="worst_to_best_ratio", marker="o", ax=axes[0], label="Worst / Best")
    sns.lineplot(data=size_summary, x="query_vertices", y="median_to_best_ratio", marker="o", ax=axes[0], label="Median / Best")
    axes[0].set_yscale("log")
    axes[0].set_title("Selection Difficulty by Query Size")
    axes[0].set_xlabel("Query vertices")
    axes[0].set_ylabel("Penalty ratio")

    density_summary = (
        speedup_by_density.groupby("density_bucket", observed=True)[["worst_to_best_ratio", "median_to_best_ratio"]]
        .median()
        .reset_index()
    )
    sns.lineplot(data=density_summary, x="density_bucket", y="worst_to_best_ratio", marker="o", ax=axes[1], label="Worst / Best")
    sns.lineplot(data=density_summary, x="density_bucket", y="median_to_best_ratio", marker="o", ax=axes[1], label="Median / Best")
    axes[1].set_yscale("log")
    axes[1].set_title("Selection Difficulty by Query Density")
    axes[1].set_xlabel("Density bucket")
    axes[1].set_ylabel("Penalty ratio")
    axes[1].tick_params(axis="x", rotation=30)
    return fig, axes.tolist()


def plot_position_analysis(position_overlap: pd.DataFrame, position_eta: pd.DataFrame) -> tuple[plt.Figure, list[plt.Axes]]:
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    overlap_summary = (
        position_overlap.groupby("position", observed=True)["same_vertex"]
        .mean()
        .reset_index()
    )
    eta_summary = (
        position_eta.groupby("position", observed=True)["eta_squared"]
        .median()
        .reset_index()
    )
    sns.lineplot(data=overlap_summary, x="position", y="same_vertex", marker="o", color="#2563eb", ax=axes[0])
    axes[0].set_title("Best/Worst Sequence Vertex Agreement by Position")
    axes[0].set_xlabel("Position")
    axes[0].set_ylabel("Share of groups with same vertex")
    axes[0].set_ylim(0, 1)

    sns.lineplot(data=eta_summary, x="position", y="eta_squared", marker="o", color="#dc2626", ax=axes[1])
    axes[1].set_title("Correlation Ratio Between Vertex Choice and Runtime")
    axes[1].set_xlabel("Position")
    axes[1].set_ylabel("Median eta-squared on log(enum_time)")
    return fig, axes.tolist()


def fastest_engine_by_sequence_metric(
    frame: pd.DataFrame, metric_col: str, higher_is_better: bool
) -> pd.DataFrame:
    agg = "max" if higher_is_better else "min"
    perf = (
        frame.groupby(["dataset", "query_file", "engine", "sequence"], observed=True)[metric_col]
        .agg(agg)
        .reset_index()
    )
    idx = (
        perf.groupby(["dataset", "query_file", "sequence"], observed=True)[metric_col].idxmax()
        if higher_is_better
        else perf.groupby(["dataset", "query_file", "sequence"], observed=True)[metric_col].idxmin()
    )
    winners = perf.loc[idx]
    summary = winners.groupby(["dataset", "engine"], observed=True).size().rename("win_count").reset_index()
    totals = summary.groupby("dataset", observed=True)["win_count"].transform("sum")
    summary["win_share"] = summary["win_count"] / totals
    summary["metric"] = metric_col
    return summary.sort_values(["dataset", "win_share"], ascending=[True, False])


def metric_gap(frame: pd.DataFrame, metric_col: str, higher_is_better: bool) -> pd.DataFrame:
    agg = "max" if higher_is_better else "min"
    perf = (
        frame.groupby(["dataset", "query_file", "engine", "sequence"], observed=True)[metric_col]
        .agg(agg)
        .reset_index()
    )
    effect = (
        perf.groupby(["dataset", "query_file", "sequence"], observed=True)[metric_col]
        .agg(best="max" if higher_is_better else "min", worst="min" if higher_is_better else "max", engine_count="size")
        .reset_index()
    )
    effect["gap_ratio"] = effect["best"] / effect["worst"] if higher_is_better else effect["worst"] / effect["best"]
    effect["metric"] = metric_col
    return effect


def metric_rank_correlations(frame: pd.DataFrame, metric_col: str, higher_is_better: bool) -> pd.DataFrame:
    agg = "max" if higher_is_better else "min"
    perf = (
        frame.groupby(["dataset", "query_file", "engine", "sequence"], observed=True)[metric_col]
        .agg(agg)
        .reset_index()
    )
    rows: list[dict[str, object]] = []
    for (dataset, query_file), part in perf.groupby(["dataset", "query_file"], observed=True):
        pivot = part.pivot(index="sequence", columns="engine", values=metric_col)
        rank_frame = pivot.rank(axis=0, method="average", ascending=not higher_is_better)
        for engine_a, engine_b in combinations([c for c in rank_frame.columns if c in ENGINES], 2):
            pair = rank_frame[[engine_a, engine_b]].dropna()
            if len(pair) < 3 or pair[engine_a].nunique() < 2 or pair[engine_b].nunique() < 2:
                continue
            rows.append(
                {
                    "dataset": str(dataset),
                    "query_file": str(query_file),
                    "engine_a": str(engine_a),
                    "engine_b": str(engine_b),
                    "sequence_overlap": int(len(pair)),
                    "spearman_rho": float(pair[engine_a].corr(pair[engine_b], method="spearman")),
                    "metric": metric_col,
                }
            )
    return pd.DataFrame(rows)


def metric_universal_best_sequences(frame: pd.DataFrame, metric_col: str, higher_is_better: bool) -> pd.DataFrame:
    agg = "max" if higher_is_better else "min"
    perf = (
        frame.groupby(["dataset", "query_file", "engine", "sequence"], observed=True)[metric_col]
        .agg(agg)
        .reset_index()
    )
    idx = (
        perf.groupby(["dataset", "query_file", "engine"], observed=True)[metric_col].idxmax()
        if higher_is_better
        else perf.groupby(["dataset", "query_file", "engine"], observed=True)[metric_col].idxmin()
    )
    best = perf.loc[idx]
    out = (
        best.groupby(["dataset", "query_file"], observed=True)
        .agg(engine_count=("engine", "nunique"), distinct_best_sequences=("sequence", "nunique"))
        .reset_index()
    )
    out["universally_good"] = out["distinct_best_sequences"].eq(1)
    out["metric"] = metric_col
    return out


def metric_sequence_quality(frame: pd.DataFrame, metric_col: str, higher_is_better: bool) -> pd.DataFrame:
    agg = "max" if higher_is_better else "min"
    perf = (
        frame.groupby(["dataset", "query_file", "engine", "sequence"], observed=True)[metric_col]
        .agg(agg)
        .reset_index()
    )
    summary = (
        perf.groupby(["dataset", "query_file", "engine"], observed=True)[metric_col]
        .agg(best="max" if higher_is_better else "min", median="median", worst="min" if higher_is_better else "max", sequence_count="size")
        .reset_index()
    )
    summary["median_penalty_ratio"] = summary["best"] / summary["median"] if higher_is_better else summary["median"] / summary["best"]
    summary["worst_penalty_ratio"] = summary["best"] / summary["worst"] if higher_is_better else summary["worst"] / summary["best"]
    summary["metric"] = metric_col
    return summary


def eps_vs_time_winner_agreement(m3_ok: pd.DataFrame, m3_eps_ok: pd.DataFrame) -> pd.DataFrame:
    time_perf = (
        m3_ok.groupby(["dataset", "query_file", "engine", "sequence"], observed=True)["enum_time"]
        .min()
        .reset_index()
    )
    time_best = time_perf.loc[time_perf.groupby(["dataset", "query_file", "engine"], observed=True)["enum_time"].idxmin()]
    eps_perf = (
        m3_eps_ok.groupby(["dataset", "query_file", "engine", "sequence"], observed=True)["eps_metric"]
        .max()
        .reset_index()
    )
    eps_best = eps_perf.loc[eps_perf.groupby(["dataset", "query_file", "engine"], observed=True)["eps_metric"].idxmax()]
    merged = time_best.merge(
        eps_best,
        on=["dataset", "query_file", "engine"],
        suffixes=("_time", "_eps"),
        how="inner",
    )
    merged["same_sequence"] = merged["sequence_time"].eq(merged["sequence_eps"])
    return merged


def eps_reliability_frontier(m3: pd.DataFrame, m3_eps_ok: pd.DataFrame) -> pd.DataFrame:
    reliability = engine_ok_rates(m3)[["engine", "failure_rate", "crash_rate", "timeout_rate"]]
    throughput = (
        m3_eps_ok.groupby("engine", observed=True)["eps_metric"]
        .agg(median_eps="median", p90_eps=lambda s: s.quantile(0.9), query_count="size")
        .reset_index()
    )
    return reliability.merge(throughput, on="engine", how="left").sort_values(["failure_rate", "median_eps"], ascending=[True, False])


def plot_rank_correlations(rank_corr: pd.DataFrame) -> plt.Axes:
    ax = sns.boxplot(data=rank_corr, x="dataset", y="spearman_rho", color="#a78bfa")
    ax.set_title("Cross-Engine Rank Correlation")
    ax.set_xlabel("Dataset")
    ax.set_ylabel("Spearman rho")
    ax.tick_params(axis="x", rotation=30)
    return ax


def plot_eps_distribution(m3_eps_ok: pd.DataFrame) -> plt.Axes:
    sample = m3_eps_ok.copy()
    sample["log_eps"] = np.log10(sample["eps_metric"])
    ax = sns.violinplot(data=sample, x="engine", y="log_eps", order=ENGINES, palette=PLOT_COLORS, cut=0)
    ax.set_title("M3 OK EPS Distribution")
    ax.set_xlabel("Engine")
    ax.set_ylabel("log10(EPS)")
    return ax


def plot_metric_winners(summary: pd.DataFrame, title: str, y_label: str) -> plt.Axes:
    pivot = summary.pivot(index="dataset", columns="engine", values="win_share").fillna(0)
    ax = pivot.plot(kind="bar", stacked=True, color=[PLOT_COLORS.get(c, "#94a3b8") for c in pivot.columns])
    ax.set_title(title)
    ax.set_xlabel("Dataset")
    ax.set_ylabel(y_label)
    ax.legend(title="Engine", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.xticks(rotation=30)
    return ax


def plot_metric_gap_distribution(gap: pd.DataFrame, title: str) -> plt.Axes:
    ax = sns.boxplot(data=gap, x="dataset", y="gap_ratio", color="#14b8a6")
    ax.set_yscale("log")
    ax.set_title(title)
    ax.set_xlabel("Dataset")
    ax.set_ylabel("Best / Worst ratio")
    ax.tick_params(axis="x", rotation=30)
    return ax


def plot_reliability_frontier(frontier: pd.DataFrame) -> plt.Axes:
    ax = sns.scatterplot(data=frontier, x="failure_rate", y="median_eps", hue="engine", palette=PLOT_COLORS, s=140)
    for _, row in frontier.iterrows():
        ax.text(row["failure_rate"], row["median_eps"], f" {row['engine']}", va="center")
    ax.set_title("Reliability vs Throughput Frontier")
    ax.set_xlabel("Average failure rate")
    ax.set_ylabel("Median EPS")
    ax.set_yscale("log")
    return ax


def markdown_table(frame: pd.DataFrame, columns: Iterable[str] | None = None, head: int | None = None) -> str:
    table = frame.copy()
    if columns is not None:
        table = table.loc[:, list(columns)]
    if head is not None:
        table = table.head(head)
    table = table.replace({np.nan: ""})
    headers = [str(col) for col in table.columns]
    rows = [[str(value) for value in row] for row in table.itertuples(index=False, name=None)]
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    row_lines = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header_line, sep_line, *row_lines])
