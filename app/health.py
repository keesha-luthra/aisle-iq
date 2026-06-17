from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.schemas import HealthResponse, StoreHealth
from app.config import settings

async def get_health(db: AsyncSession) -> HealthResponse:
    """
    Performs system readiness checks, evaluating database connectivity
    and feed ingestion lags per active store.
    """
    now_utc = datetime.utcnow()

    # 1. Check DB connectivity
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    # If DB is down, return DEGRADED status immediately
    if not db_ok:
        return HealthResponse(
            api_version="1.0.0",
            checked_at=now_utc.replace(tzinfo=timezone.utc),
            stores=[
                StoreHealth(
                    store_id="ALL",
                    status="DEGRADED",
                    last_event_at=None,
                    lag_seconds=None,
                    warning="DATABASE_UNAVAILABLE"
                )
            ]
        )

    # 2. Per-store health: get last event timestamp for each known store_id
    query = """
      SELECT store_id, MAX(timestamp) as last_event_at
      FROM events
      GROUP BY store_id
    """
    
    try:
        result = await db.execute(text(query))
        rows = result.all()
    except Exception:
        # If query fails, treat as database unavailable
        return HealthResponse(
            api_version="1.0.0",
            checked_at=now_utc.replace(tzinfo=timezone.utc),
            stores=[
                StoreHealth(
                    store_id="ALL",
                    status="DEGRADED",
                    last_event_at=None,
                    lag_seconds=None,
                    warning="DATABASE_UNAVAILABLE"
                )
            ]
        )

    store_healths = []
    for row in rows:
        last_event_at = row.last_event_at
        if last_event_at is not None:
            # SQLite stores dates as strings, parse them if needed
            if isinstance(last_event_at, str):
                try:
                    clean_str = last_event_at.replace(" ", "T")
                    last_event_dt = datetime.fromisoformat(clean_str)
                except Exception:
                    last_event_dt = now_utc
            else:
                last_event_dt = last_event_at

            # Strip timezone if present to perform timezone-safe subtraction with datetime.utcnow()
            last_event_naive = last_event_dt.replace(tzinfo=None) if last_event_dt.tzinfo is not None else last_event_dt
            lag_seconds = (now_utc - last_event_naive).total_seconds()
            
            if lag_seconds > settings.stale_feed_seconds:
                status = "STALE"
                warning = "STALE_FEED"
            else:
                status = "OK"
                warning = None
                
            store_healths.append(
                StoreHealth(
                    store_id=str(row.store_id),
                    status=status,
                    last_event_at=last_event_dt,
                    lag_seconds=lag_seconds,
                    warning=warning
                )
            )

    # If no events in DB at all, return single store health with status STALE
    if not store_healths:
        store_healths = [
            StoreHealth(
                store_id="UNKNOWN",
                status="STALE",
                last_event_at=None,
                lag_seconds=None,
                warning="NO_DATA"
            )
        ]

    return HealthResponse(
        api_version="1.0.0",
        checked_at=now_utc.replace(tzinfo=timezone.utc),
        stores=store_healths
    )
