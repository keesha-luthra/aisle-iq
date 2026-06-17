from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.schemas import MetricsResponse, LiveMetricsResponse

async def get_live_store_metrics(store_id: str, db: AsyncSession) -> LiveMetricsResponse:
    """Compute live metrics for a store using a short time window (last 5 minutes).
    Returns the same fields as MetricsResponse (via inheritance).
    """
    window_hours = 0  # not used, we'll define minutes directly
    # Define a 5‑minute window ending now
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    window_start = (now - timedelta(minutes=5)).replace(tzinfo=timezone.utc)
    window_end = now
    # Reuse the same query logic as get_store_metrics but with the short window
    dialect = db.bind.dialect.name
    is_staff_cond = "is_staff = 0" if dialect == "sqlite" else "is_staff = false"

    unique_visitors_query = f"""
      SELECT COUNT(DISTINCT visitor_id) FROM visitor_sessions
      WHERE store_id = :store_id AND entry_time >= :window_start
      AND {is_staff_cond}
    """
    conversion_query = f"""
      SELECT
        CAST(COUNT(CASE WHEN is_converted OR visitor_id IN (SELECT visitor_id FROM events WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN') THEN 1 END) AS FLOAT) /
        NULLIF(COUNT(*), 0) as conversion_rate
      FROM visitor_sessions
      WHERE store_id = :store_id AND entry_time >= :window_start AND {is_staff_cond}
    """
    dwell_query = f"""
      SELECT zone_id, AVG(dwell_ms) / 1000.0 as avg_dwell_seconds
      FROM events
      WHERE store_id = :store_id AND timestamp >= :window_start
      AND event_type = 'ZONE_DWELL' AND {is_staff_cond} AND zone_id IS NOT NULL
      GROUP BY zone_id
    """
    if dialect == "sqlite":
        queue_query = """
          SELECT COALESCE(MAX(CAST(json_extract(metadata, '$.queue_depth') AS INTEGER)), 0)
          FROM events
          WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp >= :window_start
        """
    else:
        queue_query = """
          SELECT COALESCE(MAX((metadata->>'queue_depth')::int), 0)
          FROM events
          WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp >= NOW() - INTERVAL '5 minutes'
        """
    abandon_query = f"""
      SELECT
        CAST(COUNT(CASE WHEN event_type = 'BILLING_QUEUE_ABANDON' THEN 1 END) AS FLOAT) /
        NULLIF(COUNT(CASE WHEN event_type = 'BILLING_QUEUE_JOIN' THEN 1 END), 0)
      FROM events
      WHERE store_id = :store_id AND timestamp >= :window_start AND {is_staff_cond}
    """
    res_visitors = await db.execute(text(unique_visitors_query), {"store_id": store_id, "window_start": window_start})
    res_conv = await db.execute(text(conversion_query), {"store_id": store_id, "window_start": window_start})
    res_dwell = await db.execute(text(dwell_query), {"store_id": store_id, "window_start": window_start})
    res_queue = await db.execute(text(queue_query), {"store_id": store_id, "window_start": window_start} if dialect == "sqlite" else {"store_id": store_id})
    res_abandon = await db.execute(text(abandon_query), {"store_id": store_id, "window_start": window_start})
    unique_visitors = res_visitors.scalar() or 0
    conversion_rate = res_conv.scalar() or 0.0
    avg_dwell_by_zone = {}
    for row in res_dwell.all():
        if row[0] is not None:
            avg_dwell_by_zone[str(row[0])] = float(row[1] or 0.0)
    current_queue_depth = res_queue.scalar() or 0
    abandonment_rate = res_abandon.scalar() or 0.0
    return LiveMetricsResponse(
        store_id=store_id,
        window_start=window_start,
        window_end=window_end,
        unique_visitors=unique_visitors,
        conversion_rate=min(1.0, max(0.0, conversion_rate)),
        avg_dwell_by_zone=avg_dwell_by_zone,
        current_queue_depth=current_queue_depth,
        abandonment_rate=abandonment_rate
    )


