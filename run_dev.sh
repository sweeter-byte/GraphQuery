#!/usr/bin/env bash
# run_dev.sh — One-command launcher for GraphQuery development
# Starts both the FastAPI backend and Vite frontend dev server.
# Press Ctrl+C to gracefully shut down both.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
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
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Installing Python dependencies..."
    pip install -r "$ROOT_DIR/server/requirements.txt" -q
fi

# ── Step 3: Install frontend deps if needed ──
if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    (cd "$ROOT_DIR/frontend" && npm install --silent)
fi

# ── Step 4: Start backend ──
echo "Starting FastAPI backend on http://localhost:8000 ..."
(cd "$ROOT_DIR" && uvicorn server.main:app --reload --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!

# Give the backend a moment to start
sleep 2

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
