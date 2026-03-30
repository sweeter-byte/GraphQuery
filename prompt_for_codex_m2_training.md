# Task: Build M2 Training Data Pipeline with FaSTest Cardinality Features and Train LambdaMART Model

## Context

You are working in the `GraphQuery` repository — a subgraph matching query optimization platform with a three-stage pipeline:

- **M1**: Generates candidate matching sequences via SubgraphMatchingSurvey filter-order combinations (~15-30 unique sequences per query after deduplication from 81 filter-order pairs).
- **M2**: Selects the best sequence from candidates. Currently uses a hand-coded weighted sum of FaSTest prefix cardinality estimates. Your task is to replace it with a trained ML model whose **core features are the FaSTest prefix cardinality estimates themselves**.
- **M3**: Executes the selected sequence on a real enumeration engine and records performance (enum_time, EPS, etc.).

Large-scale M1/M3 batch experiments have already been completed on HPC. The raw data is pre-processed into parquet files under `analysis/processed/`. Your job is:
1. Deduplicate sequences per (dataset, query) and compute FaSTest cardinality estimates for each prefix of each unique sequence.
2. Conduct a pilot study to determine which prefix levels are most informative for the model.
3. Construct training features combining the informative prefix cardinality estimates with sequence-structural, query-graph, and M1-aggregated features.
4. Train a LightGBM LambdaMART ranking model with proper train/validation/test splits.
5. Evaluate comprehensively.

---

## Available Data

### Parquet files in `analysis/processed/`

#### `m3_ok.parquet` (1,128,422 rows)
Each row = one (query, sequence, engine) execution that completed successfully (status=OK).

| Column | Type | Description |
|--------|------|-------------|
| `dataset` | str | One of: dblp, eu2005, hprd, human, patents, wordnet, yeast, youtube |
| `query_file` | str | e.g. `query_dense_10_1.graph` |
| `query_vertices` | int16 | Number of vertices in the query graph (4-32) |
| `query_edges` | int16 | Number of edges in the query graph |
| `query_density` | float64 | `2*E / (V*(V-1))` |
| `filter` | category | Filter method used in M1 |
| `order` | category | Order method used in M1 |
| `engine` | category | Enumeration engine: EXPLORE, LFTJ, QSI, GQL, KSS, RM |
| `sequence` | str | Space-separated vertex IDs, e.g. `"7 0 5 3 4 2 6 1 8 9"` |
| `embedding_count` | float64 | Number of subgraph matches found |
| `enum_time` | float32 | Enumeration time in seconds (**primary label**) |
| `total_time` | float32 | Total execution time |
| `filter_time` | float32 | Filter phase time |
| `build_table_time` | float32 | Table building time |
| `call_count` | float64 | Backtracking call count |
| `eps` | float32 | Embeddings per second (**secondary label**) |
| `mode` | category | `dense` or `sparse` |
| `size` | Int16 | Query vertex count |
| `query_id` | Int16 | Numeric query ID |

#### `m1_all.parquet` (4,603,300 rows)
Each row = one (query, filter, order) M1 execution producing one sequence.

| Column | Type | Description |
|--------|------|-------------|
| `dataset` | str | Dataset name |
| `query_file` | str | Query filename |
| `query_vertices` | int16 | Vertex count |
| `query_edges` | int16 | Edge count |
| `query_density` | float64 | Density |
| `filter` | category | Filter method |
| `order` | category | Order method |
| `sequence` | str | Space-separated vertex IDs |
| `filter_time` | float32 | M1 filter time |
| `plan_time` | float32 | M1 plan time |

### Local dataset files

Query graph files are at `dataset/<name>/query_graph/<query_file>` in standard format:
```
t [#Vertex] [#Edge]
v [ID] [Label] [Degree]
e [Source] [Target] [EdgeLabel]
```

**Currently available locally**: Only `yeast` has data graph + query graphs on disk.
Other datasets (dblp, hprd, wordnet) need to be downloaded before use. The download link is in `docs/implementation_plan.md`.

**Phase 1 scope**: Use only **dblp, hprd, wordnet, yeast** (4 small datasets). Exclude youtube, patents, eu2005, human — they are too large for local computation.

### FaSTest C++ engine

The repository includes a pybind11 bridge to the FaSTest cardinality estimator:

- **Source**: `core/pybind/FastestPybind.cc`
- **Build output**: `fastest_core.*.so` (pybind11 module, placed at project root)
- **Build command**:
  ```bash
  pip install pybind11
  mkdir -p build && cd build
  cmake .. -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())")
  make -j$(nproc)
  cd ..
  ```
