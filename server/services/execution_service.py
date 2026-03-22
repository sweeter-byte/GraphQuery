"""Helpers for executing the downstream Survey engine."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..models import NormalizedGraph
from .graph_format_converter import serialize_graph_to_file
from .survey_engine_adapter import get_survey_engine


def execute_downstream_query(
    *,
    dataset_root: str,
    dataset_id: str,
    graph: NormalizedGraph,
    execution_config: dict[str, Any] | None = None,
    custom_order: list[int] | None = None,
) -> dict[str, Any]:
    """Execute the Survey engine for a query graph and optional explicit order."""
    tmp_query_path = serialize_graph_to_file(graph)
    try:
        data_graph_path = str(Path(dataset_root) / dataset_id / f"{dataset_id}.graph")
        cfg = execution_config or {}
        exec_kwargs: dict[str, Any] = {}
        for key in ("filter_type", "order_type", "engine_type"):
            if key in cfg:
                exec_kwargs[key] = cfg[key]
        for key in ("max_embeddings", "time_limit"):
            if key in cfg:
                exec_kwargs[key] = int(cfg[key])
        if custom_order is not None:
            exec_kwargs["custom_order"] = custom_order

        engine = get_survey_engine()
        result = engine.execute(data_graph_path, tmp_query_path, **exec_kwargs)
        result.pop("stdout", None)
        return result
    finally:
        if os.path.exists(tmp_query_path):
            os.remove(tmp_query_path)
