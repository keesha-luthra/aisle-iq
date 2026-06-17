# PROMPT: We are in store-intelligence/tests/. Write the API endpoint test suite for metrics. Test class TestMetricsEndpoint with valid/empty/unknown stores, staff filters, average dwell zone rules, and window queries.
# CHANGES MADE: Added TestMetricsEndpoint with comprehensive assertions, autouse data injection, and required prompt headers.

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient

@pytest.mark.asyncio
class TestMetricsEndpoint:
    @pytest.fixture(autouse=True)
    async def setup_metrics_data(self, client: AsyncClient, sample_events_batch):
        # Ingest standard events for STORE_BLR_002
        await client.post("/events/ingest", json={"events": sample_events_batch})

    async def test_metrics_returns_200_for_valid_store(self, client: AsyncClient):
        response = await client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["store_id"] == "STORE_BLR_002"

    async def test_metrics_returns_nonzero_unique_visitors(self, client: AsyncClient):
        response = await client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["unique_visitors"] == 2

    async def test_metrics_excludes_staff_from_visitor_count(self, client: AsyncClient):
        staff_event_dict = {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_01",
            "visitor_id": "VIS_999999",
            "event_type": "ENTRY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_staff": True,
            "confidence": 0.95
        }
        await client.post("/events/ingest", json={"events": [staff_event_dict]})
        
        response = await client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["unique_visitors"] == 2

    async def test_metrics_returns_zero_for_empty_store(self, client: AsyncClient):
        response = await client.get("/stores/STORE_BLR_003/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["store_id"] == "STORE_BLR_003"
        assert data["unique_visitors"] == 0
        assert data["conversion_rate"] == 0.0

    async def test_metrics_conversion_rate_between_0_and_1(self, client: AsyncClient):
        response = await client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert 0.0 <= data["conversion_rate"] <= 1.0

    async def test_metrics_avg_dwell_only_from_zone_dwell_events(self, client: AsyncClient):
        response = await client.get("/stores/STORE_BLR_002/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["avg_dwell_by_zone"]["AISLE_01"] == 5.0
        assert data["avg_dwell_by_zone"]["AISLE_02"] == 4.0

    async def test_metrics_window_param_filters_correctly(self, client: AsyncClient):
        now = datetime.now(timezone.utc)
        event_old = {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_001",
            "camera_id": "CAM_01",
            "visitor_id": "VIS_123456",
            "event_type": "ENTRY",
            "timestamp": (now - timedelta(hours=30)).isoformat(),
            "confidence": 0.95
        }
        event_new = {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_001",
            "camera_id": "CAM_01",
            "visitor_id": "VIS_654321",
            "event_type": "ENTRY",
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "confidence": 0.95
        }
        await client.post("/events/ingest", json={"events": [event_old, event_new]})
        
        res_window_2 = await client.get("/stores/STORE_BLR_001/metrics?window_hours=2")
        assert res_window_2.status_code == 200
        assert res_window_2.json()["unique_visitors"] == 1
        
        res_window_48 = await client.get("/stores/STORE_BLR_001/metrics?window_hours=48")
        assert res_window_48.status_code == 200
        assert res_window_48.json()["unique_visitors"] == 2

    async def test_metrics_returns_404_for_unknown_store(self, client: AsyncClient):
        response = await client.get("/stores/STORE_123/metrics")
        assert response.status_code == 404
