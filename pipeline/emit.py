import argparse
import json
import os
import time
import httpx
import sys
from typing import List, Dict, Any
from pydantic import ValidationError

# Add the workspace root to sys.path to allow importing app modules if run from pipeline/ dir
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import StoreEvent

def parse_args():
    parser = argparse.ArgumentParser(description="Emit validated event logs in batches to Store Intelligence API")
    parser.add_argument(
        "--events-dir",
        type=str,
        default="./data/events",
        help="Directory containing JSONL event log files"
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
        help="Base URL of the Store Intelligence API"
    )
    return parser.parse_args()

def send_batch_with_retry(client: httpx.Client, endpoint: str, batch: List[Dict[str, Any]], max_retries: int = 3) -> Dict[str, Any] | None:
    """
    Sends a batch of events to the ingestion endpoint.
    Retries on connection errors or HTTP 5xx responses up to `max_retries` times with exponential backoff.
    """
    payload = {"events": batch}
    backoff = 1.0  # initial sleep in seconds

    for attempt in range(max_retries + 1):
        try:
            response = client.post(endpoint, json=payload, timeout=10.0)
            
            # If 5xx, raise for status to trigger retry logic
            if 500 <= response.status_code < 600:
                response.raise_for_status()
                
            # If successful or 4xx (non-retryable client error), return response JSON
            return response.json()
            
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            if attempt < max_retries:
                print(f"[Warning] Ingestion POST failed (Attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {backoff}s...")
                time.sleep(backoff)
                backoff *= 2.0
            else:
                print(f"[Error] Ingestion POST failed after {max_retries + 1} attempts: {e}")
                return None

def emit_events(events_dir: str, api_url: str):
    """
    Reads all JSONL files, validates schemas, batches by 500, sends with retry logic.
    """
    endpoint = f"{api_url.rstrip('/')}/events/ingest"
    print(f"Emitting events from '{events_dir}' to '{endpoint}'...")
    
    if not os.path.exists(events_dir):
        print(f"Error: Directory '{events_dir}' does not exist.")
        return

    jsonl_files = [f for f in os.listdir(events_dir) if f.endswith(".jsonl")]
    if not jsonl_files:
        print("No event log files (.jsonl) found.")
        return

    # Tracking counters
    total_files = len(jsonl_files)
    total_lines = 0
    pydantic_rejected = 0
    api_accepted = 0
    api_rejected = 0
    api_duplicate = 0
    transmission_failed = 0

    batch = []
    
    with httpx.Client() as client:
        for file_name in jsonl_files:
            file_path = os.path.join(events_dir, file_name)
            
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    total_lines += 1
                    try:
                        event_data = json.loads(line)
                        # Validate event schema
                        try:
                            store_event = StoreEvent(**event_data)
                            # Dump as JSON-compatible dict (UUID -> str, datetime -> ISO string)
                            batch.append(store_event.model_dump(mode="json"))
                        except ValidationError as ve:
                            # If it's the new schema format, allow it to bypass client-side validation and let the API normalize it
                            new_schema_types = ("entry", "exit", "zone_entered", "zone_exited", "queue_completed", "queue_abandoned")
                            if "event_type" in event_data and event_data["event_type"] in new_schema_types:
                                batch.append(event_data)
                            elif "queue_event_id" in event_data:  # queue_completed/abandoned might only have event_type inside or be recognized by queue_event_id
                                batch.append(event_data)
                            else:
                                raise ve
                    except (json.JSONDecodeError, ValidationError) as e:
                        pydantic_rejected += 1
                        print(f"[Validation Error] Skipped invalid event in {file_name}: {e}")
                        continue
                    
                    # Send when batch reaches 500 events
                    if len(batch) == 500:
                        res = send_batch_with_retry(client, endpoint, batch)
                        if res:
                            api_accepted += res.get("accepted", 0)
                            api_rejected += res.get("rejected", 0)
                            api_duplicate += res.get("duplicate", 0)
                            if res.get("errors"):
                                print(f"[API Error Details] {res.get('errors')}")
                        else:
                            transmission_failed += len(batch)
                        batch = []

        # Send any remaining events
        if batch:
            res = send_batch_with_retry(client, endpoint, batch)
            if res:
                api_accepted += res.get("accepted", 0)
                api_rejected += res.get("rejected", 0)
                api_duplicate += res.get("duplicate", 0)
                if res.get("errors"):
                    print(f"[API Error Details] {res.get('errors')}")
            else:
                transmission_failed += len(batch)

    # Print ingestion summary
    print("\n=== Event Emitter Ingestion Summary ===")
    print(f"Total Files Scanned      : {total_files}")
    print(f"Total Lines Processed    : {total_lines}")
    print(f"Schema Validation Failures: {pydantic_rejected}")
    print(f"API Accepted Events      : {api_accepted}")
    print(f"API Rejected Events      : {api_rejected}")
    print(f"API Duplicate Events     : {api_duplicate}")
    print(f"Transmission Failed Events: {transmission_failed}")
    print("=======================================")

if __name__ == "__main__":
    args = parse_args()
    emit_events(args.events_dir, args.api_url)
