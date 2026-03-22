# GraphQuery — Subgraph Cardinality Estimation Platform

> **FaSTest** \[VLDB 2024\] with a full-stack web interface for interactive query plan optimization.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Browser (localhost:5173)                      │
│  ┌──────────────┐  ┌────────────────────┐  ┌────────────────────┐  │
│  │   Dataset     │  │  Query Graph Editor │  │  Evaluation        │  │
│  │   Selector    │  │  (React Flow)       │  │  Dashboard         │  │
│  │               │  │                     │  │  • Status Badge    │  │
│  │  GET /datasets│  │  POST /sessions     │  │  • Progress Bar    │  │
│  │               │  │  {vertices, edges}  │  │  • Leaderboard     │  │
│  │               │  │                     │  │  • Live Charts     │  │
│  └──────────────┘  └────────────────────┘  └────────┬───────────┘  │
│                                                      │ SSE          │
│                                              EventSource            │
│                                         GET /sessions/{id}/stream   │
└──────────────────────────────────────────────────────┼──────────────┘
                                                       │
                          ┌────────────────────────────┼──────────────┐
                          │          FastAPI Backend (localhost:8000)  │
                          │                                           │
                          │  ┌─────────────────────────────────────┐  │
                          │  │         Session Pipeline             │  │
                          │  │  1. Validate & normalize query       │  │
                          │  │  2. Generate connected orders        │  │
                          │  │     (exact DFS | beam search)        │  │
                          │  │  3. Build prefix subgraphs           │  │
                          │  │  4. Estimate cardinality per prefix  │  │
                          │  │  5. Score aggregation & ranking      │  │
                          │  └─────────────┬───────────────────────┘  │
                          │                │                          │
                          │  ┌─────────────▼───────────────────────┐  │
                          │  │   ScoreAggregator (75ms batching)   │  │
                          │  │   → SSE: batch_update events        │  │
                          │  └─────────────┬───────────────────────┘  │
                          │                │                          │
                          │  ┌─────────────▼───────────────────────┐  │
                          │  │   EstimatorAdapter (Singleton)       │  │
                          │  │   pybind11 bridge to C++ engine      │  │
                          │  └─────────────┬───────────────────────┘  │
                          └────────────────┼──────────────────────────┘
                                           │
                          ┌────────────────▼──────────────────────────┐
                          │        C++ Engine (fastest_core.so)       │
                          │                                           │
                          │  • Header-only library in lib/            │
                          │  • Filtering-Sampling estimation          │
                          │  • Triangle & four-cycle safety filters   │
                          │  • Binary index: graph.bin, triangles.bin │
                          │  • OpenMP + TBB parallelism               │
                          └───────────────────────────────────────────┘
```

## Prerequisites

| Dependency       | Minimum Version | Notes                                      |
|------------------|-----------------|---------------------------------------------|
| **CMake**        | 3.21            | Build system for C++ targets                |
| **g++ / clang++**| C++20 support   | GCC 11+ or Clang 14+ recommended            |
| **Boost**        | 1.74            | `system`, `filesystem` components           |
| **GSL**          | 2.6             | GNU Scientific Library                      |
| **TBB**          | 2021.x          | Intel Threading Building Blocks             |
| **Python**       | 3.10+           | FastAPI backend and pybind11 bindings       |
| **pybind11**     | 2.11+           | `pip install pybind11` (for fastest_core.so)|
| **Node.js**      | 20+             | Vite frontend dev server and build          |
| **npm**          | 10+             | Comes with Node.js                          |

## Quick Start

```bash
# Clone and enter the project
git clone <repo-url> && cd GraphQuery

# Full setup (all 4 steps)
./run_dev.sh          # builds C++, installs deps, starts both servers
```

Or follow each step manually:

---

### Step 1: Build the C++ Core & Index Builder

```bash
# Install pybind11 first (needed for the Python module)
pip install pybind11

# Create the build directory and compile
mkdir -p build && cd build
cmake .. -Dpybind11_DIR=$(python3 -c "import pybind11; print(pybind11.get_cmake_dir())")
make -j$(nproc)
cd ..
```

This produces two artifacts:

| Target            | Location                       | Purpose                              |
|-------------------|-------------------------------|---------------------------------------|
| `Fastest`         | `build/Fastest`               | CLI for batch estimation & indexing   |
| `fastest_core.so` | `fastest_core.*.so` (project root) | Python-importable pybind11 module |

### Step 2: Build the Dataset Index

Before the web server can run estimation queries, each dataset needs a pre-built binary index.

```bash
# Build the index for the yeast dataset
./build/Fastest -d yeast --STRUCTURE 4
```

This reads `dataset/yeast/yeast.graph` and writes binary index files to `dataset/yeast/index/`:
- `graph.bin` — Compressed graph topology
- `triangles.bin` — Triangle safety index
- `four_cycles.bin` — Four-cycle safety index

Once the index exists, the web UI will show `index_status: ready` for that dataset.

**Available datasets**: Any directory under `dataset/` containing a `<name>.graph` file.

### Step 3: Run the Backend (FastAPI)

```bash
# Create a virtual environment (recommended)
python3 -m venv .venv && source .venv/bin/activate

