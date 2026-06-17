import time
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db_session
from app.schemas import IngestRequest, IngestResponse
from app.ingestion import ingest_events

logger = structlog.get_logger()
router = APIRouter()

@router.post("/ingest", response_model=IngestResponse)
async def ingest(payload: IngestRequest, db: AsyncSession = Depends(get_db_session)):
    """
    POST /events/ingest endpoint.
    Accepts an IngestRequest payload and processes it using the business logic.
    """
    start_time = time.time()
    trace_id = structlog.contextvars.get_contextvars().get("trace_id", "unknown")
    
    # Track store IDs affected
    store_ids = set()
    for event in payload.events:
        if isinstance(event, dict):
            store_ids.add(event.get("store_id", "unknown"))
        else:
            store_ids.add(event.store_id)
            
    store_id = list(store_ids)[0] if store_ids else "unknown"
    structlog.contextvars.bind_contextvars(
        event_count=len(payload.events),
        store_id=store_id
    )

    try:
        # Wrap entire operation in a database transaction block
        async with db.begin_nested():
            response = await ingest_events(payload.events, db)
            
        latency_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "Events ingestion summary",
            trace_id=trace_id,
            store_ids=list(store_ids),
            accepted=response.accepted,
            rejected=response.rejected,
            duplicate=response.duplicate,
            latency_ms=latency_ms
        )
        return response
        
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "Unhandled exception during events ingestion",
            trace_id=trace_id,
            store_ids=list(store_ids),
            error=str(e),
            latency_ms=latency_ms
        )
        # On unhandled exceptions, raise HTTP 500 with structured JSON detail instead of raw tracebacks
        raise HTTPException(
            status_code=500,
            detail={
                "message": "An internal database error occurred during ingestion.",
                "error_type": type(e).__name__,
                "reason": str(e)
            }
        )
