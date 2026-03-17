"""Order generation strategy dispatcher.

Routes to either the baseline (original) or pruned generator
based on the ``strategy`` parameter.

Usage::

    from server.services.order_strategies import generate_orders

    orders = generate_orders(graph, beam_width=50, strategy="pruned")
"""
from __future__ import annotations

import enum
import logging

from ...models import NormalizedGraph
from .baseline import generate_orders_baseline
from .pruned import generate_orders_pruned

logger = logging.getLogger("gq.estimation")


class OrderStrategy(str, enum.Enum):
    BASELINE = "baseline"
    PRUNED = "pruned"


def generate_orders(
    graph: NormalizedGraph,
    beam_width: int | None = None,
    exact_threshold: int = 7,
    strategy: str = "baseline",
) -> list[list[int]]:
    """Dispatch order generation to the selected strategy.

    Parameters
    ----------
    graph : NormalizedGraph
    beam_width : passed through to the underlying generator
    exact_threshold : passed through to the underlying generator
    strategy : ``"baseline"`` or ``"pruned"``
    """
    strat = OrderStrategy(strategy)
    logger.info("ORDER_STRATEGY | strategy=%s | V=%d", strat.value, graph.num_vertices)

    if strat is OrderStrategy.PRUNED:
        return generate_orders_pruned(
            graph, beam_width=beam_width, exact_threshold=exact_threshold,
        )

    return generate_orders_baseline(
        graph, beam_width=beam_width, exact_threshold=exact_threshold,
    )
