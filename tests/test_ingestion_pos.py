# PROMPT: We are in store-intelligence/tests/. Write tests for POS data loading, visitor-to-transaction correlation, and ingest validation with duplicate and invalid event mixes.
# CHANGES MADE: Created test_ingestion_pos.py with POS CSV load tests, session correlation assertions, and mixed-batch ingest validation.
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy import select
from app.models import Event, VisitorSession, POSTransaction
from app.pos_correlator import load_pos_data, run_correlation

@pytest.mark.asyncio
async def test_pos_data_loading_and_correlation(client: AsyncClient, db_session, tmp_path):
    # 1. Create a mock POS transaction CSV
    csv_file = tmp_path / "pos_test.csv"
    tx_time1 = datetime.now(timezone.utc)
    tx_time2 = tx_time1 - timedelta(minutes=1)
    
    csv_content = f"""transaction_id,store_id,timestamp,basket_value_inr
TX_001,STORE_BLR_002,{tx_time1.isoformat()},500.50
TX_002,STORE_BLR_002,{tx_time2.isoformat()},150.00
"""
    csv_file.write_text(csv_content, encoding="utf-8")
    
    # 2. Call load_pos_data
    await load_pos_data(str(csv_file), db_session)
    
    # Verify transaction rows exist
    stmt = select(POSTransaction).where(POSTransaction.store_id == "STORE_BLR_002")
    res = await db_session.execute(stmt)
    txs = res.scalars().all()
    assert len(txs) == 2
    assert any(t.transaction_id == "TX_001" for t in txs)
    
    # 3. Create a visitor session
    visitor_id = "VIS_1a2b3c"
    session_id = uuid.uuid4()
    entry_time = tx_time1 - timedelta(minutes=4)
    sess = VisitorSession(
        session_id=session_id,
        visitor_id=visitor_id,
        store_id="STORE_BLR_002",
        entry_time=entry_time,
        is_staff=False
    )
    db_session.add(sess)
    
    # 4. Insert BILLING_QUEUE_JOIN event for this visitor
    # Occurs 3 minutes before tx_time1 (within the 5 minute lookback window)
    event_id = uuid.uuid4()
    join_ev = Event(
        event_id=event_id,
        store_id="STORE_BLR_002",
        camera_id="CAM_01",
        visitor_id=visitor_id,
        event_type="BILLING_QUEUE_JOIN",
        timestamp=tx_time1 - timedelta(minutes=3),
        dwell_ms=0,
        is_staff=False,
        confidence=0.9,
        event_metadata={"queue_depth": 2}
    )
    db_session.add(join_ev)
    await db_session.flush()
    
    # 5. Run correlation
    await run_correlation("STORE_BLR_002", db_session, commit=False)
    
    # 6. Verify matched transaction and converted session
    stmt_tx = select(POSTransaction).where(POSTransaction.transaction_id == "TX_001")
    res_tx = await db_session.execute(stmt_tx)
    tx = res_tx.scalar_one()
    
    assert tx.matched_visitor_id == visitor_id
    assert tx.matched_session_id == session_id
    
    # Verify session is marked converted
    stmt_sess = select(VisitorSession).where(VisitorSession.session_id == session_id)
    res_sess = await db_session.execute(stmt_sess)
    session_obj = res_sess.scalar_one()
    assert session_obj.is_converted is True

@pytest.mark.asyncio
async def test_ingest_duplicate_and_validation_errors(client: AsyncClient, db_session):
    # Prepare batch containing valid, duplicate, and invalid events
    event_id_1 = uuid.uuid4()
    event_id_2 = uuid.uuid4()
    
    # Ingest the first event to set up a duplicate
    payload_setup = {
        "events": [
            {
                "event_id": str(event_id_1),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_abc111",
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dwell_ms": 1000,
                "confidence": 0.95
            }
        ]
    }
    setup_resp = await client.post("/events/ingest", json=payload_setup)
    assert setup_resp.status_code == 200
    
    # Now ingest a batch containing:
    # 1. A new valid event
    # 2. A duplicate of the setup event (by event_id)
    # 3. An invalid event (violating visitor_id hex pattern)
    payload_batch = {
        "events": [
            {
                "event_id": str(event_id_2),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_abc222",
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dwell_ms": 2000,
                "confidence": 0.90
            },
            {
                "event_id": str(event_id_1),  # Duplicate
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_abc111",
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dwell_ms": 1000,
                "confidence": 0.95
            },
            {
                "event_id": str(uuid.uuid4()),
                "store_id": "STORE_BLR_002",
                "camera_id": "CAM_01",
                "visitor_id": "VIS_nonhex",  # Invalid visitor_id
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dwell_ms": 1000,
                "confidence": 0.95
            }
        ]
    }
    
    resp = await client.post("/events/ingest", json=payload_batch)
    assert resp.status_code == 200
    data = resp.json()
    
    assert data["accepted"] == 1
    assert data["duplicate"] == 1
    assert data["rejected"] == 1
    assert len(data["errors"]) == 2
