#!/bin/bash
# run.sh — One-command startup for Store Intelligence
# Usage: bash run.sh

set -e

echo "=== Store Intelligence — Starting ==="

# 1. Build and start all containers
echo "[1/4] Building and starting Docker containers..."
docker compose up -d --build

# 2. Wait for API to be healthy
echo "[2/4] Waiting for API to become healthy..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "  API is healthy."
        break
    fi
    if [ $i -eq 30 ]; then
        echo "  ERROR: API did not become healthy in 30 seconds."
        docker compose logs api
        exit 1
    fi
    sleep 1
done

# 3. Generate and ingest sample data
echo "[3/4] Generating and ingesting sample events..."
python3 scripts/generate_test_events.py
bash scripts/smoke_test.sh

# 4. Report URLs
echo ""
echo "=== Store Intelligence — Ready ==="
echo "  API:       http://localhost:8000"
echo "  Swagger:   http://localhost:8000/docs"
echo "  Frontend:  http://localhost:80"
echo "========================================"
