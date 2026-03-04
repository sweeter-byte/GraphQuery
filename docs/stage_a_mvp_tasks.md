# Stage A (MVP) Detailed Development Tasks (Revised)

Annotation style used in this document:
- ✅ Verified in code
- ⚠️ TBD / Not confirmed in code

## 1. Executive Summary
Stage A provides the minimum end-to-end closure around the current FaSTest estimator kernel: dataset metadata APIs, query submission, deterministic single connected expansion order generation, prefix construction, per-prefix cardinality estimation, streaming progress, and mock downstream execution. ✅ The repository already implements only the estimator kernel and CLI flow (data graph loading, preprocessing/indexing, candidate-space build, filtering, sampling estimation), while all service/API/frontend/session orchestration described here is to be implemented in Stage A.

## 2. Scope and Non-Scope

### In Scope (Stage A)
- Dataset listing/detail APIs with index status metadata.
- Online index artifact existence check and coarse-grained index loading events.
- Query graph submission endpoint.
- Deterministic single connected expansion order generation.
- Prefix subgraph construction for that single order.
- Per-prefix estimator invocation via existing CLI.
- Accumulated score computation and streaming update after each prefix.
- Session status polling endpoint.
- Best-order selection (trivial: only one order).
- Mock downstream execution boundary.
- Minimal frontend: JSON editor/form + progress visualization.

### Out of Scope (Stage A)
- Top-K / multi-order ranking.
- Pruning / branch-and-bound / anytime scheduling.
- Candidate-space reuse or cross-order memoization.
- Real downstream query engine integration.
- Replay-buffered streaming guarantees (Stage A+ optional only).
- Refactoring estimator core into a library.
- Uploading new datasets through UI.
- Online index construction on user request.
- Long-running background indexing jobs with detailed progress UI.

## 3. Architecture for Stage A

### Stage A Components
- UI (to be implemented): dataset selection, query JSON editor, live progress view, result view.
- API server (to be implemented): REST endpoints + SSE endpoint.
- Session manager (to be implemented): state machine and result aggregation.
- Estimator runner adapter (to be implemented): CLI invocation + stdout parsing.
- Storage (to be implemented): dataset registry + session records.

### Stage A Data Flow
1. Frontend calls `GET /api/datasets` and selects one dataset.
2. Frontend sees dataset index status (`ready | missing | unknown`) and index summary (if available).
3. Frontend submits query graph via `POST /api/sessions`.
4. Backend validates query and creates session.
5. Backend validates index artifacts exist and performs index loading step (coarse start/end events).
6. Backend generates one deterministic connected expansion order.
7. Backend builds prefixes from that order.
8. Backend runs estimator for each prefix (sequential for Stage A).
9. After each prefix estimate, backend updates `accumulated_score` and emits SSE event.
10. Frontend renders prefix metrics and accumulated curve.
11. User triggers mock execution endpoint; backend returns mock result.

Stage A index lifecycle rule:
- Index artifacts are prebuilt offline by developer workflow.
- Online Stage A behavior is index status/reporting + index loading, not index construction.

### REST vs Streaming
- REST: metadata lookup, session creation/status, execute, result.
- Streaming: one-way progress updates (`/stream`) via SSE.

### Stage A Diagram
```text
Frontend UI
  | REST + SSE
  v
API Server
  | invokes
  v
Session Manager
  | invokes
  v
Estimator Adapter (CLI wrapper)
  | spawns
  v
Fastest binary (existing C++ kernel)
```

## 4. Data Contracts (Schemas)

### Dataset Summary
```json
{
  "id": "wordnet",
  "name": "WordNet",
  "num_vertices": 82670,
  "num_edges": 742134,
  "labels": [0, 1, 2],
  "index_status": "ready",
  "index_artifact_path": "dataset/wordnet/index/v1",
  "index_version": "v1.0",
  "index_built_at": "2026-03-01T10:30:00Z",
  "index_summary": {
    "structure_filter": "triangle+four_cycle",
    "num_indexed_edges": 742134
  },
  "location": "dataset/wordnet"
}
```

