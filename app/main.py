import re
import json
from pathlib import Path
import uuid
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from app.config import settings
from app.logging_config import setup_logging
from app.middleware import TrackingMiddleware
from app.database import init_db, async_session_factory, run_migrations
from app.pos_correlator import load_pos_data

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Setup logging
    setup_logging()
    
    # 1b. Run alembic database migrations
    await run_migrations()
    
    # 2. Initialize database schema
    await init_db()
    
    # 3. Load POS data if configured CSV path exists
    csv_path = settings.POS_CSV_PATH
    import os
    if os.path.exists(csv_path):
        async with async_session_factory() as db:
            await load_pos_data(csv_path, db)

    # 4. Log ready signal with redacted DB password
    redacted_db_url = re.sub(r":([^@/]+)@", ":****@", settings.DATABASE_URL)
    logger.info(
        "Store Intelligence API ready",
        version="1.0.0",
        db_url=redacted_db_url
    )
    yield


# Initialize FastAPI application
app = FastAPI(
    title="Store Intelligence API",
    description="APIs for retail store tracking events, visitor flows, metrics, and funnel anomalies.",
    version="1.0.0",
    lifespan=lifespan
)

from fastapi.middleware.cors import CORSMiddleware

# Apply tracking middleware
app.add_middleware(TrackingMiddleware)

# Apply CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and register API routers
from app.routers.events import router as events_router
from app.routers.stores import router as stores_router
from app.routers.health import router as health_router
from app.routers.metrics_live import router as live_metrics_router
from app.routers.video import router as video_router

app.include_router(events_router, prefix="/events", tags=["Events"])
app.include_router(stores_router, prefix="/stores", tags=["Store Analytics"])
app.include_router(health_router, tags=["Ops"])
app.include_router(live_metrics_router, prefix="/metrics/live", tags=["Live Metrics"])
app.include_router(video_router, prefix="/video", tags=["Video Feeds"])

# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Returns structured 422 error details instead of raw FastAPI lists.
    """
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "details": exc.errors()
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Prevents raw tracebacks from being exposed. Returns structured 500 JSON, 
    or HTTP 503 if a database connection error is identified.
    """
    trace_id = structlog.contextvars.get_contextvars().get("trace_id", str(uuid.uuid4()))
    
    # Identify database connection/unavailability errors
    exc_str = str(exc).lower()
    is_db_unavailable = (
        "connection refused" in exc_str or 
        "cannot connect" in exc_str or 
        "operationalerror" in exc_str or 
        "interfaceerror" in exc_str or
        "connection closed" in exc_str or
        "connection timeout" in exc_str or
        "database_unavailable" in exc_str or
        "is unavailable" in exc_str or
        "cannot open database" in exc_str or
        "adaptedconnection" in exc_str or
        "database error" in exc_str or
        "connection reset" in exc_str
    )
    
    # Check explicitly for SQLAlchemy connection errors
    from sqlalchemy.exc import SQLAlchemyError
    if isinstance(exc, SQLAlchemyError):
        from sqlalchemy.exc import OperationalError, InterfaceError
        if isinstance(exc, (OperationalError, InterfaceError)):
            is_db_unavailable = True
            
    if is_db_unavailable:
        logger.error("Database connection failure detected", error=str(exc), trace_id=trace_id)
        return JSONResponse(
            status_code=503,
            content={
                "error": "database_unavailable",
                "message": "The database is currently unavailable. Please try again later.",
                "trace_id": trace_id
            }
        )
        
    logger.error("Unhandled server exception", error=str(exc), trace_id=trace_id)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred.",
            "trace_id": trace_id
        }
    )



@app.get("/")
async def root():
    return {"message": "Welcome to the Store Intelligence API. Visit /docs for OpenAPI documentation."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=True)
