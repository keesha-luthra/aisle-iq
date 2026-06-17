# PROMPT: We are in store-intelligence/tests/. Write direct coverage tests for app/anomalies.py. Test function get_anomalies and get_layout_zones directly with mock/live database sessions to hit all branches and lines.
# CHANGES MADE: Created TestAnomaliesCoverage covering get_anomalies, get_layout_zones, exception handling, SQLite/PostgreSQL branches, datetime parsing edge cases, and all anomaly types (SPIKE, CONVERSION_DROP, DEAD_ZONE, ABANDONMENT).

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from app.anomalies import get_anomalies, get_layout_zones
from sqlalchemy.ext.asyncio import AsyncSession

class TestAnomaliesCoverage:
    @patch("builtins.open", side_effect=IOError("Mock read error"))
    @patch("os.path.exists", return_value=True)
    def test_get_layout_zones_exception(self, mock_exists, mock_open):
        zones = get_layout_zones("STORE_BLR_002")
        # Should fallback to default layout zones on exception
        assert zones == ["AISLE_01", "AISLE_02", "AISLE_03", "ENTRY_AREA", "BILLING"]

    @pytest.mark.asyncio
    async def test_get_anomalies_postgresql_dialect(self):
        # Mock AsyncSession with postgresql dialect
        mock_db = MagicMock(spec=AsyncSession)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.bind = mock_bind
        
        # Mock db.execute to return empty mock results
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        res = await get_anomalies("STORE_BLR_002", mock_db)
        assert res.store_id == "STORE_BLR_002"

    @pytest.mark.asyncio
    async def test_get_anomalies_all_anomalies_and_string_datetimes(self):
        mock_db = MagicMock(spec=AsyncSession)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "sqlite"
        mock_db.bind = mock_bind

        mock_queue = MagicMock()
        mock_queue.scalar.return_value = 15  # > threshold (5) -> queue spike
        
        mock_today = MagicMock()
        mock_today.scalar.return_value = 0.05  # conversion today
        
        mock_seven = MagicMock()
        mock_seven.scalar.return_value = 0.50  # conversion 7-day average
        
        mock_earliest = MagicMock()
        # string date with Z to trigger clean_str.endswith("Z") (line 130-131)
        mock_earliest.scalar.return_value = "2026-05-01 12:00:00Z"  
        
        mock_active = MagicMock()
        mock_active.all.return_value = [("AISLE_01",)]  # AISLE_02 will be dead
        
        mock_abandon = MagicMock()
        mock_abandon.scalar.return_value = 0.65  # > 0.40 -> high abandonment
        
        # Dead zone last visit: string without Z to trigger replace(tzinfo=timezone.utc) (line 185-186)
        mock_visit = MagicMock()
        mock_visit.scalar.return_value = "2026-06-03 09:00:00"
        
        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [
            mock_queue,
            mock_today,
            mock_seven,
            mock_earliest,
            mock_active,
            mock_abandon,
            mock_visit  # for AISLE_02
        ]
        
        with patch("app.anomalies.get_layout_zones", return_value=["AISLE_01", "AISLE_02"]):
            res = await get_anomalies("STORE_BLR_002", mock_db)
            
            # Verify we triggered all four anomalies
            anomaly_types = [a.anomaly_type.value for a in res.anomalies]
            assert "BILLING_QUEUE_SPIKE" in anomaly_types
            assert "CONVERSION_DROP" in anomaly_types
            assert "DEAD_ZONE" in anomaly_types
            assert "HIGH_ABANDONMENT" in anomaly_types
            
            # Verify WARN severity on CONVERSION_DROP
            conv_drop = [a for a in res.anomalies if a.anomaly_type.value == "CONVERSION_DROP"][0]
            assert conv_drop.severity.value == "WARN"

    @pytest.mark.asyncio
    async def test_get_anomalies_invalid_datetimes_and_short_history(self):
        mock_db = MagicMock(spec=AsyncSession)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "sqlite"
        mock_db.bind = mock_bind

        mock_queue = MagicMock()
        mock_queue.scalar.return_value = 0
        
        mock_today = MagicMock()
        mock_today.scalar.return_value = 0.05
        
        mock_seven = MagicMock()
        mock_seven.scalar.return_value = 0.50
        
        mock_earliest = MagicMock()
        mock_earliest.scalar.return_value = None  # None to trigger has_7_days = False branch (line 140)
        
        mock_active = MagicMock()
        mock_active.all.return_value = []  # both dead
        
        mock_abandon = MagicMock()
        mock_abandon.scalar.return_value = 0.0
        
        # Dead zones last visits: None and invalid-date
        mock_visit_none = MagicMock()
        mock_visit_none.scalar.return_value = None
        
        mock_visit_invalid = MagicMock()
        mock_visit_invalid.scalar.return_value = "invalid-date-format"
        
        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [
            mock_queue,
            mock_today,
            mock_seven,
            mock_earliest,
            mock_active,
            mock_abandon,
            mock_visit_none,
            mock_visit_invalid
        ]
        
        with patch("app.anomalies.get_layout_zones", return_value=["AISLE_01", "AISLE_02"]):
            res = await get_anomalies("STORE_BLR_002", mock_db)
            
            # Verify conversion drop has INFO severity because of invalid/short history
            conv_drop = [a for a in res.anomalies if a.anomaly_type.value == "CONVERSION_DROP"][0]
            assert conv_drop.severity.value == "INFO"

            # Verify dead zones are listed
            dead_zones = [a for a in res.anomalies if a.anomaly_type.value == "DEAD_ZONE"]
            assert len(dead_zones) == 2

    @pytest.mark.asyncio
    async def test_get_anomalies_earliest_session_invalid_date(self):
        mock_db = MagicMock(spec=AsyncSession)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "sqlite"
        mock_db.bind = mock_bind

        mock_queue = MagicMock()
        mock_queue.scalar.return_value = 0
        mock_today = MagicMock()
        mock_today.scalar.return_value = 0.05
        mock_seven = MagicMock()
        mock_seven.scalar.return_value = 0.50
        
        mock_earliest = MagicMock()
        mock_earliest.scalar.return_value = "invalid-date"  # invalid date to trigger exception catch (line 133)
        
        mock_active = MagicMock()
        mock_active.all.return_value = []
        mock_abandon = MagicMock()
        mock_abandon.scalar.return_value = 0.0
        
        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [
            mock_queue,
            mock_today,
            mock_seven,
            mock_earliest,
            mock_active,
            mock_abandon
        ]
        
        with patch("app.anomalies.get_layout_zones", return_value=[]):
            res = await get_anomalies("STORE_BLR_002", mock_db)
            conv_drop = [a for a in res.anomalies if a.anomaly_type.value == "CONVERSION_DROP"][0]
            assert conv_drop.severity.value == "INFO"

    @pytest.mark.asyncio
    async def test_get_anomalies_reverse_timezone_formats(self):
        mock_db = MagicMock(spec=AsyncSession)
        mock_bind = MagicMock()
        mock_bind.dialect.name = "sqlite"
        mock_db.bind = mock_bind

        mock_queue = MagicMock()
        mock_queue.scalar.return_value = 0
        mock_today = MagicMock()
        mock_today.scalar.return_value = 0.05
        mock_seven = MagicMock()
        mock_seven.scalar.return_value = 0.50
        
        # String date without Z to trigger replace(tzinfo=timezone.utc) (line 136)
        mock_earliest = MagicMock()
        mock_earliest.scalar.return_value = "2026-05-01 12:00:00"
        
        mock_active = MagicMock()
        mock_active.all.return_value = []
        mock_abandon = MagicMock()
        mock_abandon.scalar.return_value = 0.0
        
        # String date with Z to trigger endswith("Z") (line 181)
        mock_visit = MagicMock()
        mock_visit.scalar.return_value = "2026-06-03 09:00:00Z"
        
        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [
            mock_queue,
            mock_today,
            mock_seven,
            mock_earliest,
            mock_active,
            mock_abandon,
            mock_visit,
            mock_visit
        ]
        
        with patch("app.anomalies.get_layout_zones", return_value=["AISLE_01", "AISLE_02"]):
            res = await get_anomalies("STORE_BLR_002", mock_db)
            assert len(res.anomalies) > 0


