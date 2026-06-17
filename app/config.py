from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Pydantic Settings reads from environment variables, fallback to defaults
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # DB Config
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/storedb.sqlite3"

    # API Config
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Logging Config
    LOG_LEVEL: str = "info"

    # Path Config
    STORE_LAYOUT_PATH: str = "data/store_layout.json"
    POS_CSV_PATH: str = "data/pos_transactions.csv"
    EVENTS_OUTPUT_DIR: str = "data/events"

    # Thresholds
    REID_THRESHOLD: float = 0.6
    STAFF_CONFIDENCE_THRESHOLD: float = 0.85

    # Analytics Config
    ZONE_DWELL_SECONDS: int = 30
    QUEUE_DWELL_SECONDS: int = 5

    # Anomaly Thresholds
    anomaly_queue_spike_threshold: int = 5
    anomaly_conversion_drop_pct: float = 0.2
    dead_zone_minutes: int = 30
    stale_feed_seconds: int = 600

settings = Settings()
