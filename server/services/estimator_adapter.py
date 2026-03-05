"""
Estimator Adapter: bridges Python backend to the C++ FaSTest pybind11 module.

Manages a singleton FastestEstimator instance that persists for the server
lifecycle to avoid repeated index loading.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from ..models import PrefixPayload

logger = logging.getLogger(__name__)

# Try importing the pybind module; fall back to a mock for testing
_fastest_core = None
try:
    import fastest_core as _fastest_core
except ImportError:
    logger.warning(
        "fastest_core pybind11 module not found. "
        "Estimation will use mock values. Build with: "
        "cd build && cmake .. -Dpybind11_DIR=$(python3 -c 'import pybind11; print(pybind11.get_cmake_dir())') && make"
    )


class EstimatorAdapter:
    """
    Singleton-style adapter for the C++ FaSTest estimation engine.
    Thread-safe: the C++ wrapper uses a mutex internally.
    """

    def __init__(self) -> None:
        self._estimator: Any = None
        self._loaded_dataset: str | None = None
        self._lock = threading.Lock()

    def load_dataset(self, dataset_id: str, dataset_root: str = "dataset") -> None:
        """Load data graph + index for a given dataset (idempotent for same dataset)."""
        with self._lock:
            if self._loaded_dataset == dataset_id and self._estimator is not None:
                return

            dataset_path = str(Path(dataset_root) / dataset_id / f"{dataset_id}.graph")
            index_dir = str(Path(dataset_root) / dataset_id / "index")

            if _fastest_core is None:
                logger.info(f"[Mock] Would load dataset: {dataset_path} with index: {index_dir}")
                self._loaded_dataset = dataset_id
                return

            logger.info(f"Loading dataset: {dataset_path} with index: {index_dir}")
            self._estimator = _fastest_core.FastestEstimator()
            self._estimator.load_data_graph_and_index(dataset_path, index_dir)
            self._loaded_dataset = dataset_id
            logger.info(
                f"Dataset loaded: V={self._estimator.get_num_vertices()}, "
                f"E={self._estimator.get_num_edges()}"
            )

    def estimate_prefix(self, prefix: PrefixPayload) -> dict[str, Any]:
        """
        Estimate cardinality for a single prefix subgraph.
        Returns dict with 'estimated_cardinality' and timing fields.
        """
        payload = prefix.to_dict()

        if _fastest_core is None or self._estimator is None:
            # Mock estimation for testing without the C++ module
            import random
            return {
                "estimated_cardinality": float(random.randint(10, 10000)),
                "CSBuildTime": 0.1,
                "TreeCountTime": 0.05,
                "TreeSampleTime": 0.02,
                "GraphSampleTime": 0.0,
                "QueryTime": 0.17,
            }

        result = self._estimator.estimate_prefix(payload)
        # Convert pybind dict to Python dict
        return dict(result)

    @property
    def is_loaded(self) -> bool:
        if _fastest_core is None:
            return self._loaded_dataset is not None
        return self._estimator is not None and self._estimator.is_loaded()

    @property
    def loaded_dataset(self) -> str | None:
        return self._loaded_dataset


# Global singleton
_adapter_instance: EstimatorAdapter | None = None
_adapter_lock = threading.Lock()


def get_estimator_adapter() -> EstimatorAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        with _adapter_lock:
            if _adapter_instance is None:
                _adapter_instance = EstimatorAdapter()
    return _adapter_instance
