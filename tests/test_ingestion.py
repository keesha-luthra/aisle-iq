# PROMPT: We are in store-intelligence/tests/. Write the API endpoint test suite for events ingestion. Test class TestIngestEndpoint with idempotency tests, partial success, batch limits, and required validation checks.
# CHANGES MADE: Added TestIngestEndpoint with robust unit test coverage, database row verification, and required prompt headers.

import uuid
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
class TestIngestEndpoint:
    async def test_ingest_valid_batch_returns_200(self, client: AsyncClient):
        payload = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "store_id": "STORE_BLR_002",
                    "camera_id": "CAM_01",
                    "visitor_id": "VIS_abc123",
                    "event_type": "ENTRY",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "confidence": 0.95
                }
            ]
        }
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1
        assert data["rejected"] == 0
        assert data["duplicate"] == 0

    async def test_ingest_empty_batch_returns_200_with_zero_counts(self, client: AsyncClient):
        payload = {"events": []}
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 0
        assert data["rejected"] == 0
        assert data["duplicate"] == 0

    async def test_ingest_returns_partial_success_on_mixed_batch(self, client: AsyncClient):
        # 5 valid + 3 invalid events
        events = []
        # 5 valid events
        for _ in range(5):
            events.append({
                "event_id": str(uuid.uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_abc123",
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": 0.9
            })
        # 3 invalid events (missing visitor_id or pattern mismatch)
        for _ in range(3):
            events.append({
                "event_id": str(uuid.uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "invalid_vis",
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": 0.9
            })
            
        payload = {"events": events}
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 5
        assert data["rejected"] == 3
        assert len(data["errors"]) == 3

    async def test_ingest_is_idempotent(self, client: AsyncClient, db_session: AsyncSession):
        # POST same 10-event batch twice
        events = []
        for _ in range(10):
            events.append({
                "event_id": str(uuid.uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_abc123",
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": 0.95
            })
            
        payload = {"events": events}
        
        # First POST
        res1 = await client.post("/events/ingest", json=payload)
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["accepted"] == 10
        assert data1["duplicate"] == 0
        
        # Second POST
        res2 = await client.post("/events/ingest", json=payload)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["accepted"] == 0
        assert data2["duplicate"] == 10
        
        # Verify DB row count did NOT increase on second POST
        result = await db_session.execute(text("SELECT COUNT(*) FROM events"))
        count = result.scalar()
        assert count == 10

    async def test_ingest_rejects_batch_over_500_events(self, client: AsyncClient):
        events = []
        for _ in range(501):
            events.append({
                "event_id": str(uuid.uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_abc123",
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": 0.95
            })
        payload = {"events": events}
        # FastAPI validation error at schema level should return HTTP 422
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 422

    async def test_ingest_rejects_invalid_event_type(self, client: AsyncClient):
        payload = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "store_id": "STORE_BLR_002",
                    "camera_id": "CAM_01",
                    "visitor_id": "VIS_abc123",
                    "event_type": "INVALID_EVENT_TYPE",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "confidence": 0.95
                }
            ]
        }
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 0
        assert data["rejected"] == 1

    async def test_ingest_rejects_missing_required_fields(self, client: AsyncClient):
        payload = {
            "events": [
                {
                    "store_id": "STORE_BLR_002",
                    "camera_id": "CAM_01",
                    "visitor_id": "VIS_abc123",
                    "event_type": "ENTRY",
                    "confidence": 0.95
                }
            ]
        }
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 0
        assert data["rejected"] == 1

    async def test_ingest_handles_all_staff_events(self, client: AsyncClient, db_session: AsyncSession):
        visitor_id = "VIS_def456"
        payload = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "store_id": "STORE_BLR_002",
                    "camera_id": "CAM_01",
                    "visitor_id": visitor_id,
                    "event_type": "ENTRY",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "is_staff": True,
                    "confidence": 0.95
                }
            ]
        }
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1
        
        # Verify visitor_sessions.is_staff = True in DB
        result = await db_session.execute(
            text("SELECT is_staff FROM visitor_sessions WHERE visitor_id = :vid"),
            {"vid": visitor_id}
        )
        is_staff_val = result.scalar()
        assert bool(is_staff_val) is True

    async def test_ingest_invalid_store_id_format_rejected(self, client: AsyncClient):
        payload = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "store_id": "STORE_INVALID_FORMAT_123",
                    "camera_id": "CAM_01",
                    "visitor_id": "VIS_abc123",
                    "event_type": "ENTRY",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "confidence": 0.95
                }
            ]
        }
        # Ingest validation rejects layout mismatch
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 0
        assert data["rejected"] == 1

    async def test_duplicate_event_id_does_not_create_duplicate_db_row(self, client: AsyncClient, db_session: AsyncSession):
        event_id = str(uuid.uuid4())
        event_dict = {
            "event_id": event_id,
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_01",
            "visitor_id": "VIS_abc123",
            "event_type": "ENTRY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence": 0.95
        }
        
        # Submit twice with same event_id
        await client.post("/events/ingest", json={"events": [event_dict]})
        await client.post("/events/ingest", json={"events": [event_dict]})
        
        # Count rows in DB for this event_id
        from app.models import Event
        from sqlalchemy import select
        result = await db_session.execute(
            select(Event).where(Event.event_id == uuid.UUID(event_id))
        )
        count = len(result.scalars().all())
        assert count == 1