- **Index build** (required once per dataset):
  ```bash
  ./build/Fastest -d <dataset_name> --STRUCTURE 4
  # Reads dataset/<name>/<name>.graph, writes dataset/<name>/index/{graph.bin, triangles.bin, four_cycles.bin}
  ```

**Python API** (see `server/services/estimator_adapter.py` and `server/services/prefix_builder.py` for reference):
```python
import fastest_core

est = fastest_core.FastestEstimator()
est.set_option(num_threads=8, ub_initial=100000, structure_filter="4")
est.load_data_graph_and_index("dataset/yeast/yeast.graph", "dataset/yeast/index")

# Estimate cardinality for a prefix subgraph
result = est.estimate_prefix({
    "num_vertices": 3,
    "num_edges": 2,
    "vertices": [{"id": 0, "label": 16}, {"id": 1, "label": 3}, {"id": 2, "label": 3}],
    "edges": [{"source": 0, "target": 1, "label": 0}, {"source": 0, "target": 2, "label": 0}],
})
c_hat = result["estimated_cardinality"]  # float
```

To build prefix subgraphs from a sequence, see `server/services/prefix_builder.py:build_prefix_subgraphs()`. It takes a `NormalizedGraph` and an order (list of vertex IDs), and returns `PrefixPayload` objects for each prefix depth k=1..n. The prefix at depth k is the induced subgraph on vertices {v_1, ..., v_k} from the original query graph, with vertex IDs renormalized to 0..k-1.

**Important**: To build prefix subgraphs, you need vertex labels and edge structure from the original query graph file. Parse the `.graph` file to get this information.

---

## Design Decisions (Already Finalized)

Follow these strictly (from `docs/m2_model_design.md`, `docs/m2_model_analysis.md`, `docs/m2_design_memo_from_paper_and_data.md`):

1. **M2 is an engine-aware sequence reranker**. The `engine` must be an explicit input. Train a shared model with engine as a feature.

2. **Training target: Learning to Rank (LambdaMART)** via LightGBM's native `lambdarank` objective.

3. **Phase 1 engines**: EXPLORE, LFTJ, QSI (OK rate ~88-89%).

4. **Dual-label evaluation**: Always evaluate under both `enum_time` (lower is better) and `EPS` (higher is better).

5. **Deduplication**: For each (dataset, query_file), deduplicate sequences first, then construct training samples per engine. Never let filter/order identity leak into the model.

6. **Label scheme**: Graded relevance within each (dataset, query_file, engine) group based on `enum_time` rank:
   - Rank 1 → label 5, Rank 2-3 → label 3, Rank 4-10 → label 1, Rank 11+ → label 0

7. **Three-way data split**: train / validation / test:
   - **Primary split**: Query-level, stratified by (dataset, size). All sequences for a given (dataset, query_file) go to the same split. Ratio: 70/15/15.
   - **Supplementary**: Dataset-level leave-one-out for cross-domain generalization analysis.

8. **GPU available**: NVIDIA RTX 4070 Laptop (8GB VRAM, CUDA 12.9). Use GPU acceleration for model training if beneficial (LightGBM supports `device="gpu"`).

---

## Deliverables

Create `m2_training/` at repository root with these scripts, to be run **sequentially**:

```bash
# Step 0: Prerequisites (manual, not scripted)
#   - Build fastest_core.so (see build command above)
#   - Build index for each dataset: ./build/Fastest -d yeast --STRUCTURE 4
#   - Download dblp, hprd, wordnet datasets to dataset/

# Step 1: Compute FaSTest cardinality estimates
python m2_training/compute_cardinalities.py --datasets yeast

# Step 2: Pilot analysis — which prefix levels matter?
python m2_training/analyze_prefix_importance.py

# Step 3: Build training dataset with selected features
python m2_training/build_dataset.py

# Step 4: Train model
python m2_training/train.py

# Step 5: Evaluate
python m2_training/evaluate.py
```

---

### Script 1: `m2_training/compute_cardinalities.py`

**Purpose**: For each unique (dataset, query_file, sequence) in the Phase 1 data, compute the FaSTest cardinality estimate for every prefix depth k=1..n.