# Install Python dependencies
pip install -r server/requirements.txt

# Launch the API server
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

The server will:
1. Scan `dataset/` for available datasets and their index status
2. Expose the REST + SSE API at `http://localhost:8000/api/`
3. Gracefully fall back to **mock estimation** if `fastest_core.so` is not built

**Key API endpoints:**

| Method | Endpoint                          | Description                        |
|--------|-----------------------------------|------------------------------------|
| GET    | `/api/health`                     | Health check                       |
| GET    | `/api/datasets`                   | List datasets with index status    |
| POST   | `/api/sessions`                   | Create evaluation session          |
| GET    | `/api/sessions/{id}/stream`       | SSE stream (75ms batched events)   |
| GET    | `/api/sessions/{id}/result`       | Final ranking result               |
| POST   | `/api/sessions/{id}/execute`      | Trigger downstream execution       |

### Step 4: Run the Frontend (React)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser. The Vite dev server proxies `/api/*` requests to the FastAPI backend on port 8000.

**Frontend workflow:**
1. Select a dataset from the sidebar (must have `index_status: ready`)
2. Build a query graph on the canvas (click "Add Vertex", drag between nodes to create edges, double-click to edit labels)
3. Click **"Submit Query"** to start a session
4. Watch real-time evaluation in the dashboard panel: progress bar, live leaderboard with animated rank changes, and two charts showing prefix depth vs. estimated cardinality and accumulated score
5. When completed, click **"Execute on Downstream Engine"**

---

## Project Structure

```
GraphQuery/
├── lib/                        # C++ header-only estimation library
├── driver/                     # C++ CLI entry point (Fastest binary)
├── pybind/                     # pybind11 wrapper (FastestPybind.cc)
├── dataset/                    # Graph datasets and index artifacts
│   └── yeast/
│       ├── yeast.graph         # Input graph
│       ├── yeast_ans.txt       # Ground truth cardinalities
│       └── index/              # Binary index (built in Step 2)
├── server/                     # FastAPI backend
│   ├── main.py                 # App entry point with CORS
│   ├── models.py               # Pydantic data models
│   ├── storage.py              # In-memory dataset & session store
│   ├── requirements.txt        # Python dependencies
│   ├── routes/
│   │   ├── datasets.py         # GET /api/datasets
│   │   └── sessions.py         # POST /api/sessions, SSE streaming
│   └── services/
│       ├── estimator_adapter.py  # Singleton C++ bridge (with mock fallback)
│       ├── order_generator.py    # DFS exact + beam search
│       ├── prefix_builder.py     # Prefix subgraph extraction
│       ├── query_validator.py    # Graph validation & normalization
│       ├── score_aggregator.py   # 75ms SSE batching & Top-K ranking
│       └── session_pipeline.py   # Async orchestrator
├── frontend/                   # React + TypeScript UI
│   ├── src/
│   │   ├── components/         # DatasetSelector, QueryGraphEditor, etc.
│   │   ├── hooks/              # useSessionStream (SSE consumer)
│   │   ├── lib/                # API client
│   │   └── types/              # TypeScript type definitions
│   ├── vite.config.ts          # Dev proxy to FastAPI
│   └── package.json
├── tests/                      # Python unit tests (31/31 passing)
├── CMakeLists.txt              # C++ build (Fastest + fastest_core.so)
├── run_dev.sh                  # One-command dev launcher
└── README.md                   # This file
```

## Testing

```bash
# Run all Python tests (backend + services)
python -m pytest tests/ -v

# Type-check the frontend
cd frontend && npx tsc --noEmit

# Production build
cd frontend && npm run build
```

## Input Format

Query graphs use the standard format:
```
t [#Vertex] [#Edge]
v [ID] [Label] [Degree]
e [Source] [Target] [EdgeLabel]
```

The web UI serializes graphs as JSON:
```json
{
  "vertices": [{"id": 0, "label": 2}, {"id": 1, "label": 5}],
  "edges": [{"source": 0, "target": 1, "label": 0}]
}
```

## Reference

**Cardinality Estimation of Subgraph Matching: A Filtering-Sampling Approach** (VLDB 2024)

Datasets and query graphs from [RapidMatch](https://github.com/RapidsAtHKUST/RapidMatch/).