Field constraints:
- `index_status` enum: `ready | missing | unknown`.
- `index_artifact_path`: artifact directory path (or derivable convention).
- `index_version`: developer-managed semantic/version string.
- `index_built_at`: optional timestamp string.
- `index_summary`: optional precomputed summary for UI display.

### QueryGraph
```json
{
  "directed": false,
  "vertices": [
    {"id": 0, "label": 1},
    {"id": 1, "label": 1},
    {"id": 2, "label": 2}
  ],
  "edges": [
    {"id": 0, "source": 0, "target": 1, "label": 0},
    {"id": 1, "source": 1, "target": 2, "label": 0}
  ]
}
```

### Order
```json
{
  "order_id": "order-0",
  "vertex_sequence": [1, 0, 2],
  "heuristic_name": "connected_expansion_min_label_min_id"
}
```

### Prefix Progress Event Payload
```json
{
  "event_type": "prefix_progress",
  "session_id": "sess-20260303-0001",
  "order_id": "order-0",
  "prefix_index": 2,
  "prefix_vertices": [1, 0],
  "prefix_edges": [0],
  "estimated_cardinality": 1542.37,
  "accumulated_score": 1833.12,
  "started_at": "2026-03-03T14:01:05.121Z",
  "finished_at": "2026-03-03T14:01:05.921Z"
}
```

### Session Object
```json
{
  "session_id": "sess-20260303-0001",
  "dataset_id": "wordnet",
  "query_graph": {"directed": false, "vertices": [], "edges": []},
  "order": {"order_id": "order-0", "vertex_sequence": [1, 0, 2], "heuristic_name": "connected_expansion_min_label_min_id"},
  "status": "running"
}
```

### Mock Execution Result
```json
{
  "session_id": "sess-20260303-0001",
  "engine": "mock-engine-v1",
  "selected_order_id": "order-0",
  "execution_status": "completed",
  "estimated_runtime_ms": 12,
  "match_count": 42,
  "details": "Mock response for Stage A"
}
```

## 5. API Specification (Stage A)

### Error Payload (common)
```json
{
  "error": {
    "code": "INVALID_QUERY_GRAPH",
    "message": "Query graph is disconnected",
    "details": {}
  },
  "request_id": "req-7f2d"
}
```

### `GET /api/datasets`
- `200`: `{ "datasets": [DatasetSummary, ...] }`
- `500`: registry load failure.

### `GET /api/datasets/{id}`
- `200`: `DatasetSummary`
- `404`: unknown dataset.

### `POST /api/sessions`
- Request: `{ "dataset_id": "...", "query_graph": QueryGraph }`
- `202`:
```json
{
  "session_id": "sess-20260303-0001",
  "status": "queued",
  "stream_url": "/api/sessions/sess-20260303-0001/stream"
}
```
- `400`: malformed JSON.
- `404`: dataset not found.
- `422`: validation failure.
- `409`: concurrency/session limit hit (see `Stage A Concurrency Policy (MVP Constraint)`).

### `GET /api/sessions/{session_id}`
- `200`: session status + progress counters.
- `404`: unknown session.

### `GET /api/sessions/{session_id}/stream` (SSE)
Why SSE for MVP:
- ✅ One-way server-to-client progress is sufficient.
- ✅ Simpler than WebSocket for Stage A.

Example stream:
```text
event: index_loading
data: {"session_id":"sess-20260303-0001","dataset_id":"wordnet","status":"index_loading"}

event: index_loaded
data: {"session_id":"sess-20260303-0001","dataset_id":"wordnet","status":"index_loaded","index_version":"v1.0"}

event: session_started
data: {"session_id":"sess-20260303-0001","status":"running"}

event: prefix_progress
data: {"session_id":"sess-20260303-0001","prefix_index":1,"estimated_cardinality":290.75,"accumulated_score":290.75}

event: session_completed
data: {"session_id":"sess-20260303-0001","status":"completed","accumulated_score":2103.55}
```
- `404`: unknown session.