async def get_store_metrics(store_id: str, window_hours: int, db: AsyncSession) -> MetricsResponse:
    """Compute store metrics for the given window (in hours)."""
    # Define window
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    window_start = (now - timedelta(hours=window_hours)).replace(tzinfo=timezone.utc)
    window_end = now

    dialect = db.bind.dialect.name
    is_staff_cond = "is_staff = 0" if dialect == "sqlite" else "is_staff = false"

    unique_visitors_query = f"""
      SELECT COUNT(DISTINCT visitor_id) FROM visitor_sessions
      WHERE store_id = :store_id AND entry_time >= :window_start
      AND {is_staff_cond}
    """
    conversion_query = f"""
      SELECT
        CAST(COUNT(CASE WHEN is_converted OR visitor_id IN (SELECT visitor_id FROM events WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN') THEN 1 END) AS FLOAT) /
        NULLIF(COUNT(*), 0) as conversion_rate
      FROM visitor_sessions
      WHERE store_id = :store_id AND entry_time >= :window_start AND {is_staff_cond}
    """
    dwell_query = f"""
      SELECT zone_id, AVG(dwell_ms) / 1000.0 as avg_dwell_seconds
      FROM events
      WHERE store_id = :store_id AND timestamp >= :window_start
      AND event_type = 'ZONE_DWELL' AND {is_staff_cond} AND zone_id IS NOT NULL
      GROUP BY zone_id
    """
    # Queue depth logic (10‑minute window for live, full window for regular)
    if dialect == "sqlite":
        queue_query = """
          SELECT COALESCE(MAX(CAST(json_extract(metadata, '$.queue_depth') AS INTEGER)), 0)
          FROM events
          WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp >= :window_start
        """
    else:
        queue_query = """
          SELECT COALESCE(MAX((metadata->>'queue_depth')::int), 0)
          FROM events
          WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp >= :window_start
        """
    abandon_query = f"""
      SELECT
        CAST(COUNT(CASE WHEN event_type = 'BILLING_QUEUE_ABANDON' THEN 1 END) AS FLOAT) /
        NULLIF(COUNT(CASE WHEN event_type = 'BILLING_QUEUE_JOIN' THEN 1 END), 0)
      FROM events
      WHERE store_id = :store_id AND timestamp >= :window_start AND {is_staff_cond}
    """
    res_visitors = await db.execute(text(unique_visitors_query), {"store_id": store_id, "window_start": window_start})
    res_conv = await db.execute(text(conversion_query), {"store_id": store_id, "window_start": window_start})
    res_dwell = await db.execute(text(dwell_query), {"store_id": store_id, "window_start": window_start})
    res_queue = await db.execute(text(queue_query), {"store_id": store_id, "window_start": window_start})
    res_abandon = await db.execute(text(abandon_query), {"store_id": store_id, "window_start": window_start})
    unique_visitors = res_visitors.scalar() or 0
    conversion_rate = res_conv.scalar() or 0.0
    avg_dwell_by_zone = {}
    for row in res_dwell.all():
        if row[0] is not None:
            avg_dwell_by_zone[str(row[0])] = float(row[1] or 0.0)
    current_queue_depth = res_queue.scalar() or 0
    abandonment_rate = res_abandon.scalar() or 0.0
    return MetricsResponse(
        store_id=store_id,
        window_start=window_start,
        window_end=window_end,
        unique_visitors=unique_visitors,
        conversion_rate=min(1.0, max(0.0, conversion_rate)),
        avg_dwell_by_zone=avg_dwell_by_zone,
        current_queue_depth=current_queue_depth,
        abandonment_rate=abandonment_rate,
    )


