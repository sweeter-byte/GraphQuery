# Index Artifact Specification (Offline Build + Online Load)

## Verified vs TBD
- ✅ Verified in current repository:
  - Dataset root uses `dataset/<dataset_name>/` conventions.
  - Dataset graph file naming convention is `dataset/<dataset_name>/<dataset_name>.graph`.
  - Query graphs live under `dataset/<dataset_name>/query_graph/`.
  - Estimator CLI performs indexing in memory during runtime.
  - CLI supports structure mode via `--STRUCTURE X|3|4`.
  - CLI supports build-parameter flags `--threads`, `--group_size`, `--incident_edges_size`.
- ⚠️ Not implemented in current CLI:
  - On-disk persistence of index artifacts.
  - Standardized index artifact layout and metadata.

This document defines the required contract for implementing persistence and load validation.

## 1. Design Goals
1. Deterministic reproducibility:
   Same dataset content + same build parameters + same source version must produce equivalent artifact metadata.
2. Dataset-index version binding:
   Index artifacts must be cryptographically bound to the exact dataset graph file.
3. Forward compatibility:
   Artifact format must allow introducing new fields/files without breaking older loaders that follow compatibility policy.
4. Stale-index detection:
   Runtime must detect when graph content no longer matches index artifacts.
5. Extensibility:
   New index/cost/cache families must be addable without changing root conventions.

## 2. Root Directory Layout
Canonical layout:
```text
dataset/
  <dataset_name>/
    <dataset_name>.graph
    query_graph/
    index/
      meta.json
      structure/
      statistics/
      optional_future/
```

Directory roles:
- `dataset/<dataset_name>/<dataset_name>.graph`: source-of-truth graph file.
- `dataset/<dataset_name>/query_graph/`: query files for estimator execution.
- `dataset/<dataset_name>/index/meta.json`: authoritative artifact metadata and compatibility gate.
- `dataset/<dataset_name>/index/structure/`: serialized structure-specific index blobs.
- `dataset/<dataset_name>/index/statistics/`: non-kernel summary data for UI/inspection.
- `dataset/<dataset_name>/index/optional_future/`: reserved for future extensions.

## 3. `meta.json` Schema (Mandatory)
Required schema:
```json
{
  "dataset_name": "wordnet",
  "dataset_hash": "sha256:<hex>",
  "graph_vertex_count": 82670,
  "graph_edge_count": 742134,
  "structure_mode": "4",
  "index_version": "v1.0",
  "built_at": "2026-03-03T12:34:56Z",
  "built_by": "developer_or_ci_identity",
  "fastest_commit_hash": "<git_sha_or_unknown>",
  "build_parameters": {
    "threads": 4,
    "group_size": 16,
    "incident_edges_size": 50000
  },
  "artifact_format_version": "1.0"
}
```

Field requirements:
- `dataset_name`: must match dataset directory name.
- `dataset_hash`: SHA-256 of canonical bytes of `<dataset_name>.graph`; required for stale-index detection.
- `graph_vertex_count`, `graph_edge_count`: stored counts for quick integrity checks.
- `structure_mode`: one of `"X"`, `"3"`, `"4"`.
- `index_version`: semantic/index algorithm version managed by project maintainers.
- `built_at`: UTC ISO-8601 timestamp.
- `built_by`: build actor identity (human/CI).
- `fastest_commit_hash`: source commit used for build.
- `build_parameters`: exact runtime-affecting build parameters.
- `artifact_format_version`: serialization contract version for loader compatibility.

Why `dataset_hash` is mandatory:
- It proves artifact-to-dataset binding and prevents silent reuse of stale indices after graph file changes.

Why `artifact_format_version` is separate from `index_version`:
- `index_version` tracks algorithm/index semantics.
- `artifact_format_version` tracks on-disk serialization compatibility.
- Either can change independently; loader must validate both.

