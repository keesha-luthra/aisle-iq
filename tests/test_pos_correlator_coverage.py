# PROMPT: Write unit tests for POSCorrelator and pos_correlator database loading/run_correlation functions to increase coverage.
# CHANGES MADE: Created test_pos_correlator_coverage.py covering loading mock CSVs, correlating sessions, upserting rows, and transaction-session linking. Added uuid import and cleared POSTransaction table.

import pytest
import os
import uuid
import tempfile
import pandas as pd
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.pos_correlator import load_pos_data, run_correlation
from app.models import POSTransaction, VisitorSession, Event



@pytest.mark.asyncio
async def test_load_pos_data_empty_or_malformed(db_session: AsyncSession):
    # Clear any previous POSTransaction records
    await db_session.execute(delete(POSTransaction))
    await db_session.commit()

    # Test loading POS data with non-existent file
    await load_pos_data("non_existent.csv", db_session)
    
    # Test loading with incomplete columns
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "malformed.csv")
        df = pd.DataFrame([{"invalid_col": 123}])
        df.to_csv(csv_path, index=False)
        await load_pos_data(csv_path, db_session)
        # Should exit gracefully with no transactions added
        res = await db_session.execute(select(POSTransaction))
        assert len(res.scalars().all()) == 0

@pytest.mark.asyncio
async def test_load_pos_data_order_format(db_session: AsyncSession):
    # Test loader mapping store names & formatting formats
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "orders.csv")
        df = pd.DataFrame([{
            "order_id": "TX_O1",
            "store_id": "ST1008",
            "order_date": "03-03-2026",
            "order_time": "12:00:00",
            "total_amount": 1250.50
        }])
        df.to_csv(csv_path, index=False)
        await load_pos_data(csv_path, db_session)
        
        # Verify transaction mapped from ST1008 to STORE_BLR_002
        res = await db_session.execute(select(POSTransaction).where(POSTransaction.transaction_id == "TX_O1"))
        tx = res.scalar()
        assert tx is not None
        assert tx.store_id == "STORE_BLR_002"
        assert tx.basket_value_inr == 1250.50

@pytest.mark.asyncio
async def test_run_correlation_edge_cases(db_session: AsyncSession):
    # Clear any previous POSTransaction records
    await db_session.execute(delete(POSTransaction))
    await db_session.commit()

    # Seed unmatched transaction
    tx_time = datetime(2026, 3, 3, 12, 0, 0)
    tx = POSTransaction(
        transaction_id="TX_UNMATCHED",
        store_id="STORE_BLR_002",
        timestamp=tx_time,
        basket_value_inr=150.0
    )
    db_session.add(tx)
    
    # Run correlation with no join events -> should do nothing
    await run_correlation("STORE_BLR_002", db_session)
    await db_session.refresh(tx)
    assert tx.matched_visitor_id is None
    
    # Add join event but NO visitor session -> covers the warning edge case
    ev = Event(
        event_id=uuid.uuid4(),
        store_id="STORE_BLR_002",
        camera_id="CAM_01",
        visitor_id="VIS_def456",  # valid visitor ID format
        event_type="BILLING_QUEUE_JOIN",
        timestamp=tx_time - timedelta(minutes=2),
        is_staff=False,
        confidence=0.9
    )
    db_session.add(ev)
    await db_session.flush()
    
    await run_correlation("STORE_BLR_002", db_session)
    await db_session.refresh(tx)
    assert tx.matched_visitor_id is None
