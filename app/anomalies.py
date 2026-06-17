import uuid
import json
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.schemas import AnomalyResponse, Anomaly, AnomalyType, AnomalySeverity
from app.config import settings

def get_layout_zones(store_id: str) -> list:
    """
    Parses store_layout.json to retrieve the configured zones.
    Falls back to a default set if layout file is missing or invalid.
    """
    path = settings.STORE_LAYOUT_PATH
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                layout = json.load(f)
            return [z["zone_id"] for z in layout.get("zones", []) if "zone_id" in z]
        except Exception:
            pass
    return ["AISLE_01", "AISLE_02", "AISLE_03", "ENTRY_AREA", "BILLING"]

async def get_anomalies(store_id: str, db: AsyncSession) -> AnomalyResponse:
    """
    Identifies operations and customer flow anomalies using concurrent raw SQL checks.
    """
    now = datetime.now(timezone.utc)
    five_minutes_ago = now - timedelta(minutes=5)
    today_start = now - timedelta(days=1)
    seven_day_start = now - timedelta(days=7)
    dead_zone_start = now - timedelta(minutes=settings.dead_zone_minutes)
    one_hour_ago = now - timedelta(hours=1)

    dialect = db.bind.dialect.name
    is_staff_cond = "is_staff = 0" if dialect == "sqlite" else "is_staff = false"

    # 1. Billing queue spike check query
    if dialect == "sqlite":
        queue_query = """
          SELECT COALESCE(MAX(CAST(json_extract(metadata, '$.queue_depth') AS INTEGER)), 0)
          FROM events
          WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp >= :five_minutes_ago
        """
    else:
        queue_query = """
          SELECT COALESCE(MAX((metadata->>'queue_depth')::int), 0)
          FROM events
          WHERE store_id = :store_id AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp >= NOW() - INTERVAL '5 minutes'
        """

    # 2. Conversion rate queries
    today_conv_query = f"""
      SELECT
        CAST(COUNT(CASE WHEN is_converted THEN 1 END) AS FLOAT) / NULLIF(COUNT(*), 0) as rate
      FROM visitor_sessions
      WHERE store_id = :store_id AND entry_time >= :today_start AND {is_staff_cond}
    """
    seven_day_conv_query = f"""
      SELECT
        CAST(COUNT(CASE WHEN is_converted THEN 1 END) AS FLOAT) / NULLIF(COUNT(*), 0) as rate
      FROM visitor_sessions
      WHERE store_id = :store_id AND entry_time >= :seven_day_start AND {is_staff_cond}
    """
    earliest_session_query = f"""
      SELECT MIN(entry_time) FROM visitor_sessions
      WHERE store_id = :store_id AND {is_staff_cond}
    """

    # 3. Dead zones active zones query
    active_zones_query = f"""
      SELECT DISTINCT zone_id FROM events
      WHERE store_id = :store_id AND event_type = 'ZONE_ENTER'
      AND timestamp >= :dead_zone_start AND {is_staff_cond}
    """

    # 4. High abandonment rate query
    abandon_query = f"""
      SELECT
        CAST(COUNT(CASE WHEN event_type = 'BILLING_QUEUE_ABANDON' THEN 1 END) AS FLOAT) /
        NULLIF(COUNT(CASE WHEN event_type = 'BILLING_QUEUE_JOIN' THEN 1 END), 0) as rate
      FROM events
      WHERE store_id = :store_id AND timestamp >= :one_hour_ago AND {is_staff_cond}
    """

    # Gather primary query results sequentially
    res_queue = await db.execute(text(queue_query), {"store_id": store_id, "five_minutes_ago": five_minutes_ago} if dialect == "sqlite" else {"store_id": store_id})
    res_today = await db.execute(text(today_conv_query), {"store_id": store_id, "today_start": today_start})
    res_seven = await db.execute(text(seven_day_conv_query), {"store_id": store_id, "seven_day_start": seven_day_start})
    res_earliest = await db.execute(text(earliest_session_query), {"store_id": store_id})
    res_active = await db.execute(text(active_zones_query), {"store_id": store_id, "dead_zone_start": dead_zone_start})
    res_abandon = await db.execute(text(abandon_query), {"store_id": store_id, "one_hour_ago": one_hour_ago})

    anomalies_list = []

    # Check 1: BILLING_QUEUE_SPIKE
    max_queue_depth = res_queue.scalar() or 0
    if max_queue_depth > settings.anomaly_queue_spike_threshold:
        anomalies_list.append(
            Anomaly(
                anomaly_id=uuid.uuid4(),
                store_id=store_id,
                anomaly_type=AnomalyType.BILLING_QUEUE_SPIKE,
                severity=AnomalySeverity.CRITICAL,
                description=f"Max billing queue depth in last 5 minutes reached {max_queue_depth} (Threshold: {settings.anomaly_queue_spike_threshold})",
                suggested_action="Open additional checkout counter or dispatch floor staff to billing area",
                detected_at=now,
                metric_value=float(max_queue_depth),
                threshold=float(settings.anomaly_queue_spike_threshold)
            )
        )

    # Check 2: CONVERSION_DROP
    today_rate = res_today.scalar()
    seven_day_rate = res_seven.scalar()
    earliest_session_time = res_earliest.scalar()

    if today_rate is not None and seven_day_rate is not None:
        threshold_rate = seven_day_rate * (1 - settings.anomaly_conversion_drop_pct)
        if today_rate < threshold_rate:
            if earliest_session_time is not None:
                # Force parsed datetime comparison to be timezone-aware
                if not isinstance(earliest_session_time, datetime):
                    try:
                        clean_str = str(earliest_session_time).replace(" ", "T")
                        if clean_str.endswith("Z"):
                            clean_str = clean_str[:-1] + "+00:00"
                        earliest_session_time = datetime.fromisoformat(clean_str)
                    except Exception:
                        earliest_session_time = now
                if earliest_session_time.tzinfo is None:
                    earliest_session_time = earliest_session_time.replace(tzinfo=timezone.utc)
                data_age = now - earliest_session_time
                has_7_days = data_age >= timedelta(days=7)
            else:
                has_7_days = False

            severity = AnomalySeverity.WARN if has_7_days else AnomalySeverity.INFO
            anomalies_list.append(
                Anomaly(
                    anomaly_id=uuid.uuid4(),
                    store_id=store_id,
                    anomaly_type=AnomalyType.CONVERSION_DROP,
                    severity=severity,
                    description=f"Conversion rate drop detected: Today's rate {today_rate:.2f} is below threshold {threshold_rate:.2f} (7-day avg: {seven_day_rate:.2f})",
                    suggested_action="Review floor staff availability and product display in entry zone",
                    detected_at=now,
                    metric_value=float(today_rate),
                    threshold=float(threshold_rate)
                )
            )

    # Check 3: DEAD_ZONE
    active_zones = {row[0] for row in res_active.all() if row[0] is not None}
    layout_zones = get_layout_zones(store_id)
    dead_zones = [z for z in layout_zones if z not in active_zones]

    if dead_zones:
        # Query last visit time for dead zones concurrently
        last_visit_query = f"""
          SELECT MAX(timestamp) FROM events
          WHERE store_id = :store_id AND event_type = 'ZONE_ENTER'
          AND zone_id = :zone_id AND {is_staff_cond}
        """
        last_visit_results = []
        for zone_id in dead_zones:
            res_visit = await db.execute(text(last_visit_query), {"store_id": store_id, "zone_id": zone_id})
            last_visit_results.append(res_visit)

        for zone_id, res_visit in zip(dead_zones, last_visit_results):
            last_visit_time = res_visit.scalar()
            if last_visit_time is not None:
                if not isinstance(last_visit_time, datetime):
                    try:
                        clean_str = str(last_visit_time).replace(" ", "T")
                        if clean_str.endswith("Z"):
                            clean_str = clean_str[:-1] + "+00:00"
                        last_visit_time = datetime.fromisoformat(clean_str)
                    except Exception:
                        last_visit_time = now
                if last_visit_time.tzinfo is None:
                    last_visit_time = last_visit_time.replace(tzinfo=timezone.utc)
                elapsed_minutes = int((now - last_visit_time).total_seconds() / 60)
            else:
                elapsed_minutes = settings.dead_zone_minutes

            anomalies_list.append(
                Anomaly(
                    anomaly_id=uuid.uuid4(),
                    store_id=store_id,
                    anomaly_type=AnomalyType.DEAD_ZONE,
                    severity=AnomalySeverity.INFO,
                    description=f"Dead zone alert: Zone '{zone_id}' has had no visits for {elapsed_minutes} minutes.",
                    suggested_action=f"Zone {zone_id} has had no visitors for {elapsed_minutes} minutes — check for obstruction or restocking needs",
                    detected_at=now,
                    zone_id=zone_id,
                    metric_value=float(elapsed_minutes),
                    threshold=float(settings.dead_zone_minutes)
                )
            )

    # Check 4: HIGH_ABANDONMENT
    abandonment_rate = res_abandon.scalar()
    if abandonment_rate is not None and abandonment_rate > 0.4:
        anomalies_list.append(
            Anomaly(
                anomaly_id=uuid.uuid4(),
                store_id=store_id,
                anomaly_type=AnomalyType.HIGH_ABANDONMENT,
                severity=AnomalySeverity.WARN,
                description=f"High abandonment rate in billing queue detected: {abandonment_rate:.2f} (Threshold: 0.40)",
                suggested_action="Queue wait time may be excessive — consider express checkout or staff reassignment",
                detected_at=now,
                metric_value=float(abandonment_rate),
                threshold=0.40
            )
        )

    return AnomalyResponse(
        store_id=store_id,
        anomalies=anomalies_list,
        checked_at=now
    )