async def get_camera_analytics(store_id: str, db: AsyncSession) -> dict:
    """
    Computes real-time per-camera visitor metrics and store-level peak traffic hours.
    """
    dialect = db.bind.dialect.name
    is_staff_cond = "is_staff = 0" if dialect == "sqlite" else "is_staff = false"
    
    # Define five minutes ago based on the most recent event in the DB to simulate "live" data
    res_max = await db.execute(text("SELECT MAX(timestamp) FROM events WHERE store_id = :store_id"), {"store_id": store_id})
    max_ts = res_max.scalar()
    if max_ts:
        if isinstance(max_ts, str):
            try:
                max_ts = datetime.fromisoformat(max_ts)
            except Exception:
                max_ts = None
        if isinstance(max_ts, datetime):
            if max_ts.tzinfo is None:
                max_ts = max_ts.replace(tzinfo=timezone.utc)
            now = max_ts
        else:
            now = datetime.utcnow().replace(tzinfo=timezone.utc)
    else:
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
    five_min_ago = now - timedelta(minutes=5)
    
    camera_ids = ["CAM_01", "CAM_02", "CAM_03", "CAM_05"]
    cameras_stats = {}
    
    for cam_id in camera_ids:
        # 1. Active visitors (seen in last 5 minutes)
        active_query = f"""
            SELECT DISTINCT visitor_id FROM events
            WHERE store_id = :store_id AND camera_id = :camera_id AND timestamp >= :five_min_ago AND {is_staff_cond}
        """
        # 2. Entries (total unique visitors seen on this camera)
        entries_query = f"""
            SELECT COUNT(DISTINCT visitor_id) FROM events
            WHERE store_id = :store_id AND camera_id = :camera_id AND {is_staff_cond}
        """
        # 3. Exits (visitors who triggered ZONE_EXIT or general EXIT from this camera)
        exits_query = f"""
            SELECT COUNT(DISTINCT visitor_id) FROM events
            WHERE store_id = :store_id AND camera_id = :camera_id AND event_type IN ('ZONE_EXIT', 'EXIT') AND {is_staff_cond}
        """
        # 4. Active tracks (unique track_ids in last 5 minutes)
        tracks_query = f"""
            SELECT COUNT(DISTINCT track_id) FROM events
            WHERE store_id = :store_id AND camera_id = :camera_id AND timestamp >= :five_min_ago AND track_id IS NOT NULL
        """
        
        params = {"store_id": store_id, "camera_id": cam_id, "five_min_ago": five_min_ago}
        res_active = await db.execute(text(active_query), params)
        active_vids = [row[0] for row in res_active.all()]
        
        res_entries = await db.execute(text(entries_query), params)
        res_exits = await db.execute(text(exits_query), params)
        res_tracks = await db.execute(text(tracks_query), params)
        
        cameras_stats[cam_id] = {
            "active_visitors_count": len(active_vids),
            "active_visitors": active_vids,
            "entries": res_entries.scalar() or 0,
            "exits": res_exits.scalar() or 0,
            "active_tracks": res_tracks.scalar() or 0
        }
        
    # 5. Billing visitors (unique visitors who joined queue)
    billing_query = f"""
        SELECT COUNT(DISTINCT visitor_id) FROM events
        WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN' AND {is_staff_cond}
    """
    res_billing = await db.execute(text(billing_query), {"store_id": store_id})
    billing_visitors = res_billing.scalar() or 0
    
    # 6. Peak traffic hour
    if dialect == "sqlite":
        peak_query = f"""
            SELECT strftime('%H', timestamp) as hr, COUNT(DISTINCT visitor_id) as cnt
            FROM events
            WHERE store_id = :store_id AND {is_staff_cond}
            GROUP BY hr
            ORDER BY cnt DESC
            LIMIT 1
        """
    else:
        peak_query = f"""
            SELECT EXTRACT(HOUR FROM timestamp) as hr, COUNT(DISTINCT visitor_id) as cnt
            FROM events
            WHERE store_id = :store_id AND {is_staff_cond}
            GROUP BY hr
            ORDER BY cnt DESC
            LIMIT 1
        """
    res_peak = await db.execute(text(peak_query), {"store_id": store_id})
    peak_row = res_peak.first()
    
    if peak_row and peak_row[0] is not None:
        try:
            hr_int = int(float(peak_row[0]))
            peak_traffic_hour = f"{hr_int:02d}:00 - {hr_int+1:02d}:00"
        except ValueError:
            peak_traffic_hour = "12:00 - 13:00"
    else:
        peak_traffic_hour = "12:00 - 13:00"
        
    return {
        "store_id": store_id,
        "cameras": cameras_stats,
        "billing_visitors": billing_visitors,
        "peak_traffic_hour": peak_traffic_hour
    }
