"""CLI argument parsing and path constants for experiment scripts."""
from __future__ import annotations

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = PROJECT_ROOT / "dataset"
RESULTS_DIR = PROJECT_ROOT / "experiments" / "results"

DATASETS_WITH_INDEX = ["yeast", "wordnet", "dblp"]

ALL_DATASETS = ["yeast", "wordnet", "dblp", "human", "youtube", "patents"]

# Query vertex sizes per dataset
DATASET_SIZES: dict[str, list[int]] = {
    "yeast": [4, 8, 16, 24, 32],
    "dblp": [4, 8, 16, 24, 32],
    "youtube": [4, 8, 16, 24, 32],
    "patents": [4, 8, 16, 24, 32],
    "wordnet": [4, 8, 12, 16, 20],
    "human": [4, 8, 12, 16, 20],
}


def base_argparser(desc: str) -> argparse.ArgumentParser:
    """Create an ArgumentParser with common experiment CLI flags."""
    p = argparse.ArgumentParser(description=desc)
    p.add_argument(
        "--datasets", nargs="+", default=DATASETS_WITH_INDEX,
        help="Dataset IDs to run (default: datasets with C++ index)",
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
    return p
