# System Development Roadmap for Expanding FaSTest into an Optimized Graph Query System

## 1. Scope and Baseline

### 1.1 Current Baseline (Implemented)
The current repository provides a C++ cardinality-estimation kernel with:

- Data graph loading and preprocessing.
- Optional motif indexing (triangle and four-cycle safety structures).
- Candidate space construction/filtering.
- Tree/graph sampling-based cardinality estimation.
- A CLI driver that processes query files sequentially.

### 1.2 Expansion Goal
Build a complete system layer on top of the estimator core to support:

1. Dataset storage and index-building visualization.
2. Query graph submission from frontend.
3. Query order generation (single order first, then multiple).
4. Prefix subgraph construction and evaluation.
5. Accumulated order scoring.
6. Real-time ranking updates.
7. Best-order selection and execution via downstream engine (mock first).

### 1.3 Guiding Constraints

- Do not rewrite estimator internals during early stages.
- Wrap existing estimator capabilities behind stable service interfaces.
- Keep staged scope realistic and measurable.
- Preserve a clear boundary between orchestration logic and estimator kernel logic.

---

## 2. Architectural Layering Overview

### 2.1 Target Layers

- Core Estimator Layer:
  Existing C++ kernel for indexing, candidate-space build, and cardinality estimation.
- Orchestration Layer:
  Query session lifecycle, order generation, prefix construction, task scheduling, scoring, state transitions.
- API Layer:
  External contract for dataset operations, query submission, order-evaluation control, result retrieval.
- Streaming Layer:
  Progress and ranking events via SSE or WebSocket.
- Frontend Layer:
  Dataset/index status UI, query editor, order leaderboard, prefix trajectory view, best-order animation, execution results.

### 2.2 Interaction Model

1. Frontend submits query session request.
2. API layer validates input and opens a session in orchestration layer.
3. Orchestration layer obtains order(s), builds prefixes, invokes estimator, accumulates scores.
4. Streaming layer emits progress events.
5. Orchestration selects best order and triggers downstream execution adapter.

### 2.3 Core Integration Principle

Estimator must be called through a single internal adapter (`EstimatorFacade`) that hides process/library details and returns normalized metrics (`estimate`, `timing`, `status`, `error`).

---

## 3. Stage A — MVP (1–2 Weeks, End-to-End Demonstration)

### 3.1 Objective
Deliver a minimal but complete online flow from query submission to streamed prefix-score updates and mock execution.

### 3.2 Required Components

- Dataset listing API.
- Basic dataset/index registry (read-only metadata acceptable).
- Query submission endpoint.
- Single-order generator (BFS-style heuristic).
- Prefix builder for one order.
- Estimator invocation adapter (recompute each prefix independently).
- Streaming channel (SSE preferred for implementation simplicity).
- Mock downstream execution endpoint.

### 3.3 Required New Modules

- `DatasetService`:
  Returns available datasets and index-ready status.
- `QuerySessionService`:
  Creates session and stores query graph payload.
- `SingleOrderGenerator`:
  Produces one deterministic BFS-based order.
- `PrefixBuilder`:
  Produces connected prefix subgraphs from the selected order.
- `EstimatorFacade`:
  Invokes existing estimator for each prefix graph.
- `ScoreAccumulator`:
  Maintains cumulative score per prefix.
- `ProgressStreamer`:
  Emits prefix progress + cumulative score events.
- `ExecutionMockAdapter`:
  Returns deterministic mock response for best order.

### 3.4 Data Structures (Minimum)

- `QueryGraph { vertices[], edges[], labels }`
- `Order { order_id, vertex_sequence[] }`
- `PrefixEval { prefix_index, subgraph_id, estimate, partial_sum, elapsed_ms, status }`
- `QuerySession { session_id, dataset_id, query_graph, order, state }`

### 3.5 Interaction with Existing Estimator Core

- Input: one generated prefix graph at a time.
- Invocation style: synchronous call per prefix via adapter.
- Reuse scope: data graph/index can be loaded once per worker process; prefix estimation still recomputed from scratch.

### 3.6 API-Level Responsibilities

- `GET /datasets`: list available datasets and index status.
- `POST /query-sessions`: submit `QueryGraph` and start evaluation.
- `GET /query-sessions/{id}`: retrieve session state and final summary.
- `GET /query-sessions/{id}/stream` (SSE) or WS equivalent: prefix updates.
- `POST /query-sessions/{id}/execute`: invoke mock downstream execution.

