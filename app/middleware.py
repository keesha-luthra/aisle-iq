import uuid
import time
import re
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = structlog.get_logger()

class TrackingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that injects a unique trace_id into request headers
    and logs request details, status codes, and execution latency.
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        endpoint = request.url.path
        
        # Try to parse store_id from path
        store_match = re.search(r"STORE_[A-Z]{3}_[0-9]{3}", endpoint)
        store_id = store_match.group(0) if store_match else None
        
        # Bind core contextvars
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            endpoint=endpoint
        )
        if store_id:
            structlog.contextvars.bind_contextvars(store_id=store_id)
            
        start_time = time.time()
        
        # Log incoming request
        logger.info(
            "Incoming request",
            method=request.method,
            endpoint=endpoint,
            client_host=request.client.host if request.client else "unknown"
        )
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            latency_ms = int(process_time * 1000)
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Process-Time"] = f"{process_time:.4f}s"
            
            # Retrieve values bound in router (e.g. event_count or store_id)
            ctx = structlog.contextvars.get_contextvars()
            final_store_id = ctx.get("store_id", store_id)
            event_count = ctx.get("event_count", None)
            
            logger.info(
                "Request processed successfully",
                trace_id=trace_id,
                store_id=final_store_id,
                endpoint=endpoint,
                latency_ms=latency_ms,
                event_count=event_count,
                status_code=response.status_code
            )
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            latency_ms = int(process_time * 1000)
            ctx = structlog.contextvars.get_contextvars()
            final_store_id = ctx.get("store_id", store_id)
            event_count = ctx.get("event_count", None)
            
            logger.error(
                "Request failed with unhandled exception",
                trace_id=trace_id,
                store_id=final_store_id,
                endpoint=endpoint,
                latency_ms=latency_ms,
                event_count=event_count,
                error=str(e)
            )
            raise e
            
        finally:
            # Clean up contextvars
            structlog.contextvars.clear_contextvars()

