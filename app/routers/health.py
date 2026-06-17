from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.schemas import HealthResponse, StoreHealth
from app.health import get_health

from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, status

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
async def read_health(db: AsyncSession = Depends(get_db_session)):
    """
    Performs system readiness and store ingestion feed checks.
    Responds with HTTP 503 if database connectivity is degraded.
    """
    try:
        health_data = await get_health(db)
        is_db_down = any(
            store.status == "DEGRADED" and store.warning == "DATABASE_UNAVAILABLE"
            for store in health_data.stores
        )
        if is_db_down:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=jsonable_encoder(health_data)
            )
        return health_data
    except Exception as e:
        fallback = HealthResponse(
            api_version="1.0.0",
            checked_at=datetime.now(timezone.utc),
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
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=jsonable_encoder(fallback)
        )
