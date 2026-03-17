"""Load .graph files and discover query graphs for experiments."""
from __future__ import annotations

import random
from pathlib import Path

import sys, os
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.models import NormalizedGraph, Vertex, Edge
from .config import DATASET_ROOT, DATASET_SIZES


def load_query_graph(filepath: str | Path) -> NormalizedGraph:
    """Parse a .graph file into a NormalizedGraph.

    Format:
        t <num_vertices> <num_edges>
        v <id> <label> <degree>
        ...
        e <src> <tgt> <label>
        ...
    """
    filepath = Path(filepath)
    vertices: list[Vertex] = []
    edges: list[Edge] = []
    num_vertices = 0
    num_edges = 0

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if parts[0] == "t":
                num_vertices = int(parts[1])
                num_edges = int(parts[2])
            elif parts[0] == "v":
                vid = int(parts[1])
                label = int(parts[2])
                vertices.append(Vertex(id=vid, label=label))
            elif parts[0] == "e":
                src = int(parts[1])
                tgt = int(parts[2])
                elabel = int(parts[3]) if len(parts) > 3 else 0
                edges.append(Edge(source=src, target=tgt, label=elabel))

    return NormalizedGraph(
        num_vertices=num_vertices,
        num_edges=num_edges,
        vertices=vertices,
        edges=edges,
    )


def discover_queries(
    dataset_id: str,
    sizes: list[int] | None = None,
    density: str | None = None,
    max_per_size: int = 50,
    seed: int = 42,
    dataset_root: str | Path = DATASET_ROOT,
) -> list[dict]:
    """Discover and sample query graph files for a dataset.

    Returns a list of dicts:
        [{dataset, size, density, name, path, graph}, ...]
    """
    qdir = Path(dataset_root) / dataset_id / "query_graph"
    if not qdir.is_dir():
        return []

    available_sizes = sizes or DATASET_SIZES.get(dataset_id, [])
    densities = [density] if density else ["sparse", "dense"]

    results: list[dict] = []
    rng = random.Random(seed)

    for sz in available_sizes:
        for den in densities:
            pattern = f"query_{den}_{sz}_*.graph"
            files = sorted(qdir.glob(pattern))
            if not files:
                continue
            if len(files) > max_per_size:
                files = rng.sample(files, max_per_size)
                files.sort()
            for fp in files:
                results.append({
                    "dataset": dataset_id,
                    "size": sz,
                    "density": den,
                    "name": fp.stem,
                    "path": str(fp),
                    "graph": load_query_graph(fp),
                })

    return results
