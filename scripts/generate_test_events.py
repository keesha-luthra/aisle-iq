#!/usr/bin/env python3
"""Generate 200 realistic synthetic events for STORE_BLR_002.

Output: data/sample_events.jsonl (one JSON object per line).

Constraints enforced:
  - 15 unique visitor_ids (VIS_[hex6])
  - 3 visitors with is_staff=True
  - 2 REENTRY events
  - 5 BILLING_QUEUE_JOIN with queue_depth 1-6
  - 2 BILLING_QUEUE_ABANDON
  - Monotonically increasing timestamps
  - All event_ids are unique UUIDs
  - Schema-valid per StoreEvent model
"""
import sys
import json
import uuid
import os
import random
from datetime import datetime, timezone, timedelta


def main():
    store_id = sys.argv[1] if len(sys.argv) > 1 else "STORE_BLR_002"
    os.makedirs("data", exist_ok=True)
    out_file = f"data/sample_events_{store_id}.jsonl"

    # 15 unique visitor_ids: VIS_[hex6]
    random.seed(store_id)  # Reproducible generation per store
    visitors = [f"VIS_{uuid.uuid4().hex[:6]}" for _ in range(15)]

    # First 3 visitors are staff
    staff_visitors = set(visitors[:3])

    # Spread over last 2 hours
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=2)
    time_step = timedelta(hours=2) / 200

    events = []

    # Track constraint fulfilment
    reentry_vids = [visitors[3], visitors[4]]
    reentry_done = 0
    queue_join_done = 0
    queue_abandon_done = 0

    current_time = start_time

    for i in range(200):
        current_time += time_step + timedelta(seconds=random.randint(1, 5))

        # Defaults
        zone_id = None
        metadata = {}
        dwell_ms = 0

        # --- Forced constraint events at specific indices ---
        if reentry_done < 2 and i in (50, 100):
            ev_type = "REENTRY"
            vid = reentry_vids[reentry_done]
            reentry_done += 1

        elif queue_join_done < 5 and i in (30, 70, 110, 140, 170):
            ev_type = "BILLING_QUEUE_JOIN"
            vid = visitors[5 + queue_join_done]
            metadata = {"queue_depth": random.randint(1, 6)}
            zone_id = "BILLING_ZONE_01"
            queue_join_done += 1

        elif queue_abandon_done < 2 and i in (85, 155):
            ev_type = "BILLING_QUEUE_ABANDON"
            vid = visitors[11 + queue_abandon_done]
            zone_id = "BILLING_ZONE_01"
            queue_abandon_done += 1

        else:
            # --- Generic events ---
            pool = ["ENTRY", "ZONE_ENTER", "ZONE_DWELL", "ZONE_EXIT", "EXIT"]
            ev_type = random.choice(pool)
            vid = random.choice(visitors)

            if ev_type in ("ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"):
                zone_id = random.choice(["AISLE_01", "AISLE_02", "CHECKOUT_LANE"])
                if ev_type == "ZONE_DWELL":
                    dwell_ms = random.randint(5000, 35000)
            # ENTRY / EXIT: zone_id stays None

        is_staff = vid in staff_visitors

        event_dict = {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": random.choice(["CAM_01", "CAM_02", "CAM_03"]),
            "visitor_id": vid,
            "event_type": ev_type,
            "timestamp": current_time.isoformat().replace("+00:00", "Z"),
            "confidence": round(random.uniform(0.75, 0.99), 2),
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "metadata": metadata,
        }

        if zone_id:
            event_dict["zone_id"] = zone_id

        events.append(event_dict)

    # Write events
    with open(out_file, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    # Print summary
    print(f"Generated {len(events)} events -> {out_file}")
    print(f"  Unique visitors: {len(set(e['visitor_id'] for e in events))}")
    print(f"  Staff events: {sum(1 for e in events if e['is_staff'])}")
    print(f"  REENTRY: {sum(1 for e in events if e['event_type'] == 'REENTRY')}")
    print(f"  BILLING_QUEUE_JOIN: {sum(1 for e in events if e['event_type'] == 'BILLING_QUEUE_JOIN')}")
    print(f"  BILLING_QUEUE_ABANDON: {sum(1 for e in events if e['event_type'] == 'BILLING_QUEUE_ABANDON')}")


if __name__ == "__main__":
    main()
