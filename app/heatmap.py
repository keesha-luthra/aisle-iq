from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.schemas import HeatmapResponse, HeatmapZone

async def get_heatmap(store_id: str, window_hours: int, db: AsyncSession) -> HeatmapResponse:
    """
    Computes visitor spatial distribution and average dwell time per zone using raw SQL.
    """
    window_start = (datetime.utcnow() - timedelta(hours=window_hours)).replace(tzinfo=timezone.utc)

    dialect = db.bind.dialect.name
    is_staff_cond = "is_staff = 0" if dialect == "sqlite" else "is_staff = false"

    query = f"""
      SELECT
        zone_id,
        COUNT(DISTINCT visitor_id) as visit_frequency,
        AVG(dwell_ms) / 1000.0 as avg_dwell_seconds,
        COUNT(DISTINCT visitor_id) as session_count
      FROM events
      WHERE store_id = :store_id
        AND timestamp >= :window_start
        AND {is_staff_cond}
        AND zone_id IS NOT NULL
        AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
      GROUP BY zone_id
    """

    result = await db.execute(text(query), {"store_id": store_id, "window_start": window_start})
    rows = result.all()

    # Normalise visit_frequency to 0–100 scale (min-max normalization)
    max_visits = max((row.visit_frequency for row in rows), default=1)

    zones = []
    for row in rows:
        normalised_score = round((row.visit_frequency / max_visits) * 100.0, 1)
        # data_confidence flag: False if fewer than 20 sessions in window
        data_confidence = row.session_count >= 20

        zones.append(
            HeatmapZone(
                zone_id=str(row.zone_id),
                visit_frequency=row.visit_frequency,
                avg_dwell_seconds=float(row.avg_dwell_seconds or 0.0),
                normalised_score=normalised_score,
                data_confidence=data_confidence
            )
        )

    return HeatmapResponse(
        store_id=store_id,
        zones=zones,
        generated_at=datetime.utcnow().replace(tzinfo=timezone.utc)
    )
