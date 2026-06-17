#!/usr/bin/env python3
"""
run_pipeline_and_ingest.py
--------------------------
Runs the YOLOv8 CV pipeline on all video clips in data/clips/ and
posts the resulting events to the FastAPI /events/ingest endpoint.

Usage (from store-intelligence/ directory):
    python scripts/run_pipeline_and_ingest.py

Options:
    --clips-dir       Path to clips directory (default: data/clips)
    --store-id        Store ID override (default: STORE_BLR_002)
    --api-url         FastAPI URL (default: http://127.0.0.1:8000)
    --fps-process     Frames per second to process (default: 3)
    --device          'cuda' or 'cpu' (auto-detected)
    --no-ingest       Only run pipeline, don't POST to API
"""
import argparse
import json
import os
import sys
import time
import uuid
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set up minimal environment for the app config to load
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///temp_verify.db")


def parse_args():
    p = argparse.ArgumentParser(description="Run CV pipeline and ingest events")
    p.add_argument("--clips-dir", default="data/clips")
    p.add_argument("--store-id", default="STORE_BLR_002")
    p.add_argument("--layout-path", default="data/store_layout_STORE_BLR_002.json")
    p.add_argument("--api-url", default="http://127.0.0.1:8000")
    p.add_argument("--fps-process", type=int, default=3)
    p.add_argument("--device", default=None)
    p.add_argument("--no-ingest", action="store_true", help="Skip API ingestion")
    p.add_argument("--output-dir", default="data/events")
    p.add_argument("--annotate", action="store_true",
                   help="Generate annotated output videos with bounding boxes and global IDs")
    p.add_argument("--annotated-dir", default="data/annotated",
                   help="Directory for annotated output videos (default: data/annotated)")
    return p.parse_args()


