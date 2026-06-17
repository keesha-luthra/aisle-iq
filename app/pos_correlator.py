import pandas as pd
from datetime import datetime, timedelta


import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import POSTransaction, VisitorSession, Event

logger = structlog.get_logger()

async def load_pos_data(csv_path: str, db: AsyncSession):
    """
    Read pos_transactions.csv using pandas.
    Supports both the real Brigade CSV format (order_id, order_date, order_time, total_amount)
    and the mock format (transaction_id, timestamp, basket_value_inr).
    For each row: upsert into pos_transactions table.
    """
    logger.info("Loading POS transaction data from CSV", path=csv_path)
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception as e:
        logger.error("Failed to read POS CSV file", path=csv_path, error=str(e))
        return

    # Map from real store_id to pipeline store_id
    STORE_ID_MAP = {
        "ST1008": "STORE_BLR_002",
        "ST1076": "STORE_MUM_076",
        "store_1076": "STORE_MUM_076"
    }

    loaded = 0
    for _, row in df.iterrows():
        # --- Resolve transaction_id ---
        if "transaction_id" in row and pd.notna(row.get("transaction_id")):
            transaction_id = str(row["transaction_id"])
        elif "order_id" in row and pd.notna(row.get("order_id")):
            transaction_id = str(row["order_id"])
        elif "invoice_number" in row and pd.notna(row.get("invoice_number")):
            transaction_id = str(row["invoice_number"])
        else:
            continue

        # --- Resolve store_id ---
        raw_store = str(row.get("store_id", ""))
        store_id = STORE_ID_MAP.get(raw_store, raw_store)
        # Normalize resolved store_id
        if not store_id.startswith("STORE_"):
            if store_id.startswith("ST"):
                digits = "".join(filter(str.isdigit, store_id))
                if digits:
                    store_id = f"STORE_{digits}"
            else:
                digits = "".join(filter(str.isdigit, store_id))
                if digits:
                    store_id = f"STORE_{digits}"

        # --- Resolve timestamp ---
        ts = None
        if "timestamp" in row and pd.notna(row.get("timestamp")):
            try:
                ts = pd.to_datetime(row["timestamp"]).to_pydatetime()
            except Exception:
                pass
        if ts is None and "order_date" in row and pd.notna(row.get("order_date")):
            try:
                date_str = str(row["order_date"])
                time_str = str(row.get("order_time", "00:00:00")) if pd.notna(row.get("order_time")) else "00:00:00"
                ts = pd.to_datetime(f"{date_str} {time_str}", dayfirst=True).to_pydatetime()
            except Exception:
                logger.warning("Skipping POS row with unparseable date", transaction_id=transaction_id)
                continue
        if ts is None:
            continue

        # --- Resolve basket value ---
        basket_value = 0.0
        for col in ("basket_value_inr", "total_amount", "NMV", "GMV"):
            if col in row and pd.notna(row.get(col)):
                try:
                    basket_value = float(row[col])
                    break
                except (ValueError, TypeError):
                    pass

        # Upsert
        stmt = select(POSTransaction).where(POSTransaction.transaction_id == transaction_id)
        res = await db.execute(stmt)
        tx = res.scalar_one_or_none()

        if tx:
            tx.store_id = store_id
            tx.timestamp = ts
            tx.basket_value_inr = basket_value
        else:
            tx = POSTransaction(
                transaction_id=transaction_id,
                store_id=store_id,
                timestamp=ts,
                basket_value_inr=basket_value
            )
            db.add(tx)
        loaded += 1

    await db.commit()
    logger.info("Successfully loaded/upserted POS transaction data", rows_loaded=loaded)

async def run_correlation(store_id: str, db: AsyncSession, commit: bool = True):
    """
    For each unmatched POS transaction (matched_visitor_id IS NULL) for this store:
      Look back 5 minutes from transaction timestamp.
      Find visitor_id(s) that had a BILLING_QUEUE_JOIN event in that window.
      If exactly one match: set matched_visitor_id, matched_session_id; mark session is_converted=True.
      If multiple matches: pick the one whose BILLING_QUEUE_JOIN is closest in time to transaction.
      Log correlation result.
    """
    logger.info("Running POS transaction correlation", store_id=store_id)
    stmt = (
        select(POSTransaction)
        .where(
            POSTransaction.store_id == store_id,
            POSTransaction.matched_visitor_id == None
        )
    )
    res = await db.execute(stmt)
    unmatched_txs = res.scalars().all()

    if not unmatched_txs:
        logger.info("No unmatched POS transactions found for correlation", store_id=store_id)
        return

    correlated_count = 0
    for tx in unmatched_txs:
        # 5-minute lookback window
        window_start = tx.timestamp - timedelta(minutes=5)
        window_end = tx.timestamp

        stmt_events = (
            select(Event)
            .where(
                Event.store_id == store_id,
                Event.event_type == "BILLING_QUEUE_JOIN",
                Event.timestamp >= window_start,
                Event.timestamp <= window_end
            )
        )
        res_events = await db.execute(stmt_events)
        join_events = res_events.scalars().all()

        if not join_events:
            continue

        # Find closest join event in time to the transaction
        best_event = min(join_events, key=lambda e: abs((e.timestamp.replace(tzinfo=None) - tx.timestamp.replace(tzinfo=None)).total_seconds()))
        matched_vid = best_event.visitor_id

        # Find the most recent session for this visitor in the store
        stmt_session = (
            select(VisitorSession)
            .where(
                VisitorSession.visitor_id == matched_vid,
                VisitorSession.store_id == store_id
            )
            .order_by(VisitorSession.entry_time.desc())
        )
        res_session = await db.execute(stmt_session)
        session = res_session.scalars().first()

        if session:
            tx.matched_visitor_id = matched_vid
            tx.matched_session_id = session.session_id
            session.is_converted = True
            correlated_count += 1
            logger.info(
                "Successfully correlated POS transaction to visitor session",
                transaction_id=tx.transaction_id,
                visitor_id=matched_vid,
                session_id=str(session.session_id),
                store_id=store_id
            )
        else:
            logger.warn(
                "Found matching BILLING_QUEUE_JOIN event but no visitor session exists for correlation",
                transaction_id=tx.transaction_id,
                visitor_id=matched_vid,
                store_id=store_id
            )

    if correlated_count > 0 and commit:
        await db.commit()
    logger.info("Finished POS transaction correlation run", store_id=store_id, correlated_count=correlated_count)

