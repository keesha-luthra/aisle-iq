import logging
import sys
import structlog
from app.config import settings

def setup_logging():
    """
    Configures standard logging and structlog to output structured JSON logs
    suitable for cloud logging systems.
    """
    log_level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    
    level = log_level_map.get(settings.LOG_LEVEL.lower(), logging.INFO)
    
    # Configure processors for structlog
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    structlog.configure(
        processors=shared_processors + [
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    
    # Root logging config for standard python logs
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
    
    # Redirect standard logging to structlog where possible
    for name in ("uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(name).handlers = [logging.StreamHandler(sys.stdout)]
        
    logger = structlog.get_logger()
    logger.info("Structured logging has been configured successfully", log_level=settings.LOG_LEVEL)