### `POST /api/sessions/{session_id}/execute`
- Request: `{ "engine": "mock-engine-v1" }`
- `202`: execution started (mock).
- `404`: unknown session.
- `409`: session not yet completed.

### `GET /api/sessions/{session_id}/result`
- `200`: session summary + prefix results + mock execution result.
- `404`: unknown session.
- `409`: result not ready.

## Stage A Concurrency Policy (MVP Constraint)
- Maximum running sessions: `1` (global process limit for Stage A).
- Queueing: not supported in Stage A.
- Rationale:
  - ✅ Estimator invocation is CLI-process based and CPU-intensive.
  - ✅ Current estimator run performs data loading + preprocessing/index build per process.
  - ✅ Deterministic one-at-a-time execution keeps MVP behavior predictable.
- If limit exceeded:
  - API returns `409 Conflict`.
  - Error payload:
```json
{
  "error": {
    "code": "SESSION_CAPACITY_REACHED",
    "message": "Stage A supports at most 1 running session and does not queue.",
    "details": {"max_running_sessions": 1}
  },
  "request_id": "req-a12b"
}
```

## 6. Core Algorithms (Stage A Only)

### Single Connected Expansion Order (Stage A Simplification)
- Stage A order space semantics follow connected expansion, not BFS-specific semantics.
- A valid order is any connected expansion order (defined formally below).
- Stage A picks exactly one deterministic representative order and does not optimize.
- Deterministic tie-breakers are mandatory.

## Formal Definition — Connected Expansion Order
Given query graph `G = (V, E)`, an order `O = (v1, v2, ..., vn)` is valid iff:
1. `O` is a permutation of `V`.
2. For every `k > 1`, there exists `j < k` such that `(vj, vk) ∈ E`.

Prefix subgraph definition:
- `Vk = {v1, ..., vk}`
- `Ek = {(x, y) ∈ E | x ∈ Vk and y ∈ Vk}`

Therefore, `prefix(k)` is the induced subgraph of the original query graph on `Vk`.

Stage A constraint:
- Stage A selects exactly one deterministic connected expansion order.
- Stage A does not enumerate all connected expansion orders.
- Stage A does not perform order optimization.
- Stage A goal is correctness of prefix semantics, estimator invocation, streaming, and session lifecycle.

Pseudo-code:
```text
generate_connected_order(G):
  require connected(G_undirected)
  root = argmin_v(label(v), id(v))
  S = {root}
  order = [root]
  while |S| < |V|:
    candidates = {v not in S | exists u in S and (u, v) in E}
    next = argmin_v_in_candidates(label(v), id(v))
    S.add(next)
    order.append(next)
  return order
```

Notes:
- BFS is one possible implementation strategy, but it is not the formal definition of valid order.
- Stage B may enumerate/search in the full connected expansion order space; Stage A intentionally uses one deterministic representative.

### Prefix Construction
Definition:
- `prefix(k)` includes first `k` vertices in order and all edges among them.
- Connectivity check (Stage A): evaluate connectivity on undirected underlying graph.

Directed handling policy (explicit):
- If `directed=false`: use undirected connectivity.
- If `directed=true`: still use undirected connectivity in Stage A.
- Justification: ✅ estimator file loader (`LoadLabeledGraph`) ingests undirected graph text and duplicates edges internally; directed semantics are not exposed by CLI path.

Pseudo-code:
```text
build_prefixes(G, order):
  S = empty set
  for k in 1..|order|:
    S.add(order[k])
    Ek = {e | endpoints(e) subset of S}
    if not connected_undirected(S, Ek): fail
    yield subgraph(S, Ek)
```

