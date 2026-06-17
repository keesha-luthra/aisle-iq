# PROMPT: Write test suite tests/test_reid_global.py verifying GlobalIdentityService registration, local collision prevention, homography speed checks, staff exclusion, and ingestion persistence.
# CHANGES MADE: Created tests/test_reid_global.py with tests covering the global tracker and metadata ingestion.

import pytest
import numpy as np
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.future import select
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from pipeline.global_id import GlobalIdentityService
from app.models import GlobalVisitorMatch, Event
from app.schemas import StoreEvent

@pytest.fixture
def store_layout_temp(tmp_path):
    import json
    layout_data = {
        "store_id": "STORE_BLR_002",
        "cameras": {
            "CAM_01": {
                "homography_src_points": [[0,0], [1920,0], [1920,1080], [0,1080]],
                "homography_dst_points": [[3000,0], [7000,0], [7000,2000], [3000,2000]]
            },
            "CAM_02": {
                "homography_src_points": [[0,0], [1920,0], [1920,1080], [0,1080]],
                "homography_dst_points": [[500,2000], [4500,2000], [4500,4000], [500,4000]]
            }
        }
    }
    layout_file = tmp_path / "store_layout.json"
    with open(layout_file, "w", encoding="utf-8") as f:
        json.dump(layout_data, f)
    return str(layout_file)

def test_global_identity_service_init(store_layout_temp):
    service = GlobalIdentityService(store_layout_path=store_layout_temp, reid_threshold=0.75, reentry_window_seconds=60)
    assert service.reid_threshold == 0.75
    assert service.reentry_window_seconds == 60
    assert len(service.homography) == 2
    assert "CAM_01" in service.homography
    assert "CAM_02" in service.homography

def test_local_track_id_collision_prevention(store_layout_temp):
    service = GlobalIdentityService(store_layout_path=store_layout_temp, reid_threshold=0.8, reentry_window_seconds=60)
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    bbox = (10, 10, 100, 100)
    now = datetime.now(timezone.utc)

    # 1. Register track_id 1 on CAM_01
    vid1, reentry1 = service.get_visitor_id(track_id=1, frame=frame, bbox=bbox, camera_id="CAM_01", frame_time=now)
    assert vid1.startswith("VIS_")
    assert reentry1 is False

    # 2. Register track_id 1 on CAM_02 at the same time. Since they are different cameras, it must NOT reuse the cache for track_id 1
    # Note: because it's same frame, similarity will be 1.0, but speed check will reject it if they are far apart, or if elapsed time is 0.
    vid2, reentry2 = service.get_visitor_id(track_id=1, frame=frame, bbox=bbox, camera_id="CAM_02", frame_time=now)
    assert vid2 != vid1
    assert reentry2 is False

def test_spatial_speed_constraints_rejection(store_layout_temp):
    service = GlobalIdentityService(store_layout_path=store_layout_temp, reid_threshold=0.5, reentry_window_seconds=10)
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    bbox = (10, 10, 100, 100)
    now = datetime.now(timezone.utc)

    # Register visitor 1 on CAM_01. Under layout, dst points are in 3000-7000 range.
    vid1, _ = service.get_visitor_id(track_id=1, frame=frame, bbox=bbox, camera_id="CAM_01", frame_time=now)
    service.mark_exited(vid1, now + timedelta(seconds=1))

    # Try to re-identify visitor 1 on CAM_02 (dst points 500-4500) only 2 seconds later.
    # The distance from CAM_01 center to CAM_02 center is ~3000mm (3 meters).
    # Since elapsed is 2 seconds, speed is 3.0m/2s = 1.5 m/s (feasible).
    # But if we try to re-identify 0.2 seconds later, distance 3 meters in 0.2 seconds = 15 m/s (impossible).
    
    # Fast re-identification (should fail speed check and register as new visitor)
    vid2, reentry = service.get_visitor_id(
        track_id=2, frame=frame, bbox=bbox, camera_id="CAM_02", frame_time=now + timedelta(seconds=0.5)
    )
    assert vid2 != vid1
    assert reentry is False

    # Feasible re-identification (should pass speed check)
    # Reset exit
    service.mark_exited(vid1, now + timedelta(seconds=1))
    vid3, reentry_ok = service.get_visitor_id(
        track_id=3, frame=frame, bbox=bbox, camera_id="CAM_02", frame_time=now + timedelta(seconds=10.0)
    )
    assert vid3 == vid1
    assert reentry_ok is True

def test_staff_exclusion(store_layout_temp):
    class MockStaffClassifier:
        def __init__(self):
            self.cache = {"VIS_staff_01": True}

    service = GlobalIdentityService(store_layout_path=store_layout_temp, reid_threshold=0.5, reentry_window_seconds=60)
    service.staff_classifier = MockStaffClassifier()

    # Pre-register mock staff member in the gallery
    service.visitor_embeddings["VIS_staff_01"] = np.ones(512, dtype=np.float32) / np.sqrt(512)
    service.visitor_last_seen["VIS_staff_01"] = datetime.now(timezone.utc)

    # Attempt to query with matching embedding
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    # Force the EmbeddingExtractor mock or exact same embedding
    service.visitor_embeddings["VIS_staff_01"] = service.embedding_extractor.extract(frame, (10, 10, 100, 100))
    
    vid, reentry = service.get_visitor_id(track_id=1, frame=frame, bbox=(10,10,100,100), camera_id="CAM_01")
    # Should not match because VIS_staff_01 is excluded as staff
    assert vid != "VIS_staff_01"
    assert reentry is False

@pytest.mark.asyncio
async def test_ingest_reid_metadata_persistence(client: AsyncClient, db_session: AsyncSession):
    event_id = str(uuid.uuid4())
    payload = {
        "events": [
            {
                "event_id": event_id,
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_02",
                "visitor_id": "VIS_abc123",
                "event_type": "REENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": 0.95,
                "metadata": {
                    "local_tracker_id": "track_12",
                    "reid_confidence": 0.82,
                    "source_camera": "CAM_01",
                    "destination_camera": "CAM_02"
                }
            }
        ]
    }

    # Ingest event containing Re-ID match metadata
    response = await client.post("/events/ingest", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1

    # Verify db entry in global_visitor_matches
    query = select(GlobalVisitorMatch).where(GlobalVisitorMatch.global_person_id == "VIS_abc123")
    result = await db_session.execute(query)
    match_record = result.scalars().first()

    assert match_record is not None
    assert match_record.local_tracker_id == "track_12"
    assert match_record.confidence == 0.82
    assert match_record.source_camera == "CAM_01"
    assert match_record.destination_camera == "CAM_02"

@pytest.mark.asyncio
async def test_get_camera_analytics_endpoint(client: AsyncClient):
    response = await client.get("/stores/STORE_BLR_002/camera-analytics")
    assert response.status_code == 200
    data = response.json()
    assert "store_id" in data
    assert data["store_id"] == "STORE_BLR_002"
    assert "cameras" in data
    for cam in ["CAM_01", "CAM_02", "CAM_03", "CAM_05"]:
        assert cam in data["cameras"]
        cam_info = data["cameras"][cam]
        assert "active_visitors_count" in cam_info
        assert "active_visitors" in cam_info
        assert "entries" in cam_info
        assert "exits" in cam_info
        assert "active_tracks" in cam_info
    assert "billing_visitors" in data
    assert "peak_traffic_hour" in data
