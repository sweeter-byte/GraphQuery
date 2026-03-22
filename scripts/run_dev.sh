#!/usr/bin/env bash
# run_dev.sh — One-command launcher for GraphQuery development
# Starts both the FastAPI backend and Vite frontend dev server.
# Press Ctrl+C to gracefully shut down both.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo "Shutting down..."
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo "  Stopped frontend (PID $FRONTEND_PID)"
    [ -n "$BACKEND_PID" ]  && kill "$BACKEND_PID"  2>/dev/null && echo "  Stopped backend  (PID $BACKEND_PID)"
    wait 2>/dev/null
    echo "Done."
}

trap cleanup EXIT INT TERM

# ── Step 1: Check C++ module ──
if ! python3 -c "import fastest_core" 2>/dev/null; then
    echo "⚠  fastest_core.so not found. The server will run in mock estimation mode."
    echo "   To build it: mkdir -p build && cd build && cmake .. -Dpybind11_DIR=\$(python3 -c 'import pybind11; print(pybind11.get_cmake_dir())') && make -j\$(nproc)"
    echo ""
fi

# ── Step 2: Install Python deps if needed ──
CONDA_ENV="fastest"
if ! conda info --envs | grep -q "^$CONDA_ENV "; then
    echo "Creating Conda environment '$CONDA_ENV'..."
    conda create -n "$CONDA_ENV" python=3.10 -y
fi

echo "Activating '$CONDA_ENV' and installing Python dependencies..."
conda run -n "$CONDA_ENV" python -m pip install -r "$ROOT_DIR/server/requirements.txt" -q

# ── Step 3: Install frontend deps if needed ──
if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    (cd "$ROOT_DIR/frontend" && npm install --silent)
fi

# ── Step 4: Start backend ──
# Kill any leftover processes on port 8000 from previous runs
if command -v fuser &>/dev/null; then
    fuser -k 8000/tcp 2>/dev/null || true
elif command -v ss &>/dev/null; then
    STALE_PIDS=$(ss -lptn 'sport = :8000' | grep -oP 'pid=\K[0-9]+' | sort -u)
    for pid in $STALE_PIDS; do
        kill -9 "$pid" 2>/dev/null || true
    done
fi
sleep 1

echo "Starting FastAPI backend on http://localhost:8000 ..."
(cd "$ROOT_DIR" && conda run -n "$CONDA_ENV" uvicorn server.main:app --reload --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!

# Give the backend enough time to start (conda activation takes a moment)
sleep 4

# ── Step 5: Start frontend ──
echo "Starting Vite dev server on http://localhost:5173 ..."
(cd "$ROOT_DIR/frontend" && npm run dev -- --host 0.0.0.0) &
FRONTEND_PID=$!

echo ""
echo "════════════════════════════════════════════════════"
echo "  GraphQuery is running!"
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"
echo "════════════════════════════════════════════════════"
echo "  Press Ctrl+C to stop both servers."
echo ""

# Wait for either process to exit
wait