### Score Accumulation and Streaming
```text
acc = 0
for k, prefix in prefixes:
  est = estimate(prefix)
  acc += est
  emit(prefix_progress(k, est, acc))
emit(session_completed(acc))
```

## 7. Estimator Integration Plan (Verified)

### 7.1 Real CLI Entrypoint and Flags
- ✅ Entrypoint: `driver/subgraph-cardinality-estimation.cc` (`main`).
- ✅ Built binary name: `Fastest` (`CMakeLists.txt`, `add_executable(Fastest ...)`).
- ✅ Supported flags from code:
  - `-d <dataset>`
  - `-q <query_list_file>`
  - `-K <ub_initial>`
  - `-x` (index only; skip query phase)
  - `--threads <int>`
  - `--group_size <int>`
  - `--incident_edges_size <int>`
  - `--STRUCTURE <X|3|4>`

### 7.2 Verified Command Syntax
Example from build directory:
```bash
./Fastest -d wordnet -q ../dataset/wordnet/wordnet_ans.txt --STRUCTURE 4 --threads 4
```

Important path/cwd note:
- ✅ Driver constructs paths with `../dataset/...`; command assumes runtime cwd similar to `build/`.

### 7.3 Single Query vs Batch Support
- ✅ CLI consumes a **list file** via `-q` (`read_ans`): each token is interpreted as one query filename.
- ✅ Batch in one run is supported by listing multiple query files in the list file.
- ⚠️ No dedicated direct “single query graph filepath” flag exists in current CLI.
- Stage A approach: create one list file per session containing prefix filenames; run one CLI process per session.

### 7.4 Dataset Root / Index Path / Query Path Discovery
- ✅ Dataset graph path: `../dataset/<dataset>/<dataset>.graph`.
- ✅ Default query list path: `../dataset/<dataset>/<dataset>_ans.txt` if `-q` omitted.
- ✅ Query graph path resolution: each entry in list file is prefixed as `../dataset/<dataset>/query_graph/<entry>`.
- ✅ Index persistence path via CLI: none exposed; indexing is built in-memory each run.
- ⚠️ Persistent index read/write directory convention: TBD (not confirmed in runtime flow).

### 7.5 Output Parsing Rules (Verified lines)
Use line-based parsing with these rules:
- Prefix start:
  - Match: `^Start Processing\s+(.+)$`
- Estimated cardinality:
  - Match: `^\s*\[Result\]\s+Est\s*:\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*$`
- Prefix completion:
  - Match: `^(.+)\s+Finished!$`
- Process failure hint:
  - Match: `^Error processing\s+(.+)\. Skipping\.$`

### 7.6 Timeout and Failure Strategy
- Session process timeout: recommended 120s default, configurable.
- Non-zero exit or parse failure: mark session `failed`, emit terminal error event.
- Missing `Est` between start/finish markers: fail-fast for Stage A.
- Always cleanup session-generated query/list temp files.

### 7.7 Adapter Modules (to be implemented in Stage A)
- `prefix_graph_writer`
- `query_list_writer`
- `fastest_process_runner`
- `fastest_stdout_parser`
- `estimation_event_mapper`

### 7.8 Logging Requirements
Log per prefix:
- `session_id`, `dataset_id`, `prefix_index`, `query_filename`, `est`, `duration_ms`, `exit_code`, `parse_status`.

## QueryGraph → CLI `.graph` Serialization (Verified from README.md)
- ⚠️ Root `README.md` is not present in this repository.
- ✅ Format references are verified from:
  - `Fastest.md` “Input Format” section.
  - `lib/DataStructure/Graph.h` (`Graph::LoadLabeledGraph`).

Minimal complete example (`3` vertices, `2` edges):
```text
t 3 2
v 0 1 1
v 1 1 2
v 2 2 1
e 0 1 0
e 1 2 0
```

Field-by-field specification:
- `t V E`
  - ✅ `V` = number of vertices.
  - ✅ `E` = number of undirected edges listed in file.
  - ✅ Loader sets internal edge count to `E * 2`.
