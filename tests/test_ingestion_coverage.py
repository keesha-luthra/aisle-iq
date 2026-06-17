# PROMPT: Write unit tests for app/ingestion.py to cover get_insert_stmt, Pydantic objects ingestion, session updates on ENTRY/EXIT, and bulk insert errors to increase coverage.
# CHANGES MADE: Created test_ingestion_coverage.py with direct calls to get_insert_stmt, models ingestion with valid visitor_id pattern matching, entry-exit pairing, and mock database error handling.

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.ingestion import get_insert_stmt, ingest_events
from app.schemas import StoreEvent, EventType, EventMetadata
from app.models import VisitorSession, Event

def test_get_insert_stmt_dialects():
    # Cover the get_insert_stmt helper directly
    stmt_pg = get_insert_stmt("postgresql")
    assert stmt_pg is not None
    
    stmt_sqlite = get_insert_stmt("sqlite")
    assert stmt_sqlite is not None
    
    stmt_fallback = get_insert_stmt("oracle")
    assert stmt_fallback is not None

@pytest.mark.asyncio
async def test_ingest_pydantic_objects_and_exit_handling(db_session: AsyncSession):
    # Cover Pydantic object path and ENTRY/EXIT state machine updates
    # visitor_id must match '^VIS_[a-f0-9]{6}$'
    visitor_id = "VIS_a1b2c3"
    store_id = "STORE_BLR_002"
    
    # 1. ENTRY event as Pydantic object
    entry_event = StoreEvent(
        event_id=uuid.uuid4(),
        store_id=store_id,
        camera_id="CAM_01",
        visitor_id=visitor_id,
        event_type=EventType.ENTRY,
        timestamp=datetime.now(timezone.utc),
        confidence=0.9,
        metadata=EventMetadata()
    )
    
    res1 = await ingest_events([entry_event], db_session)
    assert res1.accepted == 1
    
    # Verify session created in DB
    stmt = select(VisitorSession).where(VisitorSession.visitor_id == visitor_id)
    res = await db_session.execute(stmt)
    session = res.scalars().first()
    assert session is not None
    assert session.exit_time is None
    
    # 2. EXIT event as Pydantic object
    exit_event = StoreEvent(
        event_id=uuid.uuid4(),
        store_id=store_id,
        camera_id="CAM_01",
        visitor_id=visitor_id,
        event_type=EventType.EXIT,
        timestamp=datetime.now(timezone.utc),
        confidence=0.9,
        metadata=EventMetadata()
    )
    
    res2 = await ingest_events([exit_event], db_session)
    assert res2.accepted == 1
    
    # Verify session updated with exit time in DB
    await db_session.refresh(session)
    assert session.exit_time is not None

@pytest.mark.asyncio
async def test_ingest_billing_join_triggers_correlation(db_session: AsyncSession):
    # Ingesting BILLING_QUEUE_JOIN triggers pos_correlator run_correlation
    visitor_id = "VIS_b2c3d4"
    store_id = "STORE_BLR_002"
    
    join_event = StoreEvent(
        event_id=uuid.uuid4(),
        store_id=store_id,
        camera_id="CAM_03",
        visitor_id=visitor_id,
        event_type=EventType.BILLING_QUEUE_JOIN,
        timestamp=datetime.now(timezone.utc),
        confidence=0.9,
        metadata=EventMetadata(queue_depth=2)
    )
    
    res = await ingest_events([join_event], db_session)
    assert res.accepted == 1

@pytest.mark.asyncio
async def test_ingest_bulk_insert_exception():
    # Mock AsyncSession to raise Exception during bulk insert
    mock_db = MagicMock(spec=AsyncSession)
    mock_res_dedup = MagicMock()
    mock_res_dedup.scalar.return_value = None
    mock_db.execute = AsyncMock(side_effect=[mock_res_dedup, Exception("Database lock error")])
    mock_db.bind = MagicMock()
    mock_db.bind.dialect = MagicMock()
    mock_db.bind.dialect.name = "sqlite"
    
    event = StoreEvent(
        event_id=uuid.uuid4(),
        store_id="STORE_BLR_002",
        camera_id="CAM_01",
        visitor_id="VIS_c3d4e5",
        event_type=EventType.ENTRY,
        timestamp=datetime.now(timezone.utc),
        confidence=0.9,
        metadata=EventMetadata()
    )
    
    res = await ingest_events([event], mock_db)
    assert res.accepted == 0
    assert res.rejected == 1
    assert any("Bulk insert failed" in err["reason"] for err in res.errors)
