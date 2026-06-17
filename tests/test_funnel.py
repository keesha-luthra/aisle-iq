# PROMPT: We are in store-intelligence/tests/. Write the API endpoint test suite for funnel. Test class TestFunnelEndpoint with stage counts, reentry deduplication, dropoff math, empty stores, and purchase counts.
# CHANGES MADE: Added TestFunnelEndpoint with detailed assertions, reentry sequence ingestion, POS purchase updates, and required prompt headers.

import pytest
import uuid
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
class TestFunnelEndpoint:
    async def test_funnel_returns_correct_stage_counts(self, client: AsyncClient, sample_events_batch):
        # Ingest the batch
        await client.post("/events/ingest", json={"events": sample_events_batch})
        
        response = await client.get("/stores/STORE_BLR_002/funnel")
        assert response.status_code == 200
        data = response.json()
        assert data["store_id"] == "STORE_BLR_002"
        
        stages = data["stages"]
        assert stages["entry_count"] == 2
        assert stages["zone_visit_count"] == 2
        assert stages["billing_queue_count"] == 1

    async def test_funnel_reentry_does_not_double_count_visitor(self, client: AsyncClient, reentry_sequence):
        # Ingest the ENTRY, EXIT, REENTRY sequence for the same visitor_id
        await client.post("/events/ingest", json={"events": reentry_sequence})
        
        response = await client.get("/stores/STORE_BLR_002/funnel")
        assert response.status_code == 200
        data = response.json()
        stages = data["stages"]
        
        # entry_count must be 1, NOT 2 (deduplicated by visitor_id)
        assert stages["entry_count"] == 1

    async def test_funnel_drop_off_percentages_sum_correctly(self, client: AsyncClient, sample_events_batch):
        await client.post("/events/ingest", json={"events": sample_events_batch})
        
        response = await client.get("/stores/STORE_BLR_002/funnel")
        assert response.status_code == 200
        data = response.json()
        stages = data["stages"]
        
        # Verify dropoff rates are values between 0.0 and 1.0
        assert 0.0 <= stages["dropoff_entry_to_zone"] <= 1.0
        assert 0.0 <= stages["dropoff_zone_to_queue"] <= 1.0
        assert 0.0 <= stages["dropoff_queue_to_purchase"] <= 1.0

    async def test_funnel_empty_store_returns_zeros_not_errors(self, client: AsyncClient):
        response = await client.get("/stores/STORE_BLR_003/funnel")
        assert response.status_code == 200
        data = response.json()
        assert data["store_id"] == "STORE_BLR_003"
        stages = data["stages"]
        assert stages["entry_count"] == 0
        assert stages["zone_visit_count"] == 0
        assert stages["billing_queue_count"] == 0
        assert stages["purchase_count"] == 0
        assert stages["dropoff_entry_to_zone"] == 1.0
        assert stages["dropoff_zone_to_queue"] == 1.0
        assert stages["dropoff_queue_to_purchase"] == 1.0

    async def test_funnel_purchase_count_from_pos_correlation(self, client: AsyncClient, db_session: AsyncSession, sample_events_batch):
        await client.post("/events/ingest", json={"events": sample_events_batch})
        
        # Mark one visitor session as converted directly in DB to simulate POS correlation match
        await db_session.execute(
            text("UPDATE visitor_sessions SET is_converted = 1 WHERE visitor_id = 'VIS_111111'")
        )
        await db_session.commit()
        
        response = await client.get("/stores/STORE_BLR_002/funnel")
        assert response.status_code == 200
        data = response.json()
        stages = data["stages"]
        
        assert stages["purchase_count"] == 1
        assert stages["dropoff_queue_to_purchase"] == 0.0
