# Task: Build M2 Training Data Pipeline and Train LightGBM LambdaMART Model

## Context

You are working in the `GraphQuery` repository — a subgraph matching query optimization platform with a three-stage pipeline:

- **M1**: Generates candidate matching sequences via SubgraphMatchingSurvey filter-order combinations (~15-30 unique sequences per query after deduplication).
- **M2**: Selects the best sequence from candidates (currently hand-coded weighted sum; your task is to replace it with a trained ML model).
- **M3**: Executes the selected sequence on a real enumeration engine and records performance.

Large-scale batch experiments have already been completed on HPC. The raw data is pre-processed into parquet files under `analysis/processed/`. Your job is to build the M2 training pipeline end-to-end.

---

## Available Data

All data lives in `analysis/processed/`. Key files:

### `m3_ok.parquet` (1,128,422 rows)
Each row = one (query, sequence, engine) execution that completed successfully (status=OK).

| Column | Type | Description |
|--------|------|-------------|
| `dataset` | str | One of: dblp, eu2005, hprd, human, patents, wordnet, yeast, youtube |
| `query_file` | str | e.g. `query_dense_10_1.graph` |
| `query_vertices` | int16 | Number of vertices in the query graph (4-32) |
| `query_edges` | int16 | Number of edges in the query graph |
| `query_density` | float64 | `2*E / (V*(V-1))` |
| `filter` | category | Filter method used in M1 (e.g. GQL, VEQ, CFL, ...) |
| `order` | category | Order method used in M1 (e.g. QSI, GQL, TSO, ...) |
| `engine` | category | Enumeration engine: EXPLORE, LFTJ, QSI, GQL, KSS, RM (VF3 excluded - 100% crash) |
| `sequence` | str | Space-separated vertex IDs, e.g. `"7 0 5 3 4 2 6 1 8 9"` |
| `embedding_count` | float64 | Number of subgraph matches found |
| `enum_time` | float32 | Enumeration time in seconds (**primary label**) |
| `total_time` | float32 | Total execution time |
| `filter_time` | float32 | Filter phase time |
| `build_table_time` | float32 | Table building time |
| `call_count` | float64 | Backtracking call count |
| `eps` | float32 | Embeddings per second (**secondary label**) |
| `mode` | category | `dense` or `sparse` |
| `size` | Int16 | Query vertex count (same as query_vertices) |
| `query_id` | Int16 | Numeric query ID within its size/mode group |

### `m1_all.parquet` (4,603,300 rows)
Each row = one (query, filter, order) M1 execution, producing one sequence.

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

---

## Design Decisions (Already Finalized)

These decisions are documented in `docs/m2_model_design.md`, `docs/m2_model_analysis.md`, and `docs/m2_design_memo_from_paper_and_data.md`. Follow them strictly:

1. **M2 is an engine-aware sequence reranker**, not a universal scorer. The `engine` must be an explicit input condition. Train separate models per engine OR a shared model with engine as a feature.

2. **Training target: Learning to Rank (LambdaMART)**, not regression. Use LightGBM's native `lambdarank` objective. We care about picking the winner, not predicting absolute values.

3. **Phase 1 engines**: Focus on the 3 most stable engines — `EXPLORE`, `LFTJ`, `QSI` (OK rate ~88-89%). Phase 2 can extend to `RM`, `KSS`.

4. **Dual-label evaluation**: Always evaluate under both `enum_time` (lower is better) and `EPS` (higher is better) perspectives.

5. **Deduplication**: M1 produces many duplicate sequences from different filter-order pairs. Always deduplicate by `(dataset, query_file, sequence)` before constructing training samples. Never let filter/order identity leak into the model.

6. **Label scheme for LambdaMART**: Use graded relevance labels within each group:
   - Top-1 sequence (lowest enum_time for that engine) → label = 5
   - Top-3 sequences → label = 3
   - Top-10 sequences → label = 1
   - Others → label = 0

7. **Feature engineering (progressive)**:
   - **V1 (aggregate features, ~15 dims)**: Extract statistics from the raw sequence — but note: **we do NOT have FaSTest cardinality estimates in the batch data**. Instead, derive features purely from M1/M3 available columns and the sequence structure itself.
   - **V2 (hybrid, ~30 dims)**: Add positional features and cross-features.

---

## Your Deliverables

Create a new directory `m2_training/` at the repository root with the following files:

### 1. `m2_training/build_dataset.py`

**Purpose**: Construct training data from parquet files.

**Steps**:
1. Load `analysis/processed/m3_ok.parquet`.
2. Filter to Phase 1 engines: `EXPLORE`, `LFTJ`, `QSI`.
3. Deduplicate: For rows with the same `(dataset, query_file, sequence, engine)`, keep the one with the lowest `enum_time` (in case of duplicates from different filter-order pairs producing the same sequence).
4. Define groups: Each `(dataset, query_file, engine)` tuple is one ranking group.
5. Within each group, assign graded relevance labels based on `enum_time` rank:
   - Rank 1 → label 5
   - Rank 2-3 → label 3
   - Rank 4-10 → label 1
   - Rank 11+ → label 0
6. Extract features (see below).
7. Split data:
   - **Primary split**: Query-level 80/20 stratified by `(dataset, size)`. All sequences for a given `(dataset, query_file)` go to the same split.
   - **Secondary split** (for supplementary evaluation): Dataset-level leave-one-out.
