# PROMPT: We are in store-intelligence/tests/. Write the API endpoint test suite for health check. Test class TestHealthEndpoint verifying HTTP 200, stale feeds warning, fresh feeds ok, and empty DB checks.
# CHANGES MADE: Wrapped tests inside TestHealthEndpoint class, added required prompt comment headers, and ensured all checks align with the prompt.

import pytest
import uuid
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_returns_503_on_db_down(self, client: AsyncClient, db_session: AsyncSession):
        from unittest.mock import AsyncMock
        original_execute = db_session.execute
        db_session.execute = AsyncMock(side_effect=Exception("DB Down"))
        try:
            response = await client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["stores"][0]["status"] == "DEGRADED"
            assert data["stores"][0]["warning"] == "DATABASE_UNAVAILABLE"
        finally:
            db_session.execute = original_execute

    async def test_health_reports_stale_feed_when_no_recent_events(self, client: AsyncClient):
        now = datetime.now(timezone.utc)
        payload = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "store_id": "STORE_BLR_002",
                    "camera_id": "CAM_02",
                    "visitor_id": "VIS_def456",
                    "event_type": "ENTRY",
                    "timestamp": (now - timedelta(minutes=11)).isoformat(),
                    "dwell_ms": 2000,
                    "confidence": 0.95
                }
            ]
        }
        await client.post("/events/ingest", json=payload)

        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        
        stores_info = {s["store_id"]: s for s in data["stores"]}
        assert "STORE_BLR_002" in stores_info
        assert stores_info["STORE_BLR_002"]["status"] == "STALE"
        assert stores_info["STORE_BLR_002"]["warning"] == "STALE_FEED"

    async def test_health_reports_ok_when_events_are_fresh(self, client: AsyncClient):
        now = datetime.now(timezone.utc)
        payload = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "store_id": "STORE_BLR_001",
                    "camera_id": "CAM_01",
                    "visitor_id": "VIS_abc123",
                    "event_type": "ENTRY",
                    "timestamp": (now - timedelta(minutes=2)).isoformat(),
                    "dwell_ms": 1500,
                    "confidence": 0.95
                }
            ]
        }
        await client.post("/events/ingest", json=payload)

        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        
        stores_info = {s["store_id"]: s for s in data["stores"]}
        assert "STORE_BLR_001" in stores_info
        assert stores_info["STORE_BLR_001"]["status"] == "OK"
        assert stores_info["STORE_BLR_001"]["warning"] is None

    async def test_health_does_not_crash_on_empty_db(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["api_version"] == "1.0.0"
        assert len(data["stores"]) == 1
        assert data["stores"][0]["store_id"] == "UNKNOWN"
        assert data["stores"][0]["status"] == "STALE"
        assert data["stores"][0]["warning"] == "NO_DATA"

    async def test_health_check_db_query_error(self, client: AsyncClient, db_session: AsyncSession):
        from unittest.mock import AsyncMock
        original_execute = db_session.execute
        db_session.execute = AsyncMock(side_effect=Exception("DB Query Failed"))
        
        try:
            response = await client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["stores"][0]["status"] == "DEGRADED"
            assert data["stores"][0]["warning"] == "DATABASE_UNAVAILABLE"
        finally:
            db_session.execute = original_execute

    async def test_health_check_handler_unexpected_error(self, client: AsyncClient):
        with patch("app.routers.health.get_health", side_effect=Exception("Fatal check logic failure")):
            response = await client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["stores"][0]["status"] == "DEGRADED"
            assert data["stores"][0]["warning"] == "DATABASE_UNAVAILABLE"

    async def test_get_health_direct(self, db_session: AsyncSession):
        from app.health import get_health
        import uuid
        from datetime import datetime, timezone, timedelta
        from app.models import Event
        
        now = datetime.now(timezone.utc)
        ev = Event(
            event_id=uuid.uuid4(),
            store_id="STORE_BLR_002",
            camera_id="CAM_01",
            visitor_id="VIS_abc123",
            event_type="ENTRY",
            timestamp=now - timedelta(minutes=5),
            confidence=0.95
        )
        db_session.add(ev)
        await db_session.commit()
        
        res = await get_health(db_session)
        assert res.api_version == "1.0.0"
        assert len(res.stores) == 1
        assert res.stores[0].store_id == "STORE_BLR_002"
        assert res.stores[0].status == "OK"
