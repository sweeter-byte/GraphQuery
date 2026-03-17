"""Synchronous M2 evaluation loop for experiment scripts.

Replicates the core logic of session_pipeline.py (R1/R4/R3) without
asyncio or SSE, suitable for batch experiment execution.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.models import NormalizedGraph
from server.services.prefix_builder import build_prefix_subgraphs
from server.services.score_aggregator import (
    ScoreAggregator, WeightConfig, EarlyStopConfig, get_weight,
)
from server.services.estimator_adapter import EstimatorAdapter


@dataclass
class M2Result:
    """Result container for a synchronous M2 evaluation run."""
    aggregator: ScoreAggregator
    elapsed_s: float = 0.0
    n_cpp_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    r3_skips: int = 0
    per_level_times: list[float] = field(default_factory=list)


def run_m2(
    graph: NormalizedGraph,
    orders: list[list[int]],
    adapter: EstimatorAdapter,
    weight_config: WeightConfig | None = None,
    early_stop_config: EarlyStopConfig | None = None,
    prefix_eval_mode: str = "optimized",
    n_threads: int = 1,
) -> M2Result:
    """Synchronous M2 evaluation loop.

    Parameters
    ----------
    graph : NormalizedGraph
    orders : candidate expansion orders from M1
    adapter : loaded EstimatorAdapter (C++ bridge)
    weight_config : cost model weights (None = uniform)
    early_stop_config : R3 config (None = disabled)
    prefix_eval_mode : "optimized" (R1+R4) or "full" (baseline)
    n_threads : unused placeholder (kept for interface compat)
    """
    n = graph.num_vertices
    optimized = prefix_eval_mode == "optimized"

    aggregator = ScoreAggregator(
        top_k=len(orders),
        weight_config=weight_config,
        early_stop_config=early_stop_config,
    )

    # Register all orders
    for i, order in enumerate(orders):
        aggregator.register_order(i, order, n)

    # Pre-build all prefix payloads
    all_prefixes = {i: build_prefix_subgraphs(graph, order) for i, order in enumerate(orders)}

    # R1: skip last level if optimized
    if optimized and n >= 2:
        eval_levels = list(range(n - 1))
    else:
        eval_levels = list(range(n))

    prefix_cache: dict[frozenset[int], float] = {}
    cache_hits = 0
    cache_misses = 0
    r3_skips = 0
    n_cpp_calls = 0
    per_level_times: list[float] = []

    t_start = time.perf_counter()

    for level in eval_levels:
        level_start = time.perf_counter()

        for order_idx in range(len(orders)):
            prefix = all_prefixes[order_idx][level]

            # R3: skip pruned orders
            if optimized and aggregator.should_skip_order(order_idx):
                r3_skips += 1
                continue

            c_hat: float | None = None

            if optimized:
                prefix_key = frozenset(orders[order_idx][: level + 1])
                cached_val = prefix_cache.get(prefix_key)
                if cached_val is not None:
                    cache_hits += 1
                    c_hat = cached_val
                else:
                    cache_misses += 1

            if c_hat is None:
                result = adapter.estimate_prefix(prefix)
                c_hat = result.get("estimated_cardinality", 0.0)
                n_cpp_calls += 1
                if optimized:
                    prefix_cache[frozenset(orders[order_idx][: level + 1])] = c_hat

            aggregator.record_estimate(
                order_idx, level, c_hat,
                n_edges=prefix.num_edges,
                n_vertices=prefix.num_vertices,
            )

        per_level_times.append(time.perf_counter() - level_start)

    # R1: broadcast last level estimate
    if optimized and n >= 2:
        last_level = n - 1
        level_start = time.perf_counter()

        first_prefix = all_prefixes[0][last_level]
        result = adapter.estimate_prefix(first_prefix)
        shared_c_hat = result.get("estimated_cardinality", 0.0)
        n_cpp_calls += 1

        for order_idx in range(len(orders)):
            if order_idx in aggregator.skipped_orders:
                continue
            aggregator.record_estimate(
                order_idx, last_level, shared_c_hat,
                n_edges=graph.num_edges,
                n_vertices=graph.num_vertices,
            )

        per_level_times.append(time.perf_counter() - level_start)

    elapsed = time.perf_counter() - t_start

    return M2Result(
        aggregator=aggregator,
        elapsed_s=elapsed,
        n_cpp_calls=n_cpp_calls,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        r3_skips=r3_skips,
        per_level_times=per_level_times,
    )


def run_m2_full(
    graph: NormalizedGraph,
    orders: list[list[int]],
    adapter: EstimatorAdapter,
    weight_config: WeightConfig | None = None,
) -> M2Result:
    """Convenience: run M2 in full (no R1/R4/R3) mode."""
    return run_m2(
        graph, orders, adapter,
        weight_config=weight_config,
        early_stop_config=None,
        prefix_eval_mode="full",
    )
