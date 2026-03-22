#!/bin/bash
conda run -n fastest uvicorn server.main:app --host 0.0.0.0 --port 8000 &
PID=$!
sleep 3
# Test endpoints
curl -s http://127.0.0.1:8000/api/health
echo ""
curl -s http://127.0.0.1:8000/api/datasets
echo ""
kill $PID
