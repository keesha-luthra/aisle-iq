import uuid
import structlog
import pandas as pd
from typing import List
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import Event, VisitorSession, GlobalVisitorMatch
from app.schemas import IngestResponse, StoreEvent, EventType

logger = structlog.get_logger()

def get_insert_stmt(dialect_name: str):
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy import insert
    return insert

def clean_store_id(code: str) -> str:
    if not code:
        return "STORE_BLR_002"
    import re
    cleaned = str(code).upper().replace(" ", "_")
    if cleaned.startswith("STORE_") and len(cleaned) == 13:
        if re.match(r"^STORE_[A-Z]{3}_\d{3}$", cleaned):
            return cleaned
            
    digits = "".join(filter(str.isdigit, cleaned))
    if not digits:
        return "STORE_BLR_002"
        
    city = "MUM"
    if "BLR" in cleaned:
        city = "BLR"
    elif "DEL" in cleaned:
        city = "DEL"
    elif "MUM" in cleaned or "1076" in cleaned:
        city = "MUM"
        
    if len(digits) > 3:
        padded_digits = digits[-3:]
    else:
        padded_digits = digits.zfill(3)
        
    return f"STORE_{city}_{padded_digits}"

def clean_camera_id(cam: str) -> str:
    if not cam:
        return "CAM_01"
    cleaned = str(cam).upper().replace(" ", "_")
    if cleaned == "CAM1": return "CAM_01"
    if cleaned == "CAM2": return "CAM_02"
    if cleaned == "CAM3": return "CAM_03"
    if cleaned == "CAM4": return "CAM_04"
    if cleaned == "CAM5": return "CAM_05"
    return cleaned

def clean_visitor_id(val) -> str:
    if val is None:
        return "VIS_000000"
    s = str(val).upper().strip()
    if s.startswith("ID_"):
        digits = s[3:]
    elif s.startswith("VIS_"):
        digits = s[4:]
    else:
        digits = str(s)
    hex_digits = "".join([c for c in digits.lower() if c in "0123456789abcdef"])
    if not hex_digits:
        hex_digits = "000000"
    padded = hex_digits.zfill(6)[:6]
    return f"VIS_{padded}"

def to_iso_utc(ts_str: str) -> str:
    if not ts_str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
    # If no timezone info, append Z
    if not ts_str.endswith("Z") and "+" not in ts_str and "-" not in ts_str[10:]:
        return ts_str + "Z"
    return ts_str

def normalize_event_dict(event: dict) -> List[dict]:
    """
    Normalizes incoming event dict from new schema format (sample_eventsbe42122.jsonl)
    to the traditional StoreEvent schema format.
    """
    event_type = event.get("event_type", "")
    
    # If already in the old format, return as-is
    if "event_id" in event and "event_type" in event and str(event["event_type"]).upper() in ("ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL", "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"):
        return [event]
        
    normalized = []
    import uuid

    if event_type in ("entry", "exit"):
        store_id = clean_store_id(event.get("store_code", event.get("store_id", "")))
        camera_id = clean_camera_id(event.get("camera_id", ""))
        visitor_id = clean_visitor_id(event.get("id_token", event.get("visitor_id", "")))
        timestamp = to_iso_utc(event.get("event_timestamp", event.get("timestamp", "")))
        is_staff = bool(event.get("is_staff", False))
        
        meta = {}
        for k in ("gender_pred", "age_pred", "age_bucket", "is_face_hidden", "group_id", "group_size"):
            if k in event:
                meta[k] = event[k]
        
        normalized.append({
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": "ENTRY" if event_type == "entry" else "EXIT",
            "timestamp": timestamp,
            "confidence": 1.0,
            "dwell_ms": 0,
            "is_staff": is_staff,
            "metadata": meta
        })
        
    elif event_type in ("zone_entered", "zone_exited"):
        store_id = clean_store_id(event.get("store_id", event.get("store_code", "")))
        camera_id = clean_camera_id(event.get("camera_id", ""))
        visitor_id = clean_visitor_id(event.get("track_id", event.get("visitor_id", "")))
        timestamp = to_iso_utc(event.get("event_time", event.get("timestamp", "")))
        
        meta = {}
        for k in ("zone_name", "zone_type", "is_revenue_zone", "zone_hotspot_x", "zone_hotspot_y", "gender", "age", "age_bucket"):
            if k in event:
                meta[k] = event[k]
                
        sku_zone = event.get("zone_name")

        normalized.append({
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": "ZONE_ENTER" if event_type == "zone_entered" else "ZONE_EXIT",
            "timestamp": timestamp,
            "zone_id": event.get("zone_id"),
            "confidence": 1.0,
            "dwell_ms": 0,
            "is_staff": False,
            "metadata": {
                "sku_zone": sku_zone,
                **meta
            }
        })
        
    elif event_type in ("queue_completed", "queue_abandoned"):
        store_id = clean_store_id(event.get("store_id", ""))
        camera_id = clean_camera_id(event.get("camera_id", ""))
        visitor_id = clean_visitor_id(event.get("track_id", ""))
        
        queue_join_ts = to_iso_utc(event.get("queue_join_ts", ""))
        queue_exit_ts = to_iso_utc(event.get("queue_exit_ts", ""))
        wait_seconds = event.get("wait_seconds", 0) or 0
        queue_position = event.get("queue_position_at_join", 1) or 1
        
        meta = {
            "queue_event_id": event.get("queue_event_id"),
            "queue_served_ts": to_iso_utc(event.get("queue_served_ts", "")) if event.get("queue_served_ts") else None,
            "queue_exit_ts": queue_exit_ts,
            "wait_seconds": wait_seconds,
            "abandoned": event.get("abandoned", False),
            "gender": event.get("gender"),
            "age": event.get("age"),
            "age_bucket": event.get("age_bucket")
        }
        
        normalized.append({
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": queue_join_ts,
            "zone_id": event.get("zone_id"),
            "confidence": 1.0,
            "dwell_ms": 0,
            "is_staff": False,
            "metadata": {
                "queue_depth": queue_position,
                **meta
            }
        })
        
        if event_type == "queue_abandoned" or event.get("abandoned", False):
            normalized.append({
                "event_id": str(uuid.uuid4()),
                "store_id": store_id,
                "camera_id": camera_id,
                "visitor_id": visitor_id,
                "event_type": "BILLING_QUEUE_ABANDON",
                "timestamp": queue_exit_ts,
                "zone_id": event.get("zone_id"),
                "confidence": 1.0,
                "dwell_ms": int(wait_seconds * 1000),
                "is_staff": False,
                "metadata": meta
            })
            
    return normalized

