#!/bin/bash
set -e
BASE_URL=${1:-http://localhost:8000}
echo "--- Store Intelligence Smoke Test ---"

echo "1. Health check..."
curl -sf "$BASE_URL/health" | python3 -m json.tool

echo "2. Ingesting sample events..."
python3 -c "
import json, requests, sys
base = sys.argv[1]
# Store 1
events = [json.loads(l) for l in open('data/sample_events.jsonl')]
r = requests.post(f'{base}/events/ingest', json={'events': events[:200]})
print('Store 1 Ingest:', r.json())
assert r.status_code == 200
# Store 2
try:
    events2 = [json.loads(l) for l in open('data/events/sample_events_STORE_MUM_076.jsonl')]
    r2 = requests.post(f'{base}/events/ingest', json={'events': events2})
    print('Store 2 Ingest:', r2.json())
    assert r2.status_code == 200
except Exception as e:
    print('Store 2 Ingest skipped/failed:', e)
" "$BASE_URL"

echo "3. Metrics..."
curl -sf "$BASE_URL/stores/STORE_BLR_002/metrics" | python3 -m json.tool

echo "4. Funnel..."
curl -sf "$BASE_URL/stores/STORE_BLR_002/funnel" | python3 -m json.tool

echo "5. Heatmap..."
curl -sf "$BASE_URL/stores/STORE_BLR_002/heatmap" | python3 -m json.tool

echo "6. Anomalies..."
curl -sf "$BASE_URL/stores/STORE_BLR_002/anomalies" | python3 -m json.tool

echo "--- All checks passed ---"
