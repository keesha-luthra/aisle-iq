import glob
import json
import requests
import sys

def ingest_all():
    files = glob.glob('data/events/*.jsonl')
    api_url = "http://127.0.0.1:8000"
    all_events = []
    
    for f in files:
        with open(f, 'r') as file:
            for line in file:
                if line.strip():
                    all_events.append(json.loads(line))
                    
    print(f"Loaded {len(all_events)} events.")
    
    BATCH_SIZE = 200
    total_accepted = 0
    total_rejected = 0
    for i in range(0, len(all_events), BATCH_SIZE):
        batch = all_events[i:i+BATCH_SIZE]
        resp = requests.post(f"{api_url}/events/ingest", json={"events": batch})
        if resp.status_code == 200:
            data = resp.json()
            total_accepted += data.get('accepted', 0)
            total_rejected += data.get('rejected', 0)
            print(f"Batch {i//BATCH_SIZE + 1} accepted: {data.get('accepted', 0)}, rejected: {data.get('rejected', 0)}")
        else:
            print(f"Batch {i//BATCH_SIZE + 1} error: {resp.status_code} {resp.text}")

if __name__ == '__main__':
    ingest_all()
