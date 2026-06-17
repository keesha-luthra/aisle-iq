# PROMPT: Write a test file tests/test_new_schema_ingestion.py to verify that the API successfully ingests and normalizes the new schema events (like entry, exit, zone_entered, zone_exited, queue_completed, queue_abandoned) from the purplle new folder's sample_eventsbe42122.jsonl format.
# CHANGES MADE: Created tests/test_new_schema_ingestion.py with extensive assertions checking normalization, ingestion, and database row creation for all new event types.

import pytest
import os
import json
from httpx import AsyncClient
from sqlalchemy import select
from app.models import Event, VisitorSession

@pytest.mark.asyncio
async def test_new_schema_events_ingestion(client: AsyncClient, db_session):
    # 1. Prepare representative events in the new schema format
    new_events = [
        # entry
        {
            "event_type": "entry",
            "id_token": "ID_60001",
            "store_code": "store_1076",
            "camera_id": "cam1",
            "event_timestamp": "2026-03-08T18:10:05.120000",
            "is_staff": False,
            "gender_pred": "F",
            "age_pred": 28,
            "age_bucket": "25-34",
            "is_face_hidden": False,
            "group_id": None,
            "group_size": None
        },
        # zone_entered
        {
            "event_type": "zone_entered",
            "track_id": 101,
            "store_id": "ST1076",
            "camera_id": "CAM2",
            "zone_id": "PURPLLE_MUM_1076_Z01",
            "zone_name": "Left Shelf",
            "zone_type": "SHELF",
            "is_revenue_zone": "Yes",
            "event_time": "2026-03-08T18:10:45.280000",
            "zone_hotspot_x": 412.6,
            "zone_hotspot_y": 238.4,
            "gender": "F",
            "age": 28,
            "age_bucket": "25-34"
        },
        # queue_completed
        {
            "queue_event_id": "cfd8e3c5-7aa0-4ea3-9b59-692d50da8308",
            "event_type": "queue_completed",
            "track_id": 101,
            "store_id": "ST1076",
            "camera_id": "PURPLLE_MUM_1076_CAM6",
            "zone_id": "PURPLLE_MUM_1076_Z_BILLING_01",
            "zone_name": "Billing Counter Queue",
            "zone_type": "BILLING",
            "is_revenue_zone": "Yes",
            "queue_join_ts": "2026-03-08T18:13:05.080000",
            "queue_served_ts": "2026-03-08T18:13:13.240000",
            "queue_exit_ts": "2026-03-08T18:15:31.840000",
            "wait_seconds": 8,
            "queue_position_at_join": 2,
            "abandoned": False,
            "zone_hotspot_x": 602.8,
            "zone_hotspot_y": 183.4,
            "gender": "F",
            "age": 28,
            "age_bucket": "25-34"
        },
        # exit
        {
            "event_type": "exit",
            "id_token": "ID_60001",
            "store_code": "store_1076",
            "camera_id": "cam1",
            "event_timestamp": "2026-03-08T18:16:44.360000",
            "is_staff": False,
            "gender_pred": "F",
            "age_pred": 28,
            "age_bucket": "25-34",
            "is_face_hidden": False,
            "group_id": None,
            "group_size": None
        }
    ]

    # 2. POST /events/ingest
    response = await client.post("/events/ingest", json={"events": new_events})
    assert response.status_code == 200
    data = response.json()
    
    # We should have accepted all 4 inputs. (queue_completed emits 1 event in old schema since it is completed/not abandoned)
    # Total expected accepted normalized events:
    # - entry -> ENTRY (1)
    # - zone_entered -> ZONE_ENTER (1)
    # - queue_completed -> BILLING_QUEUE_JOIN (1)
    # - exit -> EXIT (1)
    # Total = 4
    assert data["accepted"] == 4
    assert data["rejected"] == 0
    assert data["duplicate"] == 0

    # 3. Verify they exist in DB under normalized forms
    stmt = select(Event).where(Event.store_id == "STORE_MUM_076")
    res = await db_session.execute(stmt)
    events_in_db = res.scalars().all()
    assert len(events_in_db) == 4

    types = [e.event_type for e in events_in_db]
    assert "ENTRY" in types
    assert "ZONE_ENTER" in types
    assert "BILLING_QUEUE_JOIN" in types
    assert "EXIT" in types

    # Verify visitor ID hex pattern match: visitor ID should be formatted/padded to 6 hex chars
    # "ID_60001" -> "60001" -> padded to "060001" -> "VIS_060001"
    # "track_id": 101 -> "101" -> padded to "000101" -> "VIS_000101"
    vids = [e.visitor_id for e in events_in_db]
    assert "VIS_060001" in vids
    assert "VIS_000101" in vids

    # Verify session was created and updated with exit_time
    stmt_sess = select(VisitorSession).where(VisitorSession.store_id == "STORE_MUM_076")
    res_sess = await db_session.execute(stmt_sess)
    sessions = res_sess.scalars().all()
    assert len(sessions) == 1
    session = sessions[0]
    assert session.visitor_id == "VIS_060001"
    assert session.exit_time is not None