### 3.7 Concurrency Considerations

- Single-session sequential prefix evaluation is acceptable for MVP.
- Run estimator in worker thread/process to avoid blocking API event loop.
- Guard session state with a mutex or actor-style single-owner loop.

### 3.8 Risks

- Prefix construction may become invalid for disconnected query graphs unless validated.
- Frequent streaming events can overload UI if not throttled.
- Per-prefix recomputation can be slow for larger queries.

### 3.9 Deliverables

- Backend MVP service with APIs + streaming endpoint.
- Frontend MVP views: dataset list, query submit, prefix curve + cumulative score.
- Mock execution result panel.
- Minimal deployment/runbook documentation.

### 3.10 Milestone Validation Criteria

- End-to-end session completes successfully on at least one dataset and multiple query examples.
- Frontend receives ordered prefix updates with monotonic `prefix_index`.
- Final cumulative score equals sum of all prefix estimates.
- Mock execution returns result tied to selected order.

---

## 4. Stage B — System Version (Multi-Order Evaluation)

### 4.1 Objective
Support Top-K order evaluation with live ranking and robust concurrent execution.

### 4.2 Required Components

- Top-K order enumerator.
- Parallel order evaluation runtime.
- Prefix-level streaming for all active orders.
- Real-time leaderboard sorted by cumulative score.
- Best-order visualization and execution adapter stub.

### 4.3 Required New Modules

- `OrderEnumeratorTopK`:
  Generates candidate orders using constrained heuristics.
- `EvaluationScheduler`:
  Dispatches `(order, prefix)` tasks to worker pool.
- `OrderStateStore`:
  Tracks per-order progress (`partial_sum`, `prefix_done`, `status`).
- `LeaderboardService`:
  Maintains sorted order ranking and emits changes.
- `FailurePolicyManager`:
  Retry/timeout/cancel logic per order.
- `ExecutionEngineAdapterStub`:
  Interface-compatible placeholder for real engine integration.

### 4.4 Concurrency Model

Recommended model:

- Global task queue for prefix-evaluation tasks.
- Fixed-size worker pool (size based on CPU and estimator parallelism).
- Session-local state lock (or actor) to serialize ranking updates.
- Backpressure on stream emission (batch or interval-based update coalescing).

### 4.5 Task Scheduling Strategy

- Initial strategy: round-robin across orders for fairness and early leaderboard visibility.
- Optional enhancement: shortest-prefix-first or uncertainty-driven scheduling.
- Hard limits: max active sessions, max active orders/session, max pending tasks.

### 4.6 Partial Sum Propagation

For each completed prefix evaluation:

1. Update `OrderStateStore.partial_sum += estimate`.
2. Emit `order_progress` event.
3. Recompute leaderboard position (incremental update preferred).
4. Emit `leaderboard_update` event when rank changes.

### 4.7 Performance Considerations

- Avoid repeated dataset/index reload per task; preload once per worker.
- Bound event frequency to protect frontend rendering.
- Track per-stage timings (`queue_wait`, `estimation`, `serialization`, `stream_send`).

### 4.8 Failure Handling

- Prefix estimation failure marks order as `failed` or `degraded`.
- Session continues if at least one order remains evaluable.
- Timeout policy for slow orders; cancellation support by session.

### 4.9 Deliverables

- Multi-order backend with live leaderboard streaming.
- Frontend ranking table with expandable per-order prefix trajectory.
- Best-order animation and execution adapter stub wiring.
- Operational dashboards for queue depth, throughput, and error rate.

### 4.10 Milestone Validation Criteria

- Top-K sessions show concurrent progress for multiple orders.
- Leaderboard updates reflect cumulative-score ordering with bounded latency.
- System remains stable under configured parallel load.
- Failure of one order does not terminate whole session.

---

## 5. Stage C — Research Enhancement (Algorithmic Contributions)

### 5.1 Objective
Introduce algorithmic improvements that reduce redundant work and improve optimization quality beyond system wrapping.

### 5.2 Selected Enhancements

This roadmap selects two realistic enhancements:

1. Incremental candidate-space reuse across prefixes.
2. Cross-order prefix memoization.

### 5.3 Enhancement A: Incremental Candidate-Space Reuse Across Prefixes

Problem addressed:

- Stage A/B repeatedly rebuilds estimator inputs from scratch per prefix, causing high cumulative cost.

