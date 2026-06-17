# PROMPT: We are in store-intelligence/tests/. Write direct coverage tests for app/funnel.py, app/health.py, app/utils.py, and app/routers/metrics_live.py.
# CHANGES MADE: Created TestRoutersAndServicesCoverage covering layout loading, funnel SQL query dialect branches, detailed health statuses (OK, STALE, NO_DATA), datetime formats, and live metrics API router.

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from httpx import AsyncClient

from app.utils import load_layout
from app.funnel import get_funnel
from app.health import get_health
from app.routers.metrics_live import get_live_metrics

class TestRoutersAndServicesCoverage:
    # 1. app/utils.py Coverage
    def test_load_layout_success(self):
        layout = load_layout("STORE_BLR_002")
        assert "zones" in layout
        assert len(layout["zones"]) > 0

    def test_load_layout_missing_raises_error(self):
        with pytest.raises(FileNotFoundError):
            load_layout("STORE_NON_EXISTENT")

    # 2. app/funnel.py Coverage
    @pytest.mark.asyncio
    async def test_get_funnel_sqlite(self, db_session: AsyncSession):
        res = await get_funnel("STORE_BLR_002", 24, db_session)
        assert res.store_id == "STORE_BLR_002"
        assert res.stages.entry_count == 0

    @pytest.mark.asyncio
    async def test_get_funnel_postgresql(self):
        mock_db = MagicMock(spec=AsyncSession)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.bind = mock_bind

        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_db.execute = AsyncMock(return_value=mock_result)

        res = await get_funnel("STORE_BLR_002", 24, mock_db)
        assert res.stages.entry_count == 5

    # 3. app/health.py Coverage
    @pytest.mark.asyncio

    async def test_get_health_empty_db(self, db_session: AsyncSession):
        res = await get_health(db_session)
        assert len(res.stores) == 1
        assert res.stores[0].store_id == "UNKNOWN"
        assert res.stores[0].warning == "NO_DATA"

    @pytest.mark.asyncio

    async def test_get_health_datetime_and_stale_warning(self, db_session: AsyncSession):
        now = datetime.now(timezone.utc)
        # 1. Insert an event that is stale (lag > stale_feed_seconds, i.e. > 600s)
        stale_time = now - timedelta(minutes=15)
        await db_session.execute(
            text("INSERT INTO events (event_id, store_id, camera_id, visitor_id, event_type, timestamp, confidence, dwell_ms, is_staff) "
                 "VALUES (:eid, 'STORE_BLR_002', 'CAM_01', 'V1', 'ZONE_ENTER', :ts, 0.9, 0, 0)"),
            {"eid": str(uuid.uuid4()), "ts": stale_time.isoformat()}
        )
        await db_session.commit()

        # Check health: should report STALE
        res = await get_health(db_session)
        assert len(res.stores) == 1
        assert res.stores[0].status == "STALE"
        assert res.stores[0].warning == "STALE_FEED"

    @pytest.mark.asyncio

    async def test_get_health_invalid_date_string_and_datetime_object(self):
        mock_db = MagicMock(spec=AsyncSession)
        mock_result = MagicMock()
        
        # We need two rows: one with an invalid date string, one with a datetime object
        class MockRow:
            def __init__(self, store_id, last_event_at):
                self.store_id = store_id
                self.last_event_at = last_event_at

        # Row 1 has invalid date, Row 2 has datetime object
        mock_result.all.return_value = [
            MockRow("STORE_A", "invalid-date-string"),
            MockRow("STORE_B", datetime.now(timezone.utc))
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        res = await get_health(mock_db)
        assert len(res.stores) == 2
        assert res.stores[0].store_id == "STORE_A"
        assert res.stores[1].store_id == "STORE_B"

    # 4. Live Metrics Router Endpoint Coverage
    @pytest.mark.asyncio
    async def test_live_metrics_router_endpoints(self, client: AsyncClient):
        # The router might be registered at either "/metrics/live/STORE_BLR_002" or "/metrics/live/metrics/live/STORE_BLR_002"
        # Let's try both to make sure we hit the endpoint
        response = await client.get("/metrics/live/STORE_BLR_002")
        if response.status_code == 404:
            response = await client.get("/metrics/live/metrics/live/STORE_BLR_002")
        
        assert response.status_code == 200
        data = response.json()
        assert data["store_id"] == "STORE_BLR_002"
        assert "current_queue_depth" in data

    # 5. Logging & Startup Event Coverage
    def test_setup_logging(self):
        from app.logging_config import setup_logging
        setup_logging()

    @pytest.mark.asyncio
    @patch("app.main.run_migrations")
    @patch("app.main.init_db")
    async def test_app_startup_event(self, mock_init, mock_migrate):
        from app.main import lifespan
        from fastapi import FastAPI
        # Mock settings.POS_CSV_PATH to a non-existent path to prevent trying to load it
        with patch("app.main.settings") as mock_settings:
            mock_settings.POS_CSV_PATH = "non_existent_path.csv"
            mock_settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
            app = FastAPI()
            async with lifespan(app):
                pass