Loader compatibility validation:
1. Validate required keys and types.
2. Validate supported `artifact_format_version`.
3. Validate `dataset_hash` against current graph file.
4. Validate requested structure mode is available and compatible.
5. Only then mark index as loadable.

## 4. Structure Index Storage Layout
Canonical structure-mode grouping:
```text
index/
  structure/
    mode_3/
      index.bin
      manifest.json
    mode_4/
      index.bin
      manifest.json
    mode_X/
      index.bin
      manifest.json
```

Rules:
- A single dataset can have multiple mode directories simultaneously.
- Runtime loader must validate requested mode matches selected mode directory.
- `index.bin` contents are opaque binary blobs.
- This spec does not define internal binary fields.

`manifest.json` minimum contract per mode:
```json
{
  "mode": "4",
  "artifact_format_version": "1.0",
  "index_version": "v1.0",
  "payload_files": ["index.bin"]
}
```

## 5. Statistics Storage (Optional but Recommended)
Recommended layout:
```text
index/statistics/
  summary.json
```

Example `summary.json`:
```json
{
  "triangle_count": 123456,
  "four_cycle_count": 654321,
  "avg_degree": 12.34,
  "max_degree": 987
}
```

Rules:
- Statistics are for UI/reporting only.
- Kernel correctness must not depend on this file.
- Missing statistics must not block index readiness if structural artifacts are valid.

## 6. Offline Build Workflow (Defined Contract)
### Verified current capability
- ✅ Existing CLI can run indexing phase without query phase:
  - From `build/`: `./Fastest -d <dataset_name> -x --STRUCTURE <X|3|4> [--threads N] [--group_size G] [--incident_edges_size I]`

### Contract to implement
- ⚠️ Current CLI does not persist indices; persistence hook must be added by implementation work.
- Offline build pipeline must:
1. Run index build command for target mode.
2. Serialize artifacts into `dataset/<dataset_name>/index/structure/mode_<mode>/`.
3. Compute dataset hash from `<dataset_name>.graph`.
4. Write/refresh `meta.json`.
5. Optionally write `statistics/summary.json`.

Expected output status:
- Index is `ready` only after all required files and metadata pass validation.

## 7. Online Load Contract
Runtime sequence:
1. Check `dataset/<dataset_name>/index/meta.json` exists.
2. Parse and validate metadata schema.
3. Compute graph hash and compare with `dataset_hash`.
4. Validate requested structure mode is present (`structure/mode_<mode>/`).
5. Validate `artifact_format_version` is supported.
6. Validate mode manifest and payload file existence.
7. Set status:
   - `ready`: all checks pass.
   - `missing`: required file not found.
   - `stale`: hash mismatch.
   - `invalid`: schema/version/manifest mismatch.

Stage A rule:
- Online system loads/validates prebuilt artifacts only.
- Online system never builds index artifacts.

## 8. Versioning & Compatibility Rules
Version fields:
- `artifact_format_version`: serialization compatibility.
- `index_version`: algorithm/index semantics.

Rules:
1. Change `artifact_format_version` when on-disk file schema or decoding rules change.
2. Change `index_version` when index-generation semantics change while format may remain compatible.
3. Backward compatibility policy:
   - Loader supports a declared allowlist of `artifact_format_version` values.
   - Unsupported versions must produce `invalid` status and hard-fail loading.
4. Incompatible versions:
   - Do not attempt partial load.
   - Return explicit remediation: rebuild artifacts offline with supported versions.

## 9. Future Extensions (Stage B / C Hooks)
Reserved directories:
```text
index/
  cost_models/
  memoization_cache/
  prefix_cache/
```

Purpose:
- `cost_models/`: learned or heuristic cost estimators.
- `memoization_cache/`: cross-order/prefix memoization artifacts.
- `prefix_cache/`: reusable prefix-state persistence.

Rules:
- These directories are placeholders.
- Stage A loader must ignore unknown optional directories unless explicitly configured to validate them.
