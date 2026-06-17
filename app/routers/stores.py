import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.schemas import MetricsResponse, FunnelResponse, HeatmapResponse, AnomalyResponse
from app.metrics import get_store_metrics, get_camera_analytics
from app.funnel import get_funnel
from app.heatmap import get_heatmap
from app.anomalies import get_anomalies

router = APIRouter(prefix="/{store_id}")

from app.utils import load_layout
from app.schemas import StoreLayoutResponse

def validate_store_id(store_id: str) -> str:
    """
    Validates that store_id matches the pattern STORE_[A-Z]{3}_[0-9]{3}.
    Returns 404 if not.
    """
    if not re.match(r"^STORE_[A-Z]{3}_[0-9]{3}$", store_id):
        raise HTTPException(
            status_code=404,
            detail=f"Store '{store_id}' not found. Invalid store ID format."
        )
    return store_id

@router.get("/metrics", response_model=MetricsResponse)
async def read_store_metrics(
    store_id: str,
    window_hours: int = Query(24, ge=1),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retrieves key operational and visitor metrics for the specified store.
    """
    validate_store_id(store_id)
    return await get_store_metrics(store_id, window_hours, db)

@router.get("/funnel", response_model=FunnelResponse)
async def read_store_funnel(
    store_id: str,
    window_hours: int = Query(24, ge=1),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retrieves conversion funnel analytics for the specified store.
    """
    validate_store_id(store_id)
    return await get_funnel(store_id, window_hours, db)

@router.get("/heatmap", response_model=HeatmapResponse)
async def read_store_heatmap(
    store_id: str,
    window_hours: int = Query(24, ge=1),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retrieves visitor spatial distribution/density map details.
    """
    validate_store_id(store_id)
    return await get_heatmap(store_id, window_hours, db)

@router.get("/layout", response_model=StoreLayoutResponse)
async def get_store_layout(store_id: str):
    """Return the store layout JSON for the given store_id."""
    return load_layout(store_id)

@router.get("/anomalies", response_model=AnomalyResponse)
async def read_store_anomalies(
    store_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Identifies operations or customer flow anomalies.
    """
    validate_store_id(store_id)
    return await get_anomalies(store_id, db)

@router.get("/camera-analytics")
async def read_camera_analytics(
    store_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retrieves real-time per-camera metrics and store-level peak traffic hours.
    """
    validate_store_id(store_id)
    return await get_camera_analytics(store_id, db)