async def ingest_events(events: List[StoreEvent], db: AsyncSession) -> IngestResponse:
    """
    Ingests raw visitor detection events into the database.
    Performs event-level validation, deduplication, bulk insert, and session state tracking.
    """
    accepted = 0
    rejected = 0
    duplicate = 0
    errors = []
    accepted_matches_data = []

    if not events:
        return IngestResponse(accepted=0, rejected=0, duplicate=0, errors=[])

    # Pre-process / normalize events to support the new JSONL schema
    normalized_list = []
    for event in events:
        e_dict = event if isinstance(event, dict) else event.model_dump()
        try:
            norm_events = normalize_event_dict(e_dict)
            if norm_events:
                normalized_list.extend(norm_events)
            else:
                # If normalization returns empty, fallback to validating original
                normalized_list.append(e_dict)
        except Exception as ex:
            # Fallback to validating original if normalization fails
            logger.warn("Event normalization failed, falling back to original", error=str(ex))
            normalized_list.append(e_dict)

    accepted_events_data = []
    affected_stores = set()

    for event in normalized_list:
        try:
            # 1. Validate
            if isinstance(event, dict):
                val_event = StoreEvent.model_validate(event)
            else:
                val_event = StoreEvent.model_validate(event.model_dump())
        except ValidationError as e:
            rejected += 1
            event_id = "unknown"
            if isinstance(event, dict):
                event_id = str(event.get("event_id", "unknown"))
            elif hasattr(event, "event_id"):
                event_id = str(event.event_id)
            errors.append({"event_id": event_id, "reason": str(e)})
            continue

        # 2. Deduplicate: SELECT 1 FROM events WHERE event_id = :id
        try:
            stmt_dedup = select(1).where(Event.event_id == val_event.event_id)
            res_dedup = await db.execute(stmt_dedup)
            if res_dedup.scalar() is not None:
                duplicate += 1
                errors.append({"event_id": str(val_event.event_id), "reason": "Duplicate event_id"})
                continue
        except Exception as e:
            rejected += 1
            errors.append({"event_id": str(val_event.event_id), "reason": f"Deduplication check failed: {str(e)}"})
            continue

        # 3. Add to accepted list for bulk insert
        accepted_events_data.append({
            "event_id": val_event.event_id,
            "store_id": val_event.store_id,
            "camera_id": val_event.camera_id,
            "visitor_id": val_event.visitor_id,
            "event_type": val_event.event_type.value,
            "timestamp": val_event.timestamp,
            "zone_id": val_event.zone_id,
            "dwell_ms": val_event.dwell_ms,
            "is_staff": val_event.is_staff,
            "confidence": val_event.confidence,
            "event_metadata": val_event.metadata.model_dump()
        })
        affected_stores.add(val_event.store_id)

        # Check for Re-ID metadata to log a global visitor match
        if val_event.metadata.local_tracker_id is not None and val_event.metadata.reid_confidence is not None:
            accepted_matches_data.append({
                "match_id": uuid.uuid4(),
                "global_person_id": val_event.visitor_id,
                "local_tracker_id": val_event.metadata.local_tracker_id,
                "camera_id": val_event.camera_id,
                "confidence": val_event.metadata.reid_confidence,
                "source_camera": val_event.metadata.source_camera,
                "destination_camera": val_event.metadata.destination_camera,
                "matched_at": val_event.timestamp
            })

        # 4. Update visitor_sessions: ENTRY/REENTRY (create if not active), EXIT (update exit_time)
        try:
            if val_event.event_type in (EventType.ENTRY, EventType.REENTRY):
                stmt_check = select(VisitorSession).where(
                    VisitorSession.visitor_id == val_event.visitor_id,
                    VisitorSession.store_id == val_event.store_id,
                    VisitorSession.exit_time == None
                )
                res_check = await db.execute(stmt_check)
                if res_check.scalars().first() is None:
                    new_session = VisitorSession(
                        session_id=uuid.uuid4(),
                        visitor_id=val_event.visitor_id,
                        store_id=val_event.store_id,
                        entry_time=val_event.timestamp,
                        is_staff=val_event.is_staff
                    )
                    db.add(new_session)
                    await db.flush()
            elif val_event.event_type == EventType.EXIT:
                stmt_sess = (
                    select(VisitorSession)
                    .where(
                        VisitorSession.visitor_id == val_event.visitor_id,
                        VisitorSession.exit_time == None
                    )
                    .order_by(VisitorSession.entry_time.desc())
                )
                res_sess = await db.execute(stmt_sess)
                session = res_sess.scalars().first()
                if session:
                    session.exit_time = val_event.timestamp
                    await db.flush()
        except Exception as e:
            logger.error("Failed to update visitor session during ingestion", visitor_id=val_event.visitor_id, error=str(e))

    # Perform bulk insert of accepted events
    if accepted_events_data:
        try:
            dialect_name = db.bind.dialect.name
            insert_fn = get_insert_stmt(dialect_name)
            
            stmt = insert_fn(Event).values(accepted_events_data)
            if dialect_name in ("postgresql", "sqlite"):
                stmt = stmt.on_conflict_do_nothing(index_elements=['event_id'])
                
            await db.execute(stmt)
            await db.flush()
            accepted = len(accepted_events_data)

            # Perform bulk insert of accepted global visitor matches
            if accepted_matches_data:
                stmt_match = insert_fn(GlobalVisitorMatch).values(accepted_matches_data)
                if dialect_name in ("postgresql", "sqlite"):
                    stmt_match = stmt_match.on_conflict_do_nothing(index_elements=['match_id'])
                await db.execute(stmt_match)
                await db.flush()
        except Exception as e:
            logger.error("Failed to bulk insert accepted events/matches", error=str(e))
            rejected += len(accepted_events_data)
            errors.append({"event_id": "bulk_insert", "reason": f"Bulk insert failed: {str(e)}"})
            accepted_events_data.clear()

    # Update is_staff for all sessions/events of visitors who were classified as staff in this batch
    staff_visitor_ids = {ev["visitor_id"] for ev in accepted_events_data if ev["is_staff"]}
    if staff_visitor_ids:
        try:
            from sqlalchemy import update
            stmt_staff = (
                update(VisitorSession)
                .where(
                    VisitorSession.visitor_id.in_(list(staff_visitor_ids))
                )
                .values(is_staff=True)
            )
            await db.execute(stmt_staff)
            
            stmt_staff_events = (
                update(Event)
                .where(
                    Event.visitor_id.in_(list(staff_visitor_ids))
                )
                .values(is_staff=True)
            )
            await db.execute(stmt_staff_events)
            
            await db.flush()
        except Exception as e:
            logger.error("Failed to bulk update visitor session/events staff status during ingestion", error=str(e))

    # Trigger POS transaction correlation if BILLING_QUEUE_JOIN events are accepted
    has_billing_join = any(ev["event_type"] == "BILLING_QUEUE_JOIN" for ev in accepted_events_data)
    if has_billing_join:
        from app.pos_correlator import run_correlation
        for store_id in affected_stores:
            try:
                await run_correlation(store_id, db, commit=False)
            except Exception as e:
                logger.error("POS transaction correlation failed during ingestion", store_id=store_id, error=str(e))

    return IngestResponse(
        accepted=accepted,
        rejected=rejected,
        duplicate=duplicate,
        errors=errors
    )
