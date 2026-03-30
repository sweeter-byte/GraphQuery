You are a senior data scientist working on the GraphQuery project — a subgraph matching optimization system. Your working directory is the project root. You have full permissions to read files, create files, run bash commands, and execute Python/Jupyter notebooks. You must NOT delete any existing files.

## Step 0: Read and Understand the Codebase

Before doing ANY analysis, thoroughly read the following files to understand the system architecture, data pipeline, and M2 design:

**Architecture & Design Docs:**
- `docs/m1_m2_m3_system_partition.md` — Full system architecture (M1→M2→M3 pipeline)
- `docs/m2_model_design.md` — M2 ML model design: LightGBM + LambdaMART approach
- `docs/m2_model_analysis.md` — M2 model selection rationale
- `m2_optimization_proposal.md` — M2 optimization strategies (R1/R3/R4)
- `m2_prefix_dedup_optimization.md` — Prefix memoization details
- `o2_weighted_cost_model.md` — Weighted cost model: position decay + topology factor

**Core Implementation (understand M2's prefix estimation logic):**
- `server/services/prefix_builder.py` — Builds prefix subgraphs Q_1..Q_n for a given order
- `server/services/score_aggregator.py` — Cost model: score(O) = Σ ω_k × ĉ_k
- `server/services/session_pipeline.py` — Main pipeline with R1/R3/R4 optimizations
- `server/services/estimator_adapter.py` — FaSTest C++ cardinality estimator bridge
- `server/models.py` — Data models (Session, OrderState, PrefixPayload, etc.)

**Experiment Scripts (understand data generation):**
- `tools/run_filter_order_experiment.py` — M1: generates candidate sequences
- `tools/run_m3_engine_experiment.py` — M3: runs real enumeration with 7 engines
- `tools/extract_candidate_features.py` — Feature extraction utilities
- `tools/extract_graph_features.py` — Graph feature extraction

**HPC Scripts:**
- `hpc/merge_by_dataset.sh` — How M1 data was aggregated
- `hpc/merge_m3_by_dataset.sh` — How M3 data was aggregated

## Background: The Three-Stage Pipeline

- **M1 (Sequence Generation)**: Uses SubgraphMatchingSurvey to generate candidate matching sequences via different (filter, order) algorithm combinations. Each sequence is a permutation of query graph vertices defining the backtracking search order.

- **M2 (Cost Estimation & Ranking)**: For each candidate sequence O = (v₁, ..., vₙ), builds n prefix induced subgraphs Q_1..Q_n (where Q_k is the induced subgraph on {v₁,...,v_k}), estimates cardinality ĉ_k for each using FaSTest (a sampling-based cardinality estimator, VLDB 2024), then computes Cost(O) = Σ ω_k × ĉ_k. The sequence with the lowest cost is selected. M2 has NOT been run yet as a batch experiment — we only have the online implementation.

- **M3 (Ground Truth Enumeration)**: Executes each sequence with real engines (EXPLORE, LFTJ, GQL, QSI, VF3, RM, KSS) and records actual embedding_count, enum_time, etc. This is the ground truth for evaluating M2.

## Data Available

Located in `results/`:

- `results/m1_data/<dataset>.csv` — 8 files, one per dataset (dblp, eu2005, hprd, human, patents, wordnet, yeast, youtube)
  - Columns: `dataset, query_file, query_vertices, query_edges, filter, order, sequence, filter_time, plan_time, preprocessing_time, status`
  - ~580K rows per dataset. Each row = one candidate sequence from a (filter, order) combination.

- `results/m3_data/<dataset>.csv` — 8 files, one per dataset
  - Columns: `dataset, query_file, query_vertices, query_edges, filter, order, engine, sequence, embedding_count, total_time, enum_time, filter_time, build_table_time, plan_time, preprocessing_time, memory_mb, call_count, eps, status`
  - Total ~3.3M rows. Status values: OK, TIMEOUT, CRASH:rc=1, CRASH:rc=-6, CRASH:rc=-11
  - 7 engines: EXPLORE, LFTJ, GQL, QSI, VF3, RM, KSS

- Query graph naming convention: `query_<mode>_<size>_<id>.graph` where mode ∈ {dense, sparse}, size ∈ {2,3,4,...,32}

## Your Task

Create a comprehensive analysis in `analysis/m1_m3_analysis.ipynb` that answers the questions below. After completing the notebook, generate a summary report at `analysis/m1_m3_report.md`.

### Part 1: Data Overview & Quality Assessment

1. Load all M1 and M3 CSV files. Report row counts per dataset. Use dtype optimization for large files.
2. For M3 data, compute status distribution (OK / TIMEOUT / CRASH variants) per dataset AND per engine. Visualize as a heatmap.
3. Determine which engines should be excluded due to high failure rates. Compute OK-rate per engine across all datasets.
4. For M3 OK rows, show the distribution of `enum_time` per engine (violin or box plot, log scale).
5. Parse `query_file` to extract `mode` (dense/sparse) and `size`. Add these as columns for later grouping.

### Part 2: M1 Sequence Analysis

1. For each (dataset, query_file), count unique sequences. Show distribution of candidate count per query graph.
2. How many distinct (filter, order) combinations produce sequences? Which (filter, order) pairs generate the most unique sequences?
3. Sequence diversity: what fraction of sequences are truly unique per query graph? (Some different (filter, order) methods may produce identical sequences.)

### Part 3: Engine Performance & Sequence-Engine Interaction

1. Filter M3 to status=OK only. For each (dataset, query_file, sequence), which engine achieves the lowest `enum_time` most frequently?
2. **Sequence effect vs. engine effect**: For a fixed query graph, compute:
   - Variance of `enum_time` across sequences (same engine) — how much does sequence choice matter?
   - Variance of `enum_time` across engines (same sequence) — how much does engine choice matter?
   - Report the ratio. This determines whether M2 (sequence selection) is more important than engine selection.
3. **Cross-engine ranking consistency**: For each (dataset, query_file), rank sequences by `enum_time` per engine. Compute pairwise Kendall's tau between engine rankings. Visualize as a correlation matrix heatmap.
4. Conclusion: Is the optimal sequence engine-dependent or engine-agnostic?

### Part 4: Sequence Quality & Selection Difficulty

1. For each (dataset, query_file, engine), identify the best and worst sequences by `enum_time`. Compute the speedup ratio (worst/best).
2. **Selection penalty**: Compute ratio of median `enum_time` to best `enum_time` per (dataset, query_file, engine). This quantifies "how bad is a random pick?"
3. Group by query graph size (`query_vertices`) and density (`query_edges / (query_vertices * (query_vertices-1) / 2)`). How does the speedup ratio and selection penalty vary? Plot trends.
4. **Positional analysis**: Parse sequence strings into vertex ID lists. For each position k in the sequence, compute:
   - How often the best sequence and worst sequence share the same vertex at position k?
   - Correlation between the vertex choice at position k and overall `enum_time`.
   - This reveals which positions in the sequence are most critical — directly informing which prefix layers M2 should focus on.

### Part 5: Implications for M2 Design

Based on all findings, write a detailed markdown summary addressing:

1. **Engine recommendation**: Which 2-3 engines should M2 evaluation focus on? Why?
2. **Sequence ranking stability**: Is ranking engine-agnostic? Can M2 use a single engine-independent cost model?
3. **Candidate reduction**: How many candidates per query graph does M2 actually need to consider? Can we safely subsample?
4. **Critical positions**: Which prefix layers (positions in the sequence) contribute most to performance differentiation? Should M2 estimate all n prefix cardinalities or only a subset?
5. **Performance ceiling**: What is the maximum possible speedup if M2 always picks the optimal sequence? (best vs. median, best vs. worst)
6. **Recommendations for M2 batch experiment**: Based on this analysis, specify exactly which (datasets, patterns, engines, number of sequences) should be included when running the M2 prefix cardinality estimation experiment on HPC.

### Output Requirements

- All plots should be publication-quality: clear labels, titles, legends, consistent color scheme, appropriate figure sizes.
- Use log scale for `enum_time` plots where appropriate.
- Always analyze per-dataset first, then aggregate. Never mix datasets without explicit grouping.
- Handle large DataFrames efficiently (>2M rows for hprd). Use categorical dtypes, avoid unnecessary copies.
- Save processed intermediate DataFrames to `analysis/processed/` as parquet files.
- After completing the notebook, generate `analysis/m1_m3_report.md` with all key findings, tables, and recommendations in a clean markdown format suitable for sharing with collaborators.

