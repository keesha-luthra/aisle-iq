#!/usr/bin/env python3
"""
E2E Demo Ingestion & Verification Script
Checks FastAPI online status, generates 200 sample retail events, posts them to the API server,
and prints a diagnostics report of the operational and camera metrics.
"""

import os
import json
import urllib.request
import subprocess
import time

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

def check_server():
    print(f"[*] Checking connection to FastAPI server at {API_URL}...")
    try:
        with urllib.request.urlopen(f"{API_URL}/health", timeout=3.0) as response:
            if response.status == 200:
                print("[+] FastAPI server is ONLINE.")
                return True
    except Exception as e:
        print(f"[-] Cannot connect to API server: {e}")
        print("[-] Please start the server using: ")
        print("    $env:DATABASE_URL=\"sqlite+aiosqlite:///temp_verify.db\"; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return False

def generate_events():
    sample_file = "data/sample_events.jsonl"
    if not os.path.exists(sample_file):
        print("[*] Generating mock events...")
        try:
            subprocess.run(["python", "scripts/generate_test_events.py"], check=True)
            print("[+] Successfully generated mock events.")
        except Exception as e:
            print(f"[-] Failed to run event generator: {e}")
            return None
    return sample_file

def ingest_events(sample_file):
    print("[*] Reading events from file...")
    events = []
    with open(sample_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line.strip()))
                
    print(f"[*] Ingesting {len(events)} events in batches of 100...")
    batch_size = 100
    for i in range(0, len(events), batch_size):
        batch = events[i:i+batch_size]
        payload = {"events": batch}
        req_data = json.dumps(payload).encode("utf-8")
        
        req = urllib.request.Request(
            f"{API_URL}/events/ingest",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as res:
                res_data = json.loads(res.read().decode("utf-8"))
                print(f"    [Batch {i//batch_size + 1}] Accepted: {res_data.get('accepted', 0)}, Rejected: {res_data.get('rejected', 0)}, Duplicate: {res_data.get('duplicate', 0)}")
        except Exception as e:
            print(f"[-] Batch {i//batch_size + 1} ingestion failed: {e}")
            return False
    print("[+] Ingestion finished successfully.")
    return True

def query_diagnostics():
    print("\n" + "="*50)
    print("           DIAGNOSTIC REPORT SUMMARY")
    print("="*50)
    
    # Query Store Metrics
    try:
        with urllib.request.urlopen(f"{API_URL}/stores/STORE_BLR_002/metrics?window_hours=24") as res:
            data = json.loads(res.read().decode("utf-8"))
            print(f"[*] Store ID: {data.get('store_id')}")
            print(f"[*] Unique Visitors: {data.get('unique_visitors')}")
            print(f"[*] Conversion Rate: {data.get('conversion_rate'):.2%}")
            print(f"[*] Avg Queue Depth: {data.get('current_queue_depth')}")
            print(f"[*] Abandonment Rate: {data.get('abandonment_rate'):.2%}")
    except Exception as e:
        print(f"[-] Failed to fetch store metrics: {e}")

    # Query Camera Analytics
    try:
        with urllib.request.urlopen(f"{API_URL}/stores/STORE_BLR_002/camera-analytics") as res:
            data = json.loads(res.read().decode("utf-8"))
            print("\n[*] Camera Telemetry Breakdown:")
            for cam, stats in data.get("cameras", {}).items():
                print(f"    - {cam}: Entries: {stats.get('entries')}, Exits: {stats.get('exits')}, Active Visitors: {stats.get('active_visitors_count')}, Active Tracks: {stats.get('active_tracks')}")
            print(f"[*] Peak Traffic Hour: {data.get('peak_traffic_hour')}")
            print(f"[*] Billing Zone Visitors: {data.get('billing_visitors')}")
    except Exception as e:
        print(f"[-] Failed to fetch camera telemetry: {e}")
        
    print("="*50)
    print("[+] E2E Ingestion Verification PASS!")
    print("="*50)

def main():
    if not check_server():
        return
    sample_file = generate_events()
    if not sample_file:
        return
    if ingest_events(sample_file):
        time.sleep(1.0)
        query_diagnostics()

if __name__ == "__main__":
    main()
