# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GraphQuery is a **subgraph matching query plan optimizer**. It finds the optimal vertex expansion order for subgraph matching by generating candidate orders, estimating their cost via cardinality estimation (FaSTest algorithm), and ranking them in real-time.

The system has three core modules:
- **M1 — Prefix Subgraph Enumeration**: Generates candidate expansion orders and their prefix subgraphs (`order_generator.py`, `prefix_builder.py`)
- **M2 — Sequence Cost Estimation**: Estimates cardinality for each prefix via C++ engine, scores and ranks orders (`estimator_adapter.py`, `score_aggregator.py`, C++ `fastest_core`)
- **M3 — Downstream Query Engine**: Runs actual subgraph matching with the best order using SubgraphMatchingSurvey binary (`survey_engine_adapter.py`, `graph_format_converter.py`)

Data flow: `M1 →(candidate orders)→ M2 →(best order)→ M3`

## Build & Run Commands

### Python Environment
All Python commands (backend, tests, etc.) must run inside the `fastest` conda environment:
```bash
conda activate fastest
```

### C++ Core (pybind11 module + CLI)
```bash
cmake -B build
cmake --build build --target fastest_core  # Python module → fastest_core.*.so at project root
cmake --build build --target Fastest        # CLI executable
```
Dependencies: CMake 3.21+, C++20, OpenMP, Boost, GSL, TBB, pybind11

### Backend (FastAPI)
```bash
pip install -r server/requirements.txt
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend (React + Vite)
```bash
cd frontend && npm install && npm run dev    # dev server (proxies /api to :8000)
cd frontend && npm run build                 # production build
cd frontend && npm run lint                  # ESLint
```

### Tests
```bash
pytest server/tests/                         # backend tests
pytest server/tests/test_api.py::test_name   # single test
```

### SubgraphMatchingSurvey Engine (optional M3)
```bash
cd core/engines/SubgraphMatchingSurvey/vlabel && mkdir -p build && cd build && cmake .. && make
```

## Architecture

### Pipeline Orchestration
`server/services/session_pipeline.py` is the central coordinator. It chains M1→M2→M3:
1. Normalizes query graph vertex IDs to 0..n-1
2. Calls `order_generator.generate_orders()` (exact DFS or beam search)
3. For each order, calls `prefix_builder.build_prefix_subgraphs()`
4. Submits prefixes to `EstimatorAdapter` (C++ pybind11 singleton) for cardinality estimation
5. `ScoreAggregator` accumulates scores, maintains Top-K ranking, batches SSE events (75ms windows)
6. Optionally invokes `SurveyEngineAdapter` for ground-truth execution

### C++ ↔ Python Bridge
- `core/pybind/FastestPybind.cc` exposes the C++ estimator via pybind11
- `EstimatorAdapter` is a singleton that loads dataset indices (graph.bin, triangles.bin, four_cycles.bin) into memory
- Thread-safe: GIL released during C++ calls, uses ThreadPoolExecutor for parallel prefix evaluation

### Real-time Streaming
- Backend pushes results via SSE (Server-Sent Events) through `sse-starlette`
- Frontend consumes via `useSessionStream.ts` hook (EventSource)
- `ScoreAggregator` debounces events into 75ms batches to avoid UI thrashing

### Key Data Models (`server/models.py`)
- `QueryGraph` / `NormalizedGraph`: User-drawn and normalized graph representations
- `PrefixPayload`: Prefix subgraph sent to C++ estimator
- `Session`: Full session state including orders, scores, execution results
- `OrderState`: Per-order tracking (score, prefix estimates, status)

### Dataset Layout
Each dataset under `dataset/` has:
- `*.graph` — text format graph file
- `index/` — prebuilt binary indices (graph.bin, triangles.bin, four_cycles.bin)

### Configuration
- `server/config.py`: Singleton `AppConfig` (dataset_root, log_dir, survey_binary)
- `server/default_config/schedule_config.json`: Thread pool sizing
- Environment overrides: `DATASET_ROOT`, `LOG_DIR`, `SURVEY_BINARY`

## Key Context

- The project references the SIGMOD 2024 paper: "A Comprehensive Survey and Experimental Study of Subgraph Matching: Trends, Unbiasedness, and Interaction" (Zhang et al.)
- EPS (Embeddings Per Second) = #Embeddings / Total Time — the unbiased metric from that paper
- `project_tasks.md` outlines four upgrade tasks: EPS cost model, A* search pruning, concurrency optimization, and visualization enhancement
- The SubgraphMatchingSurvey engine supports 10 filter × 10 order × 10 engine method combinations
- Graph input format: `t N M` header, `v id label degree` vertices, `e src tgt (label)?` edges