8. Save outputs:
   - `m2_training/data/train.parquet`, `m2_training/data/val.parquet`
   - `m2_training/data/group_sizes_train.json`, `m2_training/data/group_sizes_val.json`
   - `m2_training/data/feature_names.json`

**Feature Engineering**:

Since we do NOT have FaSTest prefix cardinality estimates in the batch data (those exist only in the online system), derive features from what IS available:

**Sequence-structural features** (parse the `sequence` string into a list of vertex IDs):
- `seq_length`: Number of vertices (= query_vertices)
- `seq_first_vertex`: The first vertex ID in the sequence
- `seq_last_vertex`: The last vertex ID in the sequence
- `seq_id_sum`: Sum of vertex IDs
- `seq_id_std`: Std of vertex IDs
- `seq_first_quarter_mean`: Mean of first 25% of vertex IDs
- `seq_monotonicity`: Fraction of adjacent pairs where ID increases

**Query-graph features**:
- `query_vertices`
- `query_edges`
- `query_density`
- `query_avg_degree`: `2 * query_edges / query_vertices`

**M1 aggregated features** (join from `m1_all.parquet` by `(dataset, query_file, sequence)`):
- `m1_filter_time_mean`: Mean filter_time across all filter-order methods that produced this sequence
- `m1_plan_time_mean`: Mean plan_time
- `m1_method_count`: Number of distinct (filter, order) pairs that produced this same sequence (popularity signal)

**Engine feature**:
- `engine_id`: Integer-encoded engine (EXPLORE=0, LFTJ=1, QSI=2)

**Data-graph feature**:
- `dataset_id`: Integer-encoded dataset

### 2. `m2_training/train.py`

**Purpose**: Train LightGBM LambdaMART model and evaluate.

**Steps**:
1. Load train/val parquets and group sizes from `m2_training/data/`.
2. Train a LightGBM ranking model:
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
   }
   ```
3. Use early stopping with patience=50 on validation NDCG@1.
4. Save the trained model to `m2_training/models/m2_lambdamart.txt`.
5. Print feature importance (gain-based).

### 3. `m2_training/evaluate.py`

**Purpose**: Comprehensive evaluation of the trained model.

**Steps**:
1. Load the trained model and validation data.
2. For each group (dataset, query_file, engine) in the validation set:
   - Get model's predicted ranking.
   - Compare with ground truth ranking (by `enum_time` and by `eps`).
3. Compute and report:
   - **Top-1 Accuracy**: Did the model's top pick match the actual best sequence?
   - **Top-3 Accuracy**: Is the actual best sequence in the model's top 3?
   - **Regret (enum_time)**: `(selected_time - best_time) / best_time`
   - **Regret (EPS)**: `(best_eps - selected_eps) / best_eps`
   - **NDCG@1, NDCG@3, NDCG@5**
   - **Spearman rank correlation**
4. Break down all metrics by:
   - Engine (EXPLORE vs LFTJ vs QSI)
   - Dataset
   - Query size bucket (small: 4-8, medium: 10-16, large: 20-32)
5. Compare against baselines:
   - **Random**: Randomly pick a sequence.
   - **First**: Always pick the first sequence (arbitrary).
6. Save a summary report to `m2_training/results/evaluation_report.md`.
7. Save per-group predictions to `m2_training/results/predictions.parquet`.

### 4. `m2_training/requirements.txt`

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
2. **Do NOT import or depend on the server/ code** (it requires pybind11/C++ which is not available in this context). Work purely with the parquet files.
3. All parquet paths should be relative: `analysis/processed/m3_ok.parquet` etc. Scripts should be run from the repository root.
4. Use `if __name__ == "__main__":` with `argparse` for all scripts.
5. Add clear logging with `print()` for progress tracking.
6. Handle edge cases:
   - Groups with only 1 sequence (skip or assign label=5 to the single item).
   - NaN/inf values in float columns.
   - Sequences that appear in M3 but not M1 (or vice versa) — use left join, fill missing M1 features with defaults.
7. Set random seed=42 for reproducibility.
8. The scripts should be runnable sequentially:
   ```bash
   python m2_training/build_dataset.py
   python m2_training/train.py
   python m2_training/evaluate.py
   ```

---

## Expected Outcomes

After running all three scripts:
- A trained LightGBM model at `m2_training/models/m2_lambdamart.txt`
- An evaluation report at `m2_training/results/evaluation_report.md` showing:
  - Overall Top-1 accuracy (target: significantly above random baseline)
  - Per-engine and per-dataset breakdown
  - Comparison with random and first-pick baselines
- Feature importance analysis showing which features matter most
- All intermediate data saved as parquet for reproducibility

## Directory Structure After Completion

```
m2_training/
├── build_dataset.py          # Step 1: data construction
├── train.py                  # Step 2: model training
├── evaluate.py               # Step 3: evaluation
├── requirements.txt          # Dependencies
├── data/                     # Generated training data
│   ├── train.parquet
│   ├── val.parquet
│   ├── group_sizes_train.json
│   ├── group_sizes_val.json
│   └── feature_names.json
├── models/                   # Trained model
│   └── m2_lambdamart.txt
└── results/                  # Evaluation outputs
    ├── evaluation_report.md
    └── predictions.parquet
```