- `v id label degree`
  - ✅ `id` is parsed and used as direct array index.
  - ✅ `label` is parsed (default `0` if omitted by loader).
  - ✅ Extra token(s) after label are ignored by loader; degree is not validated.
  - ⚠️ Degree exactness is therefore not required by current code path.
- `e src dst label`
  - ✅ `src`, `dst` are parsed and stored as one undirected edge; loader adds both directions internally.
  - ✅ `label` is optional (defaults to `0` if omitted).

Clarifications for Stage A prefix file generation:
- Vertex IDs:
  - ✅ Must be valid indices in range `0..V-1` for loader safety.
  - ⚠️ Contiguity is not explicitly validated by loader, but Stage A must enforce contiguous IDs (see next section).
- Degree field:
  - ✅ Present in documented format.
  - ✅ Not consumed by loader logic.
- Undirected edges:
  - ✅ Write each undirected edge once in input file.
  - ⚠️ Writing both directions would duplicate semantics and distort counts.
- Edge labels:
  - ✅ Optional in code (`default 0`), but Stage A should always write explicit labels for consistency.

## Vertex ID Normalization Rule (Stage A Requirement)
Backend must normalize every submitted `QueryGraph` to contiguous IDs before any algorithm step.

Normalization procedure:
1. Collect original vertex IDs and sort ascending.
2. Build mapping `old_id -> new_id` where `new_id` is `0..n-1`.
3. Rewrite vertices and edges using `new_id`.
4. Validate every edge endpoint exists in mapping.

Required usage of normalized IDs:
- Connected expansion order generation operates on normalized IDs.
- Prefix construction operates on normalized IDs.
- Serialized `.graph` prefix files use normalized IDs.

SSE payload ID policy (chosen for MVP simplicity):
- Use normalized IDs only in runtime fields (`prefix_vertices`, `order.vertex_sequence`).
- Include mapping once in session metadata:
```json
{
  "vertex_id_mapping": [
    {"original_id": 100, "normalized_id": 0},
    {"original_id": 205, "normalized_id": 1}
  ]
}
```
- Justification: keeps algorithm and parser paths unambiguous while preserving frontend traceability.

## 8. Streaming & Frontend Update Semantics

### Event Ordering
- Stage A guarantee: strict order by `prefix_index` (sequential execution).

### Overlap
- Stage A: no overlapping prefix evaluations in a single session.

### Frontend Update Rules
- Show index status on dataset selection (`ready | missing | unknown`).
- Show coarse index loading progress during session start (start/end only, no fine-grained bar required).
- Progress bar: `completed_prefixes / total_prefixes`.
- Line chart A: `x=prefix_index`, `y=estimated_cardinality`.
- Line chart B: `x=prefix_index`, `y=accumulated_score`.
- KPI tile: latest `accumulated_score`.

### Reconnect Strategy (MVP vs Optional)
- MVP required behavior:
  - reconnect stream from “now”;
  - call `GET /api/sessions/{id}` to recover current aggregate state.
- Stage A+ optional:
  - `Last-Event-ID` replay support.
- Replay buffer is **not** required for MVP acceptance.

## Terminal Error Event (SSE)
Stage A must emit a terminal failure event when session execution cannot continue.

Event name:
- `session_failed`

Payload example:
```json
{
  "session_id": "sess-20260303-0001",
  "status": "failed",
  "error": {
    "code": "ESTIMATOR_TIMEOUT",
    "message": "Estimator process exceeded timeout (120s).",
    "details": {
      "prefix_index": 3,
      "timeout_seconds": 120
    }
  }
}
```

Frontend behavior requirements:
- Treat `session_failed` as terminal.
- Stop progress animation and disable execute action.
- No additional `prefix_progress` events may be sent after `session_failed`.

## 9. Repository Path Alignment (Verified)

