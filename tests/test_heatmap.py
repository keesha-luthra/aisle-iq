# PROMPT: We are in store-intelligence/tests/. Write the API endpoint test suite for heatmap. Test empty heatmap, populated heatmap zones, normalised_score range checks, and data_confidence thresholds.
# CHANGES MADE: Created test_heatmap.py with tests for empty zones, populated zone normalisation, and direct get_heatmap function unit tests.
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_heatmap_empty(client: AsyncClient):
    response = await client.get("/stores/STORE_BLR_002/heatmap")
    assert response.status_code == 200
    data = response.json()
    assert data["store_id"] == "STORE_BLR_002"
    assert len(data["zones"]) == 0

@pytest.mark.asyncio
async def test_get_heatmap_populated(client: AsyncClient):
    now = datetime.now(timezone.utc)
    # Ingest 20 events in AISLE_01 for unique visitors to trigger data_confidence=True
    events = []
    for i in range(20):
        events.append({
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_01",
            "visitor_id": f"VIS_abc{i:03d}",
            "event_type": "ZONE_ENTER",
            "zone_id": "AISLE_01",
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
            "dwell_ms": 2000,
            "confidence": 0.95
        })
    # Add one event in AISLE_02 to verify normalization
    events.append({
        "event_id": str(uuid.uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_01",
        "visitor_id": "VIS_abc999",
        "event_type": "ZONE_ENTER",
        "zone_id": "AISLE_02",
        "timestamp": (now - timedelta(minutes=5)).isoformat(),
        "dwell_ms": 1000,
        "confidence": 0.95
    })
    
    await client.post("/events/ingest", json={"events": events})
    
    response = await client.get("/stores/STORE_BLR_002/heatmap")
    assert response.status_code == 200
    data = response.json()
    
    assert data["store_id"] == "STORE_BLR_002"
    zones = data["zones"]
    assert len(zones) == 2
    
    aisle1 = [z for z in zones if z["zone_id"] == "AISLE_01"][0]
    aisle2 = [z for z in zones if z["zone_id"] == "AISLE_02"][0]
    
    assert aisle1["visit_frequency"] == 20
    assert aisle1["normalised_score"] == 100.0
    assert aisle1["data_confidence"] is True
    
    assert aisle2["visit_frequency"] == 1
    assert aisle2["normalised_score"] == 5.0
    assert aisle2["data_confidence"] is False

@pytest.mark.asyncio
async def test_get_heatmap_direct(db_session):
    import uuid
    from datetime import datetime, timezone, timedelta
    from app.models import Event
    from app.heatmap import get_heatmap
    
    now = datetime.now(timezone.utc)
    ev1 = Event(
        event_id=uuid.uuid4(),
        store_id="STORE_BLR_002",
        camera_id="CAM_01",
        visitor_id="VIS_abc123",
        event_type="ZONE_ENTER",
        zone_id="AISLE_01",
        timestamp=now - timedelta(minutes=5),
        dwell_ms=2000,
        confidence=0.95
    )
    db_session.add(ev1)
    await db_session.commit()
    
    res = await get_heatmap("STORE_BLR_002", 24, db_session)
    assert res.store_id == "STORE_BLR_002"
    assert len(res.zones) == 1
    assert res.zones[0].zone_id == "AISLE_01"
