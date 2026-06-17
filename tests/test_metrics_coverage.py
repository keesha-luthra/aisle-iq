# PROMPT: We are in store-intelligence/tests/. Write direct coverage tests for app/metrics.py. Test functions get_store_metrics and get_live_store_metrics directly with mock/live database sessions to hit all branches and lines.
# CHANGES MADE: Created TestMetricsCoverage covering get_store_metrics, get_live_store_metrics, empty stores, SQLite branch, and PostgreSQL mock branches.

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock
from app.metrics import get_store_metrics, get_live_store_metrics
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
class TestMetricsCoverage:
    async def test_get_store_metrics_empty(self, db_session: AsyncSession):
        # Test get_store_metrics on an empty database
        res = await get_store_metrics("STORE_BLR_999", 24, db_session)
        assert res.store_id == "STORE_BLR_999"
        assert res.unique_visitors == 0
        assert res.conversion_rate == 0.0
        assert res.avg_dwell_by_zone == {}
        assert res.current_queue_depth == 0
        assert res.abandonment_rate == 0.0

    async def test_get_live_store_metrics_empty(self, db_session: AsyncSession):
        # Test get_live_store_metrics on an empty database
        res = await get_live_store_metrics("STORE_BLR_999", db_session)
        assert res.store_id == "STORE_BLR_999"
        assert res.unique_visitors == 0
        assert res.conversion_rate == 0.0
        assert res.avg_dwell_by_zone == {}
        assert res.current_queue_depth == 0
        assert res.abandonment_rate == 0.0

    async def test_get_live_store_metrics_with_data(self, db_session: AsyncSession, sample_events_batch, client):
        # Ingest data first
        await client.post("/events/ingest", json={"events": sample_events_batch})
        
        # Call get_live_store_metrics directly
        res = await get_live_store_metrics("STORE_BLR_002", db_session)
        assert res.store_id == "STORE_BLR_002"
        # Since events are within the last 10 minutes, they should fall within the 5 minute live window if timestamp is recent.
        # Note: sample_events_batch timestamps are offset by 1-10 minutes.
        assert isinstance(res.unique_visitors, int)
        assert isinstance(res.conversion_rate, float)

    async def test_dialect_branch_coverage_for_postgresql(self):
        # Mock the db session to simulate PostgreSQL dialect and test postgresql query branch
        mock_db = MagicMock(spec=AsyncSession)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.bind = mock_bind
        
        # Mock db.execute to return mock results for the five queries in get_live_store_metrics
        mock_result = MagicMock()
        mock_result.scalar.return_value = 10
        mock_result.all.return_value = [("ZONE_A", 120.0), (None, 0.0)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        res_live = await get_live_store_metrics("STORE_BLR_101", mock_db)
        assert res_live.unique_visitors == 10
        assert res_live.current_queue_depth == 10
        assert res_live.avg_dwell_by_zone["ZONE_A"] == 120.0

        # Also cover get_store_metrics under postgresql dialect
        res_store = await get_store_metrics("STORE_BLR_101", 24, mock_db)
        assert res_store.unique_visitors == 10

    async def test_get_camera_analytics_sqlite(self, db_session: AsyncSession):
        from app.metrics import get_camera_analytics
        res = await get_camera_analytics("STORE_BLR_002", db_session)
        assert res["store_id"] == "STORE_BLR_002"
        assert "cameras" in res
        assert "CAM_01" in res["cameras"]
        
    async def test_get_camera_analytics_postgresql(self):
        from app.metrics import get_camera_analytics
        mock_db = MagicMock(spec=AsyncSession)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.bind = mock_bind
        
        # 1. SELECT MAX(timestamp)
        mock_max = MagicMock()
        mock_max.scalar.return_value = "2026-03-03T14:22:10Z"
        
        # 2. 4 cameras * 4 queries (active, entries, exits, tracks)
        camera_mocks = []
        for _ in range(4):
            mock_active = MagicMock()
            mock_active.all.return_value = []
            
            mock_entries = MagicMock()
            mock_entries.scalar.return_value = 10
            
            mock_exits = MagicMock()
            mock_exits.scalar.return_value = 5
            
            mock_tracks = MagicMock()
            mock_tracks.scalar.return_value = 2
            
            camera_mocks.extend([mock_active, mock_entries, mock_exits, mock_tracks])
            
        # 3. billing_query
        mock_billing = MagicMock()
        mock_billing.scalar.return_value = 3
        
        # 4. peak_query
        mock_peak = MagicMock()
        mock_peak.first.return_value = (14.0, 10)
        
        mock_db.execute = AsyncMock(side_effect=[mock_max] + camera_mocks + [mock_billing, mock_peak])
        
        res = await get_camera_analytics("STORE_BLR_002", mock_db)
        assert res["store_id"] == "STORE_BLR_002"
        assert res["peak_traffic_hour"] == "14:00 - 15:00"
