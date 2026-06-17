#!/usr/bin/env python3
"""
validate_and_compile_events.py
------------------------------
Reads all generated JSONL event files in data/events/, validates every event
against the API's Pydantic StoreEvent schema, and compiles them into a single
consolidated 'events.jsonl' file.
"""
import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Any

# Ensure project root is on path to allow importing app modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set up minimal environment for the app config to load
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///temp_verify.db")

from app.schemas import StoreEvent
from pydantic import ValidationError

def main():
    events_dir = PROJECT_ROOT / "data" / "events"
    output_file_project = PROJECT_ROOT / "events.jsonl"
    output_file_root = PROJECT_ROOT.parent / "events.jsonl"

    print("=" * 65)
    print("  Store Intelligence Event Validation & Compilation Tool")
    print("=" * 65)
    print(f"  Source directory : {events_dir}")
    print(f"  Project output   : {output_file_project}")
    print(f"  Workspace output : {output_file_root}")
    print("=" * 65)

    if not events_dir.exists():
        print(f"[ERROR] Source events directory does not exist: {events_dir}")
        sys.exit(1)

    # Gather JSONL files, excluding samples
    jsonl_files = sorted([
        f for f in events_dir.glob("*.jsonl")
        if f.name not in ("sample_events.jsonl", "store2_sample_events.jsonl")
    ])

    if not jsonl_files:
        print("[WARN] No event log files found in the source directory.")
        sys.exit(0)

    print(f"Found {len(jsonl_files)} file(s) to validate:")
    for f in jsonl_files:
        print(f"  - {f.name} ({f.stat().st_size} bytes)")

    total_lines = 0
    valid_events_count = 0
    validation_failures = 0
    errors = []
    
    event_types_count = {}
    unique_visitors = set()
    staff_events_count = 0

    compiled_events: List[Dict[str, Any]] = []

    for file_path in jsonl_files:
        print(f"\nProcessing {file_path.name}...")
        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                
                try:
                    event_dict = json.loads(line)
                except json.JSONDecodeError as je:
                    validation_failures += 1
                    err_msg = f"{file_path.name}:L{line_no} - JSON decode error: {je}"
                    errors.append(err_msg)
                    print(f"  [JSON ERROR] {err_msg}")
                    continue

                try:
                    # Validate against Pydantic schema
                    validated_event = StoreEvent.model_validate(event_dict)
                    valid_events_count += 1
                    
                    # Track statistics
                    etype = validated_event.event_type.value
                    event_types_count[etype] = event_types_count.get(etype, 0) + 1
                    unique_visitors.add(validated_event.visitor_id)
                    if validated_event.is_staff:
                        staff_events_count += 1

                    # Add event dict (dumped back in JSON mode to format dates/UUIDs properly)
                    compiled_events.append(validated_event.model_dump(mode="json"))

                except ValidationError as ve:
                    validation_failures += 1
                    err_msg = f"{file_path.name}:L{line_no} - Schema error: {ve.errors()[0]['msg']} (field: {'.'.join(str(p) for p in ve.errors()[0]['loc'])})"
                    errors.append(err_msg)
                    print(f"  [SCHEMA ERROR] {err_msg}")

    # Back-propagate staff status: if a visitor is classified as staff in any event,
    # mark all their events in this session as is_staff=True.
    staff_visitor_ids = {e["visitor_id"] for e in compiled_events if e["is_staff"]}
    if staff_visitor_ids:
        for e in compiled_events:
            if e["visitor_id"] in staff_visitor_ids:
                e["is_staff"] = True
        # Recalculate staff events count for validation summary
        staff_events_count = sum(1 for e in compiled_events if e["is_staff"])

    print("\n" + "=" * 65)
    print("  Validation Results Summary")
    print("=" * 65)
    print(f"  Total Lines Read          : {total_lines}")
    print(f"  Valid Events              : {valid_events_count}")
    print(f"  Validation Failures       : {validation_failures}")
    print(f"  Unique Visitors Tracked   : {len(unique_visitors)}")
    print(f"  Staff Events Flagged      : {staff_events_count} ({staff_events_count / max(1, valid_events_count):.1%})")
    
    print("\n  Event Type Counts:")
    for etype, count in sorted(event_types_count.items()):
         print(f"    - {etype:25}: {count}")

    if validation_failures > 0:
        print("\n[FAIL] Validation encountered errors! Output file will not be written.")
        print(f"Total Errors: {len(errors)}")
        sys.exit(1)
    else:
        print("\n[OK] Validation passed successfully! Writing consolidated event logs...")
        
        # Write to project root
        with open(output_file_project, "w", encoding="utf-8") as out:
            for ev in compiled_events:
                out.write(json.dumps(ev) + "\n")
        print(f"  Wrote project events file: {output_file_project}")

        # Write to workspace root
        with open(output_file_root, "w", encoding="utf-8") as out:
            for ev in compiled_events:
                out.write(json.dumps(ev) + "\n")
        print(f"  Wrote workspace events file: {output_file_root}")
        
        print("\n[SUCCESS] Events compiled successfully.")
        sys.exit(0)

if __name__ == "__main__":
    main()
