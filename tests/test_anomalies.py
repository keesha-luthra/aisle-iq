# PROMPT: We are in store-intelligence/tests/. Write the API endpoint test suite for anomalies. Test class TestAnomalyEndpoint with empty anomalies, queue spikes (CRITICAL), dead zones (INFO), conversion drops (WARN), suggested action check, and uniqueness checks.
# CHANGES MADE: Added TestAnomalyEndpoint with mock configurations, database row inserts, and required prompt headers.

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from unittest.mock import patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
class TestAnomalyEndpoint:
    async def test_no_anomalies_returns_empty_list_not_error(self, client: AsyncClient):
        # By mocking get_layout_zones to return empty list, no dead zones are computed.
        # With an empty database, there will be no queue spikes, high abandonment, or conversion drops.
        with patch("app.anomalies.get_layout_zones", return_value=[]):
            response = await client.get("/stores/STORE_BLR_002/anomalies")
            assert response.status_code == 200
            data = response.json()
            assert data["store_id"] == "STORE_BLR_002"
            assert len(data["anomalies"]) == 0

    async def test_queue_spike_triggers_critical_anomaly(self, client: AsyncClient):
        now = datetime.now(timezone.utc)
        events = []
        # Ingest 6 BILLING_QUEUE_JOIN events with queue_depth=7
        for _ in range(6):
            events.append({
                "event_id": str(uuid.uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_03",
                "visitor_id": f"VIS_{uuid.uuid4().hex[:6]}",
                "event_type": "BILLING_QUEUE_JOIN",
                "timestamp": now.isoformat(),
                "confidence": 0.95,
                "metadata": {"queue_depth": 7}
            })
            
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/stores/STORE_BLR_002/anomalies")
        assert response.status_code == 200
        data = response.json()
        
        queue_anomalies = [a for a in data["anomalies"] if a["anomaly_type"] == "BILLING_QUEUE_SPIKE"]
        assert len(queue_anomalies) == 1
        assert queue_anomalies[0]["severity"] == "CRITICAL"
        assert queue_anomalies[0]["metric_value"] == 7.0

    async def test_dead_zone_triggers_info_anomaly(self, client: AsyncClient):
        now = datetime.now(timezone.utc)
        # Mock layout zones to be ["SKINCARE", "AISLE_01"]
        # Ingest event for AISLE_01 only, so SKINCARE triggers dead zone check
        with patch("app.anomalies.get_layout_zones", return_value=["SKINCARE", "AISLE_01"]):
            event = {
                "event_id": str(uuid.uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_abc123",
                "event_type": "ZONE_ENTER",
                "zone_id": "AISLE_01",
                "timestamp": now.isoformat(),
                "confidence": 0.95
            }
            await client.post("/events/ingest", json={"events": [event]})
            
            response = await client.get("/stores/STORE_BLR_002/anomalies")
            assert response.status_code == 200
            data = response.json()
            
            dead_zones = [a for a in data["anomalies"] if a["anomaly_type"] == "DEAD_ZONE" and a["zone_id"] == "SKINCARE"]
            assert len(dead_zones) == 1
            assert dead_zones[0]["severity"] == "INFO"

    async def test_conversion_drop_triggers_warn_anomaly(self, client: AsyncClient, db_session: AsyncSession):
        now = datetime.now(timezone.utc)
        
        # 1. Ancient session to set data_age >= 7 days
        await db_session.execute(
            text("INSERT INTO visitor_sessions (session_id, visitor_id, store_id, entry_time, is_converted, total_events, is_staff) "
                 "VALUES (:sid, :vid, :store_id, :entry, 1, 1, 0)"),
            {"sid": str(uuid.uuid4()), "vid": "VIS_ancient", "store_id": "STORE_BLR_002", "entry": now - timedelta(days=8)}
        )
        
        # 2. Historical converted sessions (7-day rate = 1.0)
        for i in range(5):
            await db_session.execute(
                text("INSERT INTO visitor_sessions (session_id, visitor_id, store_id, entry_time, is_converted, total_events, is_staff) "
                     "VALUES (:sid, :vid, :store_id, :entry, 1, 1, 0)"),
                {"sid": str(uuid.uuid4()), "vid": f"VIS_hist_{i}", "store_id": "STORE_BLR_002", "entry": now - timedelta(days=2)}
            )
            
        # 3. Unconverted today sessions (today rate = 0.0)
        for i in range(5):
            await db_session.execute(
                text("INSERT INTO visitor_sessions (session_id, visitor_id, store_id, entry_time, is_converted, total_events, is_staff) "
                     "VALUES (:sid, :vid, :store_id, :entry, 0, 1, 0)"),
                {"sid": str(uuid.uuid4()), "vid": f"VIS_today_{i}", "store_id": "STORE_BLR_002", "entry": now - timedelta(hours=2)}
            )
        await db_session.commit()
        
        with patch("app.anomalies.get_layout_zones", return_value=[]):
            response = await client.get("/stores/STORE_BLR_002/anomalies")
            assert response.status_code == 200
            data = response.json()
            
            conversion_drops = [a for a in data["anomalies"] if a["anomaly_type"] == "CONVERSION_DROP"]
            assert len(conversion_drops) == 1
            assert conversion_drops[0]["severity"] == "WARN"

    async def test_anomaly_has_suggested_action(self, client: AsyncClient):
        response = await client.get("/stores/STORE_BLR_002/anomalies")
        assert response.status_code == 200
        data = response.json()
        for anomaly in data["anomalies"]:
            assert anomaly["suggested_action"] != ""
            assert isinstance(anomaly["suggested_action"], str)

    async def test_anomaly_ids_are_unique(self, client: AsyncClient):
        response = await client.get("/stores/STORE_BLR_002/anomalies")
        assert response.status_code == 200
        data = response.json()
        
        anomaly_ids = [a["anomaly_id"] for a in data["anomalies"]]
        assert len(anomaly_ids) == len(set(anomaly_ids))