| Purpose | Actual path in repo | Source reference (file/function) | Notes |
|---|---|---|---|
| Dataset root (runtime) | `../dataset/<dataset>/` | `driver/subgraph-cardinality-estimation.cc` (`data_path` construction) | ✅ Relative to process cwd (typically `build/`). |
| Data graph file | `../dataset/<dataset>/<dataset>.graph` | same as above | ✅ Loaded by `D.LoadLabeledGraph`. |
| Query list default file | `../dataset/<dataset>/<dataset>_ans.txt` | `main`, default `query_path` | ✅ Used when `-q` not set. |
| Query graph directory | `../dataset/<dataset>/query_graph/` | `read_ans` path prefix logic | ✅ Each token in list file is treated as filename under this dir. |
| CLI driver source | `driver/subgraph-cardinality-estimation.cc` | file-level `main` | ✅ Only runtime entrypoint in repo. |
| Built binary name | `Fastest` | `CMakeLists.txt` `add_executable(Fastest ...)` | ✅ Output usually under `build/`. |
| Sample queries location | `dataset/*/query_graph/` | repository layout + `read_ans` assumption | ✅ Existing datasets follow this shape. |
| Index persistence directory | ⚠️ Not confirmed | no runtime read/write path in driver | ⚠️ Index built in-memory per run; no verified persisted index path. |

## Offline Index Build Workflow (Stage A Assumption)
- Stage A assumption:
  - Datasets are pre-registered on disk.
  - Index artifacts are prepared offline by developer workflow.
  - Online system only checks/loads artifacts and reports status/summary.

Offline procedure from current repository behavior:
- ✅ Verified command to run indexing stage only:
  - From `build/`: `./Fastest -d <dataset_id> -x --STRUCTURE 4`
  - Meaning: performs data loading + preprocessing + motif enumeration, then exits before query processing.
- ⚠️ Artifact persistence from this command is not confirmed in current code path (no verified index save path in driver runtime).

Intended Stage A artifact layout (to be supported by system layer):
- ⚠️ `dataset/<dataset_id>/index/<index_version>/`
  - `meta.json` (version, built_at, summary, status)
  - `triangle_index.*` (format TBD)
  - `four_cycle_index.*` (format TBD)
- ⚠️ Layout is an intended contract; concrete serialization format is TBD because kernel currently builds indices in-memory.

Stage A “ready” definition:
- `index_status=ready` means:
  - required artifact metadata exists and is parseable, and
  - runtime pre-session load/validation succeeds.
- If artifacts are absent: `index_status=missing`.
- If registry cannot determine state: `index_status=unknown`.

## 10. Storage and Persistence (Minimal)

Must store for Stage A:
- Session metadata: query graph, order, status timestamps.
- Prefix estimates and accumulated score.
- Mock execution result.
- Dataset registry metadata, including index fields:
  - `index_status`
  - `index_artifact_path`
  - `index_version`
  - `index_built_at` (optional)
  - `index_summary` (optional)

Storage mode:
- In-memory store is acceptable for MVP.
- Optional snapshot on terminal state to `tmp/stagea_sessions/<session_id>.json`.

File conventions for Stage A-generated temporary query assets:
- ✅ Must align with CLI expectation under `dataset/<dataset>/query_graph/`.
- Session list file can be under `tmp/`, but entries must be basenames resolvable by CLI prefix rule.

## 11. Implementation Task Breakdown (Developer Checklist)

### Backend
- Dataset registry + `GET /api/datasets`, `GET /api/datasets/{id}`.
  - Acceptance criteria: returns schema-correct payloads; proper 404.
  - Definition of done: endpoint tests pass.
- Session lifecycle manager (`queued -> running -> completed|failed`).
  - Acceptance criteria: valid transitions only.
  - Definition of done: transition tests pass.
- Index validation/loading step at session start.
  - Acceptance criteria: emits `index_loading` then `index_loaded` (or terminal failure) before prefix events.
  - Definition of done: integration test verifies ordering.
