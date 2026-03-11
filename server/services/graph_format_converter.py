"""
Graph Format Converter.

Serializes a NormalizedGraph or PrefixPayload into the `.graph` text file
format used by SubgraphMatchingSurvey (and DAF):

    t <num_vertices> <num_edges>
    v <id> <label> <degree>
    ...
    e <src> <tgt> <edge_label>
    ...

Vertices are written in ascending ID order. Degree is computed from the edge
list. Edge labels default to 0 for the vlabel-only variant.
"""
from __future__ import annotations

import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Union

from ..models import NormalizedGraph, PrefixPayload


def serialize_graph_to_file(
    graph: Union[NormalizedGraph, PrefixPayload],
    output_path: str | None = None,
    *,
    tmp_dir: str | None = None,
) -> str:
    """
    Serialize a graph object to the `.graph` text format.

    Parameters
    ----------
    graph : NormalizedGraph or PrefixPayload
        The graph to serialize. Must have ``vertices``, ``edges``,
        ``num_vertices``, and ``num_edges`` attributes.
    output_path : str or None
        If provided, write to this path. Otherwise create a temp file.
    tmp_dir : str or None
        Directory for temp files (only used when output_path is None).

    Returns
    -------
    str
        Absolute path to the written `.graph` file.
    """
    num_v = graph.num_vertices
    num_e = graph.num_edges

    # Build degree map by scanning edges
    degree: dict[int, int] = defaultdict(int)
    for e in graph.edges:
        degree[e.source] += 1
        degree[e.target] += 1

    # Sort vertices by ID
    sorted_vertices = sorted(graph.vertices, key=lambda v: v.id)

    lines: list[str] = []
    # Header
    lines.append(f"t {num_v} {num_e}")
    # Vertices
    for v in sorted_vertices:
        lines.append(f"v {v.id} {v.label} {degree.get(v.id, 0)}")
    # Edges
    for e in graph.edges:
        edge_label = getattr(e, "label", 0)
        lines.append(f"e {e.source} {e.target} {edge_label}")

    content = "\n".join(lines) + "\n"

    if output_path is None:
        fd, output_path = tempfile.mkstemp(
            suffix=".graph", prefix="survey_query_", dir=tmp_dir,
        )
        os.close(fd)

    Path(output_path).write_text(content)
    return output_path
