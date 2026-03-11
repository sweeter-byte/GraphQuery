"""
Estimator Adapter: bridges Python backend to the C++ FaSTest pybind11 module.

Manages a singleton FastestEstimator instance that persists for the server
lifecycle to avoid repeated index loading.
"""
from __future__ import annotations

import logging
import threading
import time as _time
from pathlib import Path
from typing import Any

from ..models import PrefixPayload

logger = logging.getLogger(__name__)
est_logger = logging.getLogger("gq.estimation")

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
                logger.debug("Dataset '%s' already loaded, skipping.", dataset_id)
                return

            dataset_path = str(Path(dataset_root) / dataset_id / f"{dataset_id}.graph")
            index_dir = str(Path(dataset_root) / dataset_id / "index")

            if _fastest_core is None:
                logger.info("[Mock] Would load dataset: %s with index: %s", dataset_path, index_dir)
                self._loaded_dataset = dataset_id
                return

            logger.info("Loading dataset: %s with index: %s", dataset_path, index_dir)
            t0 = _time.time()
            self._estimator = _fastest_core.FastestEstimator()
            
            # Configure threads to use all available CPU cores
            import os
            num_threads = os.cpu_count() or 4
            self._estimator.set_option(num_threads=num_threads, ub_initial=100000, structure_filter="4")
            
            self._estimator.load_data_graph_and_index(dataset_path, index_dir)
            elapsed = _time.time() - t0
            self._loaded_dataset = dataset_id
            n_v = self._estimator.get_num_vertices()
            n_e = self._estimator.get_num_edges()
            est_logger.info(
                "DATASET_LOADED | id=%s | V=%d | E=%d | load_time=%.3fs | threads=%d",
                dataset_id, n_v, n_e, elapsed, num_threads,
            )

    def estimate_prefix(self, prefix: PrefixPayload) -> dict[str, Any]:
        """
        Estimate cardinality for a single prefix subgraph.
        Returns dict with 'estimated_cardinality' and timing fields.
        """
        payload = prefix.to_dict()
        n_v = payload.get("num_vertices", 0)
        n_e = payload.get("num_edges", 0)

        if _fastest_core is None or self._estimator is None:
            # Mock estimation for testing without the C++ module
            import random
            c_hat = float(random.randint(10, 10000))
            est_logger.debug(
                "ESTIMATE_MOCK | V=%d | E=%d | c_hat=%.2f", n_v, n_e, c_hat
            )
            return {
                "estimated_cardinality": c_hat,
                "CSBuildTime": 0.1,
                "TreeCountTime": 0.05,
                "TreeSampleTime": 0.02,
                "GraphSampleTime": 0.0,
                "QueryTime": 0.17,
            }

        t0 = _time.time()
        result = self._estimator.estimate_prefix(payload)
        elapsed = _time.time() - t0
        result = dict(result)

        c_hat = result.get("estimated_cardinality", 0.0)
        cs_build = result.get("CSBuildTime", 0.0)
        tree_count = result.get("TreeCountTime", 0.0)
        tree_sample = result.get("TreeSampleTime", 0.0)
        graph_sample = result.get("GraphSampleTime", 0.0)
        query_time = result.get("QueryTime", 0.0)

        est_logger.info(
            "ESTIMATE | V=%d | E=%d | c_hat=%.4f | wall=%.3fms | "
            "CSBuild=%.2fms TreeCount=%.2fms TreeSample=%.2fms GraphSample=%.2fms QueryTime=%.2fms",
            n_v, n_e, c_hat, elapsed * 1000,
            cs_build, tree_count, tree_sample, graph_sample, query_time,
        )

        return result

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