Required structural changes:

- Introduce `PrefixStateCache` storing reusable filtering artifacts between prefix `i` and `i+1` for the same order.
- Extend `EstimatorFacade` contract to accept optional prior-state handle.

Estimator invocation changes:

- From `estimate(prefix_graph)` to `estimate(prefix_graph, previous_prefix_state?)`.

Expected benefit:

- Lower average prefix evaluation time, especially for long orders.
- Better streaming responsiveness under fixed compute budget.

Complexity implications:

- Increased memory usage for cached state.
- Added cache invalidation logic and consistency checks.

Evaluation metrics:

- Mean prefix evaluation latency reduction (%).
- End-to-end session time reduction.
- Additional memory overhead per active order.

### 5.4 Enhancement B: Cross-Order Prefix Memoization

Problem addressed:

- Different orders often share isomorphic or equivalent early prefixes; repeated evaluation wastes compute.

Required structural changes:

- Canonical prefix fingerprinting (`PrefixCanonicalKey`).
- Shared `PrefixMemoStore` across all orders within a session (or globally with dataset keying).

Estimator invocation changes:

- Lookup before execution: if key hit, reuse stored estimate/metadata.
- On miss, execute estimator and write result into memo store.

Expected benefit:

- Reduces duplicate prefix estimation.
- Improves throughput when Top-K is large and prefix overlap is high.

Complexity implications:

- Canonicalization cost per prefix.
- Potential memory growth; requires bounded cache + eviction policy.

Evaluation metrics:

- Memoization hit rate.
- Estimator call reduction ratio.
- Net speedup versus memoization overhead.

### 5.5 Stage C Deliverables

- Experimental branch with toggleable enhancement flags.
- Benchmark suite and ablation study scripts.
- Comparative report (baseline Stage B vs Enhancement A/B vs combined).

### 5.6 Stage C Milestone Validation Criteria

- Demonstrated statistically meaningful improvement on target datasets.
- Reproducible experiments with fixed configs and reported confidence intervals.
- No regression in correctness of cumulative scoring and best-order selection.

---

## 6. Risk Analysis

### 6.1 Query Size Explosion

- Prefix count grows linearly with query vertex count, but per-prefix estimator cost may grow sharply.
- Mitigation: hard caps, admission control, early stopping policies.

### 6.2 n! Order Growth

- Full permutation enumeration is intractable for nontrivial query size.
- Mitigation: constrained Top-K generation and heuristic pruning.

### 6.3 Memory Pressure

- Candidate spaces, motif indices, and future prefix caches can consume large memory.
- Mitigation: per-session limits, bounded caches, memory telemetry, spill-to-disk only when necessary.

### 6.4 Concurrency Hazards

- Race conditions in order state updates and stream emission.
- Oversubscription if estimator internal parallelism conflicts with system worker parallelism.
- Mitigation: explicit concurrency budget and synchronized state transitions.

### 6.5 Streaming Bottlenecks

- High-frequency events can saturate network/UI rendering.
- Mitigation: event coalescing, adaptive throttling, incremental diff updates.

---

## 7. Long-Term Refactoring Plan

### 7.1 Convert Estimator from CLI to Library/Service

- Extract driver logic into reusable library API.
- Provide stable C++ interface for loading data/index and estimating a query graph.
- Optionally expose via gRPC/HTTP microservice for multi-language orchestration.

### 7.2 Persistent Dataset and Index Lifecycle

- Keep datasets and indices loaded in long-lived worker processes.
- Separate dataset registration from runtime evaluation.
- Add health and warmup endpoints.

### 7.3 Avoid Repeated Index Reload and Setup

- Initialize dataset/index once per worker startup.
- Reuse across sessions with reference counting and eviction policy.
- Persist metadata for fast recovery and startup-time validation.

### 7.4 Compatibility Strategy

- Maintain estimator-core API stability while adding optional incremental features.
- Use capability flags so orchestration can degrade gracefully when advanced features are disabled.

---

## 8. Stage-by-Stage Summary

- Stage A (MVP): single-order, prefix streaming, mock execution, complete demonstrator.
- Stage B (System Version): Top-K concurrent evaluation with live leaderboard and robust state management.
- Stage C (Research Enhancement): measurable algorithmic acceleration through incremental reuse and memoization.

This sequence keeps scope achievable while preserving a clear path from engineering integration to publishable optimization contributions.
