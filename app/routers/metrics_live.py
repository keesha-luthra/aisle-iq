from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db_session
from app.metrics import get_live_store_metrics
from app.schemas import LiveMetricsResponse

router = APIRouter(prefix="/metrics/live")

@router.get("/{store_id}", response_model=LiveMetricsResponse)
async def get_live_metrics(store_id: str, db: AsyncSession = Depends(get_db_session)):
    """Return real‑time metrics for the specified store using a short time window."""
    return await get_live_store_metrics(store_id, db)