def ingest_events_to_api(events: list, api_url: str, store_id: str) -> dict:
    """POST events in batches of 200 to /events/ingest."""
    BATCH_SIZE = 200
    total_accepted = 0
    total_rejected = 0
    total_errors = 0

    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i : i + BATCH_SIZE]
        try:
            resp = requests.post(
                f"{api_url}/events/ingest",
                json={"events": batch},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                total_accepted += data.get("accepted", 0)
                total_rejected += data.get("rejected", 0)
            else:
                print(f"  [WARN] Batch {i//BATCH_SIZE + 1} returned HTTP {resp.status_code}: {resp.text[:200]}")
                total_errors += len(batch)
        except Exception as e:
            print(f"  [ERROR] Batch {i//BATCH_SIZE + 1} failed: {e}")
            total_errors += len(batch)

    return {"accepted": total_accepted, "rejected": total_rejected, "errors": total_errors}


def event_to_api_format(event: dict) -> dict:
    """
    Converts pipeline event dict to the API IngestRequest event format.
    Pipeline output keys → API schema keys.
    """
    ts = event.get("timestamp")
    if isinstance(ts, datetime):
        ts = ts.isoformat().replace("+00:00", "Z")
    elif ts is None:
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    metadata = event.get("metadata", {}) or {}

    # Flatten reid_meta into metadata if present
    reid_meta = event.get("reid_meta", {})
    if reid_meta:
        metadata.update(reid_meta)

    return {
        "event_id": event.get("event_id", str(uuid.uuid4())),
        "store_id": event.get("store_id", "STORE_BLR_002"),
        "camera_id": event.get("camera_id", "CAM_UNKNOWN"),
        "visitor_id": event.get("visitor_id", "VIS_UNKNOWN"),
        "event_type": event.get("event_type", "ZONE_ENTER"),
        "timestamp": ts,
        "confidence": float(event.get("confidence", 0.80)),
        "dwell_ms": int(event.get("dwell_ms", 0)),
        "is_staff": bool(event.get("is_staff", False)),
        "zone_id": event.get("zone_id") or None,
        "metadata": metadata,
    }


def main():
    args = parse_args()

    clips_dir = Path(args.clips_dir)
    layout_path = Path(args.layout_path)
    output_dir = Path(args.output_dir)

    print("=" * 60)
    print("  Store Intelligence CV Pipeline Runner")
    print("=" * 60)
    print(f"  Clips dir   : {clips_dir.resolve()}")
    print(f"  Store ID    : {args.store_id}")
    print(f"  Layout      : {layout_path.resolve()}")
    print(f"  API URL     : {args.api_url}")
    print(f"  FPS process : {args.fps_process}")
    print(f"  Ingest      : {'YES' if not args.no_ingest else 'NO (--no-ingest)'}")
    print(f"  Annotate    : {'YES -> ' + args.annotated_dir + '/{store_id}/' if args.annotate else 'NO'}")
    print("=" * 60)

    if not clips_dir.exists():
        print(f"[ERROR] clips-dir does not exist: {clips_dir.resolve()}")
        sys.exit(1)

    if not layout_path.exists():
        # Try generic fallback
        fallback = Path("data/store_layout.json")
        if fallback.exists():
            layout_path = fallback
            print(f"[WARN] Layout override not found, using fallback: {fallback}")
        else:
            print(f"[ERROR] store layout not found: {layout_path.resolve()}")
            sys.exit(1)

    # Check API connectivity (warn but don't abort)
    if not args.no_ingest:
        try:
            r = requests.get(f"{args.api_url}/health", timeout=5)
            if r.status_code == 200:
                print(f"[OK] API is reachable at {args.api_url}")
            else:
                print(f"[WARN] API returned {r.status_code}. Continuing anyway...")
        except Exception as e:
            print(f"[WARN] Cannot reach API at {args.api_url}: {e}")
            print("       Events will still be written to disk. Skipping ingest.")
            args.no_ingest = True

    # Import the pipeline (heavy imports — done after arg validation)
    print("\n[1/3] Loading CV pipeline (YOLOv8 + ReID)...")
    try:
        from pipeline.detect import VideoProcessor
    except ImportError as e:
        print(f"[ERROR] Cannot import pipeline: {e}")
        print("        Make sure you run this from the store-intelligence/ directory")
        sys.exit(1)

    processor = VideoProcessor(
        store_layout_path=str(layout_path),
        store_id=args.store_id,
        fps_process=args.fps_process,
        device=args.device,
    )

    # Find video clips
    video_files = sorted(clips_dir.glob("*.mp4")) + sorted(clips_dir.glob("*.avi"))
    if not video_files:
        print(f"[ERROR] No video files found in {clips_dir.resolve()}")
        sys.exit(1)

    print(f"\n[2/3] Processing {len(video_files)} clip(s)...")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_api_events = []
    total_start = time.time()

    for clip_path in video_files:
        # Infer camera ID from filename
        name_lower = clip_path.name.lower()
        if "cam 1" in name_lower or "cam_01" in name_lower or "cam1" in name_lower:
            camera_id = "CAM_01"
        elif "cam 2" in name_lower or "cam_02" in name_lower or "cam2" in name_lower:
            camera_id = "CAM_02"
        elif "cam 3" in name_lower or "cam_03" in name_lower or "cam3" in name_lower:
            camera_id = "CAM_03"
        elif "cam 5" in name_lower or "cam_05" in name_lower or "cam5" in name_lower:
            camera_id = "CAM_05"
        elif "entry" in name_lower:
            camera_id = "CAM_03"
        elif "billing" in name_lower:
            camera_id = "CAM_05"
        elif "zone" in name_lower:
            camera_id = "CAM_01"
        else:
            camera_id = "CAM_01"

        print(f"\n  → {clip_path.name}  [{camera_id}]")
        clip_start = time.time()

        # Build annotated output path if requested
        annotated_path = None
        if args.annotate:
            ann_dir = Path(args.annotated_dir) / args.store_id
            ann_dir.mkdir(parents=True, exist_ok=True)
            annotated_path = str(ann_dir / f"{camera_id}.mp4")
            print(f"     Annotated output : {annotated_path}")

        try:
            raw_events = processor.process_clip(
                str(clip_path), camera_id,
                annotated_output_path=annotated_path,
            )
        except Exception as e:
            print(f"  [ERROR] Failed to process {clip_path.name}: {e}")
            continue

        # Convert events to API format
        api_events = [event_to_api_format(ev) for ev in raw_events]
        all_api_events.extend(api_events)

        # Write per-camera JSONL
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = output_dir / f"{camera_id}_{ts_str}.jsonl"
        with open(out_file, "w", encoding="utf-8") as f:
            for ev in api_events:
                f.write(json.dumps(ev) + "\n")

        elapsed = time.time() - clip_start
        print(f"     Events generated : {len(api_events)}")
        print(f"     Saved to         : {out_file}")
        if annotated_path and Path(annotated_path).exists():
            size_mb = Path(annotated_path).stat().st_size / (1024 * 1024)
            print(f"     Annotated video  : {annotated_path} ({size_mb:.1f} MB)")
        print(f"     Time             : {elapsed:.1f}s")

    total_elapsed = time.time() - total_start
    print(f"\n  Total events across all clips: {len(all_api_events)}")
    print(f"  Total processing time       : {total_elapsed:.1f}s")

    # Ingest to API
    if not args.no_ingest and all_api_events:
        print(f"\n[3/3] Ingesting {len(all_api_events)} events to API...")
        result = ingest_events_to_api(all_api_events, args.api_url, args.store_id)
        print(f"  Accepted : {result['accepted']}")
        print(f"  Rejected : {result['rejected']}")
        print(f"  Errors   : {result['errors']}")

        # Show resulting metrics
        try:
            r = requests.get(
                f"{args.api_url}/stores/{args.store_id}/metrics?window_hours=24",
                timeout=10,
            )
            if r.status_code == 200:
                m = r.json()
                print(f"\n  ✅ Dashboard Metrics (post-ingest):")
                print(f"     Unique Visitors  : {m.get('unique_visitors', 0)}")
                print(f"     Queue Depth      : {m.get('current_queue_depth', 0)}")
                print(f"     Abandonment Rate : {m.get('abandonment_rate', 0):.1%}")
        except Exception:
            pass
    elif not all_api_events:
        print("\n[WARN] No events were generated from any clips.")

    print("\n✅ Pipeline run complete.")
    print("   Open http://localhost to see the live frontend.\n")


if __name__ == "__main__":
    main()
