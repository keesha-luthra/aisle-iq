from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.schemas import FunnelResponse, FunnelStage

async def get_funnel(store_id: str, window_hours: int, db: AsyncSession) -> FunnelResponse:
    """
    Computes the visitor conversion funnel stages using raw SQL queries.
    """
    # Aligning with utcnow but keeping timezone-awareness for database compatibility
    window_start = (datetime.utcnow() - timedelta(hours=window_hours)).replace(tzinfo=timezone.utc)
    window_end = datetime.utcnow().replace(tzinfo=timezone.utc)

    dialect = db.bind.dialect.name
    is_staff_cond = "is_staff = 0" if dialect == "sqlite" else "is_staff = false"
    is_converted_cond = "is_converted = 1" if dialect == "sqlite" else "is_converted = true"

    # 1. Entry Count: unique visitor_sessions entries
    entry_query = f"""
      SELECT COUNT(DISTINCT visitor_id) FROM visitor_sessions
      WHERE store_id = :store_id AND entry_time >= :window_start
      AND {is_staff_cond}
    """

    # 2. Zone Visit Count: ZONE_ENTER events excluding billing/checkout zones (mid-floor engagement)
    zone_query = f"""
      SELECT COUNT(DISTINCT visitor_id) FROM events
      WHERE store_id = :store_id AND timestamp >= :window_start
      AND event_type = 'ZONE_ENTER' AND {is_staff_cond}
      AND zone_id IS NOT NULL
      AND UPPER(zone_id) NOT LIKE '%BILLING%'
      AND UPPER(zone_id) NOT LIKE '%QUEUE%'
      AND UPPER(zone_id) NOT LIKE '%CHECKOUT%'
      AND UPPER(zone_id) NOT LIKE '%CASH%'
    """

    # 3. Billing Queue Count: unique visitor joins in queue
    billing_query = f"""
      SELECT COUNT(DISTINCT visitor_id) FROM events
      WHERE store_id = :store_id AND timestamp >= :window_start
      AND event_type = 'BILLING_QUEUE_JOIN' AND {is_staff_cond}
    """

    # 4. Purchase Count: unique visitor_sessions marked converted
    purchase_query = f"""
      SELECT COUNT(DISTINCT visitor_id) FROM visitor_sessions
      WHERE store_id = :store_id AND entry_time >= :window_start
      AND {is_converted_cond} AND {is_staff_cond}
    """

    res_entry = await db.execute(text(entry_query), {"store_id": store_id, "window_start": window_start})
    res_zone = await db.execute(text(zone_query), {"store_id": store_id, "window_start": window_start})
    res_billing = await db.execute(text(billing_query), {"store_id": store_id, "window_start": window_start})
    res_purchase = await db.execute(text(purchase_query), {"store_id": store_id, "window_start": window_start})

    entry_count = res_entry.scalar() or 0
    zone_visit_count = res_zone.scalar() or 0
    billing_count = res_billing.scalar() or 0
    purchase_count = res_purchase.scalar() or 0

    # Calculate Dropoffs with safe denominators
    dropoff_entry_to_zone = 1.0 - (zone_visit_count / max(entry_count, 1))
    dropoff_zone_to_billing = 1.0 - (billing_count / max(zone_visit_count, 1))
    dropoff_billing_to_purchase = 1.0 - (purchase_count / max(billing_count, 1))

    stages = FunnelStage(
        entry_count=entry_count,
        zone_visit_count=zone_visit_count,
        billing_queue_count=billing_count,
        purchase_count=purchase_count,
        dropoff_entry_to_zone=round(max(0.0, dropoff_entry_to_zone), 4),
        dropoff_zone_to_queue=round(max(0.0, dropoff_zone_to_billing), 4),
        dropoff_queue_to_purchase=round(max(0.0, dropoff_billing_to_purchase), 4)
    )

    return FunnelResponse(
        store_id=store_id,
        window_start=window_start,
        window_end=window_end,
        stages=stages
    )
