#!/usr/bin/env python3
"""
Test script for the fastest_core pybind11 module.
Validates: load graph, deserialize index, estimate prefix — all in RAM.
"""
import sys
import time

try:
    import fastest_core
except ImportError:
    print("ERROR: fastest_core module not found. Build it first:")
    print("  cd build && cmake .. -Dpybind11_DIR=$(python3 -c 'import pybind11; print(pybind11.get_cmake_dir())') && make -j$(nproc)")
    sys.exit(1)

print("=" * 60)
print("fastest_core pybind11 module test")
print("=" * 60)

# 1. Create estimator instance
estimator = fastest_core.FastestEstimator()
assert not estimator.is_loaded(), "Should not be loaded yet"
print("[PASS] FastestEstimator created successfully")

# 2. Load data graph with prebuilt index
t0 = time.time()
estimator.load_data_graph_and_index(
    dataset_path="dataset/yeast/yeast.graph",
    index_dir="dataset/yeast/index"
)
t1 = time.time()
assert estimator.is_loaded(), "Should be loaded after load_data_graph_and_index"
print(f"[PASS] Index deserialized in {t1-t0:.3f}s  (V={estimator.get_num_vertices()}, E={estimator.get_num_edges()})")

# 3. Test a simple prefix subgraph (triangle: 3 vertices, 3 edges, all label 0)
prefix_triangle = {
    "num_vertices": 3,
    "num_edges": 3,
    "vertices": [
        {"id": 0, "label": 0},
        {"id": 1, "label": 0},
        {"id": 2, "label": 0},
    ],
    "edges": [
        {"source": 0, "target": 1, "label": 0},
        {"source": 1, "target": 2, "label": 0},
        {"source": 0, "target": 2, "label": 0},
    ]
}

t0 = time.time()
result = estimator.estimate_prefix(prefix_triangle)
t1 = time.time()
est = result["estimated_cardinality"]
print(f"[PASS] Triangle estimation: {est:.2f}  (took {t1-t0:.3f}s)")
assert est >= 0, f"Estimated cardinality should be non-negative, got {est}"
print(f"       Timing: CS={result.get('CSBuildTime',0):.2f}ms, "
      f"Tree={result.get('TreeCountTime',0):.2f}+{result.get('TreeSampleTime',0):.2f}ms, "
      f"Graph={result.get('GraphSampleTime',0):.2f}ms")

# 4. Test a path prefix (2 vertices, 1 edge)
prefix_edge = {
    "num_vertices": 2,
    "num_edges": 1,
    "vertices": [
        {"id": 0, "label": 0},
        {"id": 1, "label": 0},
    ],
    "edges": [
        {"source": 0, "target": 1, "label": 0},
    ]
}

result2 = estimator.estimate_prefix(prefix_edge)
est2 = result2["estimated_cardinality"]
print(f"[PASS] Edge estimation: {est2:.2f}")
assert est2 >= 0, f"Estimated cardinality should be non-negative, got {est2}"

# 5. Test a 4-vertex path
prefix_path4 = {
    "num_vertices": 4,
    "num_edges": 3,
    "vertices": [
        {"id": 0, "label": 0},
        {"id": 1, "label": 0},
        {"id": 2, "label": 1},
        {"id": 3, "label": 0},
    ],
    "edges": [
        {"source": 0, "target": 1, "label": 0},
        {"source": 1, "target": 2, "label": 0},
        {"source": 2, "target": 3, "label": 0},
    ]
}

result3 = estimator.estimate_prefix(prefix_path4)
est3 = result3["estimated_cardinality"]
print(f"[PASS] 4-path estimation: {est3:.2f}")

# 6. Simulate a full order evaluation (score calculation)
print("\n--- Simulating order evaluation ---")
# Order: v0(label=0) -> v1(label=0) -> v2(label=1) -> v3(label=0)
# Prefix subgraphs grow from 1 vertex to full query
prefixes = [
    {
        "num_vertices": 1,
        "num_edges": 0,
        "vertices": [{"id": 0, "label": 0}],
        "edges": []
    },
    {
        "num_vertices": 2,
        "num_edges": 1,
        "vertices": [{"id": 0, "label": 0}, {"id": 1, "label": 0}],
        "edges": [{"source": 0, "target": 1, "label": 0}]
    },
    {
        "num_vertices": 3,
        "num_edges": 2,
        "vertices": [
            {"id": 0, "label": 0}, {"id": 1, "label": 0}, {"id": 2, "label": 1}
        ],
        "edges": [
            {"source": 0, "target": 1, "label": 0},
            {"source": 1, "target": 2, "label": 0},
        ]
    },
    prefix_path4,
]

score = 0.0
for k, prefix in enumerate(prefixes):
    r = estimator.estimate_prefix(prefix)
    c_hat = r["estimated_cardinality"]
    omega_k = 1.0  # Weight hardcoded to 1
    score += omega_k * c_hat
    print(f"  k={k+1}: ĉ={c_hat:.2f}, score={score:.2f}")

print(f"\n[PASS] Final score for order: {score:.2f}")

print("\n" + "=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
