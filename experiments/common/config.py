"""CLI argument parsing and path constants for experiment scripts."""
from __future__ import annotations

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = PROJECT_ROOT / "dataset"
RESULTS_DIR = PROJECT_ROOT / "experiments" / "results"

# Only these 3 datasets have local C++ index files; used as default for all experiments.
# human, youtube, patents are too large for local indexing and excluded from experiments.
DATASETS_WITH_INDEX = ["yeast", "wordnet", "dblp"]

ALL_DATASETS = [
    "yeast", "hprd", "human", "wordnet",
    "dblp", "youtube", "eu2005", "patents",
]

# Fine-grained query vertex sizes (9 sizes × 2 densities = 18 groups per dataset)
DEFAULT_QUERY_SIZES = [4, 8, 10, 12, 14, 16, 20, 24, 32]

# Query vertex sizes per dataset
DATASET_SIZES: dict[str, list[int]] = {
    "yeast": DEFAULT_QUERY_SIZES,
    "hprd": DEFAULT_QUERY_SIZES,
    "human": DEFAULT_QUERY_SIZES,
    "wordnet": DEFAULT_QUERY_SIZES,
    "dblp": DEFAULT_QUERY_SIZES,
    "youtube": DEFAULT_QUERY_SIZES,
    "eu2005": DEFAULT_QUERY_SIZES,
    "patents": DEFAULT_QUERY_SIZES,
}


def base_argparser(desc: str, default_datasets: list[str] | None = None) -> argparse.ArgumentParser:
    """Create an ArgumentParser with common experiment CLI flags."""
    if default_datasets is None:
        default_datasets = DATASETS_WITH_INDEX
    p = argparse.ArgumentParser(description=desc)
    p.add_argument(
        "--datasets", nargs="+", default=default_datasets,
        help="Dataset IDs to run (default: %(default)s)",
    )
    p.add_argument(
        "--sizes", nargs="+", type=int, default=None,
        help="Query vertex sizes to include (default: all for each dataset)",
    )
    p.add_argument(
        "--num-queries", type=int, default=50,
        help="Max queries per (dataset, size, density) group (default: 50)",
    )
    p.add_argument(
        "--density", choices=["sparse", "dense"], default=None,
        help="Filter by density (default: both)",
    )
    p.add_argument(
        "--output-dir", type=str, default=str(RESULTS_DIR),
        help="Output directory for CSV results",
    )
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument("--threads", type=int, default=1, help="Python threads for M2")
    p.add_argument("--timeout", type=int, default=120, help="Per-query timeout in seconds (0=disabled)")
    return p