- Query graph validation.
  - Acceptance criteria: rejects malformed or disconnected query.
  - Definition of done: unit tests cover positive/negative cases.
- Single connected expansion order generator.
  - Acceptance criteria: deterministic order for same input.
  - Definition of done: determinism tests pass.
- Prefix builder.
  - Acceptance criteria: produces `n` prefixes for `n` vertices with correct induced edges.
  - Definition of done: correctness tests pass for small patterns.
- Estimator adapter (CLI spawn + parse + timeout).
  - Acceptance criteria: emits one estimate per prefix.
  - Definition of done: fixture-based parser tests pass.
- SSE progress endpoint.
  - Acceptance criteria: sends `index_loading`, `index_loaded`, `session_started`, `prefix_progress*`, terminal event.
  - Definition of done: integration test validates order and payload fields.
- Mock execute + result endpoints.
  - Acceptance criteria: execute allowed only after completed session.
  - Definition of done: state-guard tests pass.

### Frontend
- Dataset selection view.
  - Acceptance criteria: datasets shown with index status.
  - Definition of done: user can select dataset and proceed.

- Stage A Minimal (Required): JSON form/editor.
  - Acceptance criteria: create valid query JSON, validate, submit.
  - Definition of done: blocked submission for invalid JSON/graph.

- Stage A+ Optional (If time): simple visual graph editor.
  - Acceptance criteria: graph created visually, exported to same QueryGraph JSON.
  - Definition of done: parity with JSON form submission path.

- Live progress view.
  - Acceptance criteria: two curves + accumulated score update from SSE events.
  - Definition of done: no page refresh required during run.

- Mock result display.
  - Acceptance criteria: result endpoint output rendered after execute.
  - Definition of done: terminal state and errors clearly shown.

## 12. Testing Plan

### Unit Tests
- Connected expansion order determinism with tie-breakers.
- Prefix induced-subgraph correctness.
- Connectivity validation rule.
- Accumulated score math.
- CLI output parser patterns.

### Integration Tests
- `POST /api/sessions` -> SSE stream (`index_loading` -> `index_loaded` -> `session_started` -> prefix events) -> terminal event -> `GET /api/sessions/{id}/result`.
- Invalid query path returns `422` with error payload.

### Smoke Test
- Select small dataset (pre-existing in `dataset/`).
- Submit 3-5 vertex connected query.
- Expect one event per prefix and valid final result.

## 13. Known Risks & Mitigations (Stage A)
- CLI process overhead.
  - Mitigation: batch all prefixes in one CLI run per session.
- In-memory indexing rebuild each run.
  - Mitigation: keep Stage A query sizes small; avoid per-prefix process spawn.
- Streaming disconnects.
  - Mitigation: reconnect + poll session status (MVP requirement).
- Query-size explosion.
  - Recommended Stage A guardrail: `|V_query| <= 10`, `|E_query| <= 20`.
- Path/cwd fragility due to relative paths in CLI.
  - Mitigation: enforce controlled working directory in adapter.

## 14. Stage A Demo Script (What to Record)
1. Build binary and start API + frontend.
2. Call `GET /api/datasets`; show dataset and index status.
3. Enter a small query graph in required JSON editor.
4. Submit and capture `session_id`.
5. Open SSE stream and show `index_loading` then `index_loaded`.
6. Show subsequent sequential prefix events.
7. Show estimated-cardinality and accumulated-score curves.
8. Show session completion status via `GET /api/sessions/{id}`.
9. Trigger mock execution (`POST /api/sessions/{id}/execute`).
10. Show final payload from `GET /api/sessions/{id}/result`.

## Suggested Backend File Structure (Stage A)
Informational only (not enforced). Provided to reduce implementation ambiguity.

```text
server/
  app.py
  routes/
    datasets.py
    sessions.py
  services/
    prefix_builder.py
    estimator_adapter.py
  models.py
  storage.py
```