**Steps**:
1. Load `analysis/processed/m3_ok.parquet`, filter to Phase 1 engines (EXPLORE, LFTJ, QSI) and Phase 1 datasets (dblp, hprd, wordnet, yeast).
2. Extract unique (dataset, query_file, sequence) tuples. Deduplication is at this level — different engines share the same sequences.
3. For each dataset:
   a. Load the data graph + index via `fastest_core`.
   b. For each (query_file, sequence):
      - Parse the `.graph` file from `dataset/<name>/query_graph/<query_file>` to get vertex labels, edges.
      - Convert the sequence string to a list of vertex IDs.
      - For each prefix depth k=1..n: build the induced subgraph on {seq[0], ..., seq[k-1]}, renormalize vertex IDs to 0..k-1, call `est.estimate_prefix(payload)`, record c_hat_k.
   c. Save per-dataset results incrementally to avoid losing progress on crash.
4. Output: `m2_training/data/cardinalities/<dataset>.parquet` with columns:
   - `dataset`, `query_file`, `sequence`, `prefix_depth` (1..n), `c_hat`, `prefix_vertices`, `prefix_edges`

**Performance considerations**:
- Total unique sequences across 4 datasets: ~494,000. Total prefix estimates: ~8.1M.
- FaSTest single-prefix estimation: ~1-50ms depending on graph size. Estimated total: 1-10 hours.
- Use `--datasets` flag to allow running one dataset at a time.
- Use `--resume` flag to skip already-computed (dataset, query_file, sequence) tuples.
- Print progress every 1000 sequences with ETA.
- Use multiprocessing where possible. The C++ engine releases the GIL (`py::gil_scoped_release`), and the FastestEstimator uses an internal mutex, so thread-based parallelism works. However, the mutex serializes calls. For true parallelism, use `ProcessPoolExecutor` with separate FastestEstimator instances per process, or run one dataset at a time.
- **Recommendation**: Process datasets sequentially. Within each dataset, process queries sequentially (each query's sequences share the same query graph parse). This avoids excessive memory from loading multiple data graphs.

**Query graph parsing function** (implement this yourself, do NOT import from server/):
```python
def parse_query_graph(filepath: str) -> dict:
    """Parse a .graph file into vertices and edges.

    Returns: {
        "num_vertices": int,
        "num_edges": int,
        "vertices": [{"id": int, "label": int}, ...],
        "edges": [{"source": int, "target": int, "label": int}, ...],
    }
    """
    # Format:
    # t [#V] [#E]
    # v [ID] [Label] [Degree]   (degree is informational, not needed for prefix)
    # e [Source] [Target] [Label]
```

**Prefix subgraph building** (implement this yourself, do NOT import from server/):

Given a query graph and a sequence `[v_1, v_2, ..., v_n]`, for prefix depth k:
1. `S_k = {v_1, ..., v_k}` (first k vertices in the sequence)
2. `E_k = {(u, w) in original_edges | u in S_k AND w in S_k}` (induced edges)
3. Renormalize vertex IDs: sort `S_k`, map each original ID to a new 0-based ID
4. Apply the same renormalization to edge endpoints
5. Carry over vertex labels and edge labels from the original query graph

---

### Script 2: `m2_training/analyze_prefix_importance.py`

**Purpose**: Determine which prefix depths are most informative for predicting sequence quality. This is a critical step — not all prefix levels contribute equally to model performance.

**Hypothesis** (to verify):
- The first prefix (single vertex) and the last prefix (full query graph, identical for all sequences of the same query) contribute little discriminative power.
- Mid-range prefixes (roughly depth 3 to n-2) are most informative because they capture the critical branching decisions.

**Steps**:
1. Load cardinality data from `m2_training/data/cardinalities/*.parquet`.
2. Join with M3 ground truth (`m3_ok.parquet`) to get enum_time labels.
3. For each prefix depth k (relative to sequence length n), compute:
   a. **Within-group variance ratio**: For each (dataset, query_file, engine) group, what fraction of the total variance in c_hat_k is explained by the sequence identity vs. random noise?
   b. **Rank correlation with label**: Spearman correlation between c_hat_k and enum_time across sequences within each group.
   c. **Mutual information**: Between binned c_hat_k and the winner/loser binary label.
4. Aggregate across all groups and produce:
   - A table of per-relative-depth importance scores (normalize depth to 0..1 for cross-size comparison).
   - A recommendation of which depths to include as features (e.g., "use depths 2 to n-1" or "use depths at 20%-80% of sequence length").
5. Also compute: for the **last prefix** (full query graph), verify that c_hat is (nearly) constant across sequences of the same (dataset, query_file) — confirming it's non-informative.

**Output**:
- `m2_training/results/prefix_importance.md` — analysis report
- `m2_training/results/prefix_importance.parquet` — raw per-depth statistics

---

### Script 3: `m2_training/build_dataset.py`

**Purpose**: Construct the final training dataset using insights from the pilot study.

**Steps**:
1. Load cardinality estimates from `m2_training/data/cardinalities/*.parquet`.
2. Load M3 labels from `analysis/processed/m3_ok.parquet` (filtered to Phase 1 engines + datasets).
3. Load M1 data from `analysis/processed/m1_all.parquet`.
4. Read prefix importance results from Script 2 to determine which prefix depths to use.
5. For each unique (dataset, query_file):
   a. Deduplicate sequences.
   b. For each sequence, extract features:

**Feature categories**:

**(A) FaSTest cardinality features** (the core — from Script 1):
- Selected raw c_hat values at informative prefix depths (based on Script 2 results).
- Aggregate statistics over the full c_hat sequence: `sum`, `mean`, `std`, `max`, `min`, `log_sum`.
- Trend features: `max_jump` (largest adjacent c_hat increase), `increasing_ratio` (fraction of depths where c_hat increases), `first_half_mean / second_half_mean` ratio.
- The existing baseline scores: `weighted_sum_uniform = sum(c_hat_k)` and `weighted_sum_decay = sum(alpha_k * c_hat_k)` where `alpha_k = ((n-k+1)/n)`.

**(B) Prefix topology features** (from prefix building):
- Per informative depth: `prefix_edges`, `prefix_vertices`, cycle count `E_k - V_k + 1`.
- Aggregate: max cycle count, mean cycle density `(E_k - V_k + 1) / V_k`.

**(C) Sequence-structural features** (from sequence string):
- `seq_length` (= query_vertices)
- `seq_first_vertex`, `seq_last_vertex`
- `seq_monotonicity`: fraction of adjacent pairs where vertex ID increases

**(D) Query-graph features**:
- `query_vertices`, `query_edges`, `query_density`, `query_avg_degree`

**(E) M1-aggregated features** (join from m1_all by (dataset, query_file, sequence)):
- `m1_method_count`: number of distinct (filter, order) pairs that produced this sequence (popularity signal — sequences produced by many methods may represent "consensus" orderings)
- `m1_filter_time_mean`, `m1_plan_time_mean`

**(F) Conditioning features**:
- `engine_id`: integer-encoded engine (EXPLORE=0, LFTJ=1, QSI=2)
- `dataset_id`: integer-encoded dataset

6. Define groups: Each (dataset, query_file, engine) is one ranking group.
7. Assign graded relevance labels based on `enum_time` rank within group.
8. **Three-way split** (train 70% / val 15% / test 15%):
   - Split at the **query level**: all sequences for a given (dataset, query_file) go to the same split.
   - Stratify by (dataset, query_vertices) to ensure balanced representation.
   - Random seed = 42.
9. Save:
   - `m2_training/data/{train,val,test}.parquet`
   - `m2_training/data/group_sizes_{train,val,test}.json`
   - `m2_training/data/feature_names.json`
   - `m2_training/data/meta_columns.json` (list of non-feature columns kept for evaluation: dataset, query_file, engine, sequence, enum_time, eps)

---

### Script 4: `m2_training/train.py`

**Purpose**: Train LightGBM LambdaMART model.

**Steps**:
1. Load train/val data and group sizes from `m2_training/data/`.
2. Configure LightGBM:
   ```python
   params = {
       "objective": "lambdarank",
       "metric": "ndcg",
       "ndcg_eval_at": [1, 3, 5],
       "learning_rate": 0.05,
       "num_leaves": 31,
       "min_data_in_leaf": 5,
       "feature_fraction": 0.8,
       "bagging_fraction": 0.8,
       "bagging_freq": 5,
       "verbose": -1,
       "device": "gpu",          # Use GPU (RTX 4070, CUDA 12.9)
       "gpu_use_dp": False,      # FP32 is fine for ranking
   }
   ```
   If GPU is not available (e.g., CUDA not configured for LightGBM), fall back to CPU gracefully.
3. Train with early stopping (patience=50) on validation NDCG@1.
4. Save model to `m2_training/models/m2_lambdamart.txt`.
5. Print and save feature importance (gain-based) to `m2_training/results/feature_importance.csv`.

---

### Script 5: `m2_training/evaluate.py`

**Purpose**: Comprehensive evaluation on the **test set** (not validation set).

**Steps**:
1. Load the trained model and the **test** split.
2. For each ranking group (dataset, query_file, engine) in the test set:
   - Predict scores and rank sequences.
   - Compare with ground truth ranking by `enum_time` and by `eps`.
3. Compute and report metrics:
   - **Top-1 Accuracy** (enum_time): model's top pick is the actual best?
   - **Top-3 Accuracy** (enum_time): actual best is in model's top 3?
   - **Regret (enum_time)**: `(selected_time - best_time) / best_time`, where `selected_time` is the enum_time of the model's top pick.
   - **Regret (EPS)**: `(best_eps - selected_eps) / best_eps`
   - **NDCG@1, NDCG@3, NDCG@5**
   - **Spearman rank correlation** (model's ranking vs ground truth)
4. Break down ALL metrics by:
   - Engine (EXPLORE / LFTJ / QSI)
   - Dataset (dblp / hprd / wordnet / yeast)
   - Query size bucket (small: 4-8, medium: 10-16, large: 20-32)
5. Compare against baselines:
   - **Random**: randomly pick a sequence (average over 100 trials).
   - **Uniform weighted sum**: current baseline `score = sum(c_hat_k)`, pick the lowest-score sequence.
   - **Position-decay weighted sum**: `score = sum(alpha_k * c_hat_k)`, pick the lowest-score sequence.
6. Output:
   - `m2_training/results/evaluation_report.md` — full markdown report with tables.
   - `m2_training/results/predictions.parquet` — per-group predictions with columns: dataset, query_file, engine, predicted_rank_1_sequence, actual_best_sequence, predicted_enum_time, best_enum_time, regret.

---

### `m2_training/requirements.txt`

```
lightgbm>=4.0
pandas>=2.0
pyarrow>=14.0
numpy>=1.24
scikit-learn>=1.3
scipy>=1.11
```

---

## Important Constraints

1. **Do NOT modify any existing files** in the repository. Only create new files under `m2_training/`.
2. **Do NOT import from `server/`**. The server code depends on pybind11 and a running environment. Instead, reimplement the two small functions you need (query graph parsing, prefix subgraph building) directly in your scripts. You CAN reference `server/services/prefix_builder.py` and `server/services/estimator_adapter.py` for logic, but copy and simplify — do not import.
3. All paths should be relative to the repository root. Scripts should be run from the repository root via `python m2_training/<script>.py`.
4. Use `if __name__ == "__main__":` with `argparse` for all scripts.
5. Add clear progress logging with `print()` including timestamps and ETAs.
6. Handle edge cases:
   - Groups with only 1 sequence: assign label=5 to the single item.
   - NaN/inf values in float columns: replace with 0 or column median.
   - Sequences in M3 but not M1: use left join, fill missing M1 features with defaults (method_count=0, times=0).
   - Missing query graph files: skip and log a warning.
7. **Random seed = 42** everywhere for reproducibility.
8. For `compute_cardinalities.py`:
   - Must support `--datasets` argument (comma-separated, e.g., `--datasets yeast,dblp`).
   - Must support `--resume` flag to skip already-computed entries.
   - Must save intermediate results frequently (every 100 queries) to avoid data loss.
   - Print progress: `[yeast] 1234/7200 queries done (17.1%), ETA: 2h 15m`

---

## Directory Structure After Completion

```
m2_training/
├── compute_cardinalities.py   # Script 1: FaSTest prefix estimates
├── analyze_prefix_importance.py # Script 2: pilot study
├── build_dataset.py           # Script 3: feature engineering + split
├── train.py                   # Script 4: LightGBM training
├── evaluate.py                # Script 5: evaluation
├── requirements.txt
├── data/
│   ├── cardinalities/         # Per-dataset cardinality estimates
│   │   ├── yeast.parquet
│   │   ├── dblp.parquet
│   │   ├── hprd.parquet
│   │   └── wordnet.parquet
│   ├── train.parquet
│   ├── val.parquet
│   ├── test.parquet
│   ├── group_sizes_train.json
│   ├── group_sizes_val.json
│   ├── group_sizes_test.json
│   ├── feature_names.json
│   └── meta_columns.json
├── models/
│   └── m2_lambdamart.txt
└── results/
    ├── prefix_importance.md
    ├── prefix_importance.parquet
    ├── feature_importance.csv
    ├── evaluation_report.md
    └── predictions.parquet
```
