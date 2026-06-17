# PROMPT: Write tests/test_assertions.py that mirrors the 10 assertion patterns from the challenge assertions.py. Tests cover POST ingest 200, metrics validation, funnel monotonicity, heatmap scores, anomalies severity, health 200, and idempotency for STORE_BLR_002.
# CHANGES MADE: Rewrote test_assertions.py to seed data before validation tests, ensuring metrics/funnel/heatmap return populated data. Added helper _seed_store_data to ingest a realistic event batch.

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _build_seed_events(store_id: str = "STORE_BLR_002") -> list[dict]:
    """Build a realistic batch of events that exercises all funnel stages."""
    now = datetime.now(timezone.utc)
    vis1, vis2, vis3 = "VIS_aaa111", "VIS_bbb222", "VIS_ccc333"
    events = []

    def _ev(visitor_id, event_type, minutes_ago, **extra):
        e = {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM_01",
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": (now - timedelta(minutes=minutes_ago)).isoformat(),
            "confidence": 0.95,
        }
        e.update(extra)
        return e

    # 3 ENTRYs
    events.append(_ev(vis1, "ENTRY", 30))
    events.append(_ev(vis2, "ENTRY", 28))
    events.append(_ev(vis3, "ENTRY", 26))

    # 3 ZONE_ENTERs (all 3 visitors visit a zone)
    events.append(_ev(vis1, "ZONE_ENTER", 25, zone_id="AISLE_01"))
    events.append(_ev(vis2, "ZONE_ENTER", 24, zone_id="AISLE_02"))
    events.append(_ev(vis3, "ZONE_ENTER", 23, zone_id="AISLE_01"))

    # 3 ZONE_DWELLs
    events.append(_ev(vis1, "ZONE_DWELL", 22, zone_id="AISLE_01", dwell_ms=10000))
    events.append(_ev(vis2, "ZONE_DWELL", 21, zone_id="AISLE_02", dwell_ms=15000))
    events.append(_ev(vis3, "ZONE_DWELL", 20, zone_id="AISLE_01", dwell_ms=8000))

    # 2 BILLING_QUEUE_JOINs (vis1 and vis2 go to billing)
    events.append(_ev(vis1, "BILLING_QUEUE_JOIN", 15, metadata={"queue_depth": 2}))
    events.append(_ev(vis2, "BILLING_QUEUE_JOIN", 14, metadata={"queue_depth": 3}))

    # 1 BILLING_QUEUE_ABANDON (vis2 abandons)
    events.append(_ev(vis2, "BILLING_QUEUE_ABANDON", 12))

    # 2 EXITs
    events.append(_ev(vis1, "EXIT", 5, dwell_ms=600000))
    events.append(_ev(vis3, "EXIT", 3, dwell_ms=480000))

    return events


@pytest.fixture
async def seeded_client(client: AsyncClient):
    """Client with pre-seeded STORE_BLR_002 data for assertion tests."""
    events = _build_seed_events()
    resp = await client.post("/events/ingest", json={"events": events})
    assert resp.status_code == 200
    assert resp.json()["accepted"] == len(events)
    return client


@pytest.mark.asyncio
class TestAssertionsSuite:
    """Mirrors the 10 assertions from the challenge assertions.py."""

    async def test_post_events_ingest_returns_200(self, client: AsyncClient):
        payload = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "store_id": "STORE_BLR_002",
                    "camera_id": "CAM_01",
                    "visitor_id": "VIS_abc123",
                    "event_type": "ENTRY",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "confidence": 0.95,
                }
            ]
        }
        response = await client.post("/events/ingest", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "accepted" in data
        assert "rejected" in data
        assert "duplicate" in data

    async def test_get_metrics_STORE_BLR_002_returns_valid_json(self, seeded_client: AsyncClient):
        response = await seeded_client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert data["store_id"] == "STORE_BLR_002"

    async def test_metrics_has_unique_visitors_field(self, seeded_client: AsyncClient):
        response = await seeded_client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "unique_visitors" in data

    async def test_metrics_unique_visitors_is_integer(self, seeded_client: AsyncClient):
        response = await seeded_client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["unique_visitors"], int)

    async def test_metrics_conversion_rate_is_between_0_and_1(self, seeded_client: AsyncClient):
        response = await seeded_client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert 0.0 <= data["conversion_rate"] <= 1.0

    async def test_funnel_entry_count_gte_purchase_count(self, seeded_client: AsyncClient):
        response = await seeded_client.get("/stores/STORE_BLR_002/funnel")
        assert response.status_code == 200
        data = response.json()
        stages = data["stages"]
        # Monotonically non-increasing funnel
        assert stages["entry_count"] >= stages["zone_visit_count"]
        assert stages["zone_visit_count"] >= stages["billing_queue_count"]
        assert stages["billing_queue_count"] >= stages["purchase_count"]
        assert stages["entry_count"] >= stages["purchase_count"]

    async def test_heatmap_normalised_scores_between_0_and_100(self, seeded_client: AsyncClient):
        response = await seeded_client.get("/stores/STORE_BLR_002/heatmap")
        assert response.status_code == 200
        data = response.json()
        for zone in data["zones"]:
            assert 0.0 <= zone["normalised_score"] <= 100.0

    async def test_anomalies_has_severity_field_in_valid_values(self, seeded_client: AsyncClient):
        response = await seeded_client.get("/stores/STORE_BLR_002/anomalies")
        assert response.status_code == 200
        data = response.json()
        # Anomalies list can be empty (no anomalies detected) — that's valid
        for anomaly in data["anomalies"]:
            assert "severity" in anomaly
            assert anomaly["severity"] in ("INFO", "WARN", "CRITICAL")

    async def test_health_responds_200(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_ingest_idempotency(self, client: AsyncClient, db_session: AsyncSession):
        # Ingest same 10-event batch twice for STORE_BLR_002
        events = []
        for i in range(10):
            events.append({
                "event_id": str(uuid.uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_abc123",
                "event_type": "ENTRY",
                "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=i)).isoformat(),
                "confidence": 0.95,
            })

        payload = {"events": events}

        # First POST: should accept 10
        res1 = await client.post("/events/ingest", json=payload)
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["accepted"] == 10
        assert data1["duplicate"] == 0

        # Second POST: should accept 0, duplicate 10
        res2 = await client.post("/events/ingest", json=payload)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["accepted"] == 0
        assert data2["duplicate"] == 10

        # Verify DB row count hasn't increased
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM events WHERE store_id = 'STORE_BLR_002'")
        )
        count = result.scalar()
        assert count == 10
