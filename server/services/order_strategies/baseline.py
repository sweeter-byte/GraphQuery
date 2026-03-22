"""Baseline order generation strategy.

Thin wrapper that delegates directly to the original order_generator
module, preserving its exact behavior as an experimental baseline.
"""
from __future__ import annotations

from ...models import NormalizedGraph
from ..order_generator import generate_orders as _original_generate_orders


def generate_orders_baseline(
    graph: NormalizedGraph,
    beam_width: int | None = None,
    exact_threshold: int = 7,
) -> list[list[int]]:
    """Delegate to the original order_generator unchanged."""
    return _original_generate_orders(
        graph, beam_width=beam_width, exact_threshold=exact_threshold,
    )
